"""views/execution.py - pelaksanaan irigasi AKTUAL (terpisah dari persetujuan) dan evaluasi prediksi vs pengamatan."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import auth
import repository as repo
import store
from i18n import L
from ui_kit import cards, fmt_num, fmt_ts, table

WIB = ZoneInfo("Asia/Jakarta")
METHODS = ("FLOW_METER", "WEIR_FORMULA", "GATE_ESTIMATE", "OTHER")


def _dt(d, t):
    return datetime.combine(d, t, tzinfo=WIB).astimezone(timezone.utc)


def render(ctx):
    u = auth.current_user()
    st.header(L("🚿 Irrigation Execution & Evaluation", "🚿 Pelaksanaan Irigasi & Evaluasi"))
    st.caption(L("Approval is not execution. Record what actually flowed (time and volume) so the model can be checked against reality. "
                 "Simulations never enter this table.",
                 "Persetujuan bukan pelaksanaan. Catat yang benar-benar mengalir (waktu dan volume) agar model dapat diuji terhadap kenyataan. "
                 "Simulasi tidak pernah masuk tabel ini."))
    pending = store.awaiting_execution()
    st.subheader(L("Approved decisions awaiting an execution record", "Keputusan disetujui yang menunggu catatan pelaksanaan"))
    if not pending:
        st.info(L("None.", "Tidak ada."))
    else:
        did = st.selectbox(L("Decision", "Keputusan"), [r["id"] for r in pending], key="ex_dec",
                           format_func=lambda i: next(f"#{r['id']} · {r['plot_id']} · {r['decision']} {fmt_num(r['operator_mm'])} mm · {fmt_ts(r['ts'])}"
                                                      for r in pending if r["id"] == i))
        cur = next(r for r in pending if r["id"] == did)
        _form(cur, u)

    st.subheader(L("Execution records", "Catatan pelaksanaan"))
    ev = store.events(None, 100)
    if ev:
        df = pd.DataFrame(ev)
        for c in ("arrived_at", "started_at", "ended_at", "h_after_at", "recorded_at"):
            if c in df:
                df[c] = df[c].map(lambda x: fmt_ts(x) if pd.notna(x) else "")
        table(df[["event_id", "plot_id", "decision_id", "arrived_at", "started_at", "ended_at", "actual_volume_m3",
                  "measurement_method", "h_after_cm", "record_status", "note"]], key="ex_tbl")
        act = [e for e in ev if e["record_status"] == "ACTIVE" and (auth.is_admin() or e["recorded_by"] == u["username"])]
        if act:
            with st.expander(L("Void a record", "Batalkan catatan")):
                eid = st.selectbox("ID", [e["event_id"] for e in act], key="ex_void_id")
                reason = st.text_input(L("Reason (required)", "Alasan (wajib)"), key="ex_void_reason")
                if st.button(L("Void", "Batalkan"), key="ex_void_go"):
                    if not reason.strip():
                        st.warning(L("A reason is required.", "Alasan wajib diisi."))
                    else:
                        repo.void_irrigation_event(eid, u["username"], reason)
                        store.invalidate()
                        st.rerun()
    else:
        st.info(L("No execution records yet.", "Belum ada catatan pelaksanaan."))
    _evaluation()


def _form(dec, u):
    with st.form("ex_form", clear_on_submit=True):
        now = datetime.now(WIB)
        c1, c2 = st.columns(2)
        a_d = c1.date_input(L("Water arrived — date", "Air tiba — tanggal"), value=now.date())
        a_t = c2.time_input(L("Water arrived — time (WIB)", "Air tiba — jam (WIB)"), value=time(now.hour, now.minute), step=300)
        c3, c4 = st.columns(2)
        e_d = c3.date_input(L("Finished — date", "Selesai — tanggal"), value=now.date())
        e_t = c4.time_input(L("Finished — time (WIB)", "Selesai — jam (WIB)"), value=time(now.hour, now.minute), step=300)
        c5, c6 = st.columns(2)
        vol = c5.number_input(L("Actual volume (m³)", "Volume aktual (m³)"), min_value=0.0, value=0.0, step=10.0)
        q = c6.number_input(L("Plot discharge (m³/s, optional)", "Debit ke petak (m³/s, opsional)"), min_value=0.0, value=0.0, step=0.005, format="%.4f")
        method = st.selectbox(L("Measurement method", "Cara pengukuran"), METHODS)
        c7, c8 = st.columns(2)
        h_after = c7.number_input(L("h after irrigation (cm, optional)", "h setelah irigasi (cm, opsional)"), min_value=-80.0, max_value=80.0, value=0.0, step=0.5)
        use_h = c8.checkbox(L("Include h after", "Sertakan h setelah"), value=False)
        note = st.text_input(L("Note", "Catatan"), max_chars=200)
        go_save = st.form_submit_button(L("Save execution record", "Simpan catatan pelaksanaan"), type="primary")
    if not go_save:
        return
    arr, end = _dt(a_d, a_t), _dt(e_d, e_t)
    if end < arr:
        st.error(L("Finish time is before arrival time.", "Waktu selesai sebelum waktu air tiba."))
    elif arr > datetime.now(timezone.utc) + pd.Timedelta(minutes=10):
        st.error(L("Arrival time cannot be in the future.", "Waktu air tiba tidak boleh di masa depan."))
    elif vol <= 0:
        st.error(L("Enter the actual volume (> 0 m³).", "Isi volume aktual (> 0 m³)."))
    else:
        repo.add_irrigation_event(dec["plot_id"], dec["id"], dec["rec_id"], arr, arr, end, float(vol), float(q) or None, method,
                                  float(h_after) if use_h else None, end if use_h else None, note, u["username"])
        store.invalidate()
        st.success(L("Saved.", "Tersimpan."))
        st.rerun()


def _evaluation():
    st.subheader(L("Prediction vs observation (h on water arrival)", "Prediksi vs pengamatan (h saat air tiba)"))
    rows = store.evaluation()
    pair = [r for r in rows if r.get("predicted_h_arrival") is not None and r.get("observed_h_at_arrival") is not None]
    if not pair:
        st.info(L("Needs execution records with a matching recommendation and a field h reading near the arrival time.",
                  "Butuh catatan pelaksanaan dengan rekomendasi terkait dan pembacaan h lapangan di sekitar waktu air tiba."))
        return
    err = [r["predicted_h_arrival"] - r["observed_h_at_arrival"] for r in pair]
    mae = sum(abs(e) for e in err) / len(err)
    bias = sum(err) / len(err)
    cards([dict(icon="📏", title="MAE h (cm)", value_text=fmt_num(mae, 2), note=L(f"n = {len(err)}", f"n = {len(err)}"), color="blue"),
           dict(icon="➕", title=L("Mean error (pred − obs)", "Galat rerata (prediksi − amatan)"), value_text=fmt_num(bias, 2), note="cm", color="orange")], columns=2)
    df = pd.DataFrame(pair)
    df["arrived_at"] = df["arrived_at"].map(fmt_ts)
    table(df[["plot_id", "arrived_at", "run_mode", "predicted_h_arrival", "observed_h_at_arrival", "recommended_mm", "actual_volume_m3"]], key="ex_eval")
    st.caption(L("Small samples are indicative only; this is not model validation.", "Sampel kecil hanya indikatif; ini bukan validasi model."))
