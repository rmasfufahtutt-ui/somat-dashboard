import pandas as pd
from data_hub import Snapshot
import derive


def test_fallback_demo_when_no_sensor():
    d = derive.get(Snapshot(version=1))
    assert d.mode == "SIMULATION" and not d.is_real
    assert d.n_total == 8 and d.system_status in ("NORMAL", "ATTENTION")
    assert derive.get(Snapshot(version=1)) is d              # memo


def test_live_mode_and_real_flag():
    ts = pd.date_range(end=pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None), periods=6, freq="30min")
    df = pd.DataFrame({"timestamp": ts, "sensor_id": "SM-01", "sensor_type": "soil_moisture", "location": "P1",
                       "value": 33.0, "unit": "%", "status": "OK", "measurement_mode": "instantaneous",
                       "device_id": "d", "sequence": range(6), "source_type": "SENSOR"})
    d = derive.compute(Snapshot(version=2, sensor_df=df))
    assert d.mode == "LIVE" and d.is_real and d.sensor_summary["soil_moisture"] == 33.0
    df["source_type"] = "DUMMY"
    assert not derive.compute(Snapshot(version=3, sensor_df=df)).is_real


# ---------------------------------------------------------------- H06: tanpa fallback simulasi di ruang operasional
import math


def _fresh_df(values, status="OK"):
    ts = pd.date_range(end=pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None), periods=len(values), freq="30min")
    return pd.DataFrame({"timestamp": ts, "sensor_id": "SM-01", "sensor_type": "soil_moisture", "location": "P1",
                         "value": values, "unit": "%", "status": status, "measurement_mode": "instantaneous",
                         "device_id": "d", "sequence": range(len(values)), "source_type": "SENSOR"})


def test_h06_ops_without_sensor_is_unavailable_not_simulated():
    d = derive.compute(Snapshot(version=10), allow_simulation=False)
    assert d.mode == "UNAVAILABLE" and not d.is_real and not d.legacy_available
    assert math.isnan(d.sensor_summary["soil_moisture"]) and math.isnan(d.sensor_summary["rainfall"])
    assert math.isnan(d.latest["soil_moisture"]) and math.isnan(d.latest["available_discharge"])
    assert d.sensor_df.empty and d.alerts == [] and d.system_status == "UNKNOWN"
    assert d.sensor_daily[["soil_moisture", "water_level", "rainfall"]].isna().all().all()


def test_h06_ops_live_missing_types_stay_nan_demo_keeps_fallback():
    df = _fresh_df([33.0, 33.0, 33.0])
    ops = derive.compute(Snapshot(version=11, sensor_df=df), allow_simulation=False)
    assert ops.mode == "LIVE" and ops.sensor_summary["soil_moisture"] == 33.0
    assert math.isnan(ops.sensor_summary["water_level"]) and math.isnan(ops.sensor_summary["rainfall"])
    assert not ops.legacy_available and ops.sensor_daily["water_level"].isna().all()
    demo = derive.compute(Snapshot(version=12, sensor_df=df), allow_simulation=True)
    assert not math.isnan(demo.sensor_summary["water_level"]) and demo.legacy_available


def test_h06_ops_all_readings_excluded_by_qc_is_unavailable():
    df = _fresh_df([150.0, 160.0, 170.0])                              # semua di luar rentang -> tersaring
    ops = derive.compute(Snapshot(version=13, sensor_df=df), allow_simulation=False)
    assert math.isnan(ops.sensor_summary["soil_moisture"]) and ops.n_qc_excluded == 3
    assert ops.sensor_df["value"].tolist() == [150.0, 160.0, 170.0]    # mentah tetap tampil


def test_h06_memo_separates_ops_and_demo():
    s = Snapshot(version=14)
    a, b = derive.get(s, allow_simulation=True), derive.get(s, allow_simulation=False)
    assert a is not b and a.mode == "SIMULATION" and b.mode == "UNAVAILABLE"
