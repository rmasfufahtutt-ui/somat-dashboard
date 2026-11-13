"""views/operator.py - keputusan operator (human in the loop) atas rekomendasi TERBIT. Atomik + idempoten."""
from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

import auth
import physics_engine as pe
import recommendation_service as rsvc
import repository as repo
import store
import texts
from i18n import L
from ui_kit import cards, chip, fmt_num, fmt_ts, table


def _idem(rec_id, action):
    k = f"_idem_{rec_id}_{action}"
    if k not in st.session_state:
        st.session_state[k] = uuid.uuid4().hex
    return st.session_state[k]


def _clear_idem(rec_id):
    for a in ("APPROVE", "MODIFY", "DELAY"):
        st.session_state.pop(f"_idem_{rec_id}_{a}", None)


def _submit(run, decision, mm, hours, note, verified=False):
    u = auth.refresh_user(force=True)
    if not auth.can_decide():
        st.error(auth.auth_msg("forbidden"))
        return
    try:
        did, dup = repo.record_decision(run["rec_id"], u["username"], decision, mm, hours, note,
                                        _idem(run["rec_id"], decision), duration_verified=verified)
    except repo.DecisionError as e:
        st.session_state["op_flash"] = ("warning", texts.decision_error(e.code))
        _clear_idem(run["rec_id"])
        store.invalidate()
        st.rerun()
        return
    except Exception:
        st.error(auth.auth_msg("db"))
        return
    _clear_idem(run["rec_id"])
    store.invalidate()
    msg = {"APPROVE": L("✅ Decision recorded: APPROVE", "✅ Keputusan dicatat: APPROVE"),
           "DELAY": L("⏸️ Decision recorded: DELAY", "⏸️ Keputusan dicatat: DELAY"),
           "MODIFY": L("✏️ Decision recorded: MODIFY", "✏️ Keputusan dicatat: MODIFY")}[decision]
    st.session_state["op_flash"] = ("success", msg + (L(" (already recorded earlier)", " (sudah tercatat sebelumnya)") if dup else "")
                                    + L(" — record the actual irrigation in **Irrigation Execution**.",
                                        " — catat irigasi aktual di **Pelaksanaan Irigasi**."))
    st.rerun()


def _run_card(ctx, run):
    out = run["output"] or {}
    mode = run["run_mode"]
    st.markdown(f"##### {run['plot_id']} · #{run['rec_id']} "
                + chip(mode, texts.RUN_KIND.get(mode, "info")) + " " + chip(texts.status_label(run["status_code"]), "info"),
                unsafe_allow_html=True)
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
    st.caption(L(f"Published {fmt_ts(run['created_at'])} by {run['created_by']} · inputs hash {run['inputs_hash'][:10]}…",
                 f"Terbit {fmt_ts(run['created_at'])} oleh {run['created_by']} · hash input {run['inputs_hash'][:10]}…"))
    for r in out.get("reasons") or []:
        st.markdown(f"- {r}")

    operational = mode in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED")
    if not operational:
        st.warning(texts.decision_error("not_operational"))
        return
    note = st.text_input(L("📝 Operator note (optional for APPROVE and DELAY)", "📝 Catatan operator (opsional untuk APPROVE dan DELAY)"),
                         key=f"note_{run['rec_id']}")
    b1, b2, b3 = st.columns(3)
    can_apply = bool(out.get("irrigate")) and out.get("total_mm") is not None
    if b1.button("APPROVE", type="primary", width="stretch", key=f"ap_{run['rec_id']}", disabled=not can_apply):
        _submit(run, "APPROVE", out["total_mm"], out.get("duration_h"), note, verified=out.get("duration_h") is not None)
    if b3.button("DELAY", width="stretch", key=f"dl_{run['rec_id']}"):
        _submit(run, "DELAY", 0.0, 0.0, note.strip() or L("Postponed by operator", "Ditunda oleh operator"))
    if b2.button("MODIFY", width="stretch", key=f"mo_{run['rec_id']}", disabled=not can_apply):
        st.session_state["op_modify"] = run["rec_id"]
    if st.session_state.get("op_modify") == run["rec_id"] and can_apply:
        _modify_form(run, out)
    if not can_apply:
        st.caption(L("APPROVE/MODIFY need a computed amount (irrigation recommended). DELAY is always possible.",
                     "APPROVE/MODIFY butuh jumlah terhitung (irigasi disarankan). DELAY selalu dapat dilakukan."))


