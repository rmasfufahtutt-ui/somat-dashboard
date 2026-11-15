"""views/observations.py - input h manual (tinggi air petak). Waktu kejadian dan waktu input dicatat terpisah;
koreksi = record baru yang menggantikan, pembatalan = VOID beralasan. Tidak ada edit/hapus di tempat."""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auth
import demo_mode
import formstate as fs
import repo_router as repo
import store
from i18n import L
from ui_kit import apply_plot_theme, fmt_ts, plot, table

WIB = ZoneInfo("Asia/Jakarta")
H_MIN, H_MAX = -60.0, 50.0           # cm; rentang masuk akal untuk validasi input (bukan batas fisika)


def _validate(value, observed_at):
    if value is None or not math.isfinite(value) or not (H_MIN <= value <= H_MAX):
        return L(f"h must be a number between {H_MIN:.0f} and {H_MAX:.0f} cm.", f"h harus angka antara {H_MIN:.0f} dan {H_MAX:.0f} cm.")
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=10):
        return L("Observation time cannot be in the future.", "Waktu pengamatan tidak boleh di masa depan.")
    return None


def _fill_example(pid):
    """Isi contoh (hanya DEMO): nilai wajar relatif terhadap pengamatan terakhir petak, ditandai sebagai contoh."""
    last = repo.latest_h(pid)
    base = float(last["value"]) if last else -8.0
    now_wib = datetime.now(WIB)
    st.session_state["obs_h_val"] = round(max(H_MIN, min(H_MAX, base - 2.0)) * 2) / 2.0
    st.session_state["obs_h_date"] = now_wib.date()
    st.session_state["obs_h_time"] = time(now_wib.hour, now_wib.minute)
    st.session_state["obs_h_note"] = L(demo_mode.EXAMPLE_NOTE_EN, demo_mode.EXAMPLE_NOTE_ID)


