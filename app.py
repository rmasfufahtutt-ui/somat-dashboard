# ============================================================
# SOMAT - Smart Adaptive Irrigation Management System
# PROTOTYPE: seluruh data di bawah adalah DATA SIMULASI,
# bukan data penelitian aktual.
# ============================================================
from datetime import datetime
from pathlib import Path
import base64
import html
import json
import re

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="SOMAT Dashboard",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- ASSUMPTIONS (angka contoh, bukan data lapangan) ----------------
# Semua nilai di bawah adalah ASUMSI PROTOTYPE. Ubah di sini saja,
# lalu seluruh fungsi di bawah otomatis memakai nilai yang sama.
ASSUMPTIONS = {
    "area_ha": 50,                # luas areal layanan (ha)
    "delivery_hours": 8,          # lama pemberian air (jam)
    "min_water_level": 0.90,      # batas minimum muka air (m)
    "gate_max_discharge": 0.45,   # kapasitas maksimum pintu (m3/s)
}


def generate_simulated_data(days=30, seed=42):
    """Membuat tabel data harian simulasi untuk prototype SOMAT."""
    # "seed" membuat angka acak selalu sama setiap dijalankan,
    # jadi hasil demo ke dosen konsisten.
    rng = np.random.default_rng(seed)

    # Daftar tanggal: 30 hari berakhir hari ini
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days)

    # Hujan: kebanyakan hari kering, kadang hujan
    is_rainy = rng.random(days) < 0.25
    rainfall = np.where(is_rainy, rng.gamma(2.0, 6.0, days), 0.0)

    # Evapotranspirasi acuan (ET0): sekitar 4-5 mm/hari + sedikit variasi
    et0 = np.clip(rng.normal(4.5, 0.6, days), 2.5, 6.5)

    # Kelembapan tanah: turun karena penguapan, naik saat hujan
    soil_moisture = np.zeros(days)
    soil_moisture[0] = 32.0
    for i in range(1, days):
        change = -0.9 * et0[i] / 4.5 + 0.35 * rainfall[i]
        soil_moisture[i] = np.clip(soil_moisture[i - 1] + change, 12, 45)

    # Tinggi muka air saluran (m): naik saat hujan, ada variasi kecil
    water_level = np.clip(1.10 + 0.012 * rainfall + rng.normal(0, 0.05, days), 0.6, 1.8)

    # Debit tersedia (m3/s): terkait tinggi muka air
    available_discharge = np.clip(0.30 * (water_level / 1.10) ** 1.5, 0.05, 0.80)

    # Kebutuhan air tanaman (mm/hari): naik saat ET0 tinggi,
    # turun saat tanah sudah lembap atau hujan
    crop_water_requirement = np.clip(
        et0 * 1.1 - 0.08 * (soil_moisture - 25) - 0.4 * rainfall, 0, None
    )

    return pd.DataFrame({
        "date": dates,
        "soil_moisture": soil_moisture.round(1),
        "rainfall": rainfall.round(1),
        "et0": et0.round(2),
        "water_level": water_level.round(2),
        "available_discharge": available_discharge.round(3),
        "crop_water_requirement": crop_water_requirement.round(1),
    })


# ---------------- Prediction logic (PROTOTYPE) ----------------
def predict_irrigation_requirement(
    soil_moisture,      # kelembapan tanah hari ini (%)
    rainfall,           # hujan hari ini (mm)
    et0,                # evapotranspirasi acuan (mm/hari)
    kc=1.1,             # koefisien tanaman (padi fase tengah, contoh)
    target_moisture=30, # target kelembapan tanah (%)
    root_depth_mm=300,  # kedalaman zona akar (mm)
    effective_rain=0.8, # fraksi hujan yang efektif
):
    """
    PROTOTYPE PREDICTION LOGIC - bukan model AI final tesis.

    Rumus sederhana berbasis aturan (rule-based) untuk menghasilkan
    estimasi kebutuhan irigasi (mm). Fungsi ini sengaja dipisah dari
    tampilan dashboard agar nanti dapat diganti dengan model prediksi
    yang lebih baik tanpa mengubah bagian lain.
    """
    # 1. Kebutuhan air tanaman dasar
    base_demand = et0 * kc

    # 2. Kekurangan air di tanah (dikonversi dari % ke mm)
    moisture_deficit = max(0.0, target_moisture - soil_moisture)
    deficit_mm = moisture_deficit / 100 * root_depth_mm

    # 3. Hujan yang benar-benar bermanfaat
    useful_rain = rainfall * effective_rain

    # 4. Hasil akhir, tidak boleh negatif
    requirement = max(0.0, base_demand + deficit_mm - useful_rain)

    return {
        "irrigation_mm": round(requirement, 1),
        "base_demand": round(base_demand, 1),
        "deficit_mm": round(deficit_mm, 1),
        "useful_rain": round(useful_rain, 1),
    }


# ---------------- Hydraulic feasibility (PROTOTYPE) ----------------
def check_hydraulic_feasibility(
    irrigation_mm,                                   # kebutuhan irigasi hasil prediksi (mm)
    available_discharge,                             # debit tersedia di saluran (m3/s)
    water_level,                                     # tinggi muka air saluran (m)
    area_ha=ASSUMPTIONS["area_ha"],                  # luas areal layanan (ha) - CONTOH
    delivery_hours=ASSUMPTIONS["delivery_hours"],    # lama pemberian air (jam) - CONTOH
    min_water_level=ASSUMPTIONS["min_water_level"],  # batas minimum muka air (m) - CONTOH
    gate_max_discharge=ASSUMPTIONS["gate_max_discharge"],  # kapasitas pintu (m3/s) - CONTOH
):
    """
    PROTOTYPE HYDRAULIC LOGIC - aturan sederhana (rule-based),
    bukan model hidraulik final tesis. Semua batas di atas adalah
    angka contoh. Fungsi ini sengaja dipisah agar nanti dapat diganti
    dengan model hidraulik yang lebih baik.
    """
    # 1. Ubah mm menjadi debit yang dibutuhkan (m3/s)
    volume_m3 = irrigation_mm * area_ha * 10
    required_discharge = volume_m3 / (delivery_hours * 3600)

    # 2. Tiga aturan cek
    checks = [
        {
            "Pemeriksaan": "Tinggi muka air saluran",
            "Nilai": f"{water_level:.2f} m",
            "Batas": f">= {min_water_level:.2f} m",
            "Result": "PASS" if water_level >= min_water_level else "FAIL",
        },
        {
            "Pemeriksaan": "Debit tersedia",
            "Nilai": f"{available_discharge:.3f} m3/s (dibutuhkan {required_discharge:.3f})",
            "Batas": "tersedia >= dibutuhkan",
            "Result": "PASS" if available_discharge >= required_discharge else "FAIL",
        },
        {
            "Pemeriksaan": "Batas operasi pintu",
            "Nilai": f"{required_discharge:.3f} m3/s",
            "Batas": f"<= {gate_max_discharge:.2f} m3/s",
            "Result": "PASS" if required_discharge <= gate_max_discharge else "FAIL",
        },
    ]

    # 3. FEASIBLE hanya jika semua cek lolos
    feasible = all(c["Result"] == "PASS" for c in checks)

    return {
        "feasible": feasible,
        "status": "FEASIBLE" if feasible else "NOT FEASIBLE",
        "required_discharge": round(required_discharge, 3),
        "checks": checks,
    }


# ---------------- SOMAT recommendation engine (PROTOTYPE) ----------------
def generate_recommendation(
    prediction,                 # hasil predict_irrigation_requirement()
    hydraulic,                  # hasil check_hydraulic_feasibility()
    available_discharge,        # debit tersedia (m3/s)
    soil_moisture,              # kelembapan tanah (%)
    area_ha=ASSUMPTIONS["area_ha"],
    delivery_hours=ASSUMPTIONS["delivery_hours"],
    gate_max_discharge=ASSUMPTIONS["gate_max_discharge"],
):
    """
    PROTOTYPE RECOMMENDATION LOGIC - aturan sederhana, bukan keputusan final.
    Menggabungkan prediksi kebutuhan air dan cek hidraulik menjadi saran
    operasi. Operator tetap pengambil keputusan akhir.
    """
    demand_mm = prediction["irrigation_mm"]
    reasons = []

    # Apakah muka air saluran cukup? (cek pertama pada hasil hidraulik)
    level_ok = hydraulic["checks"][0]["Result"] == "PASS"

    # Debit yang benar-benar bisa dipakai
    if level_ok:
        usable_discharge = min(available_discharge, gate_max_discharge)
    else:
        usable_discharge = 0.0

    # Jumlah air maksimum (mm) yang bisa dialirkan dalam jam pemberian air
    max_deliverable_mm = usable_discharge * delivery_hours * 3600 / (area_ha * 10)

    # Tentukan jumlah irigasi yang direkomendasikan
    if demand_mm <= 0:
        recommended_mm = 0.0
        reasons.append("Prediksi kebutuhan 0 mm, sehingga irigasi belum diperlukan.")
    elif hydraulic["feasible"]:
        recommended_mm = demand_mm
        reasons.append(
            f"Prediksi kebutuhan {demand_mm} mm dan semua cek hidraulik lolos, "
            "sehingga kebutuhan penuh disarankan."
        )
    else:
        recommended_mm = min(demand_mm, max_deliverable_mm)
        reasons.append(
            f"Prediksi kebutuhan {demand_mm} mm, tetapi cek hidraulik TIDAK LAYAK."
        )
        if not level_ok:
            reasons.append("Tinggi muka air saluran di bawah batas minimum.")
        reasons.append(
            f"Hanya sekitar {max_deliverable_mm:.1f} mm yang dapat dialirkan dalam "
            f"{delivery_hours} jam, sehingga rekomendasi dikurangi."
        )
    recommended_mm = round(recommended_mm, 1)

    # Hitung durasi pemberian air (jam)
    if recommended_mm > 0 and usable_discharge > 0:
        duration_hours = recommended_mm * area_ha * 10 / (usable_discharge * 3600)
    else:
        duration_hours = 0.0

    # Tentukan prioritas
    if soil_moisture < 20 or demand_mm >= 20:
        priority = "HIGH"
        reasons.append("Tanah sangat kering atau kebutuhan besar, sehingga prioritas TINGGI.")
    elif demand_mm >= 3:
        priority = "NORMAL"
        reasons.append("Kebutuhan sedang, sehingga prioritas NORMAL.")
    else:
        priority = "LOW"
        reasons.append("Kebutuhan sangat kecil, sehingga prioritas RENDAH.")

    return {
        "recommended_mm": recommended_mm,
        "duration_hours": round(duration_hours, 1),
        "feasibility": hydraulic["status"],
        "priority": priority,
        "reasons": reasons,
    }


# ---------------- Decision log (disimpan selama session) ----------------
def log_decision(decision, recommendation, irrigation_mm, duration_hours, note):
    """Menambahkan satu catatan keputusan operator ke Decision Log."""
    st.session_state.pop("pending_recommendation", None)
    feedback = simulate_field_response(
        decision=decision,
        operator_mm=irrigation_mm,
        recommended_mm=recommendation["recommended_mm"],
        soil_moisture=float(latest["soil_moisture"]),
    )
    st.session_state["last_feedback"] = {
        "decision": decision,
        "recommended_mm": recommendation["recommended_mm"],
        "operator_mm": irrigation_mm,
        "feedback": feedback,
    }
    st.session_state["decision_log"].append({
        "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Keputusan": decision,
        "Rekomendasi SOMAT (mm)": recommendation["recommended_mm"],
        "Irigasi operator (mm)": irrigation_mm,
        "Durasi operator (jam)": duration_hours,
        "Alasan / catatan": note,
        "Kelembapan tanah setelah (simulasi, %)": feedback["new_moisture"],
        "Respons lapangan (simulasi)": feedback["status"],
    })


# ---------------- Alerts / anomaly (PROTOTYPE) ----------------
def detect_alerts(
    soil_moisture,          # kelembapan tanah (%)
    water_level,            # tinggi muka air saluran (m)
    rainfall,               # hujan hari ini (mm)
    prediction,             # hasil predict_irrigation_requirement()
    recommendation,         # hasil generate_recommendation()
    low_moisture=20,        # batas kelembapan tanah rendah (%) - CONTOH
    min_water_level=ASSUMPTIONS["min_water_level"],
    heavy_rain=20,          # batas hujan tinggi (mm/hari) - CONTOH
):
    """
    PROTOTYPE ALERT LOGIC - aturan sederhana (rule-based), bukan
    metode deteksi anomali final tesis. Semua batas adalah angka contoh.
    """
    alerts = []

    if soil_moisture < low_moisture:
        alerts.append({
            "level": "warning",
            "title": "Kelembapan tanah terlalu rendah",
            "detail": f"Kelembapan tanah {soil_moisture}% di bawah batas {low_moisture}%.",
        })

    if water_level < min_water_level:
        alerts.append({
            "level": "error",
            "title": "Muka air saluran terlalu rendah",
            "detail": f"Tinggi muka air {water_level} m di bawah batas {min_water_level} m.",
        })

    if rainfall >= heavy_rain:
        alerts.append({
            "level": "warning",
            "title": "Hujan lebat",
            "detail": f"Curah hujan {rainfall} mm mencapai batas {heavy_rain} mm.",
        })

    if recommendation["recommended_mm"] < prediction["irrigation_mm"]:
        alerts.append({
            "level": "error",
            "title": "Kebutuhan melebihi kapasitas hidraulik",
            "detail": (
                f"Kebutuhan prediksi {prediction['irrigation_mm']} mm, tetapi hanya "
                f"{recommendation['recommended_mm']} mm yang direkomendasikan."
            ),
        })

    return alerts


