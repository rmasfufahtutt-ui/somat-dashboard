"""
sensor_sheet.py - pembaca data sensor SOMAT dari Google Apps Script (Google Sheets).

Modul ini TIDAK memakai Streamlit sehingga dapat dipanggil dari thread latar (data_hub) dan worker terjadwal.
Pengambilan data tidak pernah dilakukan dari siklus tampilan; UI hanya membaca snapshot di data_hub.

fetch_sensor_data(settings) -> (DataFrame, dict koneksi)

DataFrame kolom : timestamp (WIB, tanpa timezone), sensor_id, sensor_type, location, value, unit,
                  status, measurement_mode, device_id, sequence, source_type
dict koneksi    : configured (bool), ok (bool), count (int), sensors (list), message (str), error (str|None)

source_type TIDAK diturunkan dari keberhasilan konektor: data yang lewat Google Sheets tetap DUMMY sampai
perangkat fisik terpasang dan `source_type` diubah di konfigurasi (atau dikirim per baris oleh Apps Script).
Key baca tidak pernah ditulis ke pesan galat atau log.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from settings import SOURCE_TYPES, Settings

TIMEOUT_SECONDS = 20
MAX_FUTURE_MINUTES = 10

COLUMNS = [
    "timestamp", "sensor_id", "sensor_type", "location", "value", "unit",
    "status", "measurement_mode", "device_id", "sequence", "source_type",
]


def empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _fetch_json(url: str, key: str, hours: int, limit: int) -> dict:
    """Ambil JSON dari Apps Script. Hanya hasil sukses/gagal ringkas yang dikembalikan."""
    query = urlencode({"action": "readings", "key": key, "hours": int(hours), "limit": int(limit)})
    sep = "&" if "?" in url else "?"
    try:
        req = Request(f"{url}{sep}{query}", headers={"Accept": "application/json"})
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except ValueError:
        return {"ok": False, "error": "invalid_url"}
    except HTTPError as exc:
        return {"ok": False, "error": f"http_{exc.code}"}
    except URLError:
        return {"ok": False, "error": "network_error"}
    except Exception:
        return {"ok": False, "error": "request_failed"}
    try:
        payload = json.loads(raw)
    except ValueError:
        # Apps Script mengembalikan halaman HTML jika deployment belum publik / salah URL.
        return {"ok": False, "error": "response_not_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "unexpected_response"}
    return payload


def to_frame(readings, default_source_type: str = "DUMMY", now=None) -> pd.DataFrame:
    """Daftar pembacaan -> DataFrame bersih. Duplikat (sensor_id, timestamp) dibuang (nilai terakhir menang);
    baris dengan waktu di masa depan (> 10 menit) dibuang karena tidak dapat menjadi pengamatan."""
    if not readings:
        return empty_df()
    df = pd.DataFrame(readings)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["timestamp"] = ts.dt.tz_convert("Asia/Jakarta").dt.tz_localize(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value"] = df["value"].where(np.isfinite(df["value"]))     # +-Inf -> NaN (tidak sah)
    df["status"] = df["status"].fillna("").astype(str).str.upper()
    src = df["source_type"].fillna("").astype(str).str.upper()
    df["source_type"] = src.where(src.isin(SOURCE_TYPES), default_source_type)
    df = df.dropna(subset=["timestamp"])
    df = df[df["sensor_id"].astype(str).str.strip() != ""]
    now = now or pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None)
    df = df[df["timestamp"] <= now + pd.Timedelta(minutes=MAX_FUTURE_MINUTES)]
    df = df.sort_values("timestamp").drop_duplicates(["sensor_id", "timestamp"], keep="last")
    return df[COLUMNS].reset_index(drop=True)


def _result(df, configured, ok, message, sensors=None, error=None):
    return df, {"configured": configured, "ok": ok, "count": int(len(df)), "sensors": sensors or [],
                "message": message, "error": error}


def fetch_sensor_data(settings: Settings):
    """Ambil dan normalisasi pembacaan sensor. Mengembalikan (DataFrame, dict koneksi)."""
    url, key = settings.sensor_url, settings.sensor_key
    if not url or not key:
        return _result(empty_df(), False, False, "SENSOR_SHEET_URL / SENSOR_SHEET_READ_KEY belum diisi di Secrets.")
    if not url.lower().startswith(("https://", "http://")):
        return _result(empty_df(), True, False, "SENSOR_SHEET_URL harus diawali https:// (cek nilai di Secrets).",
                       error="invalid_url")
    payload = _fetch_json(url, key, settings.sensor_hours, settings.sensor_limit)
    if not payload.get("ok"):
        reason = str(payload.get("error") or "unknown_error")
        return _result(empty_df(), True, False, f"Gagal membaca Google Sheets: {reason}", error=reason)
    df = to_frame(payload.get("readings") or [], settings.sensor_source_type)
    sensors = payload.get("sensors") or []
    msg = "OK" if len(df) else "Terhubung, belum ada pembacaan sensor."
    return _result(df, True, True, msg, sensors=sensors)
