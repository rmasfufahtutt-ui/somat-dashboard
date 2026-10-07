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
import streamlit.components.v1 as components
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
        template="plotly_dark",
        plot_bgcolor="#101F36", paper_bgcolor="#101F36",
    )
    fig.update_yaxes(title_text="Kelembapan (%) / muka air (skala)", secondary_y=False)
    fig.update_yaxes(title_text="Hujan (mm)", secondary_y=True)
    return fig

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

# ---------------- Grafik beranimasi ----------------
def make_animated_line(data, column, title, y_label, color="#1E9E57"):
    """Grafik garis yang tergambar bertahap saat dibuka (animasi)."""
    x = list(data["date"])
    y = list(data[column])
    n = len(x)

    fig = go.Figure(
        data=[go.Scatter(x=x[:1], y=y[:1], mode="lines+markers",
                         line=dict(color=color, width=3))],
        frames=[go.Frame(data=[go.Scatter(x=x[:k], y=y[:k])])
                for k in range(1, n + 1)],
    )
    pad = (max(y) - min(y)) * 0.15 or 1
    fig.update_layout(
        title=title, height=320, template="plotly_dark",
        paper_bgcolor="#101F36", plot_bgcolor="#101F36",
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(range=[x[0], x[-1]]),
        yaxis=dict(range=[min(y) - pad, max(y) + pad], title=y_label),
        updatemenus=[dict(
            type="buttons", showactive=False, x=1, y=1.18, xanchor="right",
            buttons=[dict(label="▶ Putar ulang", method="animate",
                          args=[None, dict(frame=dict(duration=70, redraw=True),
                                           transition=dict(duration=0),
                                           fromcurrent=False)])],
        )],
    )
    return fig


def show_animated(fig, height=340, spin=False):
    """Menampilkan grafik Plotly dan memutar animasinya otomatis."""
    html = fig.to_html(include_plotlyjs="cdn", full_html=False, auto_play=True)
    anim = (
        "<style>@keyframes spinIn{from{opacity:0;transform:rotate(-120deg) scale(.4);}"
        "to{opacity:1;transform:none;}}"
        ".spin{animation:spinIn 1.2s ease-out both;transform-origin:50% 55%;}</style>"
    )
    body = f'<div class="spin">{html}</div>' if spin else html
    components.html(
        f'<body style="margin:0;background:#101F36;overflow:hidden;">{anim}{body}</body>',
        height=height,
    )