# ---------------- Simulated field response / feedback (PROTOTYPE) ----------------
def simulate_field_response(
    decision,               # "APPROVE", "MODIFY", atau "DELAY"
    operator_mm,            # jumlah irigasi yang diputuskan operator (mm)
    recommended_mm,         # jumlah yang disarankan SOMAT (mm)
    soil_moisture,          # kelembapan tanah sebelum irigasi (%)
    target_moisture=30,     # target kelembapan tanah (%) - CONTOH
    root_depth_mm=300,      # kedalaman zona akar (mm) - CONTOH
):
    """
    PROTOTYPE FEEDBACK LOGIC - simulasi sederhana, bukan model tanaman
    atau tanah yang sesungguhnya. Tujuannya menunjukkan alur
    Recommendation -> Operator Decision -> Simulated Field Response.
    """
    # Kenaikan kelembapan tanah (%) dari irigasi (konversi mm -> %)
    moisture_gain = operator_mm / root_depth_mm * 100
    new_moisture = min(45.0, soil_moisture + moisture_gain)

    if new_moisture < target_moisture - 2:
        status = "Di bawah target"
    elif new_moisture <= target_moisture + 5:
        status = "Sesuai target"
    else:
        status = "Di atas target (risiko irigasi berlebih)"

    # Pesan umpan balik ke sistem SOMAT
    difference = operator_mm - recommended_mm
    if decision == "APPROVE":
        learning = "Operator menyetujui rekomendasi. Tidak perlu penyesuaian."
    elif decision == "DELAY":
        learning = "Operator menunda irigasi. SOMAT mencatat alasannya untuk ditinjau."
    elif difference > 0:
        learning = (
            f"Operator memberi {difference:.1f} mm LEBIH BANYAK dari rekomendasi. "
            "SOMAT mungkin perlu memperhitungkan kebutuhan yang lebih tinggi."
        )
    else:
        learning = (
            f"Operator memberi {abs(difference):.1f} mm LEBIH SEDIKIT dari rekomendasi. "
            "SOMAT mungkin melebih-lebihkan kebutuhan atau batas hidraulik."
        )

    return {
        "new_moisture": round(new_moisture, 1),
        "status": status,
        "learning": learning,
    }


# ---------------- Sensor simulasi (PROTOTYPE) ----------------
SENSORS = [
    {"sensor_id": "SM-01", "sensor_type": "soil_moisture", "location": "Petak 1", "unit": "%"},
    {"sensor_id": "SM-02", "sensor_type": "soil_moisture", "location": "Petak 2", "unit": "%"},
    {"sensor_id": "SM-03", "sensor_type": "soil_moisture", "location": "Petak 3", "unit": "%"},
    {"sensor_id": "SM-04", "sensor_type": "soil_moisture", "location": "Petak 4", "unit": "%"},
    {"sensor_id": "SM-05", "sensor_type": "soil_moisture", "location": "Petak 5", "unit": "%"},
    {"sensor_id": "SM-06", "sensor_type": "soil_moisture", "location": "Petak 6", "unit": "%"},
    {"sensor_id": "WL-01", "sensor_type": "water_level", "location": "Depan pintu tersier", "unit": "m"},
    {"sensor_id": "RF-01", "sensor_type": "rainfall",
     "location": "Stasiun hujan eksternal (simulasi; nanti BMKG/BBWS)", "unit": "mm"},
]


def generate_sensor_readings(hours=168, seed=7):
    """
    PROTOTYPE: membangkitkan pembacaan sensor SIMULASI per jam.
    Bukan data sensor nyata. Saat sensor sungguhan tersedia, fungsi ini
    diganti dengan pembaca data sensor; bagian lain tidak perlu berubah.
    """
    rng = np.random.default_rng(seed)
    times = pd.date_range(end=pd.Timestamp.now().floor("h"), periods=hours, freq="h")

    # Hujan per jam: jarang terjadi, kadang deras
    rain = np.where(rng.random(hours) < 0.04, rng.gamma(2.0, 3.0, hours), 0.0)

    values = {}

    # 6 sensor kelembapan tanah: turun karena penguapan, naik saat hujan
    for k in range(1, 7):
        sm = np.zeros(hours)
        sm[0] = rng.normal(31, 2)
        for i in range(1, hours):
            evap = 0.05 if 8 <= times[i].hour <= 16 else 0.02  # siang lebih cepat
            sm[i] = np.clip(sm[i - 1] - evap + 0.3 * rain[i], 12, 45)
        values[f"SM-{k:02d}"] = sm + rng.normal(0, 0.15, hours)

    # Muka air: naik sedikit setelah hujan + gelombang pelan + noise
    recent_rain = pd.Series(rain).rolling(6, min_periods=1).sum().to_numpy()
    wl = 1.10 + 0.015 * recent_rain + 0.03 * np.sin(np.arange(hours) / 12)
    wl = wl + rng.normal(0, 0.01, hours)
    values["WL-01"] = np.clip(wl, 0.6, 1.8)

    values["RF-01"] = rain

    # Susun menjadi satu tabel panjang
    frames = []
    for s in SENSORS:
        v = values[s["sensor_id"]].copy()
        missing = rng.random(hours) < 0.01      # sekitar 1% data hilang
        if s["sensor_id"] == "SM-04":
            missing[-5:] = True                 # SM-04 mati 5 jam terakhir
        v[missing] = np.nan
        frames.append(pd.DataFrame({
            "timestamp": times,
            "sensor_id": s["sensor_id"],
            "sensor_type": s["sensor_type"],
            "location": s["location"],
            "value": np.round(v, 2),
            "unit": s["unit"],
            "status": np.where(np.isnan(v), "NO DATA", "OK"),
        }))
    return pd.concat(frames, ignore_index=True)


# ---------------- Ringkasan sensor -> kondisi terbaru ----------------
def summarize_sensors(sensor_df):
    """Mengubah pembacaan sensor per jam menjadi kondisi terbaru untuk SOMAT."""
    ok = sensor_df[sensor_df["status"] == "OK"]

    # Kelembapan tanah: ambil pembacaan valid terakhir tiap sensor, lalu rata-rata
    sm_last = (
        ok[ok["sensor_type"] == "soil_moisture"]
        .sort_values("timestamp")
        .groupby("sensor_id")
        .tail(1)
    )
    soil_moisture = float(sm_last["value"].mean())

    # Muka air: pembacaan valid terakhir WL-01
    wl = ok[ok["sensor_type"] == "water_level"].sort_values("timestamp")
    water_level = float(wl["value"].iloc[-1])

    # Hujan: jumlah 24 jam terakhir
    rf = ok[ok["sensor_type"] == "rainfall"].sort_values("timestamp")
    rainfall_24h = float(rf["value"].tail(24).sum())

    # Kualitas data: persentase pembacaan valid
    data_quality = 100 * len(ok) / len(sensor_df)

    return {
        "soil_moisture": round(soil_moisture, 1),
        "water_level": round(water_level, 2),
        "rainfall": round(rainfall_24h, 1),
        "sensors_used": int(sm_last["sensor_id"].nunique()),
        "data_quality": round(data_quality, 1),
    }


# ---------------- Status sensor (online/offline) ----------------
def sensor_status_table(sensor_df, offline_after_hours=3):
    """Menentukan tiap sensor Online atau Offline dari pembacaan valid terakhir."""
    now = sensor_df["timestamp"].max()
    ok = sensor_df[sensor_df["status"] == "OK"]
    last_ok = ok.groupby("sensor_id")["timestamp"].max()

    rows = []
    for s in SENSORS:
        last = last_ok.get(s["sensor_id"])
        if last is None or (now - last) > pd.Timedelta(hours=offline_after_hours):
            state = "Offline"
        else:
            state = "Online"
        rows.append({
            "Sensor": s["sensor_id"],
            "Jenis": s["sensor_type"],
            "Lokasi": s["location"],
            "Status": state,
            "Data valid terakhir": last,
        })
    return pd.DataFrame(rows)


# ============================================================
# SOMAT UI v2 — responsive layout, light/dark mode, animated
# metrics, modern navigation, and interactive sensor donut.
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "assets" / "somat_logo.png"
PLOTLY_CONFIG = {
    # Semua kontrol modebar tetap tersedia kecuali tombol Zoom (ikon kaca pembesar).
    # Drag default tetap untuk zoom timeframe; tombol Pan bersifat toggle.
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["zoom2d"],
    "displaylogo": False,
    "responsive": False,
    "scrollZoom": False,
}

if "page" not in st.session_state:
    st.session_state["page"] = "Ringkasan"
if "light_mode" not in st.session_state:
    st.session_state["light_mode"] = False
if "decision_log" not in st.session_state:
    st.session_state["decision_log"] = []
if "show_modify" not in st.session_state:
    st.session_state["show_modify"] = False

IS_DARK = not bool(st.session_state.get("light_mode", False))
THEME = {
    "dark": IS_DARK,
    "bg": "#0B1220" if IS_DARK else "#F4F7FB",
    "panel": "#111B2C" if IS_DARK else "#FFFFFF",
    "panel2": "#0F1A2A" if IS_DARK else "#F8FAFD",
    "sidebar": "#080F1A" if IS_DARK else "#FFFFFF",
    "text": "#E8EEF8" if IS_DARK else "#172033",
    "muted": "#94A3B8" if IS_DARK else "#667085",
    "border": "#24324A" if IS_DARK else "#DCE3ED",
    "grid": "rgba(148,163,184,.12)" if IS_DARK else "rgba(71,85,105,.12)",
}

# Ikon tombol tema (SVG di-encode untuk dipakai di CSS).
# Mode gelap -> ikon matahari (pindah ke terang); mode terang -> ikon bulan.
if IS_DARK:
    THEME_ICON = (
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='%23F59E0B' stroke-width='2' stroke-linecap='round'%3E"
        "%3Ccircle cx='12' cy='12' r='4' fill='%23FBBF24' stroke='%23F59E0B'/%3E"
        "%3Cpath d='M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2"
        "M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41'/%3E%3C/svg%3E"
    )
else:
    THEME_ICON = (
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E"
        "%3Cpath fill='%23F8D96B' d='M20.4 15.4A8.4 8.4 0 0 1 8.6 3.6 8.8 8.8 0 1 0 20.4 15.4Z'/%3E"
        "%3Cpath fill='none' stroke='%23EAB308' stroke-width='1.5' "
        "d='M20.4 15.4A8.4 8.4 0 0 1 8.6 3.6 8.8 8.8 0 1 0 20.4 15.4Z'/%3E%3C/svg%3E"
    )


def _logo_b64():
    """Cari logo di beberapa lokasi umum. Kosong jika tidak ditemukan."""
    for cand in (
        LOGO_PATH,
        Path.cwd() / "assets" / "somat_logo.png",
        BASE_DIR / "somat_logo.png",
        Path.cwd() / "somat_logo.png",
    ):
        try:
            if cand.exists():
                return base64.b64encode(cand.read_bytes()).decode("ascii")
        except OSError:
            pass
    return ""


# Logo cadangan (SVG) jika file assets/somat_logo.png belum ada.
LOGO_FALLBACK = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='0' y2='1'%3E"
    "%3Cstop offset='0' stop-color='%2338BDF8'/%3E%3Cstop offset='1' stop-color='%232F80ED'/%3E"
    "%3C/linearGradient%3E%3C/defs%3E"
    "%3Cpath d='M32 3C32 3 11 26 11 40a21 21 0 0 0 42 0C53 26 32 3 32 3Z' fill='url(%23g)'/%3E"
    "%3Cpath d='M32 52c0-10 3-17 12-22-1 11-5 19-12 22Z' fill='%2322A55B'/%3E"
    "%3Cpath d='M32 52c0-8-3-13-10-16 0 8 4 14 10 16Z' fill='%2384CC16'/%3E"
    "%3C/svg%3E"
)


logo_b64 = _logo_b64()
LOGO_SRC = f"data:image/png;base64,{logo_b64}" if logo_b64 else LOGO_FALLBACK

