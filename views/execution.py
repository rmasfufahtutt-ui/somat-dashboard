"""views/execution.py - pelaksanaan irigasi AKTUAL (terpisah dari persetujuan) dan evaluasi prediksi vs pengamatan."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import auth
import demo_mode
import formstate as fs
import repo_router as repo
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
    if demo_mode.is_demo():
        st.info(L("DEMO: this page records SIMULATED execution only (marked [SIMULATION]). Nothing here is a field measurement, "
                  "and nothing reaches operational data.",
                  "DEMO: halaman ini hanya mencatat pelaksanaan SIMULASI (ditandai [SIMULASI]). Tidak ada yang merupakan pengukuran lapangan "
                  "dan tidak ada yang masuk ke data operasional."))
    pending = store.awaiting_execution()
    st.subheader(L("Approved decisions awaiting an execution record", "Keputusan disetujui yang menunggu catatan pelaksanaan"))
    if not pending:
        st.info(L("None.", "Tidak ada."))
    else:
        fs.keep("ex_dec", pending[0]["id"], [r["id"] for r in pending])
        did = st.selectbox(L("Decision", "Keputusan"), [r["id"] for r in pending], key="ex_dec",
                           format_func=lambda i: next(f"#{r['id']} · {r['plot_id']} · {r['decision']} {fmt_num(r['operator_mm'])} mm · {fmt_ts(r['ts'])}"
                                                      for r in pending if r["id"] == i))
        fs.sync("ex_dec")
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


def _fill_example(dec):
    """Isi contoh pelaksanaan SIMULASI dari keputusan: volume = jumlah keputusan x luas, h setelah dari neraca mesin."""
    import demo_service as ds
    now = datetime.now(WIB)
    prof = repo.get_active_profile(dec["plot_id"]) or {}
    area = ((prof.get("params") or {}).get("area_ha") or {}).get("value") or 1.0
    mm = float(dec.get("operator_mm") or 0.0)
    dur = float(dec.get("duration_h") or 2.0)
    run = repo.get_run(dec["rec_id"]) if dec.get("rec_id") else None
    h_arr = ((run or {}).get("output") or {}).get("h_arrival_cm")
    end = now + pd.Timedelta(hours=dur)
    ss = st.session_state
    ss["ex_a_d"], ss["ex_a_t"] = now.date(), time(now.hour, now.minute)
    ss["ex_e_d"], ss["ex_e_t"] = end.date(), time(end.hour, end.minute)
    ss["ex_vol"] = round(10.0 * area * mm, 1)
    ss["ex_q"] = round((ss["ex_vol"] / (dur * 3600.0)) if dur > 0 else 0.0, 4)
    ss["ex_method"] = "OTHER"
    if h_arr is not None:
        try:
            ss["ex_h_after"], ss["ex_use_h"] = round(ds.simulated_h_after(dec["plot_id"], h_arr, mm), 1), True
        except Exception:
            pass
    ss["ex_note"] = L(demo_mode.EXAMPLE_NOTE_EN, demo_mode.EXAMPLE_NOTE_ID)


def _form(dec, u):
    now = datetime.now(WIB)
    ss = st.session_state
    EX_KEYS = ("ex_a_d", "ex_a_t", "ex_e_d", "ex_e_t", "ex_vol", "ex_q", "ex_method", "ex_h_after", "ex_use_h", "ex_note")
    for k, v in (("ex_a_d", now.date()), ("ex_a_t", time(now.hour, now.minute)), ("ex_e_d", now.date()),
                 ("ex_e_t", time(now.hour, now.minute)), ("ex_vol", 0.0), ("ex_q", 0.0), ("ex_method", METHODS[0]),
                 ("ex_h_after", 0.0), ("ex_use_h", False), ("ex_note", "")):
        fs.keep(k, v)
    if demo_mode.is_demo():
        st.button(L("Fill example", "Isi contoh"), key="ex_fill_example", on_click=_fill_example, args=(dec,),
                  help=L("Fills a simulated execution consistent with the decision; editable before saving.",
                         "Mengisi pelaksanaan simulasi yang konsisten dengan keputusan; dapat diubah sebelum disimpan."))
    with st.container(key="ex_form"):            # widget biasa agar isian bertahan saat pindah halaman
        c1, c2 = st.columns(2)
        a_d = c1.date_input(L("Water arrived — date", "Air tiba — tanggal"), key="ex_a_d")
        a_t = c2.time_input(L("Water arrived — time (WIB)", "Air tiba — jam (WIB)"), step=300, key="ex_a_t")
        c3, c4 = st.columns(2)
        e_d = c3.date_input(L("Finished — date", "Selesai — tanggal"), key="ex_e_d")
        e_t = c4.time_input(L("Finished — time (WIB)", "Selesai — jam (WIB)"), step=300, key="ex_e_t")
        c5, c6 = st.columns(2)
        vol = c5.number_input(L("Actual volume (m³)", "Volume aktual (m³)"), min_value=0.0, step=10.0, key="ex_vol")
        q = c6.number_input(L("Plot discharge (m³/s, optional)", "Debit ke petak (m³/s, opsional)"), min_value=0.0, step=0.005, format="%.4f", key="ex_q")
        method = st.selectbox(L("Measurement method", "Cara pengukuran"), METHODS, key="ex_method")
        c7, c8 = st.columns(2)
        h_after = c7.number_input(L("h after irrigation (cm, optional)", "h setelah irigasi (cm, opsional)"), min_value=-80.0, max_value=80.0, step=0.5, key="ex_h_after")
        use_h = c8.checkbox(L("Include h after", "Sertakan h setelah"), key="ex_use_h")
        note = st.text_input(L("Note", "Catatan"), max_chars=200, key="ex_note")
        go_save = st.button(L("Save execution record", "Simpan catatan pelaksanaan"), type="primary", key="ex_save")
    fs.sync(*EX_KEYS)
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
        note_txt = ("[SIMULASI] " + note) if demo_mode.is_demo() and not note.startswith("[SIMULASI]") else note
        repo.add_irrigation_event(dec["plot_id"], dec["id"], dec["rec_id"], arr, arr, end, float(vol), float(q) or None, method,
                                  float(h_after) if use_h else None, end if use_h else None, note_txt, u["username"])
        fs.reset(*EX_KEYS)
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
    if demo_mode.is_demo():
        _chain(rows)


def _chain(rows):
    """DEMO: rantai rekomendasi → keputusan → pelaksanaan (simulasi) dengan selisihnya."""
    data = []
    for r in rows:
        area_mm = None
        if r.get("recommended_volume_m3") and r.get("recommended_mm"):
            area_mm = r["recommended_volume_m3"] / r["recommended_mm"]          # m3 per mm (= 10 * ha)
        actual_mm = (r["actual_volume_m3"] / area_mm) if (area_mm and r.get("actual_volume_m3") is not None) else None
        data.append({L("Plot", "Petak"): r["plot_id"], L("SOMAT (mm)", "SOMAT (mm)"): r.get("recommended_mm"),
                     L("Decision", "Keputusan"): r.get("decision"), L("Operator (mm)", "Operator (mm)"): r.get("decision_mm"),
                     L("Actual (mm, sim)", "Aktual (mm, sim)"): None if actual_mm is None else round(actual_mm, 1),
                     L("SOMAT dur (h)", "Durasi SOMAT (jam)"): r.get("recommended_duration_h"),
                     L("Actual dur (h)", "Durasi aktual (jam)"): r.get("actual_duration_h"),
                     L("Pred h arrival", "Prediksi h tiba"): r.get("predicted_h_arrival"),
                     L("Measured h (sim)", "h terukur (sim)"): r.get("observed_h_at_arrival"),
                     L("h after", "h setelah"): r.get("h_after_cm")})
    if data:
        st.subheader(L("Chain: SOMAT → operator → simulated execution", "Rantai: SOMAT → operator → pelaksanaan simulasi"))
        table(pd.DataFrame(data).round(2), key="ex_chain")
