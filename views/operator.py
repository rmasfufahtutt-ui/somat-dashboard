"""views/operator.py - keputusan operator (human in the loop) atas rekomendasi TERBIT. Atomik + idempoten.

Tombol APPROVE / MODIFY / DELAY SELALU tampil (nonaktif bila tidak ada rekomendasi yang dapat diputuskan).
MODIFY = isian jumlah & durasi di tempat + alasan wajib (catatan operator disembunyikan saat MODIFY).
DELAY = langsung tercatat. Riwayat = satu tabel responsif dengan kolom Aksi:
  Edit   -> koreksi (record baru, yang lama SUPERSEDED)   : admin, atau operator untuk catatannya sendiri
  Delete -> pembatalan (VOID, beralasan, tidak dihapus)   : admin saja
"""
from __future__ import annotations

import html
import uuid

import streamlit as st

import auth
import physics_engine as pe
import recommendation_service as rsvc
import repository as repo
import store
import texts
from i18n import L
from ui_kit import _T, cards, chip, fmt_num, fmt_ts

DECISIONS = ("APPROVE", "MODIFY", "DELAY")
HIST_PAGE_SIZE = 10


# ------------------------------------------------------------------ util
def _idem(rec_id, action):
    k = f"_idem_{rec_id}_{action}"
    if k not in st.session_state:
        st.session_state[k] = uuid.uuid4().hex
    return st.session_state[k]


def _clear_idem(rec_id):
    for a in DECISIONS:
        st.session_state.pop(f"_idem_{rec_id}_{a}", None)


def _submit(run, decision, mm, hours, note, verified=False):
    u = auth.refresh_user(force=True)
    if not auth.can_decide():
        st.error(auth.auth_msg("forbidden"))
        return
    try:
        _did, dup = repo.record_decision(run["rec_id"], u["username"], decision, mm, hours, note,
                                         _idem(run["rec_id"], decision), duration_verified=verified)
    except repo.DecisionError as e:
        st.session_state["op_flash"] = ("warning", texts.decision_error(e.code))
        st.session_state.pop("op_modify", None)
        _clear_idem(run["rec_id"])
        store.invalidate()
        st.rerun()
        return
    except Exception:
        st.error(auth.auth_msg("db"))
        return
    _clear_idem(run["rec_id"])
    st.session_state.pop("op_modify", None)
    store.invalidate()
    msg = {"APPROVE": L("✅ Decision recorded: APPROVE", "✅ Keputusan dicatat: APPROVE"),
           "DELAY": L("⏸️ Decision recorded: DELAY", "⏸️ Keputusan dicatat: DELAY"),
           "MODIFY": L("✏️ Decision recorded: MODIFY", "✏️ Keputusan dicatat: MODIFY")}[decision]
    st.session_state["op_flash"] = ("success", msg + (L(" (already recorded earlier)", " (sudah tercatat sebelumnya)") if dup else "")
                                    + L(" — record the actual irrigation in **Irrigation Execution**.",
                                        " — catat irigasi aktual di **Pelaksanaan Irigasi**."))
    st.rerun()


# ------------------------------------------------------------------ panel keputusan
def _disabled_buttons(key, why):
    """Tiga tombol keputusan tetap tampil tetapi nonaktif; `why` menjelaskan alasannya."""
    b1, b2, b3 = st.columns(3)
    b1.button("APPROVE", type="primary", width="stretch", key=f"{key}_ap", disabled=True)
    b2.button("MODIFY", width="stretch", key=f"{key}_mo", disabled=True)
    b3.button("DELAY", width="stretch", key=f"{key}_dl", disabled=True)
    if why:
        st.caption(why)