# Warna seri yang jelas terlihat di mode gelap maupun terang.
SERIES_COLORS = ["#22A55B", "#2F80ED", "#E87924", "#A855F7", "#E4565C", "#06B6D4"]


def apply_plot_theme(fig, height=None):
    """Terapkan tema terang/gelap SOMAT ke grafik Plotly.

    Semua warna (judul, sumbu, legenda, garis) ditulis eksplisit supaya tetap
    terbaca di mode gelap maupun terang, dan judul tidak terlalu besar.
    """
    fig.update_layout(
        template="plotly_dark" if IS_DARK else "plotly_white",
        colorway=SERIES_COLORS,
        paper_bgcolor=THEME["panel"],
        plot_bgcolor=THEME["panel"],
        font=dict(color=THEME["text"], size=12),
        title=dict(
            font=dict(size=15, color=THEME["text"]),
            x=0.02, xanchor="left", y=0.97, yanchor="top",
        ),
        legend=dict(font=dict(size=11, color=THEME["text"]), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=THEME["panel2"], font=dict(color=THEME["text"]), bordercolor=THEME["border"]),
        dragmode="zoom",
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=THEME["muted"],
            activecolor="#2F80ED",
        ),
    )
    if height:
        fig.update_layout(height=height)
    axis_style = dict(
        gridcolor=THEME["grid"], zerolinecolor=THEME["grid"],
        linecolor=THEME["border"],
        tickfont=dict(color=THEME["muted"], size=11),
        title_font=dict(color=THEME["text"], size=12),
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    return fig


def make_combo_chart(data):
    """Grafik kondisi terbaru: garis (kelembapan, muka air) + batang (hujan)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=data["date"], y=data["rainfall"], name="Curah hujan (mm)",
            marker_color="#7C93B5" if IS_DARK else "#9FB3CF", opacity=0.85,
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["soil_moisture"], mode="lines+markers",
            name="Kelembapan tanah (%)", line=dict(color="#22A55B", width=3),
        ),
        secondary_y=False,
    )
    # Muka air dikali 30 agar sebanding di sumbu kiri; nilai asli tampil saat hover.
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["water_level"] * 30, mode="lines+markers",
            name="Tinggi muka air (m, skala x30)",
            line=dict(color="#2F80ED", width=3),
            customdata=data["water_level"],
            hovertemplate="%{customdata:.2f} m<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.update_layout(
        height=360,
        # Ruang ekstra di dalam grafik agar sumbu kanan dan batang terakhir tidak terpotong.
        margin=dict(l=76, r=84, t=44, b=58),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    if len(data):
        x0 = pd.to_datetime(data["date"]).min() - pd.Timedelta(hours=12)
        x1 = pd.to_datetime(data["date"]).max() + pd.Timedelta(hours=12)
        fig.update_xaxes(range=[x0, x1], automargin=True)
    fig.update_yaxes(
        title=dict(text="Kelembapan (%) / muka air (skala)", font=dict(size=12, color=THEME["text"]), standoff=8),
        secondary_y=False, automargin=True,
    )
    fig.update_yaxes(
        title=dict(text="Curah hujan (mm)", font=dict(size=12, color=THEME["text"]), standoff=8),
        secondary_y=True, automargin=True,
    )
    return apply_plot_theme(fig)


def make_animated_line(data, column, title, y_label, color="#22A55B"):
    x = list(data["date"])
    y = [float(v) for v in data[column]]
    n = len(x)
    fig = go.Figure(
        data=[go.Scatter(
            x=x[:1], y=y[:1], mode="lines+markers",
            line=dict(color=color, width=3), marker=dict(size=6),
            name=title,
        )],
        frames=[
            go.Frame(data=[go.Scatter(
                x=x[:k], y=y[:k], mode="lines+markers",
                line=dict(color=color, width=3), marker=dict(size=6),
            )])
            for k in range(1, n + 1)
        ],
    )
    pad = (max(y) - min(y)) * 0.15 or 1
    fig.update_layout(
        title=title,
        height=320,
        margin=dict(l=10, r=10, t=64, b=10),
        xaxis=dict(range=[x[0], x[-1]], title="Tanggal"),
        yaxis=dict(range=[min(y) - pad, max(y) + pad], title=y_label),
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.02, y=1.0, xanchor="left", yanchor="bottom",
            bgcolor=THEME["panel2"], bordercolor=THEME["border"],
            font=dict(color=THEME["text"], size=11),
            buttons=[dict(
                label="▶ Putar ulang", method="animate",
                args=[None, dict(
                    frame=dict(duration=55, redraw=True),
                    transition=dict(duration=0),
                    fromcurrent=False,
                )],
            )],
        )],
    )
    return apply_plot_theme(fig)


def render_plotly_interactive(fig, height=None, auto_play=False, animation_opts=None, key_prefix="chart"):
    """Render Plotly in a fixed-height responsive SOMAT frame.

    The frame never changes size when modebar tools are toggled. Only the
    plot viewport/range changes. A ResizeObserver keeps the plot responsive
    when the Streamlit sidebar is collapsed/expanded and also scales the
    modebar just enough to keep every available button inside the frame.
    """
    if not hasattr(render_plotly_interactive, "_seq"):
        render_plotly_interactive._seq = 0
    render_plotly_interactive._seq += 1
    div_id = f"somatPlot_{key_prefix}_{render_plotly_interactive._seq}"
    h = int(height or getattr(fig.layout, "height", None) or 340)
    frame_h = h + 8
    apply_plot_theme(fig, height=h)
    fig.update_layout(autosize=True)
    plot_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        auto_play=auto_play,
        animation_opts=animation_opts,
        config=PLOTLY_CONFIG,
        div_id=div_id,
    )
    body = f"""
    <style>
      *{{box-sizing:border-box}}
      html,body{{margin:0;padding:0;width:100%;height:{frame_h}px;background:transparent;overflow:hidden;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}}
      .chart-shell{{position:relative;height:{frame_h}px!important;min-height:{frame_h}px!important;max-height:{frame_h}px!important;width:100%!important;min-width:0;border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});padding:2px 3px 1px;}}
      .chart-shell .js-plotly-plot{{position:relative!important;width:100%!important;max-width:100%!important;height:{h}px!important;min-height:{h}px!important;max-height:{h}px!important;}}
      .chart-shell .plot-container,.chart-shell .svg-container{{width:100%!important;max-width:100%!important;height:{h}px!important;min-height:{h}px!important;max-height:{h}px!important;}}
      .modebar{{top:7px!important;right:7px!important;left:auto!important;display:flex!important;flex-wrap:nowrap!important;justify-content:flex-end!important;align-items:center!important;width:max-content!important;max-width:none!important;gap:0!important;white-space:nowrap!important;transform-origin:top right!important;z-index:20!important;}}
      .modebar-group{{display:flex!important;align-items:center!important;margin:0 0 0 1px!important;white-space:nowrap!important;flex:0 0 auto!important;}}
      .modebar-btn{{width:25px!important;height:25px!important;padding:2px!important;border-radius:7px!important;display:grid!important;place-items:center!important;flex:0 0 25px!important;}}
      .modebar-btn svg{{width:16px!important;height:16px!important;}}
      .modebar-btn:hover{{background:{THEME['panel2']}!important;}}
      @media(max-width:460px){{
        .modebar{{top:5px!important;right:5px!important}}
        .modebar-btn{{width:22px!important;height:22px!important;padding:1px!important;flex-basis:22px!important}}
        .modebar-btn svg{{width:14px!important;height:14px!important}}
        .modebar-group{{margin-left:0!important}}
      }}
    </style>
    <div class="chart-shell" id="shell_{div_id}">{plot_html}</div>
    <script>
      (() => {{
        const gd = document.getElementById('{div_id}');
        const shell = document.getElementById('shell_{div_id}');
        if (!gd || !shell) return;
        const FIXED_H = {h};
        let resizeRAF = 0;

        const lockGeometry = () => {{
          shell.style.height = '{frame_h}px';
          shell.style.minHeight = '{frame_h}px';
          shell.style.maxHeight = '{frame_h}px';
          gd.style.height = FIXED_H + 'px';
          gd.style.minHeight = FIXED_H + 'px';
          gd.style.maxHeight = FIXED_H + 'px';
          gd.style.width = '100%';
          const pc = gd.querySelector('.plot-container');
          const svg = gd.querySelector('.svg-container');
          [pc, svg].forEach(el => {{
            if (!el) return;
            el.style.height = FIXED_H + 'px';
            el.style.minHeight = FIXED_H + 'px';
            el.style.maxHeight = FIXED_H + 'px';
            el.style.width = '100%';
            el.style.maxWidth = '100%';
          }});
        }};

        const fitModebar = () => {{
          const mb = gd.querySelector('.modebar');
          if (!mb) return;
          mb.style.transform = 'none';
          mb.style.transformOrigin = 'top right';
          const available = Math.max(1, gd.clientWidth - 16);
          const needed = Math.max(mb.scrollWidth || 0, mb.getBoundingClientRect().width || 0);
          if (needed > available) {{
            const scale = Math.max(0.56, Math.min(1, available / needed));
            mb.style.transform = `scale(${{scale}})`;
          }}
        }};

        let lastWidth = 0;
        const resizePlot = () => {{
          cancelAnimationFrame(resizeRAF);
          resizeRAF = requestAnimationFrame(() => {{
            const w = Math.round(shell.getBoundingClientRect().width || 0);
            lockGeometry();
            if (w > 0 && Math.abs(w - lastWidth) > 1) {{
              lastWidth = w;
              try {{ Plotly.Plots.resize(gd); }} catch (_) {{}}
            }}
            lockGeometry();
            fitModebar();
          }});
        }};

        const bindDragToggles = () => {{
          const btns = [...gd.querySelectorAll('.modebar-btn')];
          const specs = [
            {{rx:/(^|\\s)pan(\\s|$)/i, mode:'pan'}},
            {{rx:/box select/i, mode:'select'}},
            {{rx:/lasso select/i, mode:'lasso'}},
          ];
          specs.forEach(spec => {{
            const btn = btns.find(b => spec.rx.test((b.getAttribute('data-title')||b.title||'').trim()));
            if (!btn || btn.dataset.somatBound === '1') return;
            btn.dataset.somatBound = '1';
            let wasActive = false;
            btn.addEventListener('pointerdown', () => {{
              wasActive = ((gd._fullLayout && gd._fullLayout.dragmode) || gd.layout.dragmode) === spec.mode;
            }}, true);
            btn.addEventListener('click', () => {{
              if (wasActive) requestAnimationFrame(() => Plotly.relayout(gd, {{dragmode:'zoom'}}));
              requestAnimationFrame(() => {{ lockGeometry(); fitModebar(); }});
            }});
          }});
        }};

        const settle = () => {{ lockGeometry(); bindDragToggles(); fitModebar(); }};
        setTimeout(settle, 40);
        setTimeout(settle, 160);
        setTimeout(settle, 360);
        gd.on('plotly_afterplot', () => requestAnimationFrame(settle));
        gd.on('plotly_relayout', () => requestAnimationFrame(() => {{ lockGeometry(); bindDragToggles(); fitModebar(); }}));

        if ('ResizeObserver' in window) {{
          const ro = new ResizeObserver(() => resizePlot());
          ro.observe(shell);
        }}
        window.addEventListener('resize', resizePlot, {{passive:true}});
      }})();
    </script>
    """
    components.html(body, height=frame_h + 6, scrolling=False)


def show_animated(fig, height=340):
    """Animated chart with the same frame and pan-toggle behavior."""
    render_plotly_interactive(
        fig,
        height=height,
        auto_play=True,
        animation_opts=dict(
            frame=dict(duration=55, redraw=True),
            transition=dict(duration=0),
            fromcurrent=False,
            mode="immediate",
        ),
        key_prefix="animated",
    )


def make_line_chart(data, column, title, y_label, bar=False):
    if bar:
        fig = px.bar(data, x="date", y=column, title=title, color_discrete_sequence=["#38A3F5"])
    else:
        fig = px.line(data, x="date", y=column, title=title, markers=True, color_discrete_sequence=["#22A55B"])
        fig.update_traces(line=dict(width=3), marker=dict(size=6))
    fig.update_layout(
        xaxis_title="Tanggal",
        yaxis_title=y_label,
        height=320,
        margin=dict(l=10, r=10, t=56, b=10),
    )
    return apply_plot_theme(fig)


def render_counter_card(
    icon,
    title,
    note="",
    badge_text="",
    badge_kind="info",
    color="blue",
    target=None,
    decimals=0,
    prefix="",
    suffix="",
    value_text=None,
):
    """Card with a fresh 0→value counter animation on every Streamlit rerun/tab switch."""
    palette = {
        "green": ("#22A55B", "#0F2A24" if IS_DARK else "#F0FBF4"),
        "blue": ("#2F80ED", "#0F2440" if IS_DARK else "#F1F6FE"),
        "orange": ("#E87924", "#302012" if IS_DARK else "#FFF7ED"),
        "red": ("#E4565C", "#32191C" if IS_DARK else "#FFF1F2"),
    }
    accent, bg = palette.get(color, palette["blue"])
    badge_colors = {
        "ok": "#16884A",
        "warn": "#D85A10",
        "info": "#256FD1",
    }
    badge_bg = badge_colors.get(badge_kind, badge_colors["info"])
    safe_icon = html.escape(str(icon))
    safe_title = html.escape(str(title))
    safe_note = html.escape(str(note))
    safe_badge = html.escape(str(badge_text))
    safe_prefix = html.escape(str(prefix))
    safe_suffix = html.escape(str(suffix))

    if target is not None:
        numeric = float(target)
        value_html = (
            f'<span class="counter" data-target="{numeric}" data-decimals="{int(decimals)}" '
            f'data-prefix="{safe_prefix}" data-suffix="{safe_suffix}">{safe_prefix}0{safe_suffix}</span>'
        )
    else:
        value_html = html.escape(str(value_text if value_text is not None else ""))

    badge_html = f'<span class="badge">{safe_badge}</span>' if badge_text else ""

    card = f'''
    <div class="metric-card">
      <div class="title"><span class="ico">{safe_icon}</span>{safe_title}</div>
      <div class="value">{value_html}</div>
      <div class="foot">
        {badge_html}
        <span class="note">{safe_note}</span>
      </div>
    </div>
    <style>
      *{{box-sizing:border-box}}
      body{{margin:0;background:transparent;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:{THEME['text']};}}
      .metric-card{{height:150px;background:{bg};border:1px solid {THEME['border']};border-top:3px solid {accent};border-radius:16px;padding:14px 16px;box-shadow:0 8px 24px rgba(2,8,23,{'.20' if IS_DARK else '.06'});overflow:hidden;animation:up .45s ease-out both}}
      .title{{font-size:.82rem;color:{THEME['muted']};font-weight:750;line-height:1.25;min-height:34px;display:flex;gap:7px;align-items:flex-start}}
      .ico{{font-size:1rem;line-height:1}}
      .value{{font-size:1.8rem;font-weight:850;line-height:1.15;color:{THEME['text']};margin:5px 0 9px;white-space:nowrap}}
      .foot{{display:flex;gap:7px;align-items:center;min-height:24px;overflow:hidden}}
      .badge{{background:{badge_bg};color:white;padding:3px 8px;border-radius:999px;font-size:.68rem;font-weight:800;white-space:nowrap}}
      .note{{font-size:.72rem;color:{THEME['muted']};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
      @keyframes up{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
      @media(max-width:480px){{.metric-card{{height:142px}}.value{{font-size:1.65rem}}}}
      @media(prefers-reduced-motion:reduce){{.metric-card{{animation:none}}}}
    </style>
    <script>
      const el=document.querySelector('.counter');
      if(el){{
        const target=parseFloat(el.dataset.target||'0');
        const dec=parseInt(el.dataset.decimals||'0');
        const pre=el.dataset.prefix||''; const suf=el.dataset.suffix||'';
        const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const duration=reduced?0:850;
        const start=performance.now();
        const fmt=(v)=>pre+v.toFixed(dec)+suf;
        function tick(now){{
          const p=duration===0?1:Math.min(1,(now-start)/duration);
          const eased=1-Math.pow(1-p,3);
          el.textContent=fmt(target*eased);
          if(p<1)requestAnimationFrame(tick); else el.textContent=fmt(target);
        }}
        requestAnimationFrame(tick);
      }}
    </script>
    '''
    components.html(card, height=154, scrolling=False)


def render_card_rows(cards, columns=4):
    """Render card specs in Streamlit columns; columns stack naturally on mobile."""
    for start in range(0, len(cards), columns):
        batch = cards[start:start + columns]
        cols = st.columns(len(batch), gap="small")
        for col, spec in zip(cols, batch):
            with col:
                render_counter_card(**spec)


def show_sensor_donut(n_online, n_offline):
    """Animated donut in the exact same fixed frame used by the trend chart."""
    total = max(1, int(n_online + n_offline))
    online_pct = 100 * n_online / total
    offline_pct = 100 * n_offline / total
    frames = []
    steps = 28
    for i in range(steps + 1):
        p = i / steps
        frames.append(go.Frame(
            name=f"f{i}",
            data=[go.Pie(values=[n_online * p, n_offline * p, total * (1 - p)])],
        ))
    fig = go.Figure(
        data=[go.Pie(
            labels=["Online", "Offline", ""],
            values=[0, 0, total],
            hole=0.62,
            sort=False,
            direction="clockwise",
            rotation=0,
            marker=dict(colors=["#55C985", "#8F8B80", "rgba(0,0,0,0)"]),
            pull=[0, 0, 0],
            showlegend=False,
            customdata=[f"{online_pct:.1f}%", f"{offline_pct:.1f}%", ""],
            text=[f"{online_pct:.1f}%", f"{offline_pct:.1f}%", ""],
            textinfo="text",
            textfont=dict(color=THEME["text"], size=14),
            hovertemplate="%{label}: %{customdata}<extra></extra>",
        )],
        frames=frames,
    )
    fig.update_layout(
        title=dict(text="Distribusi Status Sensor", x=0.02, xanchor="left", font=dict(size=15, color=THEME["text"])),
        height=315,
        autosize=True,
        margin=dict(l=8, r=8, t=55, b=5),
        annotations=[dict(
            text=f"{total}<br>Sensor", x=0.5, y=0.5,
            showarrow=False, font=dict(size=19, color=THEME["text"]),
        )],
    )
    apply_plot_theme(fig)
    plot_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        auto_play=True,
        animation_opts=dict(
            frame=dict(duration=26, redraw=True),
            transition=dict(duration=18, easing="cubic-in-out"),
            fromcurrent=False,
            mode="immediate",
        ),
        config=PLOTLY_CONFIG,
        div_id="sensorDonut",
    )
    body = f'''
    <style>
      *{{box-sizing:border-box}}
      html,body{{margin:0;padding:0;width:100%;height:376px;background:transparent;overflow:hidden;font-family:Inter,ui-sans-serif,system-ui;color:{THEME['text']}}}
      .chart-shell{{position:relative;height:376px!important;min-height:376px!important;max-height:376px!important;width:100%!important;min-width:0;border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};padding:2px 3px 1px;overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});transition:box-shadow .22s ease}}
      .chart-shell:hover{{box-shadow:0 10px 30px rgba(2,8,23,{'.22' if IS_DARK else '.08'})}}
      #sensorDonut,.plot-container,.svg-container{{height:315px!important;min-height:315px!important;max-height:315px!important;width:100%!important;max-width:100%!important}}
      .modebar{{top:7px!important;right:7px!important;left:auto!important;width:max-content!important;max-width:none!important;display:flex!important;flex-wrap:nowrap!important;justify-content:flex-end!important;white-space:nowrap!important;transform-origin:top right!important}}
      .modebar-group{{display:flex!important;margin-left:1px!important;flex:0 0 auto!important}}
      .modebar-btn{{width:25px!important;height:25px!important;padding:2px!important;border-radius:7px!important;flex:0 0 25px!important}}
      .modebar-btn svg{{width:16px!important;height:16px!important}}
      .legend{{display:flex;justify-content:center;gap:8px;margin-top:-5px}}
      .legend button{{appearance:none;border:1px solid {THEME['border']};background:{THEME['panel2']};color:{THEME['text']};padding:6px 10px;border-radius:999px;cursor:pointer;font-size:12px;font-weight:750;transition:.18s ease}}
      .legend button:hover,.legend button.active{{transform:translateY(-1px);border-color:#2F80ED;box-shadow:0 5px 12px rgba(47,128,237,.16)}}
      .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
    </style>
    <div class="chart-shell" id="donutShell">
      {plot_html}
      <div class="legend">
        <button data-i="0"><span class="dot" style="background:#55C985"></span>Online&nbsp; {online_pct:.1f}%</button>
        <button data-i="1"><span class="dot" style="background:#8F8B80"></span>Offline&nbsp; {offline_pct:.1f}%</button>
      </div>
    </div>
    <script>
      const gd=document.getElementById('sensorDonut');
      const shell=document.getElementById('donutShell');
      const buttons=[...document.querySelectorAll('.legend button')];
      let selected=-1, hover=-1, currentPull=[0,0,0], raf=null, resizeRAF=0;
      const ease=t=>t<.5 ? 4*t*t*t : 1-Math.pow(-2*t+2,3)/2;
      function lockGeometry(){{
        shell.style.height='376px'; shell.style.minHeight='376px'; shell.style.maxHeight='376px';
        gd.style.height='315px'; gd.style.minHeight='315px'; gd.style.maxHeight='315px'; gd.style.width='100%';
      }}
      function fitModebar(){{
        const mb=gd.querySelector('.modebar'); if(!mb)return;
        mb.style.transform='none';
        const room=Math.max(1,gd.clientWidth-16), need=Math.max(mb.scrollWidth||0,mb.getBoundingClientRect().width||0);
        if(need>room)mb.style.transform=`scale(${{Math.max(.56,Math.min(1,room/need))}})`;
      }}
      function resizePlot(){{
        cancelAnimationFrame(resizeRAF);
        resizeRAF=requestAnimationFrame(()=>{{lockGeometry();try{{Plotly.Plots.resize(gd)}}catch(_){{}}lockGeometry();fitModebar();}});
      }}
      function desiredPull(){{
        const p=[0,0,0];
        if(selected>=0)p[selected]=0.14;
        if(hover>=0 && hover!==selected)p[hover]=0.052;
        return p;
      }}
      function animatePull(target,duration=300){{
        if(raf)cancelAnimationFrame(raf);
        const start=currentPull.slice(), t0=performance.now();
        const step=now=>{{
          const q=Math.min(1,(now-t0)/duration), e=ease(q);
          currentPull=start.map((v,i)=>v+(target[i]-v)*e);
          Plotly.restyle(gd,{{pull:[currentPull]}},[0]);
          if(q<1)raf=requestAnimationFrame(step); else {{currentPull=target.slice();raf=null;}}
        }};
        raf=requestAnimationFrame(step);
      }}
      function sync(duration=300){{animatePull(desiredPull(),duration);}}
      function select(idx){{
        selected=(selected===idx)?-1:idx;
        buttons.forEach((b,j)=>b.classList.toggle('active',j===selected));
        sync(340);
      }}
      gd.on('plotly_hover',e=>{{const i=e.points?.[0]?.pointNumber;hover=(i<2?i:-1);sync(170);}});
      gd.on('plotly_unhover',()=>{{hover=-1;sync(200);}});
      gd.on('plotly_click',e=>{{const i=e.points?.[0]?.pointNumber;if(i<2)select(i);}});
      gd.on('plotly_afterplot',()=>requestAnimationFrame(()=>{{lockGeometry();fitModebar();}}));
      buttons.forEach(b=>b.addEventListener('click',()=>select(parseInt(b.dataset.i))));
      if('ResizeObserver' in window){{const ro=new ResizeObserver(resizePlot);ro.observe(shell);ro.observe(document.documentElement);}}
      window.addEventListener('resize',resizePlot,{{passive:true}});
      setTimeout(()=>{{lockGeometry();fitModebar();}},60);
      setTimeout(resizePlot,240);
    </script>
    '''
    components.html(body, height=382, scrolling=False)


# ---------------- Universal interactive table ----------------
# Terjemahan nama kolom dan nilai tabel (hanya untuk tampilan; data asli tidak berubah).
COLUMN_ID = {
    "date": "Tanggal", "timestamp": "Waktu", "soil_moisture": "Kelembapan tanah (%)",
    "rainfall": "Curah hujan (mm)", "et0": "ET0 (mm/hari)", "water_level": "Tinggi muka air (m)",
    "available_discharge": "Debit tersedia (m³/s)", "crop_water_requirement": "Kebutuhan air tanaman (mm/hari)",
    "sensor_id": "ID Sensor", "sensor_type": "Jenis sensor", "location": "Lokasi", "unit": "Satuan",
    "value": "Nilai", "status": "Status", "Result": "Hasil",
}
VALUE_ID = {
    "soil_moisture": "Kelembapan tanah", "water_level": "Muka air", "rainfall": "Curah hujan",
    "OK": "Valid", "NO DATA": "Tidak ada data", "PASS": "LOLOS", "FAIL": "GAGAL",
}


def render_interactive_table(data, *, key="table", hide_index=True, max_height=420):
    """Tabel interaktif: urut, ubah lebar kolom, pilih kolom, cari, layar penuh, unduh CSV."""
    df_t = pd.DataFrame(data).copy()
    df_t = df_t.rename(columns=COLUMN_ID)
    for c in df_t.columns:
        if pd.api.types.is_object_dtype(df_t[c]) or pd.api.types.is_string_dtype(df_t[c]):
            df_t[c] = df_t[c].map(lambda v: VALUE_ID.get(v, v) if isinstance(v, str) else v)
    if not hide_index:
        idx_name = df_t.index.name or "No."
        df_t.insert(0, idx_name, df_t.index + 1 if pd.api.types.is_integer_dtype(df_t.index) else df_t.index)
    for c in df_t.columns:
        if pd.api.types.is_datetime64_any_dtype(df_t[c]):
            df_t[c] = df_t[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df_t[c] = df_t[c].map(lambda v: "" if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
    columns = [str(c) for c in df_t.columns]
    records = [{str(k): v for k, v in r.items()} for r in df_t.to_dict(orient="records")]
    payload = json.dumps({"columns": columns, "rows": records}, ensure_ascii=False, default=str).replace("</", "<\\/")
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key))
    visible_rows = min(max(len(records), 1), 9)
    outer_h = min(max_height, 122 + visible_rows * 39)
    body = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>
    :root{{--panel:{THEME['panel']};--panel2:{THEME['panel2']};--text:{THEME['text']};--muted:{THEME['muted']};--border:{THEME['border']};--blue:#2F80ED;--shadow:0 12px 28px rgba(2,8,23,{'.24' if IS_DARK else '.08'});}}
    *{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:transparent;color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;overflow:hidden}}
    .frame{{position:relative;height:{outer_h-6}px;border:1px solid var(--border);border-radius:14px;background:var(--panel);overflow:hidden;box-shadow:var(--shadow)}}
    .viewport{{position:absolute;inset:0;overflow:auto;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,.45) transparent}}
    .viewport::-webkit-scrollbar{{width:5px;height:5px}}.viewport::-webkit-scrollbar-track{{background:transparent}}.viewport::-webkit-scrollbar-thumb{{background:rgba(148,163,184,.45);border-radius:999px}}
    table{{border-collapse:separate;border-spacing:0;table-layout:fixed;min-width:100%;width:max-content;font-size:13px;background:var(--panel)}}
    th,td{{height:38px;padding:8px 12px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:110px;max-width:520px}}
    th{{position:sticky;top:0;z-index:5;background:var(--panel2);font-weight:800;color:var(--text);cursor:pointer;user-select:none;padding-right:25px}}
    th:hover{{background:rgba(47,128,237,.12)}} tr:hover td{{background:rgba(47,128,237,.06)}}
    .sort{{position:absolute;right:9px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--muted)}}
    .resize{{position:absolute;right:-3px;top:0;width:8px;height:100%;cursor:col-resize;z-index:8}}.resize:hover{{background:rgba(47,128,237,.35)}}
    .toolbar{{position:absolute;right:12px;top:8px;z-index:30;display:flex;align-items:center;justify-content:center;gap:2px;height:42px;padding:5px 6px;border-radius:13px;background:var(--panel2);border:1px solid color-mix(in srgb,var(--border) 72%,transparent);box-shadow:0 12px 28px rgba(2,8,23,.28);opacity:0;transform:translateY(-8px) scale(.965);transform-origin:top right;pointer-events:none;transition:opacity .18s ease,transform .22s cubic-bezier(.2,.8,.2,1),box-shadow .18s ease}}
    .frame:hover .toolbar,.toolbar.open,.frame:fullscreen .toolbar{{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}}
    .tool{{width:32px;height:32px;min-width:32px;min-height:32px;padding:0;border:0;border-radius:9px;background:transparent;color:var(--muted);cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:0;transition:background .15s ease,color .15s ease,transform .15s ease}}
    .tool svg{{display:block;width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}}
    .tool:hover,.tool.active{{color:var(--text);background:rgba(47,128,237,.13)}}.tool:active{{transform:scale(.94)}}
    .searchbox{{position:absolute;right:10px;top:50px;z-index:22;width:min(310px,calc(100% - 20px));display:none;background:var(--panel2);border:1px solid var(--border);padding:7px;border-radius:10px;box-shadow:var(--shadow)}}
    .searchbox.open{{display:block}}.searchbox input{{width:100%;border:1px solid var(--border);border-radius:8px;background:var(--panel);color:var(--text);padding:8px 10px;outline:none}}.searchbox input:focus{{border-color:var(--blue)}}
    .chooser{{position:absolute;right:10px;top:50px;z-index:22;max-height:270px;min-width:235px;overflow:auto;display:none;background:var(--panel2);border:1px solid var(--border);padding:8px;border-radius:10px;box-shadow:var(--shadow)}}.chooser.open{{display:block}}
    .chooser label{{display:flex;align-items:center;gap:8px;padding:6px 5px;font-size:12px;cursor:pointer;border-radius:7px}}.chooser label:hover{{background:rgba(47,128,237,.1)}}
    .scrollbtn{{position:absolute;top:50%;transform:translateY(-50%);z-index:18;width:30px;height:54px;border:1px solid var(--border);background:var(--panel2);color:var(--text);border-radius:10px;box-shadow:var(--shadow);cursor:pointer;display:none;place-items:center;font-size:20px}}.frame:hover .scrollbtn.show{{display:grid}}.left{{left:7px}}.right{{right:7px}}
    .empty{{padding:40px;color:var(--muted);text-align:center}}
    .frame:fullscreen{{width:100vw;height:100vh;border-radius:0}}.frame:fullscreen .viewport{{inset:0}}.frame:fullscreen .toolbar{{opacity:1;pointer-events:auto}}
    </style></head><body><div class='frame' id='frame_{safe_key}'><div class='viewport' id='vp_{safe_key}'><table id='tbl_{safe_key}'><thead></thead><tbody></tbody></table></div>
    <button class='scrollbtn left' title='Geser ke kiri'>‹</button><button class='scrollbtn right' title='Geser ke kanan'>›</button>
    <div class='toolbar' aria-label='Navigasi tabel'>
      <button class='tool columns' title='Pilih kolom' aria-label='Pilih kolom'><svg viewBox='0 0 24 24'><path d='M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6S2.5 12 2.5 12Z'/><circle cx='12' cy='12' r='2.7'/></svg></button>
      <button class='tool download' title='Unduh CSV' aria-label='Unduh CSV'><svg viewBox='0 0 24 24'><path d='M12 3v11'/><path d='m8 10 4 4 4-4'/><path d='M5 19h14'/></svg></button>
      <button class='tool search' title='Cari' aria-label='Cari'><svg viewBox='0 0 24 24'><circle cx='10.5' cy='10.5' r='5.5'/><path d='m15 15 5 5'/></svg></button>
      <button class='tool full' title='Zoom tabel' aria-label='Zoom tabel'><svg viewBox='0 0 24 24'><path d='M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5'/></svg></button>
    </div>
    <div class='searchbox'><input type='search' placeholder='Cari di tabel...'></div><div class='chooser'></div></div>
    <script>
    const DATA={payload};const frame=document.getElementById('frame_{safe_key}'),vp=document.getElementById('vp_{safe_key}'),tbl=document.getElementById('tbl_{safe_key}');
    const thead=tbl.tHead||tbl.createTHead(),tbody=tbl.tBodies[0]||tbl.createTBody(),chooser=frame.querySelector('.chooser'),searchbox=frame.querySelector('.searchbox'),searchInput=searchbox.querySelector('input');
    let cols=DATA.columns.map((name,i)=>({{name,visible:true,width:Math.max(110,Math.min(260,String(name).length*8+44)),i}}));let rows=DATA.rows.slice(),sortCol=-1,sortDir=1,query='';
    function escCSV(v){{const s=String(v??'');return /[\\",\\n]/.test(s)?'\\"'+s.replaceAll('\\"','\\"\\"')+'\\"':s}}
    function parse(v){{if(v===null||v===undefined||v==='')return {{t:3,v:''}};const n=Number(v);if(Number.isFinite(n)&&String(v).trim()!=='')return {{t:0,v:n}};const d=Date.parse(v);if(!Number.isNaN(d)&&/[-/:]/.test(String(v)))return {{t:1,v:d}};return {{t:2,v:String(v).toLocaleLowerCase('id-ID')}}}}
    function filtered(){{let a=rows.slice();if(query)a=a.filter(r=>cols.some(c=>c.visible&&String(r[c.name]??'').toLocaleLowerCase('id-ID').includes(query)));if(sortCol>=0){{const c=cols[sortCol];a.sort((x,y)=>{{const aa=parse(x[c.name]),bb=parse(y[c.name]);if(aa.t!==bb.t)return (aa.t-bb.t)*sortDir;return (aa.v<bb.v?-1:aa.v>bb.v?1:0)*sortDir}})}}return a}}
    function renderHead(){{thead.innerHTML='';const tr=document.createElement('tr');cols.forEach((c,i)=>{{const th=document.createElement('th');th.dataset.i=i;th.style.width=c.width+'px';th.style.minWidth=c.width+'px';th.style.maxWidth=c.width+'px';th.style.display=c.visible?'table-cell':'none';const tx=document.createElement('span');tx.textContent=c.name;th.appendChild(tx);const si=document.createElement('span');si.className='sort';si.textContent=sortCol===i?(sortDir>0?'▲':'▼'):'↕';th.appendChild(si);const grip=document.createElement('span');grip.className='resize';th.appendChild(grip);th.onclick=e=>{{if(e.target===grip)return;sortDir=sortCol===i?-sortDir:1;sortCol=i;render()}};grip.onpointerdown=e=>{{e.preventDefault();e.stopPropagation();const x=e.clientX,w=c.width;grip.setPointerCapture(e.pointerId);grip.onpointermove=ev=>{{c.width=Math.max(90,Math.min(520,w+ev.clientX-x));applyWidths()}};grip.onpointerup=()=>{{grip.onpointermove=null;updateArrows()}}}};tr.appendChild(th)}});thead.appendChild(tr)}}
    function applyWidths(){{const hs=thead.querySelectorAll('th');hs.forEach((th,i)=>{{const c=cols[i];th.style.width=c.width+'px';th.style.minWidth=c.width+'px';th.style.maxWidth=c.width+'px';th.style.display=c.visible?'table-cell':'none'}});tbody.querySelectorAll('tr').forEach(tr=>[...tr.children].forEach((td,i)=>{{const c=cols[i];td.style.width=c.width+'px';td.style.minWidth=c.width+'px';td.style.maxWidth=c.width+'px';td.style.display=c.visible?'table-cell':'none'}}));updateArrows()}}
    function renderBody(){{tbody.innerHTML='';const data=filtered();if(!data.length){{const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=Math.max(1,cols.filter(c=>c.visible).length);td.className='empty';td.textContent='Tidak ada data yang cocok';tr.appendChild(td);tbody.appendChild(tr);return}}data.forEach(r=>{{const tr=document.createElement('tr');cols.forEach(c=>{{const td=document.createElement('td');td.textContent=r[c.name]??'';td.title=String(r[c.name]??'');td.style.width=c.width+'px';td.style.minWidth=c.width+'px';td.style.maxWidth=c.width+'px';td.style.display=c.visible?'table-cell':'none';tr.appendChild(td)}});tbody.appendChild(tr)}})}}
    function renderChooser(){{chooser.innerHTML='';cols.forEach((c,i)=>{{const lab=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.checked=c.visible;cb.onchange=()=>{{if(!cb.checked&&cols.filter(x=>x.visible).length===1){{cb.checked=true;return}}c.visible=cb.checked;render()}};const sp=document.createElement('span');sp.textContent=c.name;lab.append(cb,sp);chooser.appendChild(lab)}})}}
    function render(){{renderHead();renderBody();renderChooser();requestAnimationFrame(updateArrows)}}
    function updateArrows(){{const ov=vp.scrollWidth>vp.clientWidth+2,l=frame.querySelector('.left'),r=frame.querySelector('.right');l.classList.toggle('show',ov&&vp.scrollLeft>2);r.classList.toggle('show',ov&&vp.scrollLeft<vp.scrollWidth-vp.clientWidth-2)}}
    frame.querySelector('.left').onclick=()=>vp.scrollBy({{left:-Math.max(220,vp.clientWidth*.55),behavior:'smooth'}});frame.querySelector('.right').onclick=()=>vp.scrollBy({{left:Math.max(220,vp.clientWidth*.55),behavior:'smooth'}});vp.addEventListener('scroll',updateArrows,{{passive:true}});
    const colBtn=frame.querySelector('.columns'),findBtn=frame.querySelector('.search');
    function syncToolState(){{colBtn.classList.toggle('active',chooser.classList.contains('open'));findBtn.classList.toggle('active',searchbox.classList.contains('open'));}}
    colBtn.onclick=e=>{{e.stopPropagation();chooser.classList.toggle('open');searchbox.classList.remove('open');syncToolState()}};findBtn.onclick=e=>{{e.stopPropagation();searchbox.classList.toggle('open');chooser.classList.remove('open');syncToolState();if(searchbox.classList.contains('open'))searchInput.focus()}};searchInput.oninput=()=>{{query=searchInput.value.trim().toLocaleLowerCase('id-ID');renderBody();updateArrows()}};
    frame.querySelector('.download').onclick=()=>{{const visible=cols.filter(c=>c.visible),data=filtered(),csv=[visible.map(c=>escCSV(c.name)).join(','),...data.map(r=>visible.map(c=>escCSV(r[c.name])).join(','))].join('\\n');const b=new Blob([csv],{{type:'text/csv;charset=utf-8;'}}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='somat_{safe_key}.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};
    frame.querySelector('.full').onclick=async()=>{{try{{if(!document.fullscreenElement)await frame.requestFullscreen();else await document.exitFullscreen()}}catch(_){{}}}};
    document.addEventListener('click',e=>{{if(!chooser.contains(e.target)&&!e.target.closest('.columns'))chooser.classList.remove('open');if(!searchbox.contains(e.target)&&!e.target.closest('.search'))searchbox.classList.remove('open');syncToolState()}});document.addEventListener('fullscreenchange',()=>setTimeout(updateArrows,60));
    if('ResizeObserver'in window)new ResizeObserver(updateArrows).observe(frame);render();
    </script></body></html>"""
    components.html(body, height=outer_h, scrolling=False)


