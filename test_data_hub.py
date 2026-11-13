import time
from datetime import datetime, timezone
import pandas as pd
import pytest
from settings import Settings
import sensor_sheet
from data_hub import DataHub, SOURCES


def mk_df(n=3, start="2026-11-13 06:00"):
    ts = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({"timestamp": ts, "sensor_id": "S1", "sensor_type": "soil_moisture", "location": "A",
                         "value": 40.0, "unit": "%", "status": "OK", "measurement_mode": "m", "device_id": "d",
                         "sequence": range(n), "source_type": "DUMMY"})


def hub(sensor=None, forecast=None, warn=None, **kw):
    st = Settings(background_fetch=False)
    return DataHub(st,
                   sensor or (lambda s: (mk_df(), {"configured": True, "ok": True, "message": "OK", "sensors": []})),
                   forecast or (lambda a: {"ok": True, "rows": [{}], "fetched_at": datetime.now(timezone.utc)}),
                   warn or (lambda: {"ok": True, "warnings": [1, 2]}), **kw)


def test_tick_pulls_all_and_publishes():
    h = hub()
    assert set(h.tick()) == set(SOURCES)
    s = h.snapshot()
    assert len(s.sensor_df) == 3 and s.forecast["ok"] and len(s.warnings) == 2
    assert all(s.source(n).ok for n in SOURCES) and s.version >= 3


def test_not_due_not_pulled_again():
    h = hub(); h.tick()
    assert h.tick() == []
    h.refresh_now("sensor")
    assert h.tick() == ["sensor"]


def test_failure_keeps_last_good_data():
    calls = {"n": 0}
    def sens(s):
        calls["n"] += 1
        if calls["n"] == 1:
            return mk_df(), {"configured": True, "ok": True, "message": "OK"}
        return sensor_sheet.empty_df(), {"configured": True, "ok": False, "error": "http_500", "message": "x"}
    h = hub(sensor=sens); h.tick(); h.refresh_now("sensor"); h.tick()
    s = h.snapshot()
    assert len(s.sensor_df) == 3
    assert not s.source("sensor").ok and s.source("sensor").error == "http_500"
    assert s.source("sensor").fetched_at is not None


def test_empty_ok_response_does_not_overwrite():
    calls = {"n": 0}
    def sens(s):
        calls["n"] += 1
        if calls["n"] == 1:
            return mk_df(), {"configured": True, "ok": True}
        return sensor_sheet.empty_df(), {"configured": True, "ok": True}
    h = hub(sensor=sens); h.tick(); h.refresh_now("sensor"); h.tick()
    s = h.snapshot()
    assert len(s.sensor_df) == 3 and s.source("sensor").suspicious_empty


def test_exception_in_fetcher_does_not_kill_tick():
    def boom(s): raise RuntimeError("x")
    h = hub(sensor=boom)
    h.tick()
    s = h.snapshot()
    assert not s.source("sensor").ok and s.source("forecast").ok


def test_not_configured_sensor():
    h = hub(sensor=lambda s: (sensor_sheet.empty_df(), {"configured": False, "ok": False, "message": "m"}))
    h.tick()
    assert h.snapshot().source("sensor").configured is False


def test_backoff_on_failures():
    h = hub(sensor=lambda s: (sensor_sheet.empty_df(), {"configured": True, "ok": False, "error": "e"}))
    h.tick(); h.tick(now=time.monotonic() + 1e6); h.tick(now=time.monotonic() + 2e6)
    assert h._fail_streak["sensor"] >= 2


def test_archive_failure_is_isolated():
    logged = []
    def bad(df, last): raise RuntimeError("db down")
    h = hub(archive_sensor=bad, log_ingest=lambda *a: logged.append(a))
    h.tick()
    assert len(h.snapshot().sensor_df) == 3
    assert any(not a[1] for a in logged)


def test_warm_start_marks_db_cache():
    h = hub(warm_loader=lambda: {"sensor_df": mk_df()})
    h.start()
    s = h.snapshot()
    assert s.source("sensor").origin == "db_cache" and len(s.sensor_df) == 3
    assert h._last_archived["S1"] == pd.Timestamp("2026-11-13 08:00")


def test_snapshot_immutable_swap():
    h = hub(); h.tick()
    old = h.snapshot(); h.refresh_now("warnings"); h.tick()
    assert h.snapshot().version > old.version and len(old.warnings) == 2


def test_background_thread_runs():
    st = Settings(background_fetch=True)
    h = DataHub(st, lambda s: (mk_df(), {"configured": True, "ok": True}),
                lambda a: {"ok": True, "rows": []}, lambda: {"ok": True, "warnings": []}).start()
    for _ in range(50):
        if h.snapshot().source("sensor").ok:
            break
        time.sleep(0.1)
    h.stop()
    assert h.alive() and h.snapshot().source("sensor").ok