def _summary_cards(run, out):
    cards([
        dict(icon="💧", title=L("Recommended irrigation", "Irigasi disarankan"),
             value_text=f"{fmt_num(out.get('total_mm'))} mm" if out.get("irrigate") else L("Not needed", "Belum perlu"),
             note=f"{fmt_num(out.get('volume_m3'), 0)} m³" if out.get("volume_m3") else "", badge_text=L("Awaiting", "Menunggu"),
             badge_kind="warn", color="orange"),
        dict(icon="⏱️", title=L("Duration", "Durasi"), value_text=f"{fmt_num(out.get('duration_h'))} h" if out.get("duration_h") else "—",
             note=(L("arrives ", "tiba ") + fmt_ts(out["arrival_at"])) if out.get("arrival_at") else "", color="orange"),
        dict(icon="🪣", title=L("Predicted h on arrival", "Prediksi h saat tiba"),
             value_text=f"{fmt_num(out.get('h_arrival_cm'))} cm", note=L(f"trigger {fmt_num(out.get('trigger_h_cm'))} cm",
                                                                     f"pemicu {fmt_num(out.get('trigger_h_cm'))} cm"), color="blue"),
        dict(icon="🕒", title=L("Valid until", "Berlaku sampai"), value_text=fmt_ts(run["expires_at"])[11:16],
             note=fmt_ts(run["expires_at"])[:10], color="blue"),
    ], columns=4)


def _run_card(ctx, run):
    out = run["output"] or {}
    mode = run["run_mode"]
    rid = run["rec_id"]
    st.markdown(f"##### {run['plot_id']} · #{rid} "
                + chip(mode, texts.RUN_KIND.get(mode, "info")) + " " + chip(texts.status_label(run["status_code"]), "info"),
                unsafe_allow_html=True)
    modifying = st.session_state.get("op_modify") == rid
    can_apply = bool(out.get("irrigate")) and out.get("total_mm") is not None
    operational = mode in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED")

    if modifying and operational and can_apply:
        _modify_inline(run, out)       # kartu jumlah/durasi diganti isian; catatan operator disembunyikan
        return

    _summary_cards(run, out)
    st.caption(L(f"Published {fmt_ts(run['created_at'])} by {run['created_by']} · inputs hash {run['inputs_hash'][:10]}…",
                 f"Terbit {fmt_ts(run['created_at'])} oleh {run['created_by']} · hash input {run['inputs_hash'][:10]}…"))
    for r in out.get("reasons") or []:
        st.markdown(f"- {r}")

    if not operational:
        st.warning(texts.decision_error("not_operational"))
        _disabled_buttons(f"dis_{rid}", "")
        return

    note = st.text_input(L("📝 Operator note (optional for APPROVE and DELAY)", "📝 Catatan operator (opsional untuk APPROVE dan DELAY)"),
                         key=f"note_{rid}")
    b1, b2, b3 = st.columns(3)
    if b1.button("APPROVE", type="primary", width="stretch", key=f"ap_{rid}", disabled=not can_apply):
        _submit(run, "APPROVE", out["total_mm"], out.get("duration_h"), note, verified=out.get("duration_h") is not None)
    if b2.button("MODIFY", width="stretch", key=f"mo_{rid}", disabled=not can_apply):
        st.session_state["op_modify"] = rid
        st.rerun()
    if b3.button("DELAY", width="stretch", key=f"dl_{rid}"):
        _submit(run, "DELAY", 0.0, 0.0, note.strip() or L("Postponed by operator", "Ditunda oleh operator"))
    if not can_apply:
        st.caption(L("APPROVE/MODIFY need a computed amount (irrigation recommended). DELAY is always possible.",
                     "APPROVE/MODIFY butuh jumlah terhitung (irigasi disarankan). DELAY selalu dapat dilakukan."))


