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