# ---------------- CSS tambahan: menu sidebar + mode terang ----------------
_EXTRA_CSS = """
/* ===== Menu sidebar: rata kiri, font lebih besar ===== */
[data-testid="stSidebar"] .stButton{width:100%;}
[data-testid="stSidebar"] .stButton>button{
  justify-content:flex-start!important;text-align:left!important;
  padding:.62rem 1rem!important;min-height:50px!important;
  background:__PANEL2__;color:__TEXT__;border:1px solid __BORDER__;border-radius:12px;
}
[data-testid="stSidebar"] .stButton>button>div,
[data-testid="stSidebar"] .stButton>button [data-testid="stMarkdownContainer"]{
  width:100%!important;display:flex!important;justify-content:flex-start!important;text-align:left!important;
}
[data-testid="stSidebar"] .stButton>button p{
  font-size:1rem!important;font-weight:700!important;line-height:1.25!important;
  text-align:left!important;width:100%;margin:0!important;color:inherit!important;
}
[data-testid="stSidebar"] .stButton>button[kind="primary"],
[data-testid="stSidebar"] .stButton>button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(135deg,#2F80ED,#1E63C8)!important;border-color:#2F80ED!important;
  box-shadow:0 6px 16px rgba(47,128,237,.32);
}
[data-testid="stSidebar"] .stButton>button[kind="primary"] p,
[data-testid="stSidebar"] .stButton>button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
[data-testid="stSidebar"] .stButton>button:hover{border-color:#2F80ED!important;}
.side-brand{display:flex;align-items:center;gap:14px;padding:14px 2px 14px;}
.side-brand img{width:92px;height:auto;max-height:84px;object-fit:contain;flex:0 0 auto;}
.side-brand-name{font-size:2.1rem;font-weight:850;letter-spacing:-.02em;line-height:1.05;color:__TEXT__;}
.side-brand-sub{font-size:.92rem;line-height:1.35;color:__MUTED__;margin-top:4px;}
[data-testid="stSidebar"] h4{font-size:1.15rem!important;margin-top:.6rem!important;}
[data-testid="stSidebar"] [data-testid="stAlert"]{font-size:1.02rem!important;}
[data-testid="stSidebar"] [data-testid="stAlert"] p{font-size:1.02rem!important;}
[data-testid="stSidebar"] .stButton>button{min-height:48px!important;padding:.5rem .9rem!important;}
[data-testid="stSidebar"] .stButton>button p{font-size:1rem!important;}
.side-info-title{font-size:1.1rem!important;}
.side-info-muted{font-size:.9rem!important;}
.side-info-line{font-size:.98rem!important;}
.side-flow{font-size:.98rem!important;line-height:1.65!important;}
"""