def _modify_inline(run, out):
    rid = run["rec_id"]
    prof = repo.get_profile_by_id(run["profile_id"]) if run.get("profile_id") else None
    plot_profile = rsvc.build_profile(run["plot_id"], prof)[0] if prof else None
    st.info(L(f"✏️ Modify mode — SOMAT suggested **{fmt_num(out.get('total_mm'))} mm** / **{fmt_num(out.get('duration_h'))} h**. "
              "Change the amount (it must differ from the suggestion) and give a reason.",
              f"✏️ Mode ubah — SOMAT menyarankan **{fmt_num(out.get('total_mm'))} mm** / **{fmt_num(out.get('duration_h'))} jam**. "
              "Ubah jumlahnya (harus berbeda dari saran) dan beri alasan."))
    with st.form(f"modify_{rid}"):
        c1, c2 = st.columns(2)
        mm = c1.number_input(L("💧 Irrigation amount (mm)", "💧 Jumlah irigasi (mm)"), min_value=0.0, max_value=1000.0,
                             value=float(out["total_mm"]), step=0.5)
        hrs = c2.number_input(L("⏱️ Duration (h)", "⏱️ Durasi (jam)"), min_value=0.0, max_value=240.0,
                              value=float(out.get("duration_h") or 0.0), step=0.5)
        reason = st.text_area(L("📝 Reason for change (required)", "📝 Alasan perubahan (wajib)"))
        s1, s2 = st.columns(2)
        save = s1.form_submit_button(L("Save modified decision", "Simpan keputusan yang diubah"), type="primary", width="stretch")
        cancel = s2.form_submit_button(L("Cancel", "Batal"), width="stretch")
    if cancel:
        st.session_state.pop("op_modify", None)
        st.rerun()
    if save:
        if not reason.strip():
            st.warning(L("A reason is required.", "Alasan wajib diisi."))
            return
        if plot_profile is None:
            st.error(texts.issue_text({"code": "BAD_AMOUNT"}))
            return
        q = plot_profile.q_plot_m3s.value if plot_profile.q_plot_m3s.known else None
        ev = pe.evaluate_modification(out, plot_profile, mm, q, duration_h=hrs or None)
        if not ev["valid"]:
            for i in ev["issues"]:
                st.error(texts.issue_text(i))
            return
        _submit(run, "MODIFY", mm, hrs if hrs else ev.get("duration_h"), reason, verified=bool(ev.get("duration_verified")))


# ------------------------------------------------------------------ riwayat (tabel gabungan + aksi)
def _can_edit(rec):
    me = auth.current_user()
    return (bool(me) and rec.get("record_status") == "ACTIVE"
            and (auth.is_admin() or (auth.can_decide() and rec.get("username") == me["username"])))


@st.dialog(L("✏️ Correct decision record", "✏️ Koreksi catatan keputusan"))
def _edit_dialog(rec_id):
    rows = [r for r in store.decisions(200) if r["id"] == rec_id]
    me = auth.current_user()
    if not rows or not me:
        st.error(auth.auth_msg("not_found"))
        return
    cur = rows[0]
    if not _can_edit(cur):
        st.error(auth.auth_msg("forbidden"))
        return
    st.caption(L("A correction creates a NEW record; the old one is kept as SUPERSEDED. The SOMAT recommendation is not recalculated.",
                 "Koreksi membuat record BARU; yang lama tetap tersimpan sebagai SUPERSEDED. Rekomendasi SOMAT tidak dihitung ulang."))
    with st.form(f"dec_edit_form_{rec_id}"):
        dec = st.selectbox(L("Decision", "Keputusan"), DECISIONS,
                           index=DECISIONS.index(cur["decision"]) if cur["decision"] in DECISIONS else 0)
        mm = st.number_input(L("Operator irrigation (mm)", "Irigasi operator (mm)"), 0.0, 1000.0, float(cur["operator_mm"] or 0.0), 0.5)
        hrs = st.number_input(L("Operator duration (h)", "Durasi operator (jam)"), 0.0, 240.0, float(cur["duration_h"] or 0.0), 0.5)
        note = st.text_area(L("Note", "Catatan"), value=cur.get("note") or "")
        reason = st.text_input(L("Reason for correction (required)", "Alasan koreksi (wajib)"))
        go = st.form_submit_button(L("Save correction", "Simpan koreksi"), type="primary")
    if go:
        if not reason.strip():
            st.warning(L("A reason is required.", "Alasan wajib diisi."))
            return
        try:
            new_id = repo.supersede_decision(rec_id, me["username"], dec, mm, hrs or None, note, reason)
        except repo.DecisionError as e:
            st.error(texts.decision_error(e.code) if e.code != "not_active"
                     else L("This record is no longer active.", "Catatan ini sudah tidak aktif."))
            return
        except Exception:
            st.error(auth.auth_msg("db"))
            return
        if not new_id:
            st.error(auth.auth_msg("not_found"))
            return
        store.invalidate()
        st.session_state["op_flash"] = ("success", L(f"Record #{rec_id} corrected (old record kept as SUPERSEDED).",
                                                     f"Catatan #{rec_id} dikoreksi (catatan lama tetap tersimpan sebagai SUPERSEDED)."))
        st.rerun()


