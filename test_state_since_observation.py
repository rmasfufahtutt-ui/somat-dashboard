"""H11: kejadian aktual sejak h dibaca (irigasi, hujan terukur) memengaruhi keadaan petak yang dihitung."""
from datetime import timedelta

import pandas as pd
import pytest

import recommendation_service as rs
from physics_engine import recommend_timed
from test_physics_timed import D1, at, drivers, make_profile, RULE_AT, KC_AT


def run(since_obs=None, **kw):
    base = dict(h_obs_cm=-12.0, observed_at=at(D1, 7), decision_at=at(D1, 13), drivers=drivers(),
                profile=make_profile(), rule_at=RULE_AT, kc_param_at=KC_AT, model="M1", since_obs=since_obs)
    base.update(kw)
    return recommend_timed(**base)


def test_no_events_runs_normally_and_identical_without_since_obs():
    a = run(since_obs={"irrigation_events": 0, "irrigation_decided": 0, "rain_mm": 0.0})
    b = run(since_obs=None)
    assert a["status"] == "OK" and a["h_arrival_cm"] == b["h_arrival_cm"] and a["issues"] == b["issues"]


@pytest.mark.parametrize("key", ["irrigation_events", "irrigation_decided"])
def test_irrigation_since_observation_needs_new_h(key):
    r = run(since_obs={"irrigation_events": 0, "irrigation_decided": 0, "rain_mm": 0.0, key: 1})
    assert r["status"] == "STATE_NOT_RECONSTRUCTABLE" and r["run_mode"] == "MANUAL_REQUIRED"
    assert r["issues"][0]["code"] == "IRRIGATION_SINCE_OBSERVATION" and r["h_decision_cm"] is None


def test_measured_rain_since_observation_needs_new_h_but_zero_does_not():
    r = run(since_obs={"irrigation_events": 0, "irrigation_decided": 0, "rain_mm": 6.2})
    assert r["status"] == "STATE_NOT_RECONSTRUCTABLE" and r["issues"][0]["code"] == "RAIN_SINCE_OBSERVATION"
    assert run(since_obs={"rain_mm": 0.0})["status"] == "OK"


def test_unknown_rain_is_not_zero_it_is_flagged_but_does_not_block():
    r = run(since_obs={"irrigation_events": 0, "irrigation_decided": 0, "rain_mm": None})
    assert r["status"] == "OK"
    assert any(i["code"] == "PAST_RAIN_UNKNOWN" for i in r["issues"])


def test_demo_style_since_obs_without_rain_key_skips_rain_check():
    r = run(since_obs={"irrigation_events": 0, "irrigation_decided": 0})
    assert r["status"] == "OK" and not any(i["code"] == "PAST_RAIN_UNKNOWN" for i in r["issues"])


# ------------------------------------------------------------------ rain_since_observation (cakupan gauge)
def _rain(times, vals, sid="RG-01", mode="interval_mm", status="OK"):
    return pd.DataFrame({"timestamp": times, "sensor_id": sid, "sensor_type": "rainfall", "value": vals,
                         "status": status, "measurement_mode": mode, "unit": "mm"})


def _wib_naive(dt):
    return pd.Timestamp(dt.astimezone(rs.TZ).replace(tzinfo=None))


def test_rain_sum_when_gauge_covers_whole_interval():
    obs, dec = at(D1, 7), at(D1, 13)
    t = [_wib_naive(obs) + timedelta(minutes=30 * i) for i in range(0, 13)]       # 07:00..13:00 tiap 30 mnt
    df = _rain(t, [0.0] * 5 + [1.5, 2.0] + [0.0] * 6)
    assert rs.rain_since_observation(df, "RG-01", obs, dec) == pytest.approx(3.5)


def test_rain_unknown_when_gap_or_no_gauge_or_wrong_sensor():
    obs, dec = at(D1, 7), at(D1, 13)
    t = [_wib_naive(obs) + timedelta(minutes=30 * i) for i in range(0, 13)]
    gap = _rain(t[:4] + t[10:], [0.0] * 7)                                       # celah 4,5 jam
    assert rs.rain_since_observation(gap, "RG-01", obs, dec) is None
    assert rs.rain_since_observation(_rain(t, [0.0] * 13), None, obs, dec) is None       # petak tanpa rain gauge
    assert rs.rain_since_observation(_rain(t, [0.0] * 13), "RG-99", obs, dec) is None    # sensor lain
    assert rs.rain_since_observation(None, "RG-01", obs, dec) is None
    stale = _rain(t[:3], [0.0] * 3)                                              # berhenti sebelum keputusan
    assert rs.rain_since_observation(stale, "RG-01", obs, dec) is None
    assert rs.rain_since_observation(_rain(t, [0.0] * 13, status="ERROR"), "RG-01", obs, dec) is None


def test_events_since_observation_counts_only_active_in_window():
    obs, dec = at(D1, 7), at(D1, 13)

    class Repo:
        def list_irrigation_events(self, plot_id, limit):
            return [{"record_status": "ACTIVE", "arrived_at": obs + timedelta(hours=2)},
                    {"record_status": "VOID", "arrived_at": obs + timedelta(hours=3)},
                    {"record_status": "ACTIVE", "arrived_at": obs - timedelta(hours=1)},
                    {"record_status": "ACTIVE", "arrived_at": dec + timedelta(hours=1)}]

        def list_decisions(self, limit, plot_id, only_active):
            return [{"decision": "APPROVE", "ts": obs + timedelta(hours=1), "plot_id": "P1"},
                    {"decision": "DELAY", "ts": obs + timedelta(hours=1), "plot_id": "P1"},
                    {"decision": "MODIFY", "ts": obs - timedelta(hours=1), "plot_id": "P1"}]

    got = rs.events_since_observation(Repo(), "P1", obs, dec)
    assert got == {"irrigation_events": 1, "irrigation_decided": 1}
