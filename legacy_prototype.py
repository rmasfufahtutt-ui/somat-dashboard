"""legacy_prototype.py - logika PROTOTYPE lama (aturan sederhana + data simulasi).

Sejak Grand Framework v2 modul ini HANYA untuk mode DEMO:
  * hasilnya tidak pernah dipakai sebagai rekomendasi operasional, label pelatihan, atau metrik penelitian;
  * keluaran bertanda run_mode = DEMO dan sumber SIMULATED;
  * tidak ada ketergantungan Streamlit/DB. Teks dua bahasa memakai i18n.L.
Fungsi inti operasional ada di physics_engine.py, et0.py, dan recommendation_service.py.
"""
import numpy as np
import pandas as pd

from i18n import L

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
    dates = pd.date_range(end=pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None).normalize(), periods=days)

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
            "Pemeriksaan": L("Canal water level", "Tinggi muka air saluran"),
            "Nilai": f"{water_level:.2f} m",
            "Batas": f">= {min_water_level:.2f} m",
            "Result": "PASS" if water_level >= min_water_level else "FAIL",
        },
        {
            "Pemeriksaan": L("Available discharge", "Debit tersedia"),
            "Nilai": L(f"{available_discharge:.3f} m3/s (required {required_discharge:.3f})", f"{available_discharge:.3f} m3/s (dibutuhkan {required_discharge:.3f})"),
            "Batas": L("available >= required", "tersedia >= dibutuhkan"),
            "Result": "PASS" if available_discharge >= required_discharge else "FAIL",
        },
        {
            "Pemeriksaan": L("Gate operating limit", "Batas operasi pintu"),
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
        reasons.append(L("Predicted need is 0 mm, so irrigation is not required yet.", "Prediksi kebutuhan 0 mm, sehingga irigasi belum diperlukan."))
    elif hydraulic["feasible"]:
        recommended_mm = demand_mm
        reasons.append(L(
            f"Predicted need is {demand_mm} mm and all hydraulic checks passed, "
            "so the full amount is recommended.",
            f"Prediksi kebutuhan {demand_mm} mm dan semua cek hidraulik lolos, "
            "sehingga kebutuhan penuh disarankan.",
        ))
    else:
        recommended_mm = min(demand_mm, max_deliverable_mm)
        reasons.append(L(
            f"Predicted need is {demand_mm} mm, but the hydraulic check is NOT FEASIBLE.",
            f"Prediksi kebutuhan {demand_mm} mm, tetapi cek hidraulik TIDAK LAYAK.",
        ))
        if not level_ok:
            reasons.append(L("Canal water level is below the minimum limit.", "Tinggi muka air saluran di bawah batas minimum."))
        reasons.append(L(
            f"Only about {max_deliverable_mm:.1f} mm can be delivered within "
            f"{delivery_hours} hours, so the recommendation is reduced.",
            f"Hanya sekitar {max_deliverable_mm:.1f} mm yang dapat dialirkan dalam "
            f"{delivery_hours} jam, sehingga rekomendasi dikurangi.",
        ))
    recommended_mm = round(recommended_mm, 1)

    # Hitung durasi pemberian air (jam)
    if recommended_mm > 0 and usable_discharge > 0:
        duration_hours = recommended_mm * area_ha * 10 / (usable_discharge * 3600)
    else:
        duration_hours = 0.0

    # Tentukan prioritas
    if soil_moisture < 20 or demand_mm >= 20:
        priority = "HIGH"
        reasons.append(L("Soil is very dry or the need is large, so priority is HIGH.", "Tanah sangat kering atau kebutuhan besar, sehingga prioritas TINGGI."))
    elif demand_mm >= 3:
        priority = "NORMAL"
        reasons.append(L("Moderate need, so priority is NORMAL.", "Kebutuhan sedang, sehingga prioritas NORMAL."))
    else:
        priority = "LOW"
        reasons.append(L("Very small need, so priority is LOW.", "Kebutuhan sangat kecil, sehingga prioritas RENDAH."))

    return {
        "recommended_mm": recommended_mm,
        "duration_hours": round(duration_hours, 1),
        "feasibility": hydraulic["status"],
        "priority": priority,
        "reasons": reasons,
    }

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
            "title": L("Soil moisture too low", "Kelembapan tanah terlalu rendah"),
            "detail": L(f"Soil moisture {soil_moisture}% is below the {low_moisture}% limit.", f"Kelembapan tanah {soil_moisture}% di bawah batas {low_moisture}%."),
        })

    if water_level < min_water_level:
        alerts.append({
            "level": "error",
            "title": L("Canal water level too low", "Muka air saluran terlalu rendah"),
            "detail": L(f"Water level {water_level} m is below the {min_water_level} m limit.", f"Tinggi muka air {water_level} m di bawah batas {min_water_level} m."),
        })

    if rainfall >= heavy_rain:
        alerts.append({
            "level": "warning",
            "title": L("Heavy rain", "Hujan lebat"),
            "detail": L(f"Rainfall of {rainfall} mm reaches the {heavy_rain} mm limit.", f"Curah hujan {rainfall} mm mencapai batas {heavy_rain} mm."),
        })

    if recommendation["recommended_mm"] < prediction["irrigation_mm"]:
        alerts.append({
            "level": "error",
            "title": L("Demand exceeds hydraulic capacity", "Kebutuhan melebihi kapasitas hidraulik"),
            "detail": L(
                f"Predicted need is {prediction['irrigation_mm']} mm, but only "
                f"{recommendation['recommended_mm']} mm is recommended.",
                f"Kebutuhan prediksi {prediction['irrigation_mm']} mm, tetapi hanya "
                f"{recommendation['recommended_mm']} mm yang direkomendasikan.",
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
        status = "below"
    elif new_moisture <= target_moisture + 5:
        status = "on"
    else:
        status = "above"

    # Pesan umpan balik ke sistem SOMAT (kode + selisih; teks dibuat saat tampil)
    difference = operator_mm - recommended_mm
    if decision == "APPROVE":
        learning = {"kind": "approve", "diff": 0.0}
    elif decision == "DELAY":
        learning = {"kind": "delay", "diff": 0.0}
    elif difference > 0:
        learning = {"kind": "more", "diff": float(difference)}
    else:
        learning = {"kind": "less", "diff": float(difference)}

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

# Daftar tetap khusus generator fallback agar konfigurasi live tidak mengubah data simulasi.
SIMULATED_SENSORS = [dict(sensor) for sensor in SENSORS]


def generate_sensor_readings(hours=168, seed=7):
    """
    PROTOTYPE: membangkitkan pembacaan sensor SIMULASI per jam.
    Bukan data sensor nyata. Saat sensor sungguhan tersedia, fungsi ini
    diganti dengan pembaca data sensor; bagian lain tidak perlu berubah.
    """
    rng = np.random.default_rng(seed)
    times = pd.date_range(end=pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None).floor("h"), periods=hours, freq="h")

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
    for s in SIMULATED_SENSORS:
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
