"""sensor_logic.py - ringkasan sensor, status online/offline, dan riwayat harian (fungsi murni, tanpa Streamlit).

Dipindahkan dari app.py dan dihitung SEKALI per pembaruan data di thread latar (data_hub), bukan pada setiap
rerun tampilan. Perubahan perilaku (Grand Framework v2):
  * Nilai simulasi TIDAK lagi diam-diam menggantikan sensor pada ringkasan keputusan; nilai yang tidak tersedia
    tetap NaN dan dicatat pada `missing_inputs`. Tampilan demo memakai ringkasan simulasi secara terpisah.
  * Status sensor dipisah: Online / Terlambat / Offline, dengan jenis sumber (DUMMY/SENSOR/SIMULATED).
"""
import numpy as np
import pandas as pd


def _wib_now_naive():
    """Waktu sekarang dalam WIB tanpa timezone, agar konsisten dengan sensor_sheet.py."""
    return pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None)


def _rainfall_increments(rf):
    """
    Mengubah pembacaan hujan menjadi nilai per interval.
    interval_mm: nilai sudah merupakan hujan pada interval tersebut.
    cumulative_mm: nilai penghitung kumulatif, dikonversi memakai selisih.
    """
    if rf.empty:
        return rf.assign(rain_increment=pd.Series(dtype=float))

    out = rf.copy().sort_values("timestamp")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["timestamp", "value"])

    if "measurement_mode" not in out.columns:
        out["measurement_mode"] = "interval_mm"
    out["measurement_mode"] = (
        out["measurement_mode"].fillna("interval_mm").astype(str).str.lower()
    )

    increments = pd.Series(index=out.index, dtype=float)
    for _, group in out.groupby("sensor_id", sort=False):
        mode = str(group["measurement_mode"].iloc[-1]).lower()
        values = group["value"].astype(float)

        if mode == "cumulative_mm":
            delta = values.diff()
            # Counter pertama dalam jendela tidak dianggap sebagai hujan interval.
            if len(delta):
                delta.iloc[0] = 0.0
            # Jika counter reset, nilai baru dianggap akumulasi setelah reset.
            reset = delta < 0
            delta.loc[reset] = values.loc[reset]
            increments.loc[group.index] = delta.clip(lower=0)
        else:
            increments.loc[group.index] = values.clip(lower=0)

    out["rain_increment"] = increments.fillna(0.0)
    return out


def _rainfall_total_last_24h(rf, now=None):
    """Akumulasi hujan aktual dalam 24 jam terakhir sesuai mode pengukuran."""
    if rf.empty:
        return np.nan

    now = now or _wib_now_naive()
    cutoff = now - pd.Timedelta(hours=24)
    increments = _rainfall_increments(rf)
    recent = increments[increments["timestamp"] >= cutoff]
    if recent.empty:
        return np.nan
    return float(recent["rain_increment"].sum())