_LIGHT_CSS = """
/* ===== Mode terang: paksa semua komponen Streamlit ikut berubah ===== */
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"]{
  background:__BG__!important;color:__TEXT__!important;color-scheme:light;
}
[data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;}
[data-testid="stToolbar"] *,[data-testid="stHeader"] svg{color:__TEXT__!important;fill:__TEXT__;}
h1,h2,h3,h4,h5,h6,[data-testid="stHeading"],[data-testid="stHeading"] *,
[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] *,
[data-testid="stWidgetLabel"],[data-testid="stWidgetLabel"] *,label,label *{color:__TEXT__!important;}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:__MUTED__!important;}
.somat-header h1{color:__TEXT__!important;}
.somat-header p{color:__MUTED__!important;}
.side-info-muted{color:__MUTED__!important;}
.status-title,.status-row,.status-row *{color:__TEXT__!important;}
.st-ok{color:#16884A!important;} .st-warn{color:#D85A10!important;}
/* kotak peringatan */
[data-testid="stAlert"]{border:1px solid __BORDER__;}
[data-testid="stAlert"] *{color:inherit!important;}
[data-testid="stAlertContentWarning"]{color:#7A4B00;}
[data-testid="stAlertContentSuccess"]{color:#14532D;}
[data-testid="stAlertContentInfo"]{color:#1E3A8A;}
[data-testid="stAlertContentError"]{color:#7F1D1D;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){background:#FFF6DD!important;border-color:#F3D98B;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){background:#E8F8EE!important;border-color:#A7E0BC;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]){background:#E8F1FD!important;border-color:#AFCBF5;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){background:#FDECEC!important;border-color:#F3B4B4;}
/* expander */
div[data-testid="stExpander"],div[data-testid="stExpander"] details{background:__PANEL__!important;border-color:__BORDER__!important;}
div[data-testid="stExpander"] summary,div[data-testid="stExpander"] summary *{color:__TEXT__!important;}
/* input */
input,textarea,[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="base-input"]{
  background:__PANEL__!important;color:__TEXT__!important;border-color:__BORDER__!important;
}
[data-testid="stNumberInput"] button{background:__PANEL2__!important;color:__TEXT__!important;}
/* tombol (di luar sidebar) */
.stButton>button,[data-testid="stFormSubmitButton"]>button{background:__PANEL__;color:__TEXT__!important;border:1px solid __BORDER__;}
.stButton>button p,[data-testid="stFormSubmitButton"]>button p{color:inherit!important;}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{background:#2F80ED!important;border-color:#2F80ED!important;}
.stButton>button[kind="primary"] p,.stButton>button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
/* sidebar */
[data-testid="stSidebar"],[data-testid="stSidebarContent"]{background:__SIDEBAR__!important;}
[data-testid="stSidebar"] *{color:__TEXT__;}
[data-testid="stSidebar"] [data-testid="stAlert"] *{color:inherit!important;}
[data-testid="stSidebar"] .stButton>button[kind="primary"] *,
[data-testid="stSidebar"] .stButton>button[data-testid="stBaseButton-primary"] *{color:#FFFFFF!important;}
hr{border-color:__BORDER__!important;}
code{background:__PANEL2__!important;color:__TEXT__!important;}
"""