def _modify_form(run, out):
    prof = repo.get_profile_by_id(run["profile_id"]) if run.get("profile_id") else None
    plot_profile = rsvc.build_profile(run["plot_id"], prof)[0] if prof else None
    with st.form(f"modify_{run['rec_id']}"):
        c1, c2 = st.columns(2)
        mm = c1.number_input("mm", min_value=0.0, max_value=1000.0, value=float(out["total_mm"]), step=0.5)
        hrs = c2.number_input(L("Duration (h)", "Durasi (jam)"), min_value=0.0, max_value=240.0,
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
        ev = pe.evaluate_modification(out, plot_profile, mm, plot_profile.q_plot_m3s.value if plot_profile and plot_profile.q_plot_m3s.known else None,
                                      duration_h=hrs or None) if plot_profile else {"valid": False, "issues": [{"code": "BAD_AMOUNT"}]}
        if not ev["valid"]:
            for i in ev["issues"]:
                st.error(texts.issue_text(i))
            return
        st.session_state.pop("op_modify", None)
        _submit(run, "MODIFY", mm, hrs if hrs else ev.get("duration_h"), reason, verified=bool(ev.get("duration_verified")))


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

    if auth.can_decide():
        st.subheader(L("📨 Recommendations awaiting validation", "📨 Rekomendasi menunggu validasi"))
        runs = store.pending_runs()
        if not runs:
            st.info(L("None. Publish one from **Prediction & Recommendation**.", "Tidak ada. Terbitkan dari **Prediksi & Rekomendasi**."))
        for run in runs:
            with st.container(border=True):
                _run_card(ctx, run)
    else:
        st.warning(L("Your role can view this tab but cannot record decisions.", "Role Anda dapat melihat tab ini tetapi tidak dapat mencatat keputusan."))

    st.subheader(L("📋 Decision history (append-only)", "📋 Riwayat keputusan (hanya tambah)"))
    rows = store.decisions(200)
    if not rows:
        st.info(L("No decisions recorded yet.", "Belum ada keputusan tercatat."))
        return
    df = pd.DataFrame(rows)
    df["ts"] = df["ts"].map(fmt_ts)
    show = df[["id", "ts", "plot_id", "username", "decision", "recommended_mm", "operator_mm", "duration_h", "run_mode",
               "record_status", "note"]]
    table(show, key="dec_hist", max_height=480)
    st.download_button(L("⬇️ Download CSV", "⬇️ Unduh CSV"), df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="somat_decision_history.csv", mime="text/csv", key="dec_csv")
    _corrections(rows)


def _corrections(rows):
    """Koreksi = record baru menggantikan yang lama; pembatalan (VOID) khusus admin. Tidak ada edit/hapus di tempat."""
    u = auth.current_user()
    active = [r for r in rows if r["record_status"] == "ACTIVE" and (auth.is_admin() or r["username"] == (u or {}).get("username"))]
    if not (u and active and auth.can_decide()):
        return
    with st.expander(L("Correct or void a record", "Koreksi atau batalkan catatan")):
        did = st.selectbox("ID", [r["id"] for r in active],
                           format_func=lambda i: next(f"#{r['id']} · {r['plot_id'] or '-'} · {r['decision']} · {r['operator_mm']} mm" for r in active if r["id"] == i),
                           key="corr_id")
        cur = next(r for r in active if r["id"] == did)
        with st.form("corr_form"):
            dec = st.selectbox(L("Decision", "Keputusan"), ["APPROVE", "MODIFY", "DELAY"],
                               index=["APPROVE", "MODIFY", "DELAY"].index(cur["decision"]) if cur["decision"] in ("APPROVE", "MODIFY", "DELAY") else 0)
            mm = st.number_input("mm", 0.0, 1000.0, float(cur["operator_mm"] or 0.0), 0.5)
            hrs = st.number_input(L("Duration (h)", "Durasi (jam)"), 0.0, 240.0, float(cur["duration_h"] or 0.0), 0.5)
            reason = st.text_input(L("Reason (required)", "Alasan (wajib)"))
            c1, c2 = st.columns(2)
            go_corr = c1.form_submit_button(L("Save correction", "Simpan koreksi"), type="primary")
            go_void = c2.form_submit_button(L("Void record (admin)", "Batalkan catatan (admin)"), disabled=not auth.is_admin())
        if (go_corr or go_void) and not reason.strip():
            st.warning(L("A reason is required.", "Alasan wajib diisi."))
        elif go_corr:
            try:
                repo.supersede_decision(did, u["username"], dec, mm, hrs or None, cur.get("note") or "", reason)
                store.invalidate()
                st.session_state["op_flash"] = ("success", L("Correction saved (the old record is kept as SUPERSEDED).",
                                                             "Koreksi tersimpan (catatan lama tetap tersimpan sebagai SUPERSEDED)."))
                st.rerun()
            except Exception:
                st.error(auth.auth_msg("db"))
        elif go_void and auth.is_admin():
            if repo.void_decision(did, u["username"], reason):
                store.invalidate()
                st.session_state["op_flash"] = ("success", L("Record voided.", "Catatan dibatalkan."))
                st.rerun()
