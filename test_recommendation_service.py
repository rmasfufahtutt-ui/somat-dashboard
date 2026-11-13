from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
import recommendation_service as rs

TZ = ZoneInfo("Asia/Jakarta")
NOW = datetime(2026, 11, 13, 7, 0, tzinfo=TZ)


def prm(v, st="LITERATURE"):
    return {"value": v, "status": st}


def profile(status="LITERATURE", **over):
    p = {"area_ha": prm(1.0, status), "mu_dry": prm(0.18, status), "mu_fill": prm(0.18, status),
         "lead_time_h": prm(24.0, status), "sp_constant": prm(2.0, status),
         "kc_vegetatif": prm(1.1, status), "trigger_h_vegetatif": prm(-15.0, status),
         "target_h_vegetatif": prm(5.0, status)}
    p.update(over)
    return {"profile_id": 7, "version": 1, "validation_status": "UNVALIDATED", "params": p,
            "phases": [{"phase": "vegetatif", "from_das": 0, "to_das": 60, "protected": False}]}


def rows(days=5, start=date(2026, 11, 12)):
    out = []
    for d in range(days):
        day = start + timedelta(days=d)
        for h, t in ((1, 24), (4, 23), (7, 26), (10, 30), (13, 32), (16, 31), (19, 27), (22, 25)):
            out.append({"local_datetime": f"{day} {h:02d}:00:00", "utc_datetime": "", "temperature": t})
    return out


def inputs(**kw):
    base = dict(plot={"plot_id": "P1", "latitude": -6.7}, profile=profile(),
                cycle={"cycle_id": 1, "planting_date": date(2026, 10, 20)},
                h_obs={"obs_id": 5, "value": -12.0, "observed_at": NOW - timedelta(hours=2)},
                points=rs.composite_points(rows(), []), decision_at=NOW, max_h_age_hours=30.0)
    base.update(kw)
    return base


def test_normal_run_ok_and_provisional():
    out, snap = rs.compute(**inputs())
    assert out["status"] == "OK", out["reasons"]
    assert out["run_mode"] == "BASELINE_PROVISIONAL"
    assert snap["h_observation"]["obs_id"] == 5 and snap["profile_id"] == 7 and snap["et0_daily"]


def test_example_parameters_give_demo():
    out, _ = rs.compute(**inputs(profile=profile(status="EXAMPLE")))
    assert out["run_mode"] == "DEMO"


def test_no_h_observation_requires_field():
    out, _ = rs.compute(**inputs(h_obs=None))
    assert out["status"] == "NEEDS_FIELD_OBSERVATION" and out["run_mode"] == "MANUAL_REQUIRED"


def test_stale_h():
    out, _ = rs.compute(**inputs(h_obs={"obs_id": 5, "value": -12.0, "observed_at": NOW - timedelta(hours=40)}))
    assert out["status"] == "STALE_OBSERVATION"


def test_no_profile_and_no_cycle():
    assert rs.compute(**inputs(profile=None))[0]["status"] == "PROFILE_REQUIRED"
    assert rs.compute(**inputs(cycle=None))[0]["status"] == "PROTOCOL_REQUIRED"


def test_pending_parameter_blocks():
    out, _ = rs.compute(**inputs(profile=profile(lead_time_h={"value": None, "status": "PENDING"})))
    assert out["status"] == "MISSING_PARAMETER" and "lead_time_h" in out["issues"][0]["params"]


def test_missing_latitude_incomplete():
    out, _ = rs.compute(**inputs(plot={"plot_id": "P1", "latitude": None}))
    assert out["status"] == "INCOMPLETE_FORECAST"


def test_no_forecast_incomplete():
    out, _ = rs.compute(**inputs(points=[]))
    assert out["status"] == "INCOMPLETE_FORECAST"


def test_outside_phase_requires_protocol():
    out, _ = rs.compute(**inputs(cycle={"cycle_id": 1, "planting_date": date(2026, 6, 1)}))
    assert out["status"] == "PROTOCOL_REQUIRED"


def test_irrigates_when_dry_and_computes_volume_with_discharge():
    p = profile(q_plot_m3s=prm(0.05))
    out, _ = rs.compute(**inputs(profile=p, h_obs={"obs_id": 5, "value": -14.0, "observed_at": NOW - timedelta(hours=1)}))
    assert out["irrigate"] is True and out["total_mm"] > 0 and out["duration_h"] > 0


def test_composite_latest_wins_and_archive_fills_past():
    old = [{"valid_at": datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc), "temp": 20.0}]
    latest = [{"local_datetime": "2026-11-13 01:00:00", "utc_datetime": "", "temperature": 30}]
    pts = rs.composite_points(latest, old + [{"valid_at": datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc), "temp": 21.0}])
    assert len(pts) == 1                             # 18:00Z == 01:00 WIB -> dedup; terbaru menang
    assert pts[0][1] == 30.0


def test_phase_helpers():
    ph = [{"phase": "a", "from_das": 0, "to_das": 9}, {"phase": "b", "from_das": 10, "to_das": 20}]
    pl = date(2026, 11, 1)
    assert rs.phase_at(datetime(2026, 11, 5, 12, tzinfo=TZ), pl, ph) == "a"
    assert rs.phase_at(datetime(2026, 11, 11, 12, tzinfo=TZ), pl, ph) == "b"
    assert rs.phase_at(datetime(2026, 12, 25, tzinfo=TZ), pl, ph) is None
    br = rs.phase_breaks(datetime(2026, 11, 8, tzinfo=TZ), datetime(2026, 11, 14, tzinfo=TZ), pl, ph)
    assert br == [datetime(2026, 11, 11, tzinfo=TZ)]