def _fill_css(css):
    return (css.replace("__BG__", THEME["bg"]).replace("__PANEL__", THEME["panel"])
               .replace("__PANEL2__", THEME["panel2"]).replace("__SIDEBAR__", THEME["sidebar"])
               .replace("__TEXT__", THEME["text"]).replace("__MUTED__", THEME["muted"])
               .replace("__BORDER__", THEME["border"]))


EXTRA_CSS = _fill_css(_EXTRA_CSS) + ("" if IS_DARK else _fill_css(_LIGHT_CSS))


# ---------------- Global responsive styling ----------------
st.markdown(
    f'''
    <style>
      :root{{--somat-bg:{THEME['bg']};--somat-panel:{THEME['panel']};--somat-text:{THEME['text']};--somat-muted:{THEME['muted']};--somat-border:{THEME['border']};}}
      .stApp{{background:var(--somat-bg);color:var(--somat-text);}}
      [data-testid="stHeader"]{{background:transparent;}}
      [data-testid="stSidebar"]{{background:{THEME['sidebar']};border-right:1px solid {THEME['border']};width:21rem!important;min-width:21rem!important;}}
      [data-testid="stSidebarContent"]{{padding-top:.35rem!important;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,.48) transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar{{width:5px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-track{{background:transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb{{background:rgba(148,163,184,.42);border-radius:999px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb:hover{{background:rgba(148,163,184,.68);}}
      [data-testid="stSidebar"] *{{color:{THEME['text']};}}
      /* Compact fixed sidebar chevrons: always above the page and clickable. */
      [data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"]{{
        display:flex!important;visibility:visible!important;opacity:1!important;position:fixed!important;top:.62rem!important;z-index:999998!important;
      }}
      [data-testid="stSidebarCollapseButton"]{{left:calc(21rem - 3rem)!important;}}
      [data-testid="stExpandSidebarButton"]{{left:.65rem!important;}}
      [data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"] button{{
        width:38px!important;height:38px!important;min-height:38px!important;padding:0!important;
        border-radius:10px!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel2']}!important;color:{THEME['text']}!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:grid!important;place-items:center!important;font-size:0!important;line-height:1!important;
      }}
      [data-testid="stSidebarCollapseButton"] button svg, [data-testid="stExpandSidebarButton"] button svg{{display:none!important;}}
      [data-testid="stSidebarCollapseButton"] button::before{{content:"«";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stExpandSidebarButton"] button::before{{content:"»";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stExpandSidebarButton"] button:hover{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.18)!important;}}
      /* Icon-only light/dark control, fixed at the very top-right. */
      .st-key-theme_icon{{position:fixed!important;top:.62rem!important;right:.8rem!important;z-index:999999!important;width:38px!important;height:38px!important;pointer-events:auto!important;}}
      .st-key-theme_icon button{{
        width:38px!important;height:38px!important;min-height:38px!important;padding:0!important;
        border-radius:50%!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel']}!important;color:transparent!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:grid!important;place-items:center!important;font-size:0!important;line-height:1!important;
      }}
      .st-key-theme_icon button p{{display:none!important;}}
      .st-key-theme_icon button::before{{
        content:"";display:block;width:21px;height:21px;background:center/contain no-repeat url("data:image/svg+xml,{THEME_ICON}");
      }}
      .st-key-theme_icon button:hover{{border-color:#2F80ED!important;transform:translateY(-1px);box-shadow:0 8px 24px rgba(47,128,237,.18)!important;}}
      .block-container{{padding-top:.75rem!important;padding-bottom:2.2rem!important;max-width:1540px;}}
      p,li,label,.stMarkdown{{color:{THEME['text']};}}
      [data-testid="stCaptionContainer"] p{{color:{THEME['muted']}!important;}}
      hr{{border-color:{THEME['border']}!important;}}
      [data-testid="stSidebar"] .stButton>button{{
        width:100%;justify-content:flex-start;border-radius:11px;min-height:42px;
        font-weight:700;border:1px solid {THEME['border']};transition:.18s ease;
      }}
      [data-testid="stSidebar"] .stButton>button:hover{{transform:translateX(2px);border-color:#2F80ED;}}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:.45rem;}}
      [data-testid="stHorizontalBlock"]{{align-items:stretch!important;min-width:0!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"]{{flex:1 1 0!important;width:0!important;min-width:0!important;max-width:none!important;overflow:hidden!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"] iframe,
      [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stIFrame"]{{width:100%!important;max-width:100%!important;min-width:0!important;display:block!important;}}
      .side-info-card{{background:{THEME['panel2']};border:1px solid {THEME['border']};border-radius:14px;padding:12px 13px;margin-top:10px;box-shadow:0 6px 18px rgba(2,8,23,{'.15' if IS_DARK else '.04'});}}
      .side-info-title{{display:flex;gap:8px;align-items:center;font-size:.94rem;font-weight:820;margin:0 0 8px;color:{THEME['text']};}}
      .side-info-muted{{color:{THEME['muted']};font-size:.77rem;line-height:1.45;margin-bottom:6px;}}
      .side-info-line{{font-size:.82rem;line-height:1.55;color:{THEME['text']};}}
      .side-flow{{font-size:.81rem;line-height:1.55;color:{THEME['text']};letter-spacing:.002em;}}
      div[data-testid="stExpander"]{{border-color:{THEME['border']};background:{THEME['panel']};border-radius:12px;}}
      [data-testid="stDataFrame"]{{border:1px solid {THEME['border']};border-radius:12px;overflow:hidden;}}
      [data-testid="stPlotlyChart"]{{border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});}}
      .somat-header{{display:flex;align-items:center;gap:14px;margin:0 0 10px;padding:4px 0 2px;}}
      .somat-header img{{width:78px;height:70px;object-fit:contain;flex:0 0 auto;filter:drop-shadow(0 5px 14px rgba(0,90,160,.12));}}
      .somat-header h1{{font-size:clamp(1.55rem,2.2vw,2.45rem);line-height:1.08;margin:0;color:{THEME['text']};font-weight:850;letter-spacing:-.035em;}}
      .somat-header p{{margin:5px 0 0;color:{THEME['muted']};font-size:.93rem;}}
      .status-panel{{background:{THEME['panel']};border:1px solid {THEME['border']};border-radius:16px;padding:16px 18px;box-shadow:0 7px 20px rgba(2,8,23,{'.16' if IS_DARK else '.05'});}}
      .status-title{{font-weight:800;color:{THEME['text']};margin-bottom:8px;}}
      .status-row{{padding:5px 0;color:{THEME['text']};font-size:.92rem;}}
      .st-ok{{color:#22A55B;font-weight:900;}} .st-warn{{color:#E87924;font-weight:900;}}
      .sim-dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#2F80ED;margin-right:8px;animation:pulse 2s infinite;}}
      @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(47,128,237,.65)}}70%{{box-shadow:0 0 0 8px rgba(47,128,237,0)}}100%{{box-shadow:0 0 0 0 rgba(47,128,237,0)}}}}
      @media(max-width:800px){{
        [data-testid="stSidebar"]{{width:min(86vw,21rem)!important;min-width:min(86vw,21rem)!important;}}
        [data-testid="stSidebarCollapseButton"]{{left:calc(min(86vw,21rem) - 3rem)!important;}}
        .block-container{{padding-left:.75rem!important;padding-right:.75rem!important;padding-top:.45rem!important;}}
        .somat-header{{gap:9px;align-items:center}} .somat-header img{{width:58px;height:53px}}
        .somat-header p{{font-size:.8rem}} h1{{font-size:1.55rem!important}}
        [data-testid="stHorizontalBlock"]{{flex-wrap:wrap!important;gap:.5rem!important;}}
        [data-testid="stHorizontalBlock"] > [data-testid="column"]{{min-width:100%!important;max-width:100%!important;flex:1 1 100%!important;width:100%!important;overflow:visible!important;}}
      }}
      @media(prefers-reduced-motion:reduce){{.sim-dot{{animation:none}}}}
      {EXTRA_CSS}
    </style>
    ''',
    unsafe_allow_html=True,
)


