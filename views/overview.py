"""views/overview.py - ringkasan kondisi. Hanya membaca snapshot + turunan yang sudah di-memo."""
from __future__ import annotations

import streamlit as st

import store
from i18n import L
from legacy_prototype import ASSUMPTIONS
from ui_kit import banner, cards, chip, fmt_num, fmt_ts, make_combo_chart, memo_fig, plot, table

MODE_TEXT = {
    "LIVE": ("ok", "Live sensor data from Google Sheets (background fetch).",
             "Data sensor live dari Google Sheets (ditarik di latar belakang)."),
    "CACHED_DB": ("warn", "Showing the last archived sensor data from the database while the first live fetch completes.",
                  "Menampilkan arsip sensor terakhir dari database sambil menunggu penarikan live pertama."),
    "WAITING_FOR_DATA": ("warn", "Google Sheets is connected but has no sensor readings yet — DEMO values are shown.",
                         "Google Sheets terhubung tetapi belum ada pembacaan — nilai DEMO ditampilkan."),
    "SIMULATION_FALLBACK": ("bad", "Google Sheets unavailable — DEMO (simulated) values are shown. Not field measurements.",
                            "Google Sheets tidak terjangkau — nilai DEMO (simulasi) ditampilkan. Bukan hasil pengukuran."),
    "SIMULATION": ("warn", "No sensor source configured — DEMO (simulated) values are shown. Not field measurements.",
                   "Sumber sensor belum dikonfigurasi — nilai DEMO (simulasi) ditampilkan. Bukan hasil pengukuran."),
}


def mode_banner(d):
    kind, en, idn = MODE_TEXT[d.mode]
    extra = ""
    if d.mode in ("LIVE", "CACHED_DB") and set(d.source_types) & {"DUMMY", "SIMULATED"}:
        extra = " " + L("Source type is DUMMY: readings come from a test feed, not installed devices.",
                        "Jenis sumber DUMMY: pembacaan berasal dari umpan uji, bukan perangkat terpasang.")
        kind = "warn"
    banner(L(en, idn) + extra, kind)