def summarize_sensors(sensor_df, sensor_config=None, fallback_summary=None, soil_sensor_ids=None):
    """
    Mengubah pembacaan sensor menjadi input kondisi terbaru SOMAT.

    Sensor tanah dan muka air hanya dipakai untuk keputusan jika pembacaan
    valid masih segar (maksimum 3 jam). Jika tidak tersedia, nilai simulasi
    digunakan sebagai fallback yang ditandai pada sumber data dashboard.
    Curah hujan aktual dihitung dari 24 jam terakhir; jika rain gauge belum
    tersedia/aktif, nilai simulasi tetap dipakai untuk menjaga prototype.
    """
    now = _wib_now_naive()
    fallback_summary = fallback_summary or {}
    sensor_config = sensor_config or []

    if sensor_df is None or sensor_df.empty:
        valid = pd.DataFrame()
    else:
        work = sensor_df.copy()
        for column, default in (
            ("timestamp", pd.NaT),
            ("status", "NO DATA"),
            ("value", np.nan),
            ("sensor_type", ""),
            ("sensor_id", ""),
        ):
            if column not in work.columns:
                work[column] = default
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
        work["value"] = pd.to_numeric(work["value"], errors="coerce")
        work["status"] = work["status"].fillna("").astype(str).str.upper()
        valid = work[
            (work["status"] == "OK")
            & work["value"].notna()
            & work["timestamp"].notna()
        ].copy()

    fresh_cutoff = now - pd.Timedelta(hours=3)
    fresh = valid[valid["timestamp"] >= fresh_cutoff] if not valid.empty else valid

    # Kelembapan tanah: nilai valid terbaru setiap sensor, lalu rata-rata sensor aktif.
    sm_fresh = fresh[fresh["sensor_type"] == "soil_moisture"] if not fresh.empty else fresh
    if soil_sensor_ids and not sm_fresh.empty:
        sm_fresh = sm_fresh[sm_fresh["sensor_id"].isin(list(soil_sensor_ids))]
    sm_last = (
        sm_fresh
        .sort_values("timestamp")
        .groupby("sensor_id")
        .tail(1)
        if not fresh.empty else pd.DataFrame()
    )
    fallback_inputs = []
    if not sm_last.empty:
        soil_moisture = float(sm_last["value"].mean())
    else:
        soil_moisture = fallback_summary.get("soil_moisture", np.nan)
        fallback_inputs.append("soil moisture")

    # Muka air: pembacaan valid terbaru yang masih segar.
    wl = (
        fresh[fresh["sensor_type"] == "water_level"].sort_values("timestamp")
        if not fresh.empty else pd.DataFrame()
    )
    if not wl.empty:
        water_level = float(wl["value"].iloc[-1])
    else:
        water_level = fallback_summary.get("water_level", np.nan)
        fallback_inputs.append("water level")

    # Hujan: gunakan rain gauge aktual jika ada data dalam 24 jam terakhir.
    rf = (
        valid[valid["sensor_type"] == "rainfall"].sort_values("timestamp")
        if not valid.empty else pd.DataFrame()
    )
    rainfall_24h = _rainfall_total_last_24h(rf, now=now) if not rf.empty else np.nan
    if pd.isna(rainfall_24h):
        rainfall_24h = fallback_summary.get("rainfall", np.nan)
        fallback_inputs.append("rainfall")

    # Kualitas data live dihitung terhadap jumlah pembacaan yang diharapkan
    # berdasarkan interval pada Sensor_Config. Tidak menghitung data simulasi.
    quality_cutoff = now - pd.Timedelta(days=7)
    valid_7d = (
        valid[valid["timestamp"] >= quality_cutoff]
        if not valid.empty else pd.DataFrame()
    )

    if sensor_config:
        expected = 0
        for config in sensor_config:
            interval = max(1, int(config.get("expected_interval_min") or 30))
            expected += int((7 * 24 * 60) / interval)
        data_quality = min(
            100.0, 100.0 * len(valid_7d) / expected
        ) if expected else 0.0
    elif sensor_df is not None and not sensor_df.empty:
        work_ts = pd.to_datetime(sensor_df["timestamp"], errors="coerce")
        received_7d = sensor_df[work_ts >= quality_cutoff]
        data_quality = (
            100.0 * len(valid_7d) / len(received_7d)
            if len(received_7d) else 0.0
        )
    else:
        data_quality = 0.0

    return {
        "soil_moisture": round(float(soil_moisture), 1) if pd.notna(soil_moisture) else np.nan,
        "water_level": round(float(water_level), 2) if pd.notna(water_level) else np.nan,
        "rainfall": round(float(rainfall_24h), 1) if pd.notna(rainfall_24h) else np.nan,
        "sensors_used": int(sm_last["sensor_id"].nunique()) if not sm_last.empty else 0,
        "data_quality": round(float(data_quality), 1),
        "fallback_inputs": fallback_inputs,
    }