# ---------------- Compact theme control ----------------
def _toggle_theme():
    st.session_state["light_mode"] = not bool(st.session_state.get("light_mode", False))


# Icon menunjukkan mode tujuan: matahari = pindah ke light, bulan = pindah ke dark.
st.button(
    "Toggle theme",
    key="theme_icon",
    help="Ganti ke light mode" if IS_DARK else "Ganti ke dark mode",
    on_click=_toggle_theme,
)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown(
        f'''<div class="side-brand"><img src="{LOGO_SRC}" alt="Logo SOMAT">
        <div><div class="side-brand-name">SOMAT</div>
        <div class="side-brand-sub">Smart Adaptive Irrigation Management System</div></div></div>''',
        unsafe_allow_html=True,
    )
    st.error("⚠️ Prototype — Data Simulasi")
    st.markdown('<span class="sim-dot"></span>Mode simulasi berjalan', unsafe_allow_html=True)

    st.markdown("#### Menu")
    nav_items = [
        ("📊", "Ringkasan"),
        ("📡", "Monitoring Sensor"),
        ("💧", "Prediksi & Rekomendasi"),
        ("🚨", "Peringatan"),
        ("👷", "Keputusan Operator"),
    ]
    for icon, label in nav_items:
        selected = st.session_state["page"] == label
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{label}",
            type="primary" if selected else "secondary",
            width="stretch",
        ):
            st.session_state["page"] = label
            st.rerun()

    st.markdown(
        f"""
        <div class="side-info-card">
          <div class="side-info-title">⚙️ <span>Nilai asumsi</span></div>
          <div class="side-info-muted">Angka contoh, bukan data lapangan.</div>
          <div class="side-info-line">Luas layanan: <b>{ASSUMPTIONS['area_ha']} ha</b></div>
          <div class="side-info-line">Waktu pemberian air: <b>{ASSUMPTIONS['delivery_hours']} jam</b></div>
          <div class="side-info-line">Muka air minimum: <b>{ASSUMPTIONS['min_water_level']} m</b></div>
          <div class="side-info-line">Kapasitas pintu: <b>{ASSUMPTIONS['gate_max_discharge']} m³/s</b></div>
        </div>
        <div class="side-info-card">
          <div class="side-info-title">🔁 <span>Alur kerja SOMAT</span></div>
          <div class="side-flow">Observasi → Prediksi → Cek Hidraulik → Rekomendasi → Validasi Operator → Operasi → Umpan Balik</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

page = st.session_state["page"]

# ---------------- Header ----------------
logo_html = f'<img src="{LOGO_SRC}" alt="Logo SOMAT">'
st.markdown(
    f'''
    <div class="somat-header">
      {logo_html}
      <div>
        <h1>SOMAT — Smart Adaptive Irrigation Management System</h1>
        <p>Prototipe sistem pendukung keputusan untuk observasi, prediksi, validasi hidraulik, dan keputusan operator.</p>
      </div>
    </div>
    ''',
    unsafe_allow_html=True,
)
st.warning(
    "PROTOTYPE — DATA SIMULASI. Seluruh angka pada dashboard ini dibangkitkan "
    "secara simulasi untuk demonstrasi konsep SOMAT, bukan data penelitian aktual."
)

# ---------------- Data + shared calculation ----------------
df = generate_simulated_data()
sensor_df = generate_sensor_readings()
latest = df.iloc[-1].copy()
sensor_summary = summarize_sensors(sensor_df)
latest["soil_moisture"] = sensor_summary["soil_moisture"]
latest["water_level"] = sensor_summary["water_level"]
latest["rainfall"] = sensor_summary["rainfall"]

prediction = predict_irrigation_requirement(
    soil_moisture=latest["soil_moisture"],
    rainfall=latest["rainfall"],
    et0=latest["et0"],
)
hydraulic = check_hydraulic_feasibility(
    irrigation_mm=prediction["irrigation_mm"],
    available_discharge=latest["available_discharge"],
    water_level=latest["water_level"],
)
recommendation = generate_recommendation(
    prediction=prediction,
    hydraulic=hydraulic,
    available_discharge=latest["available_discharge"],
    soil_moisture=latest["soil_moisture"],
)
alerts = detect_alerts(
    soil_moisture=latest["soil_moisture"],
    water_level=latest["water_level"],
    rainfall=latest["rainfall"],
    prediction=prediction,
    recommendation=recommendation,
)
system_status = "ATTENTION" if (alerts or not hydraulic["feasible"]) else "NORMAL"

low_m = 20
heavy_r = 20
sm_ok = latest["soil_moisture"] >= low_m
wl_ok = latest["water_level"] >= ASSUMPTIONS["min_water_level"]
rain_ok = latest["rainfall"] < heavy_r
q_ok = latest["available_discharge"] >= hydraulic["required_discharge"]


def status_row(ok, label, text):
    mark = '<span class="st-ok">✔</span>' if ok else '<span class="st-warn">⚠</span>'
    return f'<div class="status-row">{mark} <b>{html.escape(str(label))}</b>: {html.escape(str(text))}</div>'


# ============================================================
# RINGKASAN
# ============================================================
if page == "Ringkasan":
    st.header("Ringkasan Kondisi (Overview)")
    st.caption("Kondisi terbaru. Seluruh angka adalah data simulasi prototype.")
    render_card_rows([
        dict(icon="🌱", title="Kelembapan Tanah", target=latest["soil_moisture"], decimals=1, suffix=" %",
             note=f"Batas rendah {low_m}%", badge_text="Normal" if sm_ok else "Rendah", badge_kind="ok" if sm_ok else "warn", color="green" if sm_ok else "red"),
        dict(icon="🌊", title="Tinggi Muka Air", target=latest["water_level"], decimals=2, suffix=" m",
             note=f"Minimum {ASSUMPTIONS['min_water_level']} m", badge_text="Normal" if wl_ok else "Rendah", badge_kind="ok" if wl_ok else "warn", color="blue" if wl_ok else "red"),
        dict(icon="🌧️", title="Curah Hujan", target=latest["rainfall"], decimals=1, suffix=" mm",
             note=f"Batas tinggi {heavy_r} mm", badge_text="Normal" if rain_ok else "Tinggi", badge_kind="ok" if rain_ok else "warn", color="blue" if rain_ok else "orange"),
        dict(icon="💧", title="Debit Tersedia", target=latest["available_discharge"], decimals=3, suffix=" m³/s",
             note=f"Dibutuhkan {hydraulic['required_discharge']:.3f} m³/s", badge_text="Cukup" if q_ok else "Kurang", badge_kind="ok" if q_ok else "warn", color="blue" if q_ok else "red"),
        dict(icon="🌾", title="Kebutuhan Air Tanaman", target=latest["crop_water_requirement"], decimals=1, suffix=" mm/hari",
             note=f"Irigasi prediksi {prediction['irrigation_mm']} mm", badge_text="Prediksi", badge_kind="info", color="orange"),
        dict(icon="🛡️", title="Status Sistem", value_text="NORMAL" if system_status == "NORMAL" else "PERHATIAN",
             note="Tidak ada peringatan aktif" if system_status == "NORMAL" else "Perlu validasi operator", badge_text="Normal" if system_status == "NORMAL" else "Perhatian", badge_kind="ok" if system_status == "NORMAL" else "warn", color="green" if system_status == "NORMAL" else "red"),
    ], columns=3)

    panel_html = (
        '<div class="status-panel"><div class="status-title">Status Sistem dan Lahan</div>'
        + status_row(sm_ok, "Kelembapan tanah", f"{latest['soil_moisture']} %")
        + status_row(wl_ok, "Tinggi muka air", f"{latest['water_level']} m")
        + status_row(rain_ok, "Curah hujan hari ini", f"{latest['rainfall']} mm")
        + status_row(hydraulic["feasible"], "Status hidraulik", hydraulic["status"])
        + status_row(not alerts, "Peringatan aktif", f"{len(alerts)} peringatan")
        + "</div>"
    )
    st.markdown(panel_html, unsafe_allow_html=True)
    st.write("")
    st.header("Grafik Kondisi Terbaru (14 Hari Terakhir)")
    st.caption("Data simulasi (prototype). Drag grafik untuk zoom timeframe; Pan dapat diaktifkan/nonaktifkan dari toolbar.")
    render_plotly_interactive(make_combo_chart(df.tail(14)), height=360, key_prefix="summary")


# ============================================================
# MONITORING SENSOR
# ============================================================
elif page == "Monitoring Sensor":
    sensor_table = sensor_status_table(sensor_df)
    n_online = int((sensor_table["Status"] == "Online").sum())
    n_total = len(sensor_table)
    n_off = n_total - n_online
    sm_online = int(((sensor_table["Jenis"] == "soil_moisture") & (sensor_table["Status"] == "Online")).sum())

    st.header("Monitoring Sensor")
    st.caption("Sensor SIMULASI (prototype). Stasiun hujan adalah data eksternal simulasi.")
    render_card_rows([
        dict(icon="📡", title="Sensor Online", target=n_online, decimals=0, suffix=f" / {n_total}",
             note="Tanpa data > 3 jam = offline", badge_text="Normal" if n_online == n_total else "Perhatian", badge_kind="ok" if n_online == n_total else "warn", color="green" if n_online == n_total else "orange"),
        dict(icon="🌱", title="Sensor Kelembapan Tanah", target=sm_online, decimals=0, suffix=" / 6",
             note="Petak 1–6", badge_text="Sensor", badge_kind="info", color="blue"),
        dict(icon="🚨", title="Peringatan Aktif", target=len(alerts), decimals=0,
             note="Dari modul peringatan", badge_text="Normal" if not alerts else "Perhatian", badge_kind="ok" if not alerts else "warn", color="green" if not alerts else "red"),
        dict(icon="🗄️", title="Kualitas Data", target=sensor_summary["data_quality"], decimals=1, suffix=" %",
             note="Pembacaan valid 7 hari", badge_text="Baik" if sensor_summary["data_quality"] >= 95 else "Rendah", badge_kind="ok" if sensor_summary["data_quality"] >= 95 else "warn", color="blue"),
    ], columns=4)

    d1, d2 = st.columns([1, 1], gap="medium")
    with d1:
        show_sensor_donut(n_online, n_off)
    with d2:
        sm = sensor_df[sensor_df["sensor_type"] == "soil_moisture"]
        trend = px.line(
            sm, x="timestamp", y="value", color="sensor_id",
            title="Tren Kelembapan per Sensor (7 hari)",
            color_discrete_sequence=SERIES_COLORS,
            labels={"sensor_id": "Sensor"},
        )
        trend.update_traces(line=dict(width=2))
        trend.update_layout(
            height=368, yaxis_title="Kelembapan tanah (%)", xaxis_title=None,
            margin=dict(l=10, r=10, t=56, b=64),
            legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, title_text="", font=dict(size=10)),
        )
        apply_plot_theme(trend)
        render_plotly_interactive(trend, height=368, key_prefix="sensortrend")

    render_interactive_table(sensor_table, key="sensor_status", hide_index=True)
    st.divider()

    st.header("Monitoring")
    st.caption("Seluruh grafik di bawah berasal dari data simulasi.")
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        show_animated(make_animated_line(df, "soil_moisture", "🌱 Kelembapan Tanah", "Kelembapan tanah (%)"))
        show_animated(make_animated_line(df, "water_level", "🌊 Tinggi Muka Air Saluran", "Tinggi muka air (m)", color="#2F80ED"))
    with col2:
        render_plotly_interactive(
            make_line_chart(df, "rainfall", "🌧️ Curah Hujan", "Curah hujan (mm)", bar=True),
            height=340, key_prefix="rain",
        )
        show_animated(make_animated_line(df, "crop_water_requirement", "🌾 Kebutuhan Air Tanaman", "KAT (mm/hari)", color="#E87924"))

    with st.expander("Lihat tabel data simulasi"):
        render_interactive_table(df, key="monitor_data", hide_index=False)

    # Tahap A sengaja HANYA ada di tab Monitoring Sensor.
    with st.expander("Tahap A: data sensor simulasi"):
        st.caption("Sensor SIMULASI. Bukan data sensor nyata.")
        render_interactive_table(pd.DataFrame(SENSORS), key="sensor_definition", hide_index=True)
        st.write("Pembacaan valid terakhir tiap sensor:")
        last_ok = (
            sensor_df[sensor_df["status"] == "OK"]
            .sort_values("timestamp")
            .groupby("sensor_id")
            .tail(1)
        )
        render_interactive_table(last_ok, key="sensor_last_ok", hide_index=True)


# ============================================================
# PREDIKSI & REKOMENDASI
# ============================================================
elif page == "Prediksi & Rekomendasi":
    st.header("💧 Prediksi Kebutuhan Air")
    st.caption("Logika prediksi prototype (berbasis aturan), bukan model AI final tesis.")
    render_card_rows([
        dict(icon="🌱", title="Kelembapan Tanah", target=latest["soil_moisture"], decimals=1, suffix=" %", note="Kondisi sensor terbaru", badge_text="Input", badge_kind="info", color="green"),
        dict(icon="🌧️", title="Curah Hujan", target=latest["rainfall"], decimals=1, suffix=" mm", note="Akumulasi 24 jam", badge_text="Input", badge_kind="info", color="blue"),
        dict(icon="☀️", title="ET0", target=latest["et0"], decimals=2, suffix=" mm/hari", note="Evapotranspirasi acuan", badge_text="Input", badge_kind="info", color="orange"),
        dict(icon="💧", title="Prediksi Irigasi", target=prediction["irrigation_mm"], decimals=1, suffix=" mm", note="Hasil berbasis aturan", badge_text="Prediksi", badge_kind="info", color="blue"),
    ], columns=4)

    with st.expander("🔍 Lihat rincian perhitungan"):
        st.write("Kebutuhan dasar (ET0 x Kc):", prediction["base_demand"], "mm")
        st.write("Kekurangan air tanah:", prediction["deficit_mm"], "mm")
        st.write("Hujan efektif:", prediction["useful_rain"], "mm")
        st.write("Hasil = dasar + kekurangan - hujan efektif")

    st.divider()
    st.header("🚰 Kelayakan Hidraulik")
    st.caption("Pengecekan prototype berbasis aturan. Parameter hidraulik adalah angka asumsi.")
    render_card_rows([
        dict(icon="💧", title="Kebutuhan Air", target=prediction["irrigation_mm"], decimals=1, suffix=" mm", note="Prediksi kebutuhan", badge_text="Kebutuhan", badge_kind="info", color="blue"),
        dict(icon="🌊", title="Debit Tersedia", target=latest["available_discharge"], decimals=3, suffix=" m³/s", note="Saluran saat ini", badge_text="Tersedia", badge_kind="info", color="green"),
        dict(icon="🚰", title="Debit Dibutuhkan", target=hydraulic["required_discharge"], decimals=3, suffix=" m³/s", note="Untuk durasi asumsi", badge_text="Dibutuhkan", badge_kind="info", color="orange"),
    ], columns=3)
    if hydraulic["feasible"]:
        st.success("✅ Status hidraulik = LAYAK (FEASIBLE)")
    else:
        st.error("⛔ Status hidraulik = TIDAK LAYAK (NOT FEASIBLE)")
    render_interactive_table(pd.DataFrame(hydraulic["checks"]), key="hydraulic_checks", hide_index=True)

    st.divider()
    st.header("🧭 Rekomendasi SOMAT")
    st.caption("Hanya saran sistem. Menunggu validasi operator. Data simulasi.")
    feas_ok = recommendation["feasibility"] == "FEASIBLE"
    prio = recommendation["priority"]
    prio_label = {"HIGH": "TINGGI", "NORMAL": "NORMAL", "LOW": "RENDAH"}[prio]
    render_card_rows([
        dict(icon="💧", title="Irigasi Disarankan", target=recommendation["recommended_mm"], decimals=1, suffix=" mm", note=f"Prediksi kebutuhan {prediction['irrigation_mm']} mm", badge_text="Saran", badge_kind="info", color="blue"),
        dict(icon="⏱️", title="Durasi Disarankan", target=recommendation["duration_hours"], decimals=1, suffix=" jam", note=f"Luas {ASSUMPTIONS['area_ha']} ha", badge_text="Saran", badge_kind="info", color="blue"),
        dict(icon="🚰", title="Kelayakan Hidraulik", value_text="LAYAK" if feas_ok else "TIDAK LAYAK", note="Semua cek lolos" if feas_ok else "Ada cek yang gagal", badge_text="Layak" if feas_ok else "Tidak layak", badge_kind="ok" if feas_ok else "warn", color="green" if feas_ok else "red"),
        dict(icon="⚑", title="Prioritas", value_text=prio_label, note="Berdasarkan kebutuhan dan kelembapan tanah", badge_text=prio_label.capitalize(), badge_kind="warn" if prio == "HIGH" else ("info" if prio == "NORMAL" else "ok"), color="red" if prio == "HIGH" else ("blue" if prio == "NORMAL" else "green")),
    ], columns=4)
    st.info("🕒 Status: menunggu validasi operator. Buka menu **Keputusan Operator** untuk menyetujui, mengubah, atau menunda.")
    if st.button("📨 Kirim ke Operator untuk Validasi", type="primary"):
        st.session_state["pending_recommendation"] = {
            "mm": recommendation["recommended_mm"],
            "hours": recommendation["duration_hours"],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        st.success("Rekomendasi dikirim ke operator. Buka menu **Keputusan Operator** untuk memvalidasi.")
    st.subheader("❓ Mengapa rekomendasi ini?")
    for reason in recommendation["reasons"]:
        st.markdown(f"- {reason}")


# ============================================================
# PERINGATAN
# ============================================================
elif page == "Peringatan":
    st.header("🚨 Peringatan / Anomali")
    st.caption("Peringatan simulasi (berbasis aturan). Batas peringatan adalah angka contoh.")
    if alerts:
        for a in alerts:
            if a["level"] == "error":
                st.error(f"{a['title']}: {a['detail']}")
            else:
                st.warning(f"{a['title']}: {a['detail']}")
        st.warning("Kondisi abnormal terdeteksi. Operator diminta memvalidasi rekomendasi dengan teliti sebelum mengambil keputusan.")
    else:
        st.success("✅ Tidak ada peringatan aktif. Kondisi dalam batas normal (data simulasi).")

    st.subheader("🗂️ Kejadian Terbaru")
    incidents = []
    sensor_now = sensor_status_table(sensor_df)
    for _, row in sensor_now[sensor_now["Status"] == "Offline"].iterrows():
        incidents.append({
            "Waktu": str(row["Data valid terakhir"]),
            "Sumber": row["Sensor"],
            "Kejadian": "Sensor offline (tanpa data lebih dari 3 jam)",
            "Tingkat": "Peringatan",
            "Status": "Perlu diperiksa",
        })
    for a in alerts:
        incidents.append({
            "Waktu": str(sensor_df["timestamp"].max()),
            "Sumber": "Modul peringatan",
            "Kejadian": f"{a['title']}: {a['detail']}",
            "Tingkat": "Kritis" if a["level"] == "error" else "Peringatan",
            "Status": "Terbuka",
        })
    if incidents:
        render_interactive_table(pd.DataFrame(incidents), key="incidents", hide_index=True)
    else:
        st.info("Tidak ada kejadian. Seluruh sensor online dan tidak ada peringatan aktif.")


# ============================================================
# KEPUTUSAN OPERATOR
# ============================================================
elif page == "Keputusan Operator":
    st.header("👷 Keputusan Operator (Human in the Loop)")
    st.caption("SOMAT hanya memberi saran. Operator adalah pengambil keputusan akhir. Tidak ada pintu irigasi yang digerakkan otomatis. Data simulasi.")

    # Pesan konfirmasi dari keputusan sebelumnya (ditampilkan setelah st.rerun)
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    if "pending_recommendation" in st.session_state:
        p = st.session_state["pending_recommendation"]
        st.warning(f"📨 Rekomendasi menunggu validasi: {p['mm']} mm selama {p['hours']} jam (dikirim {p['time']}). Pilih APPROVE, MODIFY, atau DELAY.")

    note = st.text_input("📝 Catatan operator (opsional untuk APPROVE dan DELAY)")
    b1, b2, b3 = st.columns(3)
    approve = b1.button("APPROVE", type="primary", width="stretch")
    modify = b2.button("MODIFY", width="stretch")
    delay = b3.button("DELAY", width="stretch")

    if approve:
        st.session_state["show_modify"] = False
        log_decision("APPROVE", recommendation, recommendation["recommended_mm"], recommendation["duration_hours"], note)
        st.session_state["flash"] = "✅ Keputusan dicatat: APPROVE"
        st.rerun()
    if delay:
        st.session_state["show_modify"] = False
        log_decision("DELAY", recommendation, 0.0, 0.0, note or "Ditunda oleh operator")
        st.session_state["flash"] = "⏸️ Keputusan dicatat: DELAY (irigasi ditunda)"
        st.rerun()
    if modify:
        st.session_state["show_modify"] = True

    if st.session_state["show_modify"]:
        with st.form("modify_form"):
            st.subheader("✏️ Ubah rekomendasi")
            mod_mm = st.number_input("Jumlah air irigasi (mm)", min_value=0.0, value=float(recommendation["recommended_mm"]), step=0.5)
            mod_hours = st.number_input("Durasi (jam)", min_value=0.0, value=float(recommendation["duration_hours"]), step=0.5)
            mod_reason = st.text_area("Alasan perubahan (wajib diisi)")
            submitted = st.form_submit_button("Simpan keputusan yang diubah")
        if submitted:
            if mod_reason.strip() == "":
                st.warning("Alasan wajib diisi sebelum menyimpan keputusan MODIFY.")
            else:
                st.session_state["show_modify"] = False
                log_decision("MODIFY", recommendation, mod_mm, mod_hours, mod_reason)
                st.session_state["flash"] = "✏️ Keputusan dicatat: MODIFY"
                st.rerun()

    st.header("🔄 Umpan Balik (Feedback Loop)")
    st.caption("Respons lapangan simulasi (prototype). Bukan hasil pengukuran lapangan.")
    if "last_feedback" in st.session_state:
        fb = st.session_state["last_feedback"]
        f1, f2, f3 = st.columns(3)
        with f1:
            st.markdown("**1. 🧭 Rekomendasi SOMAT**")
            st.write(f"{fb['recommended_mm']} mm")
        with f2:
            st.markdown("**2. 👷 Keputusan Operator**")
            st.write(f"{fb['decision']} - {fb['operator_mm']} mm")
        with f3:
            st.markdown("**3. 🌾 Respons Lapangan (Simulasi)**")
            st.write(f"Kelembapan tanah {latest['soil_moisture']}% → {fb['feedback']['new_moisture']}% ({fb['feedback']['status']})")
        st.info("Umpan balik ke SOMAT: " + fb["feedback"]["learning"])
    else:
        st.info("Belum ada keputusan. Buat keputusan operator untuk melihat alur feedback.")

    st.subheader("📋 Riwayat Keputusan (sesi ini saja)")
    if st.session_state["decision_log"]:
        log_df = pd.DataFrame(st.session_state["decision_log"][::-1])
        render_interactive_table(log_df, key="decision_history", hide_index=True)
    else:
        st.info("Belum ada keputusan operator pada session ini.")