@st.dialog(L("🗑️ Void decision record", "🗑️ Batalkan catatan keputusan"))
def _delete_dialog(rec_id):
    me = auth.current_user()
    if not auth.is_admin() or not me:
        st.error(auth.auth_msg("forbidden"))
        return
    st.warning(L(f"Record #{rec_id} will be marked VOID and removed from active use. It stays in the database and audit log (not erased).",
                 f"Catatan #{rec_id} akan ditandai VOID dan tidak dipakai lagi. Tetap tersimpan di database dan log audit (tidak dihapus)."))
    reason = st.text_input(L("Reason (required)", "Alasan (wajib)"), key=f"void_reason_{rec_id}")
    d1, d2 = st.columns(2)
    if d1.button(L("Delete", "Hapus"), type="primary", key=f"dec_del_go_{rec_id}", width="stretch"):
        if not reason.strip():
            st.warning(L("A reason is required.", "Alasan wajib diisi."))
            return
        if repo.void_decision(rec_id, me["username"], reason):
            store.invalidate()
            st.session_state["op_flash"] = ("success", L(f"Record #{rec_id} voided.", f"Catatan #{rec_id} dibatalkan."))
            st.rerun()
        else:
            st.error(L("Record is not active or not found.", "Catatan tidak aktif atau tidak ditemukan."))
    if d2.button(L("Cancel", "Batal"), key=f"dec_del_no_{rec_id}", width="stretch"):
        st.rerun()


def _history_css():
    t = _T()
    b, p = t["border"], t["panel"]
    css = f"""
.st-key-dec_table{{gap:0 !important;container-type:inline-size;container-name:dectable;}}
[class*="st-key-dec_row_"]{{border-top:1px solid {b};padding:.5rem 0;gap:0 !important;}}
.st-key-dec_head{{border-bottom:2px solid {b};padding:.25rem 0 .5rem 0;gap:0 !important;}}
.dh-h{{font-size:.74rem;font-weight:800;letter-spacing:.03em;text-transform:uppercase;opacity:.65;overflow-wrap:normal;word-break:keep-all;}}
.dh-c{{font-size:.88rem;line-height:1.3;overflow-wrap:anywhere;}}
.dh-m{{font-size:.74rem;opacity:.62;line-height:1.3;}}
.dh-l{{display:none;font-size:.68rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;opacity:.6;margin-bottom:1px;}}
.dh-chip{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.72rem;font-weight:800;color:#fff;background:#64748B;}}
.dh-chip.APPROVE{{background:#16884A;}} .dh-chip.MODIFY{{background:#D85A10;}} .dh-chip.DELAY{{background:#256FD1;}}
.dh-st{{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:6px;font-size:.66rem;font-weight:800;border:1px solid {b};opacity:.85;}}
.block-container [data-testid="stHorizontalBlock"] [class*="st-key-dec_act_"] .stButton button,
.block-container [class*="st-key-dec_pager"] [data-testid="stHorizontalBlock"] .stButton button{{min-height:2.1rem !important;height:2.1rem;padding:0 .7rem !important;border-radius:9px !important;white-space:nowrap;}}
.block-container [data-testid="stHorizontalBlock"] [class*="st-key-dec_act_"] .stButton button p,
.block-container [class*="st-key-dec_pager"] [data-testid="stHorizontalBlock"] .stButton button p{{font-size:.82rem !important;font-weight:700 !important;letter-spacing:0 !important;line-height:1 !important;}}
@container dectable (max-width: 860px){{
.st-key-dec_head{{display:none !important;}}
[class*="st-key-dec_row_"]{{border:1px solid {b};border-radius:12px;background:{p};padding:.7rem .85rem;margin-bottom:.65rem;}}
.dh-l{{display:block;}}
[class*="st-key-dec_row_"] [data-testid="stHorizontalBlock"]{{flex-wrap:wrap !important;gap:.55rem .9rem !important;}}
[class*="st-key-dec_row_"] [data-testid="stColumn"]{{flex:1 1 calc(50% - .9rem) !important;min-width:calc(50% - .9rem) !important;width:auto !important;}}
[class*="st-key-dec_row_"] [data-testid="stColumn"]:nth-child(n+7){{flex:1 1 100% !important;min-width:100% !important;}}
[class*="st-key-dec_act_"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap !important;gap:.5rem !important;}}
[class*="st-key-dec_act_"] [data-testid="stColumn"]{{flex:1 1 0 !important;min-width:0 !important;width:auto !important;}}
.block-container [data-testid="stHorizontalBlock"] [class*="st-key-dec_act_"] .stButton button{{min-height:2.5rem !important;height:2.5rem;}}
}}"""
    css = "\n".join(ln for ln in css.splitlines() if ln.strip())      # baris kosong memutus blok <style> di Markdown
    return f"<style>{css}</style>"