# ---------------- Status sensor (online/offline) ----------------
def sensor_status_table(sensor_df, sensors, offline_after_hours=3, default_source="DUMMY"):
    """Status per sensor berdasarkan umur data valid terhadap waktu WIB saat ini.

    Online    : data valid terakhir lebih baru dari 2x interval yang diharapkan
    Terlambat : lebih tua dari 2x interval tetapi belum melewati batas offline
    Offline   : tidak ada data valid, atau melewati batas offline
    Kolom `Sumber` memisahkan DUMMY / SENSOR / SIMULATED agar data dummy tidak tampak seperti alat lapangan.
    """
    now = _wib_now_naive()
    if sensor_df is None or sensor_df.empty:
        ok = pd.DataFrame(columns=["sensor_id", "timestamp"])
        src_by_sensor = {}
    else:
        work = sensor_df.copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
        work["status"] = work["status"].fillna("").astype(str).str.upper()
        ok = work[(work["status"] == "OK") & work["timestamp"].notna()].copy()
        src_by_sensor = (work.sort_values("timestamp").groupby("sensor_id")["source_type"].last().to_dict()
                         if "source_type" in work.columns else {})

    last_ok = (ok.groupby("sensor_id")["timestamp"].max()
               if not ok.empty else pd.Series(dtype="datetime64[ns]"))

    rows = []
    for sensor in sensors:
        sensor_id = sensor["sensor_id"]
        last = last_ok.get(sensor_id)
        offline_h = float(sensor.get("offline_after_min", offline_after_hours * 60)) / 60
        late_h = min(offline_h, 2.0 * float(sensor.get("expected_interval_min", 30)) / 60)
        if last is None or pd.isna(last) or (now - last) > pd.Timedelta(hours=offline_h):
            state = "Offline"
        elif (now - last) > pd.Timedelta(hours=late_h):
            state = "Terlambat"
        else:
            state = "Online"
        rows.append({
            "Sensor": sensor_id,
            "Jenis": sensor.get("sensor_type", ""),
            "Lokasi": sensor.get("location", ""),
            "Status": state,
            "Sumber": src_by_sensor.get(sensor_id, sensor.get("source_type", default_source)),
            "Data valid terakhir": last,
        })
    return pd.DataFrame(rows, columns=["Sensor", "Jenis", "Lokasi", "Status", "Sumber", "Data valid terakhir"])


def build_sensor_daily_history(sensor_df, fallback_sensor_df=None, days=14):
    """
    Membentuk seri harian untuk grafik yang sudah ada.
    Data aktual dipakai jika tersedia; simulasi hanya mengisi jenis sensor
    yang sama sekali belum memiliki sumber aktual (misalnya rain gauge belum aktif).
    Hari tanpa pembacaan aktual dibiarkan kosong, bukan diisi angka buatan.
    """
    end_date = _wib_now_naive().normalize()
    dates = pd.date_range(end=end_date, periods=days, freq="D")
    result = pd.DataFrame({"date": dates})

    def _valid_frame(frame):
        if frame is None or frame.empty:
            return pd.DataFrame()
        work = frame.copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
        work["value"] = pd.to_numeric(work["value"], errors="coerce")
        work["status"] = work["status"].fillna("").astype(str).str.upper()
        return work[
            (work["status"] == "OK")
            & work["timestamp"].notna()
            & work["value"].notna()
        ].copy()

    def _series(frame, sensor_type):
        data = _valid_frame(frame)
        data = data[data["sensor_type"] == sensor_type].copy()
        if data.empty:
            return pd.Series(dtype=float)

        data["date"] = data["timestamp"].dt.normalize()
        if sensor_type == "rainfall":
            increments = _rainfall_increments(data)
            increments["date"] = increments["timestamp"].dt.normalize()
            return increments.groupby("date")["rain_increment"].sum()
        return data.groupby("date")["value"].mean()

    for column, sensor_type in (
        ("soil_moisture", "soil_moisture"),
        ("water_level", "water_level"),
        ("rainfall", "rainfall"),
    ):
        values = _series(sensor_df, sensor_type)
        if values.empty and fallback_sensor_df is not None:
            values = _series(fallback_sensor_df, sensor_type)
        result[column] = result["date"].map(values)

    return result
