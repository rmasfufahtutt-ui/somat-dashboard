"""
sensor_sheet.py - pembaca data sensor SOMAT dari Google Apps Script (Google Sheets).

Dipanggil dari app.py:
    live_sensor_df, sensor_connection = load_sensor_sheet_data(hours=336, limit=15000)

Mengembalikan (DataFrame, dict koneksi).

DataFrame kolom : timestamp (WIB, tanpa timezone), sensor_id, sensor_type, location,
                  value, unit, status, measurement_mode, device_id, sequence
dict koneksi    : configured (bool), ok (bool), count (int), sensors (list), message (str)

Secrets Streamlit yang dibaca (salah satu bentuk):
    SENSOR_SHEET_URL      = "https://script.google.com/macros/s/.../exec"
    SENSOR_SHEET_READ_KEY = "<key baca>"
atau dalam tabel:
    [sensor_sheet]
    url = "..."
    read_key = "..."
Key tidak pernah ditulis ke pesan error atau log.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

TIMEOUT_SECONDS = 20
CACHE_TTL_SECONDS = 60

COLUMNS = [
    "timestamp", "sensor_id", "sensor_type", "location", "value", "unit",
    "status", "measurement_mode", "device_id", "sequence",
]


def _empty_df():
    return pd.DataFrame(columns=COLUMNS)


def _get_secret(*paths):
    """Coba beberapa lokasi secret. paths: ("NAMA",) atau ("tabel", "nama")."""
    for path in paths:
        try:
            node = st.secrets
            for part in path:
                node = node[part]
            value = str(node).strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def _config():
    url = (
        _get_secret(("SENSOR_SHEET_URL",), ("sensor_sheet", "url"), ("sensor", "url"))
        or os.environ.get("SENSOR_SHEET_URL", "")
    )
    key = (
        _get_secret(("SENSOR_SHEET_READ_KEY",), ("sensor_sheet", "read_key"), ("sensor", "read_key"))
        or os.environ.get("SENSOR_SHEET_READ_KEY", "")
    )
    return url.strip(), key.strip()


def _result(df, configured, ok, message, sensors=None):
    return df, {
        "configured": configured,
        "ok": ok,
        "count": int(len(df)),
        "sensors": sensors or [],
        "message": message,
    }


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _fetch(url, key, hours, limit):
    """Ambil JSON dari Apps Script. Hanya hasil sukses/gagal yang ringkas yang dikembalikan."""
    query = urlencode({"action": "readings", "key": key, "hours": int(hours), "limit": int(limit)})
    sep = "&" if "?" in url else "?"
    req = Request(f"{url}{sep}{query}", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
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


def _to_frame(readings):
    if not readings:
        return _empty_df()
    df = pd.DataFrame(readings)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["timestamp"] = ts.dt.tz_convert("Asia/Jakarta").dt.tz_localize(None)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["status"] = df["status"].fillna("").astype(str).str.upper()
    df = df.dropna(subset=["timestamp"])
    df = df[df["sensor_id"].astype(str).str.strip() != ""]
    return df[COLUMNS].sort_values("timestamp").reset_index(drop=True)


def load_sensor_sheet_data(hours=336, limit=15000):
    url, key = _config()
    if not url or not key:
        return _result(_empty_df(), False, False,
                       "SENSOR_SHEET_URL / SENSOR_SHEET_READ_KEY belum diisi di Secrets.")

    payload = _fetch(url, key, hours, limit)

    if not payload.get("ok"):
        reason = str(payload.get("error") or "unknown_error")
        return _result(_empty_df(), True, False, f"Gagal membaca Google Sheets: {reason}")

    df = _to_frame(payload.get("readings") or [])
    sensors = payload.get("sensors") or []
    msg = "OK" if len(df) else "Terhubung, belum ada pembacaan sensor."
    return _result(df, True, True, msg, sensors=sensors)