def render(ctx):
    d = ctx.d
    st.header(L("Conditions Overview", "Ringkasan Kondisi (Overview)"))
    mode_banner(d)
    lt = d.latest
    low_m, heavy_r = 20, 20
    sm_ok = lt["soil_moisture"] >= low_m
    wl_ok = lt["water_level"] >= ASSUMPTIONS["min_water_level"]
    rain_ok = lt["rainfall"] < heavy_r
    q_ok = lt["available_discharge"] >= d.hydraulic["required_discharge"]
    normal = d.system_status == "NORMAL"
    ok = lambda b, a, c: (a if b else c)
    cards([
        dict(icon="🌱", title=L("Soil Moisture", "Kelembapan Tanah"), target=lt["soil_moisture"], decimals=1, suffix=" %",
             note=L(f"Low limit {low_m}%", f"Batas rendah {low_m}%"), badge_text=ok(sm_ok, "Normal", L("Low", "Rendah")),
             badge_kind=ok(sm_ok, "ok", "warn"), color=ok(sm_ok, "green", "orange")),
        dict(icon="🌊", title=L("Canal Water Level", "Tinggi Muka Air"), target=lt["water_level"], decimals=2, suffix=" m",
             note=f"Minimum {ASSUMPTIONS['min_water_level']} m", badge_text=ok(wl_ok, "Normal", L("Low", "Rendah")),
             badge_kind=ok(wl_ok, "ok", "warn"), color=ok(wl_ok, "blue", "orange")),
        dict(icon="🌧️", title=L("Rainfall", "Curah Hujan"), target=lt["rainfall"], decimals=1, suffix=" mm",
             note=L(f"High limit {heavy_r} mm", f"Batas tinggi {heavy_r} mm"), badge_text=ok(rain_ok, "Normal", L("High", "Tinggi")),
             badge_kind=ok(rain_ok, "ok", "warn"), color=ok(rain_ok, "blue", "orange")),
        dict(icon="💧", title=L("Available Discharge", "Debit Tersedia"), target=lt["available_discharge"], decimals=3,
             suffix=" m³/s", note=L(f"Required {d.hydraulic['required_discharge']:.3f} m³/s (DEMO model)",
                                    f"Dibutuhkan {d.hydraulic['required_discharge']:.3f} m³/s (model DEMO)"),
             badge_text=ok(q_ok, L("Sufficient", "Cukup"), L("Short", "Kurang")), badge_kind=ok(q_ok, "ok", "warn"),
             color=ok(q_ok, "blue", "orange")),
        dict(icon="🌾", title=L("Crop Water Requirement", "Kebutuhan Air Tanaman"), target=lt["crop_water_requirement"],
             decimals=1, suffix=L(" mm/day", " mm/hari"),
             note=L(f"Predicted irrigation {d.prediction['irrigation_mm']} mm (DEMO)",
                    f"Irigasi prediksi {d.prediction['irrigation_mm']} mm (DEMO)"), badge_text=L("Prototype", "Prototipe"),
             badge_kind="info", color="blue"),
        dict(icon="🛡️", title=L("System Status", "Status Sistem"), value_text="NORMAL" if normal else L("ATTENTION", "PERHATIAN"),
             note=L("No active alerts", "Tidak ada peringatan aktif") if normal else L("Operator validation needed", "Perlu validasi operator"),
             badge_text="Normal" if normal else L("Attention", "Perhatian"), badge_kind=ok(normal, "ok", "warn"),
             color=ok(normal, "green", "red")),
    ], columns=3)

    # ---- petak (v2): h terakhir, status rekomendasi ----
    st.subheader(L("Plots (field-observed water depth h)", "Petak (tinggi air h hasil pengamatan lapangan)"))
    ov = store.plot_overview()
    if not ov:
        st.info(L("No plots yet. An administrator can add plots and parameters in Admin → Plots & parameters.",
                  "Belum ada petak. Administrator dapat menambah petak dan parameter di Admin → Petak & parameter."))
    else:
        rows = []
        for r in ov:
            h, pend, prof = r["h"], r["pending"], r["profile"]
            rows.append({L("Plot", "Petak"): f"{r['plot']['plot_id']} · {r['plot']['name']}",
                         L("Last h (cm)", "h terakhir (cm)"): fmt_num(h["value"]) if h else "—",
                         L("Observed at", "Diamati"): fmt_ts(h["observed_at"]) if h else L("no observation", "belum ada pengamatan"),
                         L("Profile", "Profil"): f"v{prof['version']} · {prof['validation_status']}" if prof else "—",
                         L("Recommendation", "Rekomendasi"): (f"#{pend['rec_id']} · {pend['status_code']} · {pend['run_mode']}"
                                                              if pend else "—")})
        table(rows, key="ov_plots")

    st.markdown(f'<div class="k-banner info">{chip(L("Status", "Status"), "info")} '
                + L("System and field status", "Status sistem dan lahan") + ": "
                + " · ".join([("✔" if sm_ok else "⚠") + " " + L("soil moisture", "kelembapan tanah"),
                              ("✔" if wl_ok else "⚠") + " " + L("water level", "muka air"),
                              ("✔" if rain_ok else "⚠") + " " + L("rainfall", "hujan"),
                              ("✔" if d.hydraulic["feasible"] else "⚠") + " " + L("hydraulics (DEMO)", "hidraulik (DEMO)"),
                              ("✔" if not d.alerts else "⚠") + " " + L(f"{len(d.alerts)} alert(s)", f"{len(d.alerts)} peringatan")])
                + "</div>", unsafe_allow_html=True)

    st.header(L("Latest Conditions Chart (Last 14 Days)", "Grafik Kondisi Terbaru (14 Hari Terakhir)"))
    st.caption(L("Drag to zoom. Days without readings are left blank, not filled with invented numbers.",
                 "Drag untuk zoom. Hari tanpa pembacaan dibiarkan kosong, tidak diisi angka buatan."))
    plot(memo_fig("ov_combo", d.version, lambda: make_combo_chart(d.sensor_daily.tail(14))), key="ov_combo", height=360)
