"""ml_features.py - SATU pembentuk fitur untuk pelatihan, validasi, shadow, dan operasi (audit K04).

Kontrak: fitur sebuah prediksi dibentuk pada WAKTU KEPUTUSAN t0 untuk jendela [t0, t0 + W):
  tmean, dtr, et0, etc  = rerata berbobot durasi atas jendela itu (labels.mean_over_interval; tanggal lokal);
  h_start               = h pada t0 (pengamatan awal jendela saat pelatihan; h saat keputusan saat operasi);
  kc                    = Kc pada t0.
Saat pelatihan, jendela = [awal, akhir) label. Saat operasi, jendela = [keputusan, keputusan + W_DAYS). Cuaca masa depan hanya
dari prakiraan yang SUDAH terbit pada waktu keputusan. Tidak ada tebakan: satu hari tanpa nilai OK -> fitur tidak tersedia (None + alasan).
Fungsi murni; tanpa Streamlit/DB.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional

import labels as lb

FEATURES = ("tmean", "dtr", "et0", "etc", "h_start", "kc")
W_DAYS = 2.0                 # rancangan awal jendela label (2 hari), pembanding 3 hari diuji pada pilot
DAILY_KEYS = ("tmean", "dtr", "et0")


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def daily_from_snapshot(rows: list) -> dict:
    """Baris et0_daily snapshot [{date, status, tmin, tmax, et0_mm_day}] -> {kunci: {tanggal: nilai}}.
    Hanya hari berstatus OK dengan angka hingga; hari lain DIHILANGKAN (sehingga jendela yang memerlukannya tidak tersedia)."""
    out = {k: {} for k in DAILY_KEYS}
    for r in rows or []:
        if r.get("status") != "OK" or not all(_fin(r.get(k)) for k in ("tmin", "tmax", "et0_mm_day")):
            continue
        d = r["date"]
        if isinstance(d, datetime):
            d = d.date()
        out["tmean"][d] = (r["tmin"] + r["tmax"]) / 2.0
        out["dtr"][d] = r["tmax"] - r["tmin"]
        out["et0"][d] = r["et0_mm_day"]
    return out


def build_features(daily: dict, t0: datetime, t1: datetime, h_start, kc, tz) -> tuple:
    """-> (dict fitur sesuai FEATURES, None) atau (None, alasan). Pembentuk yang SAMA untuk pelatihan dan operasi."""
    if not _fin(h_start):
        return None, "h awal tidak tersedia"
    if not _fin(kc):
        return None, "Kc tidak tersedia"
    x = {}
    for k in DAILY_KEYS:
        v = lb.mean_over_interval(daily.get(k) or {}, t0, t1, tz)
        if v is None:
            return None, f"{k} tidak lengkap pada jendela (ada hari tanpa nilai OK)"
        x[k] = v
    x["etc"] = kc * x["et0"]                  # Kc konstan dalam jendela => rerata ETc = Kc x rerata ET0
    x["h_start"] = float(h_start)
    x["kc"] = float(kc)
    return {f: x[f] for f in FEATURES}, None


def features_for_decision(snapshot_rows: list, decision_at: datetime, h_decision, kc, tz, w_days: float = W_DAYS) -> tuple:
    """Fitur operasi: jendela [decision_at, decision_at + w_days) dari et0_daily snapshot. Hari sebelum keputusan (mis. tanggal
    pengamatan h terdahulu) tidak ikut."""
    return build_features(daily_from_snapshot(snapshot_rows), decision_at, decision_at + timedelta(days=w_days),
                          h_decision, kc, tz)
