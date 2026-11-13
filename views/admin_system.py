"""views/admin_system.py - status penarikan data latar belakang, konfigurasi (tanpa menampilkan rahasia), dan log ingest."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import store
from i18n import L
from ui_kit import chip, fmt_ts, table


def render(hub, settings):
    if hub is None:
        st.info(L("Data hub is not running.", "Data hub tidak berjalan."))
        return
    st.subheader(L("Background data hub", "Data hub latar belakang"))
    c1, c2, c3 = st.columns(3)
    c1.metric("Thread", L("running", "berjalan") if hub.alive() else L("stopped", "berhenti"))
    c2.metric(L("Snapshot version", "Versi snapshot"), hub.snapshot().version)
    c3.metric(L("Database", "Database"), L("connected", "terhubung") if db.active() else (db.last_error() or L("not configured", "belum dikonfigurasi")))
    rows = []
    for r in hub.status_rows():
        age = r["age_s"]
        rows.append({L("Source", "Sumber"): r["source"], L("Last attempt OK", "Percobaan terakhir OK"): "✔" if r["ok"] else "✖",
                     L("Data origin", "Asal data"): r["origin"], L("Age (s)", "Umur (dtk)"): "—" if age is None else age,
                     L("Rows", "Baris"): r["rows"], L("Interval (s)", "Interval (dtk)"): int(r["interval_s"]),
                     L("Fail streak", "Gagal beruntun"): r["fail_streak"], L("Stale", "Basi"): "⚠" if r["stale"] else "",
                     L("Error", "Galat"): r["error"] or "", L("Message", "Pesan"): r["message"]})
    table(pd.DataFrame(rows), key="sys_hub")
    if st.button(L("Fetch now (all sources)", "Tarik sekarang (semua sumber)"), key="sys_refresh"):
        hub.refresh_now()
        st.toast(L("Fetch requested; the page updates itself.", "Penarikan diminta; halaman memperbarui sendiri."))
    st.caption(L("The page reads an in-memory snapshot, so switching tabs never waits on sensors, spreadsheets or BMKG. "
                 "A failed fetch never replaces the last good data; stale sources are flagged.",
                 "Halaman membaca snapshot di memori, sehingga pindah tab tidak menunggu sensor, spreadsheet, atau BMKG. "
                 "Penarikan gagal tidak menimpa data baik terakhir; sumber basi ditandai."))

    st.subheader(L("Configuration (secrets are never shown)", "Konfigurasi (rahasia tidak pernah ditampilkan)"))
    yes = lambda b: chip(L("set", "terisi") if b else L("missing", "kosong"), "ok" if b else "bad")
    st.markdown(f"- DATABASE_URL: {yes(bool(settings.db_url))}\n- SENSOR_SHEET_URL: {yes(bool(settings.sensor_url))}\n"
                f"- SENSOR_SHEET_READ_KEY: {yes(bool(settings.sensor_key))}\n- SENSOR_SOURCE_TYPE: `{settings.sensor_source_type}`\n"
                f"- BMKG ADM4: `{settings.bmkg_adm4}`", unsafe_allow_html=True)
    if settings.sensor_source_type == "DUMMY":
        st.warning(L("Sensor source type is DUMMY: readings are a test feed. Set it to SENSOR only when real devices are installed.",
                     "Jenis sumber sensor DUMMY: pembacaan adalah umpan uji. Ubah ke SENSOR hanya bila perangkat nyata sudah terpasang."))
    st.caption(L(f"Refresh: sensor {int(settings.refresh_sensor_s)} s · forecast {int(settings.refresh_forecast_s)} s · warnings {int(settings.refresh_warning_s)} s · "
                 f"max h age {settings.max_h_age_hours:g} h · recommendation validity {settings.rec_expiry_hours:g} h",
                 f"Penyegaran: sensor {int(settings.refresh_sensor_s)} dtk · prakiraan {int(settings.refresh_forecast_s)} dtk · peringatan {int(settings.refresh_warning_s)} dtk · "
                 f"umur maks h {settings.max_h_age_hours:g} jam · masa berlaku rekomendasi {settings.rec_expiry_hours:g} jam"))

    st.subheader(L("Ingest log (DB, includes the external worker)", "Log ingest (DB, termasuk worker eksternal)"))
    log = store.ingest_log(50)
    if log:
        df = pd.DataFrame(log)
        df["ts"] = df["ts"].map(fmt_ts)
        table(df, key="sys_ingest")
    else:
        st.info(L("Empty.", "Kosong."))