def _history_grid(rows):
    total = len(rows)
    pages = max(1, -(-total // HIST_PAGE_SIZE))
    pg = min(max(int(st.session_state.get("dec_page", 0)), 0), pages - 1)
    st.session_state["dec_page"] = pg
    chunk = rows[pg * HIST_PAGE_SIZE:(pg + 1) * HIST_PAGE_SIZE]
    esc = html.escape

    st.markdown(_history_css(), unsafe_allow_html=True)
    weights = [1.5, 0.8, 1.0, 1.15, 1.45, 0.9, 2.6, 1.9]
    heads = [L("Time (WIB)", "Waktu (WIB)"), L("Plot", "Petak"), L("Operator", "Operator"), L("Decision", "Keputusan"),
             L("SOMAT → Operator (mm)", "SOMAT → Operator (mm)"), L("Duration", "Durasi"),
             L("Reason / note", "Alasan / catatan"), L("Action", "Aksi")]
    with st.container(key="dec_table"):
        with st.container(key="dec_head"):
            for col, h in zip(st.columns(weights, vertical_alignment="center"), heads):
                col.markdown(f'<div class="dh-h">{esc(h)}</div>', unsafe_allow_html=True)
        for r in chunk:
            with st.container(key=f"dec_row_{r['id']}"):
                c = st.columns(weights, vertical_alignment="center")
                dec = str(r["decision"])
                status = str(r.get("record_status") or "ACTIVE")

                def cell(i, inner):
                    c[i].markdown(f'<div class="dh-c"><span class="dh-l">{esc(heads[i])}</span>{inner}</div>', unsafe_allow_html=True)

                cell(0, esc(fmt_ts(r["ts"])))
                cell(1, esc(str(r.get("plot_id") or "-")))
                cell(2, esc(str(r["username"])))
                cell(3, f'<span class="dh-chip {dec if dec in DECISIONS else ""}">{esc(dec)}</span>'
                        + ("" if status == "ACTIVE" else f'<span class="dh-st">{esc(status)}</span>'))
                cell(4, f'{float(r["recommended_mm"] or 0):.1f} → <b>{float(r["operator_mm"] or 0):.1f}</b> mm')
                cell(5, f'{float(r["duration_h"] or 0):.1f} {esc(L("h", "jam"))}')
                note_txt = esc(str(r.get("note") or "").replace("\n", " ")) or "-"
                extra = ""
                if r.get("edited_by"):
                    extra += f'<div class="dh-m">{esc(L("corrected by", "dikoreksi oleh"))} {esc(str(r["edited_by"]))}</div>'
                if status == "VOID" and r.get("void_reason"):
                    extra += f'<div class="dh-m">{esc(L("void reason", "alasan batal"))}: {esc(str(r["void_reason"]))}</div>'
                cell(6, note_txt + extra)
                with c[7]:
                    with st.container(key=f"dec_act_{r['id']}"):
                        a1, a2 = st.columns(2, gap="small")
                        if _can_edit(r) and a1.button("Edit", key=f"dec_edit_{r['id']}", width="stretch",
                                                      help=L("Correct this record", "Koreksi catatan ini")):
                            _edit_dialog(r["id"])
                        if auth.is_admin() and status == "ACTIVE" and a2.button("Delete", key=f"dec_del_{r['id']}", width="stretch",
                                                                                 help=L("Void this record", "Batalkan catatan ini")):
                            _delete_dialog(r["id"])
    with st.container(key="dec_pager"):
        n1, n2, n3 = st.columns([1, 2, 1], vertical_alignment="center")
        if n1.button(L("◀ Newer", "◀ Lebih baru"), key="dec_prev", disabled=pg <= 0):
            st.session_state["dec_page"] = pg - 1
            st.rerun()
        n2.caption(L(f"Page {pg + 1} of {pages} · {total} records", f"Halaman {pg + 1} dari {pages} · {total} catatan"))
        if n3.button(L("Older ▶", "Lebih lama ▶"), key="dec_next", disabled=pg >= pages - 1):
            st.session_state["dec_page"] = pg + 1
            st.rerun()


# ------------------------------------------------------------------ halaman
def render(ctx):
    auth.refresh_user()
    u = auth.current_user()
    st.header(L("👷 Operator Decision (Human in the Loop)", "👷 Keputusan Operator (Human in the Loop)"))
    st.caption(L("SOMAT only suggests. The operator decides. Approving does not mean water has flowed — record the actual irrigation separately. No gate moves automatically.",
                 "SOMAT hanya menyarankan. Operator yang memutuskan. Persetujuan tidak berarti air sudah mengalir — catat irigasi aktual terpisah. Tidak ada pintu digerakkan otomatis."))
    if u:
        st.caption(L(f"Signed in as **{u['display_name']}** ({auth.role_label(u['role'])})",
                     f"Masuk sebagai **{u['display_name']}** ({auth.role_label(u['role'])})"))
    if "op_flash" in st.session_state:
        kind, msg = st.session_state.pop("op_flash")
        (st.success if kind == "success" else st.warning)(msg)

    st.subheader(L("📨 Recommendations awaiting validation", "📨 Rekomendasi menunggu validasi"))
    if auth.can_decide():
        runs = store.pending_runs()
        if not runs:
            st.info(L("No recommendation is waiting. Publish one from **Prediction & Recommendation**.",
                      "Tidak ada rekomendasi yang menunggu. Terbitkan dari **Prediksi & Rekomendasi**."))
            with st.container(border=True):
                _disabled_buttons("none", L("Buttons are enabled when a recommendation is pending.",
                                            "Tombol aktif saat ada rekomendasi yang menunggu."))
        for run in runs:
            with st.container(border=True):
                _run_card(ctx, run)
    else:
        st.warning(L("Your role can view this tab but cannot record decisions.", "Role Anda dapat melihat tab ini tetapi tidak dapat mencatat keputusan."))
        with st.container(border=True):
            _disabled_buttons("noperm", "")

    with st.expander(L("📋 Decision history", "📋 Riwayat keputusan"), expanded=True):
        rows = store.decisions(200)
        if not rows:
            st.info(L("No decisions recorded yet.", "Belum ada keputusan tercatat."))
            return
        st.caption(L("Edit = correction (a new record; the old one is kept). Delete = void with a reason (admin only). Nothing is erased.",
                     "Edit = koreksi (record baru; yang lama tetap tersimpan). Delete = pembatalan beralasan (khusus admin). Tidak ada yang dihapus."))
        _history_grid(rows)
        import pandas as pd
        df = pd.DataFrame(rows)
        df["ts"] = df["ts"].map(fmt_ts)
        st.download_button(L("⬇️ Download CSV", "⬇️ Unduh CSV"), df.to_csv(index=False).encode("utf-8-sig"),
                           file_name="somat_decision_history.csv", mime="text/csv", key="dec_csv")
