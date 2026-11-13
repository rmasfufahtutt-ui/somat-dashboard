"""settings.py - konfigurasi SOMAT dari Streamlit Secrets atau variabel lingkungan.

Dibaca SEKALI di thread utama lalu dioper ke komponen lain, sehingga thread latar dan worker terjadwal
tidak bergantung pada Streamlit. Kunci/URL tidak pernah ditulis ke pesan galat atau log.

Secrets Streamlit (semua opsional kecuali [neon]):
    [neon]            url = "postgresql://..."
    [bootstrap_admin] username = "..."  password = "..."
    [sensor_sheet]    url = "https://script.google.com/.../exec"  read_key = "..."
                      source_type = "DUMMY"      # ubah ke "SENSOR" hanya setelah perangkat fisik terpasang
    [bmkg]            adm4 = "32.10.15.2003"
    [somat]           refresh_sensor_s = 90 | refresh_forecast_s = 1800 | refresh_warning_s = 300
                      max_h_age_hours = 30 | rec_expiry_hours = 6 | background_fetch = true
Variabel lingkungan setara: DATABASE_URL, SENSOR_SHEET_URL, SENSOR_SHEET_READ_KEY, SENSOR_SOURCE_TYPE, BMKG_ADM4.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

SOURCE_TYPES = ("MANUAL", "SENSOR", "BMKG_FORECAST", "BBWS_OBSERVED", "STATION_OBSERVED", "DUMMY", "SIMULATED")
DEFAULT_ADM4 = "32.10.15.2003"        # Desa Panongan, Jatitujuh, Majalengka (lokasi administratif, bukan koordinat petak)


def _num(value, default, lo=None, hi=None, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        return default
    if hi is not None and v > hi:
        return default
    return v


def _flag(value, default=True):
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    db_url: str = ""
    sensor_url: str = ""
    sensor_key: str = field(default="", repr=False)
    sensor_source_type: str = "DUMMY"
    bmkg_adm4: str = DEFAULT_ADM4
    refresh_sensor_s: float = 90.0
    refresh_forecast_s: float = 1800.0
    refresh_warning_s: float = 300.0
    sensor_hours: int = 336
    sensor_limit: int = 15000
    max_h_age_hours: float = 30.0       # default sementara; batas operasional ditetapkan melalui pilot
    rec_expiry_hours: float = 6.0
    background_fetch: bool = True

    @property
    def sensor_configured(self) -> bool:
        return bool(self.sensor_url and self.sensor_key)

    @classmethod
    def from_mapping(cls, get, env=os.environ) -> "Settings":
        """get(section, key) -> str|None. Nilai env dipakai bila secret kosong."""
        def pick(section, key, env_name, default=""):
            v = get(section, key)
            if v in (None, ""):
                v = env.get(env_name, "") if env_name else ""
            return str(v).strip().strip("\"'").strip() if v not in (None,) else default

        src = pick("sensor_sheet", "source_type", "SENSOR_SOURCE_TYPE", "DUMMY").upper()
        if src not in SOURCE_TYPES:
            src = "DUMMY"
        url = pick("sensor_sheet", "url", "SENSOR_SHEET_URL") or str(get("sensor", "url") or "").strip()
        key = pick("sensor_sheet", "read_key", "SENSOR_SHEET_READ_KEY") or str(get("sensor", "read_key") or "").strip()
        return cls(
            db_url=pick("neon", "url", "DATABASE_URL"),
            sensor_url=url, sensor_key=key, sensor_source_type=src,
            bmkg_adm4=pick("bmkg", "adm4", "BMKG_ADM4") or DEFAULT_ADM4,
            refresh_sensor_s=_num(get("somat", "refresh_sensor_s"), 90.0, 30.0, 3600.0),
            refresh_forecast_s=_num(get("somat", "refresh_forecast_s"), 1800.0, 300.0, 86400.0),
            refresh_warning_s=_num(get("somat", "refresh_warning_s"), 300.0, 60.0, 86400.0),
            max_h_age_hours=_num(get("somat", "max_h_age_hours"), 30.0, 1.0, 168.0),
            rec_expiry_hours=_num(get("somat", "rec_expiry_hours"), 6.0, 0.5, 72.0),
            background_fetch=_flag(get("somat", "background_fetch"), True),
        )

    @classmethod
    def from_streamlit(cls) -> "Settings":
        import streamlit as st

        def get(section, key):
            try:
                return st.secrets[section][key]
            except Exception:
                try:                                    # bentuk datar: SENSOR_SHEET_URL = "..."
                    flat = {("sensor_sheet", "url"): "SENSOR_SHEET_URL", ("sensor_sheet", "read_key"): "SENSOR_SHEET_READ_KEY",
                            ("neon", "url"): "DATABASE_URL"}.get((section, key))
                    return st.secrets[flat] if flat else None
                except Exception:
                    return None
        return cls.from_mapping(get)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_mapping(lambda section, key: None)