def make_animated_donut(labels, values, colors, title, center_text):
    """Donat statis; animasi putar masuk diberikan oleh show_animated(spin=True)."""
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.62,
        marker=dict(colors=colors), sort=False,
    ))
    fig.update_layout(
        title=title, height=320, template="plotly_dark",
        paper_bgcolor="#101F36", margin=dict(l=10, r=10, t=50, b=10),
        annotations=[dict(text=center_text, x=0.5, y=0.5, showarrow=False, font_size=18)],
    )
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
        background-color: #08111F;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    /* Ruang halaman utama sedikit lebih rapat */
    .block-container {
        padding-top: 2rem;
    }
        .card {
        background: #101F36;
        border-radius: 14px;
        padding: 16px 18px;
        border: 1px solid #1E3252;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
        height: 100%;
    }
    .card-green  { background: #0F2A24; border-color: #1B5A45; }
    .card-blue   { background: #0F2440; border-color: #1E4A80; }
    .card-orange { background: #2E2112; border-color: #6B4A1E; }
    .card-red    { background: #321618; border-color: #7A2A2E; }
    .card-title  { font-size: 0.85rem; color: #9FB1CC; font-weight: 600; }
    .card-value  { font-size: 2rem; font-weight: 800; color: #FFFFFF; line-height: 1.2; }
    .card-note   { font-size: 0.78rem; color: #8396B3; }
    .badge {
        display: inline-block; padding: 2px 10px; border-radius: 8px;
        font-size: 0.75rem; font-weight: 700; color: #FFFFFF;
    }
    .badge-ok   { background: #1E9E57; }
    .badge-warn { background: #E8590C; }
    .badge-info { background: #1E6FD9; }
    .status-panel { background:#101F36; border:1px solid #1E3252; border-radius:14px; padding:16px 18px; }
    .status-title { font-weight:700; color:#FFFFFF; margin-bottom:8px; }
    .status-row { padding:5px 0; color:#E6EDF7; font-size:0.92rem; }
    .st-ok { color:#1E9E57; font-weight:800; }
    .st-warn { color:#E8590C; font-weight:800; }
        @keyframes fadeUp {
        from { opacity: 0; transform: translateY(12px); }
        to   { opacity: 1; transform: none; }
    }
    .card, .status-panel { animation: fadeUp 0.6s ease-out both; }

    @keyframes pulse {
        0%   { box-shadow: 0 0 0 0 rgba(47, 128, 237, 0.7); }
        70%  { box-shadow: 0 0 0 8px rgba(47, 128, 237, 0); }
        100% { box-shadow: 0 0 0 0 rgba(47, 128, 237, 0); }
    }
    .sim-dot {
        display: inline-block; width: 10px; height: 10px; border-radius: 50%;
        background: #2F80ED; margin-right: 8px; animation: pulse 2s infinite;
    }
    @media (prefers-reduced-motion: reduce) {
        .card, .status-panel, .sim-dot { animation: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
df = generate_simulated_data()
sensor_df = generate_sensor_readings()
with st.sidebar:
    st.title("SOMAT")
    st.caption("Smart Adaptive Irrigation Management System")
    st.error("⚠️ Prototype — Data Simulasi")
    st.markdown(
        '<span class="sim-dot"></span>Mode simulasi berjalan',
        unsafe_allow_html=True,
    )

    st.subheader("📂 Menu")
    page = st.radio(
        "Pilih halaman",
        [
            "Ringkasan",
            "Monitoring Sensor",
            "Prediksi & Rekomendasi",
            "Peringatan",
            "Keputusan Operator",
        ],
        label_visibility="collapsed",
    )

    st.subheader("🔁 Alur kerja SOMAT")
    st.markdown(
        "Observasi → Prediksi → Cek Hidraulik → Rekomendasi → "
        "Validasi Operator → Operasi → Umpan Balik"
    )

    st.subheader("⚙️ Nilai asumsi")
    st.caption("Angka contoh, bukan data lapangan.")
    st.write(f"Luas layanan: {ASSUMPTIONS['area_ha']} ha")
    st.write(f"Waktu pemberian air: {ASSUMPTIONS['delivery_hours']} jam")
    st.write(f"Muka air minimum: {ASSUMPTIONS['min_water_level']} m")
    st.write(f"Kapasitas pintu: {ASSUMPTIONS['gate_max_discharge']} m³/s")
    
# Ambil kondisi terbaru (baris terakhir tabel)
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
overview_box = st.container()

# ---- Perhitungan (selalu dijalankan, dipakai halaman lain) ----
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

# ---- Tampilan: hanya di halaman "Prediksi & Rekomendasi" ----
if page == "Prediksi & Rekomendasi":
    st.header("💧 Prediksi Kebutuhan Air")
    st.caption("Logika prediksi prototype (berbasis aturan), bukan model AI final tesis.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🌱 Kelembapan Tanah (%)", latest["soil_moisture"])
    c2.metric("🌧️ Curah Hujan (mm)", latest["rainfall"])
    c3.metric("☀️ ET0 (mm/hari)", latest["et0"])
    c4.metric("💧 Prediksi irigasi", f"{prediction['irrigation_mm']} mm")

    with st.expander("🔍 Lihat rincian perhitungan"):
        st.write("Kebutuhan dasar (ET0 x Kc):", prediction["base_demand"], "mm")
        st.write("Kekurangan air tanah:", prediction["deficit_mm"], "mm")
        st.write("Hujan efektif:", prediction["useful_rain"], "mm")
        st.write("Hasil = dasar + kekurangan - hujan efektif")

    st.divider()

    st.header("🚰 Kelayakan Hidraulik")
    st.caption(
        "Pengecekan prototype berbasis aturan. Luas areal, jam pemberian air, batas muka air, "
        "dan kapasitas pintu adalah angka asumsi."
    )

    h1, h2, h3 = st.columns(3)
    h1.metric("💧 Kebutuhan air", f"{prediction['irrigation_mm']} mm")
    h2.metric("🌊 Debit tersedia", f"{latest['available_discharge']:.3f} m³/s")
    h3.metric("🚰 Debit dibutuhkan", f"{hydraulic['required_discharge']:.3f} m³/s")

    if hydraulic["feasible"]:
        st.success("✅ Status hidraulik = LAYAK (FEASIBLE)")
    else:
        st.error("⛔ Status hidraulik = TIDAK LAYAK (NOT FEASIBLE)")

    st.dataframe(pd.DataFrame(hydraulic["checks"]), width="stretch", hide_index=True)

    st.divider()

    st.header("🧭 Rekomendasi SOMAT")
    st.caption("Hanya saran sistem. Menunggu validasi operator. Data simulasi.")

    feas_ok = recommendation["feasibility"] == "FEASIBLE"
    prio = recommendation["priority"]
    prio_label = {"HIGH": "TINGGI", "NORMAL": "NORMAL", "LOW": "RENDAH"}[prio]
    prio_color = {"HIGH": "red", "NORMAL": "blue", "LOW": "green"}[prio]
    prio_badge = {"HIGH": "warn", "NORMAL": "info", "LOW": "ok"}[prio]

    rec_cards = [
        status_card("💧", "Irigasi Disarankan",
                    f"{recommendation['recommended_mm']} mm",
                    f"Prediksi kebutuhan {prediction['irrigation_mm']} mm",
                    "Saran", "info", "blue"),
        status_card("⏱️", "Durasi Disarankan",
                    f"{recommendation['duration_hours']} jam",
                    f"Luas {ASSUMPTIONS['area_ha']} ha",
                    "Saran", "info", "blue"),
        status_card("🚰", "Kelayakan Hidraulik",
                    "LAYAK" if feas_ok else "TIDAK LAYAK",
                    "Semua cek lolos" if feas_ok else "Ada cek yang gagal",
                    "Layak" if feas_ok else "Tidak layak",
                    "ok" if feas_ok else "warn",
                    "green" if feas_ok else "red"),
        status_card("⚑", "Prioritas",
                    prio_label,
                    "Berdasarkan kebutuhan dan kelembapan tanah",
                    prio_label.capitalize(), prio_badge, prio_color),
    ]
    for col, html in zip(st.columns(4), rec_cards):
        col.markdown(html, unsafe_allow_html=True)
    st.write("")
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

    st.divider()
alerts = detect_alerts(
    soil_moisture=latest["soil_moisture"],
    water_level=latest["water_level"],
    rainfall=latest["rainfall"],
    prediction=prediction,
    recommendation=recommendation,
)
if page == "Peringatan":
    st.header("🚨 Peringatan / Anomali")
    st.caption("Peringatan simulasi (berbasis aturan). Batas peringatan adalah angka contoh.")

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
        st.dataframe(pd.DataFrame(incidents), hide_index=True, width="stretch")
    else:
        st.info("Tidak ada kejadian. Seluruh sensor online dan tidak ada peringatan aktif.")
    st.divider()

# Status sistem: ATTENTION jika ada alert atau hidraulik tidak feasible
if alerts or not hydraulic["feasible"]:
    system_status = "ATTENTION"
else:
    system_status = "NORMAL"

with (overview_box if page == "Ringkasan" else st.empty()):
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

# Siapkan "papan catatan" jika belum ada (selalu dijalankan)
if "decision_log" not in st.session_state:
    st.session_state["decision_log"] = []
if "show_modify" not in st.session_state:
    st.session_state["show_modify"] = False

if page == "Keputusan Operator":
    st.header("👷 Keputusan Operator (Human in the Loop)")
    st.caption(
        "SOMAT hanya memberi saran. Operator adalah pengambil keputusan akhir. "
        "Tidak ada pintu irigasi yang digerakkan otomatis. Data simulasi."
    )
    if "pending_recommendation" in st.session_state:
        p = st.session_state["pending_recommendation"]
        st.warning(
            f"📨 Rekomendasi menunggu validasi: {p['mm']} mm selama {p['hours']} jam "
            f"(dikirim {p['time']}). Pilih APPROVE, MODIFY, atau DELAY."
        )
    note = st.text_input("📝 Catatan operator (opsional untuk APPROVE dan DELAY)")

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
            st.subheader("✏️ Ubah rekomendasi")
            mod_mm = st.number_input(
                "Jumlah air irigasi (mm)",
                min_value=0.0,
                value=float(recommendation["recommended_mm"]),
                step=0.5,
            )
            mod_hours = st.number_input(
                "Durasi (jam)",
                min_value=0.0,
                value=float(recommendation["duration_hours"]),
                step=0.5,
            )
            mod_reason = st.text_area("Alasan perubahan (wajib diisi)")
            submitted = st.form_submit_button("Simpan keputusan yang diubah")

        if submitted:
            if mod_reason.strip() == "":
                st.warning("Alasan wajib diisi sebelum menyimpan keputusan MODIFY.")
            else:
                st.session_state["show_modify"] = False
                log_decision("MODIFY", recommendation, mod_mm, mod_hours, mod_reason)
                st.success("Keputusan dicatat: MODIFY")

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
            st.write(
                f"Soil moisture {latest['soil_moisture']}% -> "
                f"{fb['feedback']['new_moisture']}% ({fb['feedback']['status']})"
            )
        st.info("Feedback to SOMAT: " + fb["feedback"]["learning"])
    else:
        st.info("Belum ada keputusan. Buat keputusan operator untuk melihat alur feedback.")

    st.subheader("📋 Riwayat Keputusan (sesi ini saja)")
    if st.session_state["decision_log"]:
        log_df = pd.DataFrame(st.session_state["decision_log"][::-1])
        st.dataframe(log_df, width="stretch", hide_index=True)
    else:
        st.info("Belum ada keputusan operator pada session ini.")

    st.divider()
def status_row(ok, label, text):
    mark = '<span class="st-ok">✔</span>' if ok else '<span class="st-warn">⚠</span>'
    return f'<div class="status-row">{mark} <b>{label}</b>: {text}</div>'

if page == "Monitoring Sensor":
    sensor_table = sensor_status_table(sensor_df)
    n_online = int((sensor_table["Status"] == "Online").sum())
    n_total = len(sensor_table)

    st.header("Monitoring Sensor")
    st.caption("Sensor SIMULASI (prototype). Stasiun hujan adalah data eksternal.")

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(
        status_card("📡", "Sensor Online", f"{n_online} / {n_total}",
                    "Tanpa data > 3 jam = offline",
                    "Normal" if n_online == n_total else "Perhatian",
                    "ok" if n_online == n_total else "warn",
                    "green" if n_online == n_total else "orange"),
        unsafe_allow_html=True)
    k2.markdown(
        status_card("🌱", "Sensor Kelembapan Tanah",
                    f"{int(((sensor_table['Jenis'] == 'soil_moisture') & (sensor_table['Status'] == 'Online')).sum())} / 6",
                    "Petak 1-6", "Sensor", "info", "blue"),
        unsafe_allow_html=True)
    k3.markdown(
        status_card("🚨", "Alert Aktif", f"{len(alerts)}",
                    "Dari modul alert",
                    "Normal" if not alerts else "Perhatian",
                    "ok" if not alerts else "warn",
                    "green" if not alerts else "red"),
        unsafe_allow_html=True)
    k4.markdown(
        status_card("🗄️", "Kualitas Data", f"{sensor_summary['data_quality']} %",
                    "Pembacaan valid 7 hari",
                    "Baik" if sensor_summary["data_quality"] >= 95 else "Rendah",
                    "ok" if sensor_summary["data_quality"] >= 95 else "warn",
                    "blue"),
        unsafe_allow_html=True)
    st.write("")

    d1, d2 = st.columns([1, 2])
    with d1:
        n_off = n_total - n_online
        with d1:
            n_off = n_total - n_online
            show_animated(
            make_animated_donut(
                ["Online", "Offline"], [n_online, n_off],
                ["#1E9E57", "#6B7A90"],
                "Distribusi Status Sensor", f"{n_total}<br>Sensor",
            ),
            height=340,
            spin=True,
        )
    with d2:
        sm = sensor_df[sensor_df["sensor_type"] == "soil_moisture"]
        trend = px.line(sm, x="timestamp", y="value", color="sensor_id",
                        title="Tren Kelembapan Tanah per Sensor (7 hari)")
        trend.update_layout(height=320, template="plotly_dark",
                            paper_bgcolor="#101F36", plot_bgcolor="#101F36",
                            yaxis_title="Kelembapan tanah (%)", xaxis_title="Waktu",
                            margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(trend, width="stretch")

    st.dataframe(sensor_table, hide_index=True, width="stretch")
    st.divider()

if page == "Ringkasan":
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
if page == "Monitoring Sensor":
    st.header("Monitoring")
    st.caption("Seluruh grafik di bawah berasal dari data simulasi.")

    col1, col2 = st.columns(2)

    with col1:
        show_animated(
        make_animated_line(df, "soil_moisture", "🌱 Kelembapan Tanah", "Kelembapan tanah (%)")
        )
        show_animated(
        make_animated_line(df, "water_level", "🌊 Tinggi Muka Air Saluran",
                               "Tinggi muka air (m)", color="#1E6FD9")
        )

    with col2:
        st.plotly_chart(
            make_line_chart(df, "rainfall", "🌧️ Curah Hujan", "Curah hujan (mm)", bar=True),
            width="stretch",
        )
        show_animated(
        make_animated_line(df, "crop_water_requirement", "🌾 Kebutuhan Air Tanaman",
                               "KAT (mm/hari)", color="#E8590C")
        ),
        width="stretch",
        

    with st.expander("Lihat tabel data simulasi"):
        st.dataframe(df, width="stretch")
with st.expander("Tahap A: data sensor simulasi"):
    st.caption("Sensor SIMULASI. Bukan data sensor nyata.")
    st.dataframe(pd.DataFrame(SENSORS), hide_index=True, width="stretch")

    st.write("Pembacaan valid terakhir tiap sensor:")
    last_ok = (
        sensor_df[sensor_df["status"] == "OK"]
        .sort_values("timestamp")
        .groupby("sensor_id")
        .tail(1)
    )
    st.dataframe(last_ok, hide_index=True, width="stretch")

    st.write("Jumlah baris:", len(sensor_df))
    st.write("Jumlah pembacaan NO DATA:", int((sensor_df["status"] == "NO DATA").sum()))
    st.write("Ringkasan sensor untuk SOMAT:", sensor_summary)       