def render(ctx):
    u = auth.current_user()
    st.header(L("🪣 Field Observations (water depth h)", "🪣 Pengamatan Lapangan (tinggi air h)"))
    st.caption(L("h is read from the perforated field pipe: negative = water below the soil surface, positive = ponded. "
                 "Enter the time you actually read it — not the time you type it.",
                 "h dibaca dari pipa berlubang di petak: negatif = air di bawah permukaan tanah, positif = tergenang. "
                 "Isi waktu saat benar-benar dibaca — bukan saat mengetik."))
    plots = store.plots()
    if not plots:
        st.info(L("No plots yet (Admin → Plots & parameters).", "Belum ada petak (Admin → Petak & parameter)."))
        return
    ids = [p["plot_id"] for p in plots]
    fs.keep("obs_plot", ids[0], ids)
    pid = st.selectbox(L("Plot", "Petak"), ids, format_func=lambda i: next(f"{p['plot_id']} · {p['name']}" for p in plots if p["plot_id"] == i),
                       key="obs_plot")
    fs.sync("obs_plot")

    now_wib = datetime.now(WIB)
    demo = demo_mode.is_demo()
    fs.keep("obs_h_val", -10.0)
    fs.keep("obs_h_date", now_wib.date())
    fs.keep("obs_h_time", time(now_wib.hour, now_wib.minute))
    fs.keep("obs_h_note", "")
    fs.keep("obs_h_flag", "OK")
    if demo:
        st.info(L("DEMO: observations saved here are synthetic (demo repository) and never reach operational data.",
                  "DEMO: pengamatan yang disimpan di sini bersifat sintetis (repositori demo) dan tidak pernah masuk ke data operasional."))
        st.button(L("Fill example", "Isi contoh"), key="obs_fill_example", on_click=_fill_example, args=(pid,),
                  help=L("Fills a plausible value for this plot; you can still edit it before saving.",
                         "Mengisi nilai yang wajar untuk petak ini; tetap dapat diubah sebelum disimpan."))
    # Widget biasa (bukan st.form) agar isian bertahan saat pindah halaman; tombol Simpan tetap satu-satunya penulis.
    with st.container(key="h_form"):
        c1, c2, c3 = st.columns([1, 1, 1])
        val = c1.number_input(L("h (cm)", "h (cm)"), min_value=H_MIN - 20, max_value=H_MAX + 20, step=0.5, format="%.1f", key="obs_h_val")
        d = c2.date_input(L("Date read", "Tanggal dibaca"), max_value=now_wib.date(), key="obs_h_date")
        t = c3.time_input(L("Time read (WIB)", "Jam dibaca (WIB)"), step=300, key="obs_h_time")
        flag = st.selectbox(L("Quality", "Kualitas"), ["OK", "UNCERTAIN"], key="obs_h_flag", format_func=lambda x: {"OK": L("Normal reading", "Pembacaan normal"),
                                                                                                "UNCERTAIN": L("Uncertain (e.g. muddy, blocked)", "Diragukan (mis. keruh, tersumbat)")}[x])
        note = st.text_input(L("Note (optional)", "Catatan (opsional)"), max_chars=200, key="obs_h_note")
        go_save = st.button(L("Save observation", "Simpan pengamatan"), type="primary", key="obs_h_save")
    fs.sync("obs_h_val", "obs_h_date", "obs_h_time", "obs_h_note", "obs_h_flag")
    if go_save:
        obs_at = datetime.combine(d, t, tzinfo=WIB).astimezone(timezone.utc)
        err = _validate(float(val), obs_at)
        dup = [r for r in store.h_observations(pid, 20) if r["record_status"] == "ACTIVE"
               and abs((r["observed_at"] - obs_at).total_seconds()) < 60 and abs(r["value"] - val) < 1e-9]
        if err:
            st.error(err)
        elif dup:
            st.warning(L("An identical active observation already exists for this time — not saved again.",
                         "Pengamatan aktif yang identik pada waktu ini sudah ada — tidak disimpan lagi."))
        else:
            try:
                repo.add_h_observation(pid, float(val), obs_at, u["username"], note, flag)
                fs.reset("obs_h_val", "obs_h_date", "obs_h_time", "obs_h_note", "obs_h_flag")      # form kembali ke bawaan setelah tersimpan
                store.invalidate()
                st.success(L("Saved. Recommendations use the latest active observation.", "Tersimpan. Rekomendasi memakai pengamatan aktif terbaru."))
                st.rerun()
            except Exception:
                st.error(auth.auth_msg("db"))

    rows = store.h_observations(pid, 100)
    series = [r for r in rows if r["record_status"] == "ACTIVE"]
    if series:
        s = sorted(series, key=lambda r: r["observed_at"])
        fig = go.Figure(go.Scatter(x=[r["observed_at"] for r in s], y=[r["value"] for r in s], mode="lines+markers",
                                   line=dict(color="#2F80ED", width=2), name="h (cm)"))
        fig.add_hline(y=0, line_dash="dot", opacity=.5)
        fig.update_layout(title=L("Field-observed h", "h hasil pengamatan lapangan"), yaxis_title="h (cm)", height=300,
                          margin=dict(l=10, r=10, t=50, b=10))
        plot(apply_plot_theme(fig), key=f"obs_chart_{pid}")
    if rows:
        df = pd.DataFrame(rows)
        for c in ("observed_at", "received_at"):
            df[c] = df[c].map(fmt_ts)
        cols = ["obs_id", "value", "observed_at", "received_at", "recorded_by", "quality_flag", "record_status", "note"]
        if demo_mode.is_demo() and "origin" in df:
            df["asal"] = df["origin"].map({"SEED": "data awal (sintetis)", "USER": "diisi pengguna (demo)",
                                           "SCENARIO": "skenario (demo)"}).fillna("demo")
            cols.insert(6, "asal")
        table(df[cols], key=f"obs_tbl_{pid}")
        _corrections(pid, rows, u)
    else:
        st.info(L("No observations for this plot yet.", "Belum ada pengamatan untuk petak ini."))


def _corrections(pid, rows, u):
    mine = [r for r in rows if r["record_status"] == "ACTIVE" and (auth.is_admin() or r["recorded_by"] == u["username"])]
    if not mine:
        return
    with st.expander(L("Correct or void an observation", "Koreksi atau batalkan pengamatan")):
        oid = st.selectbox("ID", [r["obs_id"] for r in mine], key="obs_corr_id",
                           format_func=lambda i: next(f"#{r['obs_id']} · {r['value']} cm · {fmt_ts(r['observed_at'])}" for r in mine if r["obs_id"] == i))
        cur = next(r for r in mine if r["obs_id"] == oid)
        with st.form("obs_corr"):
            nv = st.number_input("h (cm)", H_MIN - 20, H_MAX + 20, float(cur["value"]), 0.5, format="%.1f")
            reason = st.text_input(L("Reason (required)", "Alasan (wajib)"))
            c1, c2 = st.columns(2)
            do_fix = c1.form_submit_button(L("Save corrected value", "Simpan nilai koreksi"), type="primary")
            do_void = c2.form_submit_button(L("Void", "Batalkan"))
        if (do_fix or do_void) and not reason.strip():
            st.warning(L("A reason is required.", "Alasan wajib diisi."))
        elif do_fix:
            err = _validate(float(nv), cur["observed_at"])
            if err:
                st.error(err)
            else:
                repo.add_h_observation(pid, float(nv), cur["observed_at"], u["username"], f"koreksi #{oid}: {reason}", cur["quality_flag"], supersedes_id=oid)
                store.invalidate()
                st.rerun()
        elif do_void:
            repo.void_observation(oid, u["username"], reason)
            store.invalidate()
            st.rerun()
