"""derive.py - turunan tampilan dari snapshot hub, dihitung SEKALI per versi snapshot (memo di memori).

Pindah tab / rerun tidak menghitung ulang pandas apa pun; hanya saat hub menerbitkan snapshot baru.
Data simulasi (legacy_prototype) hanya boleh muncul di ruang DEMO (allow_simulation=True). Di ruang operasional
(allow_simulation=False) data yang tidak tersedia/tersaring QC menjadi "tidak tersedia" (NaN) atau data nyata terakhir
berumur jelas; nilai simulasi tidak pernah masuk ringkasan, tren, status petak, atau perhitungan operasional.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pandas as pd

import legacy_prototype as lp
import sensor_logic as sl
import sensor_qc

_LOCK = threading.Lock()
_MEMO: dict = {}
_SIM = {}


def _sim():
    if not _SIM:
        _SIM["df"] = lp.generate_simulated_data()
        _SIM["sensor_df"] = lp.generate_sensor_readings()
        _SIM["summary"] = sl.summarize_sensors(_SIM["sensor_df"])
    return _SIM


@dataclass
class Derived:
    version: int
    mode: str                       # LIVE | CACHED_DB | WAITING_FOR_DATA | SIMULATION_FALLBACK | SIMULATION | UNAVAILABLE
    sensor_df: pd.DataFrame
    sensors: list
    sensor_summary: dict
    sensor_daily: pd.DataFrame
    sensor_table: pd.DataFrame
    model_df: pd.DataFrame          # data harian prototipe (ET0 dst.) - DEMO
    latest: dict
    prediction: dict
    hydraulic: dict
    recommendation: dict
    alerts: list
    system_status: str
    n_online: int = 0
    n_total: int = 0
    source_types: list = field(default_factory=list)
    n_qc_excluded: int = 0          # pembacaan OK yang dikeluarkan dari perhitungan otomatis oleh QC (nilai mentah tetap ada)
    legacy_available: bool = True   # model prototipe (legacy_prototype, simulasi) tersedia hanya di ruang DEMO
    allow_simulation: bool = True

    @property
    def is_real(self) -> bool:
        return self.mode in ("LIVE", "CACHED_DB") and not set(self.source_types) & {"DUMMY", "SIMULATED"}


def _sensors_from_config(cfg):
    out = []
    for item in cfg or []:
        sid = str(item.get("sensor_id", "")).strip()
        if sid:
            out.append({"sensor_id": sid, "sensor_type": str(item.get("sensor_type", "")).strip(),
                        "location": str(item.get("location", "")).strip(), "unit": str(item.get("unit", "")).strip(),
                        "expected_interval_min": int(item.get("expected_interval_min") or 30),
                        "offline_after_min": int(item.get("offline_after_min") or 180),
                        "measurement_mode": str(item.get("measurement_mode") or "instantaneous")})
    return out


def _sensors_from_df(df):
    rows = []
    for sid, g in df.groupby("sensor_id"):
        last = g.iloc[-1]
        rows.append({"sensor_id": sid, "sensor_type": last["sensor_type"], "location": last.get("location") or "",
                     "unit": last.get("unit") or "", "expected_interval_min": 30, "offline_after_min": 180,
                     "measurement_mode": last.get("measurement_mode") or "instantaneous"})
    return rows


_NAN_LATEST_KEYS = ("soil_moisture", "water_level", "rainfall", "et0", "available_discharge", "crop_water_requirement")


def compute(snap, allow_simulation: bool = True) -> Derived:
    sim = _sim()
    src = snap.source("sensor")
    live = snap.sensor_df is not None and not snap.sensor_df.empty
    if live:
        sensor_df = snap.sensor_df                       # mentah, untuk tampilan
        gated, n_qc_excluded = sensor_qc.gate_for_decisions(sensor_df)   # untuk perhitungan otomatis
        cfg = _sensors_from_config((snap.sensor_meta or {}).get("sensors"))
        sensors = cfg or _sensors_from_df(sensor_df)
        summary = sl.summarize_sensors(gated, sensor_config=(snap.sensor_meta or {}).get("sensors"),
                                       fallback_summary=sim["summary"] if allow_simulation else None)
        daily = sl.build_sensor_daily_history(gated, fallback_sensor_df=sim["sensor_df"] if allow_simulation else None,
                                              days=14)
        mode = "CACHED_DB" if src.origin == "db_cache" else "LIVE"
    elif not allow_simulation:
        n_qc_excluded = 0
        sensor_df = gated = sim["sensor_df"].iloc[0:0].copy()          # kosong, kolom tetap
        sensors = _sensors_from_config((snap.sensor_meta or {}).get("sensors"))
        summary = sl.summarize_sensors(gated, sensor_config=(snap.sensor_meta or {}).get("sensors"), fallback_summary=None)
        daily = sl.build_sensor_daily_history(gated, days=14)
        mode = "UNAVAILABLE"
    else:
        n_qc_excluded = 0
        gated = sensor_df = sim["sensor_df"]
        sensors = [dict(s, expected_interval_min=30, offline_after_min=180, measurement_mode="instantaneous")
                   for s in lp.SENSORS]
        summary = sim["summary"]
        daily = sl.build_sensor_daily_history(sensor_df, days=14)
        if src.configured and src.ok:
            mode = "WAITING_FOR_DATA"
        elif src.configured and src.attempted_at is not None:
            mode = "SIMULATION_FALLBACK"
        else:
            mode = "SIMULATION"
    table = sl.sensor_status_table(gated, sensors)
    if not allow_simulation:
        return _operational_derived(snap, mode, sensor_df, sensors, summary, daily, table, n_qc_excluded)
    model_df = sim["df"]
    latest = model_df.iloc[-1].copy()
    for k in ("soil_moisture", "water_level", "rainfall"):
        latest[k] = summary[k]
    latest["crop_water_requirement"] = round(max(0.0, float(latest["et0"]) * 1.1
                                                 - 0.08 * (float(latest["soil_moisture"]) - 25)
                                                 - 0.4 * float(latest["rainfall"])), 1)
    pred = lp.predict_irrigation_requirement(soil_moisture=latest["soil_moisture"], rainfall=latest["rainfall"],
                                             et0=latest["et0"])
    hyd = lp.check_hydraulic_feasibility(irrigation_mm=pred["irrigation_mm"], available_discharge=latest["available_discharge"],
                                         water_level=latest["water_level"])
    rec = lp.generate_recommendation(prediction=pred, hydraulic=hyd, available_discharge=latest["available_discharge"],
                                     soil_moisture=latest["soil_moisture"])
    alerts = lp.detect_alerts(soil_moisture=latest["soil_moisture"], water_level=latest["water_level"],
                              rainfall=latest["rainfall"], prediction=pred, recommendation=rec)
    n_on = int((table["Status"] == "Online").sum()) if len(table) else 0
    types = sorted(set(sensor_df["source_type"].dropna().astype(str))) if "source_type" in sensor_df.columns else []
    return Derived(version=snap.version, mode=mode, sensor_df=sensor_df, sensors=sensors, sensor_summary=summary,
                   sensor_daily=daily, sensor_table=table, model_df=model_df, latest=latest.to_dict(),
                   prediction=pred, hydraulic=hyd, recommendation=rec, alerts=alerts,
                   system_status="ATTENTION" if (alerts or not hyd["feasible"]) else "NORMAL",
                   n_online=n_on, n_total=len(table), source_types=types, n_qc_excluded=n_qc_excluded)


def _operational_derived(snap, mode, sensor_df, sensors, summary, daily, table, n_qc_excluded) -> Derived:
    """Ruang operasional: tidak ada model prototipe simulasi; nilai tak tersedia tetap NaN."""
    latest = {k: float("nan") for k in _NAN_LATEST_KEYS}
    for k in ("soil_moisture", "water_level", "rainfall"):
        latest[k] = summary.get(k, float("nan"))
    n_on = int((table["Status"] == "Online").sum()) if len(table) else 0
    types = sorted(set(sensor_df["source_type"].dropna().astype(str))) if "source_type" in sensor_df.columns else []
    return Derived(version=snap.version, mode=mode, sensor_df=sensor_df, sensors=sensors, sensor_summary=summary,
                   sensor_daily=daily, sensor_table=table, model_df=_sim()["df"].iloc[0:0].copy(), latest=latest,
                   prediction={}, hydraulic={}, recommendation={}, alerts=[], system_status="UNKNOWN",
                   n_online=n_on, n_total=len(table), source_types=types, n_qc_excluded=n_qc_excluded,
                   legacy_available=False, allow_simulation=False)


def get(snap, allow_simulation: bool = True) -> Derived:
    """Turunan untuk snapshot ini (memo per versi; hanya 2 versi terakhir disimpan)."""
    key = (snap.version, bool(allow_simulation))
    d = _MEMO.get(key)
    if d is None:
        with _LOCK:
            d = _MEMO.get(key)
            if d is None:
                d = compute(snap, allow_simulation=allow_simulation)
                for old in sorted(_MEMO, key=lambda k: k[0])[:-2]:
                    _MEMO.pop(old, None)
                _MEMO[key] = d
    return d
