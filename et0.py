"""
et0.py - ET0 Hargreaves-Samani untuk SOMAT (fungsi murni, tanpa Streamlit/DB).

  ET0 = 0,0023 * (Tmean + 17,8) * sqrt(Tmax - Tmin) * Ra_mm      [mm/hari]
  Ra_mm = 0,408 * Ra   (Ra dalam MJ m-2 hari-1, FAO-56 pers. 21)

Catatan metodologis (Grand Framework v2, bagian 5):
  * Hargreaves-Samani adalah metode SEMENTARA untuk keterbatasan input; wajib dievaluasi terhadap
    pembanding lokal sebelum pembekuan penelitian. Arah dan besar bias belum diketahui; jangan
    memasang koreksi sepihak.
  * Tmin/Tmax dari prakiraan BMKG 3-jaman adalah ESTIMASI ekstrem harian (label
    ESTIMATED_FORECAST_EXTREMA) dan tidak setara dengan suhu pengamatan walau rumusnya sama.
  * Setiap konfigurasi (koefisien, aturan cakupan, rentang fisik) memiliki config_hash; METHOD_ID
    tunggal tidak menjamin pembekuan metode.
  * Hari dengan data kurang tetap muncul (INCOMPLETE_FORECAST) agar horizon tidak bergeser.
  * Nilai tidak masuk akal ditolak, bukan diubah diam-diam menjadi nol. Pembatasan max(0, ET0)
    ditandai (clamped=True).
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

METHOD_ID = "HS_v1"          # versi metode (rumus + definisi input)
HS_COEFFICIENT = 0.0023       # koefisien standar
GSC = 0.0820                  # MJ m-2 menit-1
LOCAL_TZ = ZoneInfo("Asia/Jakarta")
TEMP_SOURCE_FORECAST = "ESTIMATED_FORECAST_EXTREMA"
TEMP_SOURCE_OBSERVED = "OBSERVED_TEMPERATURE"

# Periode lokal untuk pemeriksaan cakupan slot. BMKG: slot lokal 01,04,07,10,13,16,19,22.
PERIODS = {"night": (0, 6), "morning": (6, 12), "afternoon": (12, 18), "evening": (18, 24)}


@dataclass(frozen=True)
class HSConfig:
    """Konfigurasi ET0 yang dibekukan. Mengubah apa pun di sini mengubah config_hash."""
    coefficient: float = HS_COEFFICIENT
    min_slots_per_day: int = 6
    required_periods: tuple = ("night", "morning", "afternoon")
    temp_min_c: float = -10.0      # rentang fisik yang disetujui untuk suhu udara
    temp_max_c: float = 55.0
    lat_limit_deg: float = 66.0

    @property
    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=list)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    @property
    def method_version(self) -> str:
        return f"{METHOD_ID}+{self.config_hash}"


DEFAULT_CONFIG = HSConfig()


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def extraterrestrial_radiation(lat_deg: float, day_of_year: int) -> float:
    """Ra (MJ m-2 hari-1), FAO-56 pers. 21-25."""
    if not _finite(lat_deg):
        raise ValueError("lintang tidak valid (bukan angka hingga)")
    if not -66.0 <= lat_deg <= 66.0:
        raise ValueError("lintang di luar jangkauan metode (±66°)")
    if not isinstance(day_of_year, int) or not 1 <= day_of_year <= 366:
        raise ValueError("day_of_year tidak valid")
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    x = max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta)))
    ws = math.acos(x)
    return (24 * 60 / math.pi) * GSC * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))


def hargreaves_et0(tmin_c: float, tmax_c: float, lat_deg: float, day_of_year: int,
                   coefficient: Optional[float] = None, config: HSConfig = DEFAULT_CONFIG) -> dict:
    """ET0 harian (mm/hari). Menolak NaN/Inf, suhu di luar rentang fisik, dan Tmax <= Tmin.

    `coefficient` (jika diberikan) menimpa config.coefficient dan menghasilkan config_hash baru.
    """
    if coefficient is not None and coefficient != config.coefficient:
        config = HSConfig(**{**asdict(config), "coefficient": float(coefficient),
                             "required_periods": config.required_periods})
    if not _finite(tmin_c, tmax_c):
        raise ValueError("suhu harus berupa angka hingga (bukan NaN/Inf)")
    if not (config.temp_min_c <= tmin_c <= config.temp_max_c and config.temp_min_c <= tmax_c <= config.temp_max_c):
        raise ValueError("suhu di luar rentang fisik yang disetujui")
    if tmax_c <= tmin_c:
        raise ValueError("Tmax harus lebih besar dari Tmin")
    if not _finite(config.coefficient) or config.coefficient <= 0:
        raise ValueError("koefisien tidak valid")
    ra = extraterrestrial_radiation(lat_deg, day_of_year)
    tmean = (tmin_c + tmax_c) / 2.0
    raw = config.coefficient * (tmean + 17.8) * math.sqrt(tmax_c - tmin_c) * 0.408 * ra
    return {"et0_mm_day": max(0.0, raw), "et0_raw": raw, "clamped": raw < 0.0, "ra_mj": ra, "tmean_c": tmean,
            "method": METHOD_ID, "method_version": config.method_version, "config_hash": config.config_hash}


# ----------------------------------------------------------------------------------------------
# Normalisasi waktu prakiraan (lokal vs UTC)
# ----------------------------------------------------------------------------------------------
def _parse_dt(text) -> Optional[datetime]:
    if isinstance(text, datetime):
        return text
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def normalize_forecast_rows(rows: Iterable[dict], tz: ZoneInfo = LOCAL_TZ) -> list:
    """Baris BMKG -> [{"valid_at": datetime berzona (lokal), "temp": float|None, "utc": datetime UTC, "time_basis": ..}].

    Prioritas: local_datetime (dianggap waktu dinding zona tz). Bila tidak ada, utc_datetime dianggap UTC
    lalu DIKONVERSI ke zona lokal sebelum agregasi harian. Baris tanpa waktu sah dibuang.
    """
    out = []
    for r in rows:
        temp = r.get("temperature", r.get("temp"))
        try:
            temp = float(temp) if temp is not None and temp != "" else None
        except (TypeError, ValueError):
            temp = None
        if temp is not None and not math.isfinite(temp):
            temp = None
        basis = None
        dt = _parse_dt(r.get("local_datetime"))
        if dt is not None:
            valid_local = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
            basis = "local"
        else:
            dtu = _parse_dt(r.get("utc_datetime"))
            if dtu is None:
                continue
            valid_local = (dtu if dtu.tzinfo else dtu.replace(tzinfo=timezone.utc)).astimezone(tz)
            basis = "utc_converted"
        out.append({"valid_at": valid_local, "utc": valid_local.astimezone(timezone.utc), "temp": temp,
                    "time_basis": basis})
    return out


def _period_of(hour: int) -> str:
    for name, (a, b) in PERIODS.items():
        if a <= hour < b:
            return name
    return "night"


def _as_local_naive(t, tz=LOCAL_TZ):
    """Waktu masukan -> waktu dinding lokal tanpa zona (naive datetime tetap dianggap lokal)."""
    if isinstance(t, datetime) and t.tzinfo is not None:
        return t.astimezone(tz).replace(tzinfo=None)
    return t


def daily_forecast_summary(points: list, config: HSConfig = DEFAULT_CONFIG, tz: ZoneInfo = LOCAL_TZ,
                           start_date: Optional[date] = None, end_date: Optional[date] = None) -> list:
    """points = [(datetime, suhu_C|None), ...]. Mengembalikan SATU entri untuk SETIAP tanggal lokal dari
    tanggal pertama sampai terakhir (atau start/end_date), termasuk hari kosong/kurang (INCOMPLETE_FORECAST).

    Slot dihitung unik berdasarkan waktu (duplikasi tidak menambah jumlah titik; nilai terakhir menang
    dan konflik ditandai). Hari lengkap bila slot unik >= min_slots_per_day DAN seluruh periode wajib terisi.
    """
    by_day = defaultdict(dict)       # tanggal -> {slot: suhu}
    conflicts = defaultdict(int)
    all_days = []
    for t, temp in points:
        t = _as_local_naive(t, tz)
        all_days.append(t.date())
        if temp is None:
            continue
        try:
            v = float(temp)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v):
            continue
        day = by_day[t.date()]
        if t in day and day[t] != v:
            conflicts[t.date()] += 1
        day[t] = v
    if not all_days and start_date is None:
        return []
    d0 = start_date or min(all_days)
    d1 = end_date or max(all_days)
    out = []
    d = d0
    while d <= d1:
        slots = by_day.get(d, {})
        vals = list(slots.values())
        periods = {_period_of(t.hour) for t in slots}
        missing = [p for p in config.required_periods if p not in periods]
        entry = {"date": d, "n": len(vals), "periods": sorted(periods), "conflicts": conflicts.get(d, 0),
                 "tmin": None, "tmax": None, "source": TEMP_SOURCE_FORECAST}
        if vals and len(vals) >= config.min_slots_per_day and not missing:
            entry.update(status="OK", tmin=min(vals), tmax=max(vals))
        else:
            reason = []
            if len(vals) < config.min_slots_per_day:
                reason.append(f"slot unik {len(vals)} < {config.min_slots_per_day}")
            if missing:
                reason.append("periode kosong: " + ",".join(missing))
            entry.update(status="INCOMPLETE_FORECAST", reason="; ".join(reason))
        out.append(entry)
        d += timedelta(days=1)
    return out


def daily_tminmax_from_forecast(points: list, min_points_per_day: int = 6) -> dict:
    """Kompatibilitas lama: {tanggal: {"tmin","tmax","n","source"}} hanya untuk hari lengkap."""
    cfg = HSConfig(min_slots_per_day=min_points_per_day)
    return {e["date"]: {"tmin": e["tmin"], "tmax": e["tmax"], "n": e["n"], "source": e["source"]}
            for e in daily_forecast_summary(points, cfg) if e["status"] == "OK"}


def forecast_et0_series(points: list, lat_deg: float, config: HSConfig = DEFAULT_CONFIG,
                        start_date: Optional[date] = None, end_date: Optional[date] = None) -> list:
    """ET0 per tanggal lokal dari prakiraan 3-jaman. Status: OK | INCOMPLETE_FORECAST | INVALID_RANGE | INVALID_INPUT.
    Tidak ada hari yang dihilangkan dari kalender."""
    res = []
    for e in daily_forecast_summary(points, config, start_date=start_date, end_date=end_date):
        row = {"date": e["date"], "status": e["status"], "n": e["n"], "tmin": e["tmin"], "tmax": e["tmax"],
               "et0_mm_day": None, "temperature_source": TEMP_SOURCE_FORECAST, "source_detail": "BMKG_FORECAST_3H",
               "method": METHOD_ID, "method_version": config.method_version, "config_hash": config.config_hash,
               "clamped": False, "periods": e["periods"], "reason": e.get("reason", "")}
        if e["status"] == "OK":
            if e["tmax"] <= e["tmin"]:
                row.update(status="INVALID_RANGE", reason="Tmax <= Tmin pada ekstrem prakiraan")
            else:
                try:
                    r = hargreaves_et0(e["tmin"], e["tmax"], lat_deg, e["date"].timetuple().tm_yday, config=config)
                    row.update(et0_mm_day=r["et0_mm_day"], clamped=r["clamped"], ra_mj=r["ra_mj"])
                except ValueError as exc:
                    row.update(status="INVALID_INPUT", reason=str(exc))
        res.append(row)
    return res
