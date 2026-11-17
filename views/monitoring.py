"""views/monitoring.py - monitoring sensor + prakiraan BMKG (dari snapshot)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from i18n import L
from ui_kit import cards, line_by_sensor, make_line_chart, memo_fig, plot, sensor_donut, table
import sensor_qc
from views import bmkg_panels
from views.overview import mode_banner


_ACTION_TXT = {"USE": ("Use", "Dipakai"), "USE_WITH_WARNING": ("Use with warning", "Dipakai dengan peringatan"),
               "EXCLUDE_FROM_AUTOMATIC_USE": ("Excluded from automatic use", "Tidak dipakai otomatis")}


def _qc_panel(d):
    """Ringkasan QC: per sensor, kode flag dan tindakannya. Nilai mentah tidak diubah; flag hanya menentukan pemakaian."""
    with st.expander(L("Data quality checks (QC)", "Pemeriksaan kualitas data (QC)")):
        df = d.sensor_df
        if df is None or df.empty or not d.sensors:
            st.caption(L("No sensor data to check yet.", "Belum ada data sensor untuk diperiksa."))
            return
        now = pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None)
        rep = sensor_qc.coverage_report(sensor_qc.assess(df), d.sensors, now)
        lang = "en" if L("en", "id") == "en" else "id"   # L() memilih teks sesuai bahasa aktif
        idx = 0 if lang == "en" else 1
        rows = []
        for r in rep.itertuples(index=False):
            rows.append({
                L("Sensor", "Sensor"): r.sensor_id,
                L("Coverage 24 h", "Cakupan 24 j"): f"{100 * r.coverage:.0f}%",
                L("Last valid (h ago)", "Valid terakhir (jam lalu)"): "—" if pd.isna(r.age_hours) else f"{r.age_hours:.1f}",
                L("Suspect / bad", "Mencurigakan / buruk"): f"{r.n_suspect} / {r.n_bad}",
                L("Findings", "Temuan"): "; ".join(sensor_qc.describe(c, lang) for c in r.codes.split(",") if c) or "—",
                L("Action", "Tindakan"): _ACTION_TXT[r.action][idx],
            })
        table(pd.DataFrame(rows), key="sensor_qc")
        st.caption(L("Flags never change or delete raw readings; they only decide how a reading may be used. "
                     "Range limits are generic physical bounds, to be confirmed per device. Isolated jumps are flagged only when "
                     "readings exist on both sides.",
                     "Flag tidak mengubah atau menghapus pembacaan mentah; hanya menentukan bagaimana pembacaan boleh dipakai. "
                     "Batas rentang adalah batas fisik generik yang perlu dikonfirmasi per perangkat. Lonjakan terisolasi hanya "
                     "ditandai bila ada pembacaan di kedua sisi."))


def render(ctx):
    d, snap = ctx.d, ctx.snap
    tbl = d.sensor_table
    st.header(L("Sensor Monitoring", "Monitoring Sensor"))
    mode_banner(d)
    bmkg_panels.forecast_panel(snap, ctx.settings.bmkg_adm4)
    st.divider()

    n_on, n_total = d.n_online, d.n_total
    n_off = n_total - n_on
    sm_on = int(((tbl["Jenis"] == "soil_moisture") & (tbl["Status"] == "Online")).sum()) if len(tbl) else 0
    all_on = n_total > 0 and n_on == n_total
    q = d.sensor_summary.get("data_quality", 0)
    cards([
        dict(icon="📡", title=L("Sensors Online", "Sensor Online"), target=n_on, decimals=0, suffix=f" / {n_total}",
             note=L("No data > 3 h = offline", "Tanpa data > 3 jam = offline"),
             badge_text="Normal" if all_on else L("Attention", "Perhatian"), badge_kind="ok" if all_on else "warn",
             color="green" if all_on else "orange"),
        dict(icon="🌱", title=L("Soil Moisture Sensors", "Sensor Kelembapan Tanah"), target=sm_on, decimals=0, suffix=" / 6",
             note=L("Plots 1–6", "Petak 1–6"), badge_text="Sensor", badge_kind="info", color="blue"),
        dict(icon="🚨", title=L("Active Alerts", "Peringatan Aktif"), target=len(d.alerts), decimals=0,
             note=L("From the alert module", "Dari modul peringatan"),
             badge_text="Normal" if not d.alerts else L("Attention", "Perhatian"),
             badge_kind="ok" if not d.alerts else "warn", color="green" if not d.alerts else "orange"),
        dict(icon="🗄️", title=L("Data Quality", "Kualitas Data"), target=q, decimals=1, suffix=" %",
             note=L("Valid readings, 7 days", "Pembacaan valid 7 hari"), badge_text=L("Good", "Baik") if q >= 95 else L("Low", "Rendah"),
             badge_kind="ok" if q >= 95 else "warn", color="green" if q >= 95 else "orange"),
    ], columns=4)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        plot(memo_fig("donut", (d.version, n_on, n_off), lambda: sensor_donut(n_on, n_off)), key="mon_donut")
    with c2:
        sm = d.sensor_df[d.sensor_df["sensor_type"] == "soil_moisture"]
        plot(memo_fig("sm_trend", d.version, lambda: line_by_sensor(
            sm, L("Soil Moisture Trend per Sensor (7 days)", "Tren Kelembapan per Sensor (7 hari)"),
            L("Soil moisture (%)", "Kelembapan tanah (%)"))), key="mon_trend")
    table(tbl, key="sensor_status")
    _qc_panel(d)
    st.divider()

    st.header("Monitoring")
    st.caption(L("Trends use available sensor inputs. Crop water requirement is the DEMO prototype model, not a field result.",
                 "Tren memakai input sensor yang tersedia. Kebutuhan air tanaman adalah model prototipe DEMO, bukan hasil lapangan."))
    sd, md = d.sensor_daily, d.model_df
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        plot(memo_fig("l_sm", d.version, lambda: make_line_chart(sd, "soil_moisture", L("🌱 Soil Moisture", "🌱 Kelembapan Tanah"),
                                                                 L("Soil moisture (%)", "Kelembapan tanah (%)"))), key="mon_sm")
        plot(memo_fig("l_wl", d.version, lambda: make_line_chart(sd, "water_level", L("🌊 Canal Water Level", "🌊 Tinggi Muka Air Saluran"),
                                                                 L("Water level (m)", "Tinggi muka air (m)"))), key="mon_wl")
    with col2:
        plot(memo_fig("l_rf", d.version, lambda: make_line_chart(sd, "rainfall", L("🌧️ Rainfall", "🌧️ Curah Hujan"),
                                                                 L("Rainfall (mm)", "Curah hujan (mm)"), bar=True)), key="mon_rf")
        plot(memo_fig("l_cwr", d.version, lambda: make_line_chart(md, "crop_water_requirement", L("🌾 Crop Water Requirement (DEMO)", "🌾 Kebutuhan Air Tanaman (DEMO)"),
                                                                  L("CWR (mm/day)", "KAT (mm/hari)"))), key="mon_cwr")

    with st.expander(L("Stage A: sensor data", "Tahap A: data sensor")):
        table(pd.DataFrame(d.sensors), key="sensor_definition")
        st.write(L("Latest valid reading per sensor:", "Pembacaan valid terakhir tiap sensor:"))
        ok = d.sensor_df[d.sensor_df["status"] == "OK"].sort_values("timestamp").groupby("sensor_id").tail(1)
        table(ok, key="sensor_last_ok")
