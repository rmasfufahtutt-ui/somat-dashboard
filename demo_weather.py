"""demo_weather.py - pemaksa cuaca untuk ruang DEMO. Murni (tanpa DB/Streamlit), deterministik.

Dua sumber SELALU terpisah dan berlabel:
* "BMKG"      - prakiraan BMKG ASLI dari data hub. Tidak pernah dibuat/diubah di sini; jika kosong, hasilnya kosong
                (rekomendasi menjadi INCOMPLETE_FORECAST), BUKAN diisi data karangan.
* "SYNTHETIC" - suhu 3-jam sintetis berlabel (untuk skenario). Tidak pernah ditulis sebagai data BMKG.
Hujan dipilih terpisah dari sumber suhu: NONE (tanpa hujan, sama dengan mode operasional), atau skenario sintetis.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jakarta")
SLOT_HOURS = (1, 4, 7, 10, 13, 16, 19, 22)         # slot lokal BMKG 3-jaman

DRIVER_SYNTHETIC = "SYNTHETIC"
DRIVER_BMKG = "BMKG"
LABEL_SYNTHETIC = "Cuaca SINTETIS (skenario demo) — bukan data BMKG"
LABEL_BMKG = "Prakiraan BMKG (sumber asli)"

TEMP_PROFILES = {            # (tmin, tmax) rata-rata harian
    "NORMAL": (24.0, 33.0), "HOT": (25.0, 36.0), "COOL": (23.0, 30.0)}
RAIN_KINDS = {
    "NONE": {},                                           # tanpa hujan (NO_RAIN_SCENARIO), sama seperti operasional
    "LIGHT": {0: 10.0, 1: 4.0},                           # hari ke-N dari hari ini -> hujan efektif (mm/hari)
    "TODAY_HEAVY": {0: 45.0},                             # hujan lebat hari ini: menahan kebutuhan irigasi
    "HEAVY": {0: 30.0, 1: 30.0, 2: 14.0}}
RAIN_LABELS = {"NONE": "Tanpa hujan (NO_RAIN_SCENARIO)", "LIGHT": "Hujan ringan (sintetis)",
               "TODAY_HEAVY": "Hujan lebat hari ini (sintetis)", "HEAVY": "Hujan lebat 3 hari (sintetis)"}


def _u(*key) -> float:
    """Bilangan pseudo-acak deterministik dalam [0,1) dari kunci (tidak bergantung pada urutan pemanggilan)."""
    h = hashlib.sha256("|".join(str(k) for k in key).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _idx(d: date, base) -> int:
    """Indeks hari: relatif terhadap `base` (tanggal jangkar dataset) agar menggeser waktu demo tidak mengubah cuacanya."""
    if base is None:
        return d.toordinal()
    b = date.fromisoformat(base) if isinstance(base, str) else base
    return (d - b).days


def day_temps(d: date, profile: str = "NORMAL", seed: str = "", base=None) -> tuple:
    """(tmin, tmax) sintetis untuk tanggal d - fungsi murni dari (indeks hari, profil, seed)."""
    lo, hi = TEMP_PROFILES.get(profile, TEMP_PROFILES["NORMAL"])
    i = _idx(d, base)
    return (round(lo + (_u(seed, i, "lo") - 0.5) * 1.6, 2),
            round(hi + (_u(seed, i, "hi") - 0.5) * 2.4, 2))


def synthetic_points(start: date, days: int, profile: str = "NORMAL", seed: str = "", base=None) -> list:
    """Titik suhu 3-jaman [(datetime berzona WIB, suhu)] untuk `days` hari mulai `start` (8 slot/hari, kurva harian)."""
    pts = []
    for k in range(days):
        d = start + timedelta(days=k)
        tmin, tmax = day_temps(d, profile, seed, base)
        for hr in SLOT_HOURS:
            # minimum sekitar jam 05, maksimum sekitar jam 14
            phase = math.cos((hr - 14) / 24.0 * 2 * math.pi)
            t = tmin + (tmax - tmin) * (phase + 1) / 2
            pts.append((datetime(d.year, d.month, d.day, hr, tzinfo=TZ), round(t, 2)))
    return pts


def rain_by_date(kind: str, today: date) -> dict:
    """Hujan efektif (Pe, mm/hari) per tanggal untuk skenario `kind`; kosong = tanpa hujan."""
    spec = RAIN_KINDS.get(kind)
    if spec is None:
        raise ValueError(f"skenario hujan tidak dikenal: {kind}")
    return {today + timedelta(days=k): v for k, v in spec.items()}


def history_rain(today: date, days: int, seed: str = "", wet_fraction: float = 0.0) -> dict:
    """Hujan masa lalu sintetis (default tanpa hujan agar riwayat h tetap bentuk gigi gergaji AWD)."""
    out = {}
    for k in range(1, days + 1):
        d = today - timedelta(days=k)
        if wet_fraction and _u(seed, d.toordinal(), "rain") < wet_fraction:
            out[d] = round(3 + 12 * _u(seed, d.toordinal(), "amt"), 1)
    return out


def bmkg_points(composite_points_fn, forecast: dict | None) -> tuple:
    """Titik dari prakiraan BMKG ASLI. -> (points, meta). Tidak ada data -> ([], meta['available']=False)."""
    rows = (forecast or {}).get("rows") or []
    pts = composite_points_fn(rows, []) if rows else []
    meta = {"driver": DRIVER_BMKG, "label": LABEL_BMKG, "available": bool(pts), "n_points": len(pts),
            "issued_at": (forecast or {}).get("issued_at"), "fetched_at": (forecast or {}).get("fetched_at")}
    return pts, meta


def driver_points(driver: str, *, today: date, days: int, profile: str = "NORMAL", seed: str = "", base=None,
                  composite_points_fn=None, forecast: dict | None = None) -> tuple:
    """-> (points, meta). Sumber tidak pernah dicampur: satu panggilan = satu sumber."""
    if driver == DRIVER_SYNTHETIC:
        pts = synthetic_points(today, days, profile, seed, base)
        return pts, {"driver": DRIVER_SYNTHETIC, "label": LABEL_SYNTHETIC, "available": True, "n_points": len(pts),
                     "profile": profile, "seed": seed, "base": str(base) if base else None}
    if driver == DRIVER_BMKG:
        if composite_points_fn is None:
            raise ValueError("composite_points_fn diperlukan untuk driver BMKG")
        return bmkg_points(composite_points_fn, forecast)
    raise ValueError(f"driver cuaca tidak dikenal: {driver}")
