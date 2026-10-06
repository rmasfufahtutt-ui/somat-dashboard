# ============================================================
# SOMAT - Smart Adaptive Irrigation Management System
# PROTOTYPE: seluruh data di bawah adalah DATA SIMULASI,
# bukan data penelitian aktual.
# ============================================================
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
st.set_page_config(
    page_title="SOMAT Dashboard",
    layout="wide",
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
    irrigation_mm,              # kebutuhan irigasi hasil prediksi (mm)
    available_discharge,        # debit tersedia di saluran (m3/s)
    water_level,                # tinggi muka air saluran (m)
    area_ha=ASSUMPTIONS["area_ha"],                 # luas areal layanan (ha) - CONTOH
    delivery_hours=ASSUMPTIONS["delivery_hours"],           # lama pemberian air (jam) - CONTOH
    min_water_level=ASSUMPTIONS["min_water_level"],       # batas minimum muka air (m) - CONTOH
    gate_max_discharge=ASSUMPTIONS["gate_max_discharge"],    # kapasitas maksimum pintu (m3/s) - CONTOH
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
            "Check": "Canal water level",
            "Value": f"{water_level:.2f} m",
            "Limit": f">= {min_water_level:.2f} m",
            "Result": "PASS" if water_level >= min_water_level else "FAIL",
        },
        {
            "Check": "Available discharge",
            "Value": f"{available_discharge:.3f} m3/s (needed {required_discharge:.3f})",
            "Limit": "available >= needed",
            "Result": "PASS" if available_discharge >= required_discharge else "FAIL",
        },
        {
            "Check": "Gate operational limit",
            "Value": f"{required_discharge:.3f} m3/s",
            "Limit": f"<= {gate_max_discharge:.2f} m3/s",
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
        reasons.append("Predicted demand is 0 mm, so no irrigation is needed now.")
    elif hydraulic["feasible"]:
        recommended_mm = demand_mm
        reasons.append(
            f"Predicted demand is {demand_mm} mm and all hydraulic checks passed, "
            "so the full demand is recommended."
        )
    else:
        recommended_mm = min(demand_mm, max_deliverable_mm)
        reasons.append(
            f"Predicted demand is {demand_mm} mm, but the hydraulic check is NOT FEASIBLE."
        )
        if not level_ok:
            reasons.append("Canal water level is below the minimum limit.")
        reasons.append(
            f"Only about {max_deliverable_mm:.1f} mm can be delivered within "
            f"{delivery_hours} hours, so the recommendation is reduced."
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
        reasons.append("Soil is very dry or demand is large, so priority is HIGH.")
    elif demand_mm >= 3:
        priority = "NORMAL"
        reasons.append("Moderate demand, so priority is NORMAL.")
    else:
        priority = "LOW"
        reasons.append("Very small demand, so priority is LOW.")

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
        "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Decision": decision,
        "SOMAT recommended (mm)": recommendation["recommended_mm"],
        "Operator irrigation (mm)": irrigation_mm,
        "Operator duration (h)": duration_hours,
        "Reason / note": note,
        "Simulated soil moisture after (%)": feedback["new_moisture"],
        "Simulated field response": feedback["status"],
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
            "title": "Soil moisture too low",
            "detail": f"Soil moisture {soil_moisture}% is below {low_moisture}%.",
        })

    if water_level < min_water_level:
        alerts.append({
            "level": "error",
            "title": "Canal water level too low",
            "detail": f"Water level {water_level} m is below {min_water_level} m.",
        })

    if rainfall >= heavy_rain:
        alerts.append({
            "level": "warning",
            "title": "Heavy rainfall",
            "detail": f"Rainfall {rainfall} mm reaches the {heavy_rain} mm threshold.",
        })

    if recommendation["recommended_mm"] < prediction["irrigation_mm"]:
        alerts.append({
            "level": "error",
            "title": "Demand exceeds hydraulic capacity",
            "detail": (
                f"Predicted demand {prediction['irrigation_mm']} mm, but only "
                f"{recommendation['recommended_mm']} mm is recommended."
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
        status = "Below target"
    elif new_moisture <= target_moisture + 5:
        status = "On target"
    else:
        status = "Above target (over-irrigation risk)"

    # Pesan umpan balik ke sistem SOMAT
    difference = operator_mm - recommended_mm
    if decision == "APPROVE":
        learning = "Operator accepted the recommendation. No adjustment needed."
    elif decision == "DELAY":
        learning = "Operator delayed irrigation. SOMAT records the reason for review."
    elif difference > 0:
        learning = (
            f"Operator applied {difference:.1f} mm MORE than recommended. "
            "SOMAT may need to account for higher demand."
        )
    else:
        learning = (
            f"Operator applied {abs(difference):.1f} mm LESS than recommended. "
            "SOMAT may be overestimating demand or hydraulic limits."
        )

    return {
        "new_moisture": round(new_moisture, 1),
        "status": status,
        "learning": learning,
    }

# ---------------- Komponen tampilan: kartu status ----------------
def status_card(icon, title, value, note, badge_text, badge_kind, color):
    """Membuat satu kartu status berwarna (HTML). Hanya urusan tampilan."""
    return (
        f'<div class="card card-{color}">'
        f'<div class="card-title">{icon} {title}</div>'
        f'<div class="card-value">{value}</div>'
        f'<span class="badge badge-{badge_kind}">{badge_text}</span> '
        f'<span class="card-note">{note}</span>'
        f"</div>"
    )

# ---------------- Grafik kombinasi gaya dashboard ----------------
def make_combo_chart(data):
    """Grafik kondisi terbaru: garis (kelembapan, muka air) + batang (hujan)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Batang hujan (sumbu kanan)
    fig.add_trace(
        go.Bar(x=data["date"], y=data["rainfall"], name="Curah hujan (mm)",
               marker_color="#B8C2CF", opacity=0.8),
        secondary_y=True,
    )
    # Garis kelembapan tanah (sumbu kiri)
    fig.add_trace(
        go.Scatter(x=data["date"], y=data["soil_moisture"], mode="lines+markers",
                   name="Kelembapan tanah (%)", line=dict(color="#1E9E57", width=3)),
        secondary_y=False,
    )
    # Garis muka air (m x 30 supaya sebanding di sumbu kiri; lihat catatan)
    fig.add_trace(
        go.Scatter(x=data["date"], y=data["water_level"] * 30, mode="lines+markers",
                   name="Tinggi muka air (m, skala x30)",
                   line=dict(color="#1E6FD9", width=3),
                   customdata=data["water_level"],
                   hovertemplate="%{customdata:.2f} m<extra></extra>"),
        secondary_y=False,
    )

    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.12),
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
    )
    fig.update_yaxes(title_text="Kelembapan (%) / muka air (skala)", secondary_y=False)
    fig.update_yaxes(title_text="Hujan (mm)", secondary_y=True)
    return fig

# ---------------- Fungsi pembuat grafik ----------------
def make_line_chart(data, column, title, y_label, bar=False):
    """Membuat satu grafik time-series dari satu kolom tabel."""
    if bar:
        fig = px.bar(data, x="date", y=column, title=title)
    else:
        fig = px.line(data, x="date", y=column, title=title, markers=True)
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title=y_label,
        height=320,
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# ---------------- Tampilan halaman ----------------
st.title("SOMAT — Smart Adaptive Irrigation Management System")
st.warning(
    "PROTOTYPE — SIMULATED DATA. Seluruh angka pada dashboard ini dibangkitkan "
    "secara simulasi untuk demonstrasi konsep SOMAT, bukan data penelitian aktual."
)

st.markdown(
    """
    <style>
    /* Sidebar biru tua seperti referensi */
    [data-testid="stSidebar"] {
        background-color: #0B3A75;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    /* Ruang halaman utama sedikit lebih rapat */
    .block-container {
        padding-top: 2rem;
    }
        .card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 16px 18px;
        border: 1px solid #E1E8F2;
        box-shadow: 0 1px 3px rgba(11, 58, 117, 0.08);
        height: 100%;
    }
    .card-green  { background: #EAF7EE; border-color: #CBEBD3; }
    .card-blue   { background: #E8F2FC; border-color: #C9DFF5; }
    .card-orange { background: #FEF1E7; border-color: #F8D8BE; }
    .card-red    { background: #FDECEC; border-color: #F6C9C9; }
    .card-title  { font-size: 0.85rem; color: #4A5A73; font-weight: 600; }
    .card-value  { font-size: 2rem; font-weight: 800; color: #0B3A75; line-height: 1.2; }
    .card-note   { font-size: 0.78rem; color: #6B7A90; }
    .badge {
        display: inline-block; padding: 2px 10px; border-radius: 8px;
        font-size: 0.75rem; font-weight: 700; color: #FFFFFF;
    }
    .badge-ok   { background: #1E9E57; }
    .badge-warn { background: #E8590C; }
    .badge-info { background: #1E6FD9; }
        .status-panel { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:14px; padding:16px 18px; }
    .status-title { font-weight:700; color:#0B3A75; margin-bottom:8px; }
    .status-row { padding:5px 0; color:#1B2A41; font-size:0.92rem; }
    .st-ok { color:#1E9E57; font-weight:800; }
    .st-warn { color:#E8590C; font-weight:800; }
    </style>
    """,
    unsafe_allow_html=True,
)
df = generate_simulated_data()
with st.sidebar:
    st.title("SOMAT")
    st.caption("Smart Adaptive Irrigation Management System")
    st.error("Prototype — Simulated Data")

    st.subheader("Navigation")
    st.markdown(
        "- [Water Demand Prediction](#water-demand-prediction)\n"
        "- [Hydraulic Feasibility](#hydraulic-feasibility)\n"
        "- [SOMAT Recommendation](#somat-recommendation)\n"
        "- [Alerts / Anomaly](#alerts-anomaly)\n"
        "- [Operator Decision](#operator-decision-human-in-the-loop)\n"
        "- [Feedback Loop](#feedback-loop)\n"
        "- [Monitoring](#monitoring)"
    )

    st.subheader("SOMAT workflow")
    st.markdown(
        "Observe → Predict → Hydraulic Check → Recommend → "
        "Human Validation → Operate → Feedback"
    )

    st.subheader("Assumed values")
    st.caption("Angka contoh, bukan data lapangan.")
    st.write(f"Service area: {ASSUMPTIONS['area_ha']} ha")
    st.write(f"Delivery time: {ASSUMPTIONS['delivery_hours']} hours")
    st.write(f"Min. water level: {ASSUMPTIONS['min_water_level']} m")
    st.write(f"Gate capacity: {ASSUMPTIONS['gate_max_discharge']} m³/s")
# Ambil kondisi terbaru (baris terakhir tabel)
latest = df.iloc[-1]

prediction = predict_irrigation_requirement(
    soil_moisture=latest["soil_moisture"],
    rainfall=latest["rainfall"],
    et0=latest["et0"],
)
overview_box = st.container()
st.header("Water Demand Prediction")
st.caption("Prototype prediction logic (rule-based), bukan model AI final tesis.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Soil Moisture (%)", latest["soil_moisture"])
c2.metric("Rainfall (mm)", latest["rainfall"])
c3.metric("ET0 (mm/day)", latest["et0"])
c4.metric("Predicted irrigation", f"{prediction['irrigation_mm']} mm")

with st.expander("Lihat rincian perhitungan"):
    st.write("Kebutuhan dasar (ET0 x Kc):", prediction["base_demand"], "mm")
    st.write("Kekurangan air tanah:", prediction["deficit_mm"], "mm")
    st.write("Hujan efektif:", prediction["useful_rain"], "mm")
    st.write("Hasil = dasar + kekurangan - hujan efektif")

st.divider()
hydraulic = check_hydraulic_feasibility(
    irrigation_mm=prediction["irrigation_mm"],
    available_discharge=latest["available_discharge"],
    water_level=latest["water_level"],
)

st.header("Hydraulic Feasibility")
st.caption(
    "Prototype rule-based check. Luas areal, jam pemberian air, batas muka air, "
    "dan kapasitas pintu adalah angka contoh (assumed values)."
)

h1, h2, h3 = st.columns(3)
h1.metric("Water demand", f"{prediction['irrigation_mm']} mm")
h2.metric("Available discharge", f"{latest['available_discharge']:.3f} m³/s")
h3.metric("Required discharge", f"{hydraulic['required_discharge']:.3f} m³/s")

if hydraulic["feasible"]:
    st.success("Hydraulic status = FEASIBLE")
else:
    st.error("Hydraulic status = NOT FEASIBLE")

st.dataframe(pd.DataFrame(hydraulic["checks"]), width="stretch", hide_index=True)

st.divider()
recommendation = generate_recommendation(
    prediction=prediction,
    hydraulic=hydraulic,
    available_discharge=latest["available_discharge"],
    soil_moisture=latest["soil_moisture"],
)

st.header("SOMAT Recommendation")
st.caption("System suggestion only. Awaiting operator validation. Simulated data.")

r1, r2, r3, r4 = st.columns(4)
r1.metric("Recommended irrigation", f"{recommendation['recommended_mm']} mm")
r2.metric("Recommended duration", f"{recommendation['duration_hours']} hours")
r3.metric("Hydraulic feasibility", recommendation["feasibility"])
r4.metric("Priority", recommendation["priority"])

st.subheader("Why this recommendation?")
for reason in recommendation["reasons"]:
    st.markdown(f"- {reason}")

st.divider()
alerts = detect_alerts(
    soil_moisture=latest["soil_moisture"],
    water_level=latest["water_level"],
    rainfall=latest["rainfall"],
    prediction=prediction,
    recommendation=recommendation,
)

st.header("Alerts / Anomaly TES")
st.caption("Simulated alerts (rule-based). Batas peringatan adalah angka contoh.")

if alerts:
    for a in alerts:
        if a["level"] == "error":
            st.error(f"{a['title']}: {a['detail']}")
        else:
            st.warning(f"{a['title']}: {a['detail']}")
    st.warning(
        "Kondisi abnormal terdeteksi. Operator diminta memvalidasi "
        "rekomendasi dengan teliti sebelum mengambil keputusan."
    )
else:
    st.success("No active alerts. Kondisi dalam batas normal (data simulasi).")

st.divider()
# Status sistem: ATTENTION jika ada alert atau hidraulik tidak feasible
if alerts or not hydraulic["feasible"]:
    system_status = "ATTENTION"
else:
    system_status = "NORMAL"

with overview_box:
    st.header("Ringkasan Kondisi (Overview)")
    st.caption(
        "Kondisi terbaru. PROTOTYPE: seluruh angka adalah data simulasi, "
        "bukan data penelitian aktual."
    )

    low_m = 20
    heavy_r = 20
    sm_ok = latest["soil_moisture"] >= low_m
    wl_ok = latest["water_level"] >= ASSUMPTIONS["min_water_level"]
    rain_ok = latest["rainfall"] < heavy_r
    q_ok = latest["available_discharge"] >= hydraulic["required_discharge"]

    cards = [
        status_card("🌱", "Kelembapan Tanah", f"{latest['soil_moisture']} %",
                    f"Batas rendah {low_m}%",
                    "Normal" if sm_ok else "Rendah",
                    "ok" if sm_ok else "warn",
                    "green" if sm_ok else "red"),
        status_card("🌊", "Tinggi Muka Air", f"{latest['water_level']} m",
                    f"Minimum {ASSUMPTIONS['min_water_level']} m",
                    "Normal" if wl_ok else "Rendah",
                    "ok" if wl_ok else "warn",
                    "blue" if wl_ok else "red"),
        status_card("🌧️", "Curah Hujan", f"{latest['rainfall']} mm",
                    f"Batas tinggi {heavy_r} mm",
                    "Normal" if rain_ok else "Tinggi",
                    "ok" if rain_ok else "warn",
                    "blue" if rain_ok else "orange"),
        status_card("💧", "Debit Tersedia (Available Discharge)",
                    f"{latest['available_discharge']:.3f} m³/s",
                    f"Dibutuhkan {hydraulic['required_discharge']:.3f} m³/s",
                    "Cukup" if q_ok else "Kurang",
                    "ok" if q_ok else "warn",
                    "blue" if q_ok else "red"),
        status_card("🌾", "Prediksi Kebutuhan Air (Crop Water Requirement)",
                    f"{latest['crop_water_requirement']} mm/hari",
                    f"Irigasi prediksi {prediction['irrigation_mm']} mm",
                    "Prediksi", "info", "orange"),
        status_card("🛡️", "Status Sistem (System Status)",
                    "NORMAL" if system_status == "NORMAL" else "PERHATIAN",
                    "Perlu validasi operator" if system_status != "NORMAL"
                    else "Tidak ada alert aktif",
                    "Normal" if system_status == "NORMAL" else "Perhatian",
                    "ok" if system_status == "NORMAL" else "warn",
                    "green" if system_status == "NORMAL" else "red"),
    ]

    row1 = st.columns(3)
    row2 = st.columns(3)
    for col, html in zip(row1 + row2, cards):
        col.markdown(html, unsafe_allow_html=True)
        col.write("")

    st.divider()
# Siapkan "papan catatan" jika belum ada
if "decision_log" not in st.session_state:
    st.session_state["decision_log"] = []
if "show_modify" not in st.session_state:
    st.session_state["show_modify"] = False

st.header("Operator Decision (Human-in-the-Loop)")
st.caption(
    "SOMAT hanya memberi saran. Operator adalah pengambil keputusan akhir. "
    "Tidak ada pintu irigasi yang digerakkan otomatis. Simulated data."
)

note = st.text_input("Operator note (opsional untuk APPROVE dan DELAY)")

b1, b2, b3 = st.columns(3)
approve = b1.button("APPROVE", type="primary", width="stretch")
modify = b2.button("MODIFY", width="stretch")
delay = b3.button("DELAY", width="stretch")

if approve:
    st.session_state["show_modify"] = False
    log_decision(
        "APPROVE", recommendation,
        recommendation["recommended_mm"], recommendation["duration_hours"], note,
    )
    st.success("Keputusan dicatat: APPROVE")

if delay:
    st.session_state["show_modify"] = False
    log_decision("DELAY", recommendation, 0.0, 0.0, note or "Delayed by operator")
    st.info("Keputusan dicatat: DELAY (irigasi ditunda)")

if modify:
    st.session_state["show_modify"] = True

if st.session_state["show_modify"]:
    with st.form("modify_form"):
        st.subheader("Modify recommendation")
        mod_mm = st.number_input(
            "Irrigation amount (mm)",
            min_value=0.0,
            value=float(recommendation["recommended_mm"]),
            step=0.5,
        )
        mod_hours = st.number_input(
            "Duration (hours)",
            min_value=0.0,
            value=float(recommendation["duration_hours"]),
            step=0.5,
        )
        mod_reason = st.text_area("Reason for modification (wajib diisi)")
        submitted = st.form_submit_button("Submit modified decision")

    if submitted:
        if mod_reason.strip() == "":
            st.warning("Alasan wajib diisi sebelum menyimpan keputusan MODIFY.")
        else:
            st.session_state["show_modify"] = False
            log_decision("MODIFY", recommendation, mod_mm, mod_hours, mod_reason)
            st.success("Keputusan dicatat: MODIFY")
st.header("Feedback Loop")
st.caption("Simulated field response (prototype). Bukan hasil pengukuran lapangan.")

if "last_feedback" in st.session_state:
    fb = st.session_state["last_feedback"]
    f1, f2, f3 = st.columns(3)
    with f1:
        st.markdown("**1. SOMAT Recommendation**")
        st.write(f"{fb['recommended_mm']} mm")
    with f2:
        st.markdown("**2. Operator Decision**")
        st.write(f"{fb['decision']} - {fb['operator_mm']} mm")
    with f3:
        st.markdown("**3. Simulated Field Response**")
        st.write(
            f"Soil moisture {latest['soil_moisture']}% -> "
            f"{fb['feedback']['new_moisture']}% ({fb['feedback']['status']})"
        )
    st.info("Feedback to SOMAT: " + fb["feedback"]["learning"])
else:
    st.info("Belum ada keputusan. Buat keputusan operator untuk melihat alur feedback.")
st.subheader("Decision Log (session ini saja)")
if st.session_state["decision_log"]:
    log_df = pd.DataFrame(st.session_state["decision_log"][::-1])
    st.dataframe(log_df, width="stretch", hide_index=True)
else:
    st.info("Belum ada keputusan operator pada session ini.")

st.divider()
def status_row(ok, label, text):
    mark = '<span class="st-ok">✔</span>' if ok else '<span class="st-warn">⚠</span>'
    return f'<div class="status-row">{mark} <b>{label}</b>: {text}</div>'


panel_html = (
    '<div class="status-panel"><div class="status-title">Status Sistem dan Lahan</div>'
    + status_row(sm_ok, "Kelembapan tanah", f"{latest['soil_moisture']} %")
    + status_row(wl_ok, "Tinggi muka air", f"{latest['water_level']} m")
    + status_row(rain_ok, "Curah hujan hari ini", f"{latest['rainfall']} mm")
    + status_row(hydraulic["feasible"], "Status hidraulik", hydraulic["status"])
    + status_row(not alerts, "Alert aktif", f"{len(alerts)} alert")
    + "</div>"
)
st.markdown(panel_html, unsafe_allow_html=True)
st.write("")
st.header("Grafik Kondisi Terbaru (14 Hari Terakhir)")
st.caption("Data simulasi (prototype).")
st.plotly_chart(make_combo_chart(df.tail(14)), width="stretch")
st.header("Monitoring")
st.caption("Seluruh grafik di bawah berasal dari data simulasi.")

col1, col2 = st.columns(2)

with col1:
    st.plotly_chart(
        make_line_chart(df, "soil_moisture", "Soil Moisture", "Soil moisture (%)"),
        width="stretch",
    )
    st.plotly_chart(
        make_line_chart(df, "water_level", "Canal Water Level", "Water level (m)"),
        width="stretch",
    )

with col2:
    st.plotly_chart(
        make_line_chart(df, "rainfall", "Rainfall", "Rainfall (mm)", bar=True),
        width="stretch",
    )
    st.plotly_chart(
        make_line_chart(
            df, "crop_water_requirement", "Crop Water Requirement", "CWR (mm/day)"
        ),
        width="stretch",
    )

with st.expander("Lihat tabel data simulasi"):
    st.dataframe(df, width="stretch")