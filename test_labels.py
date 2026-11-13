from datetime import datetime, timedelta, timezone
import labels as L

T0 = datetime(2026, 11, 1, 7, tzinfo=timezone.utc)
ETC = lambda a, b: 5.0


def ob(i, days, v, src="MANUAL"):
    t = T0 + timedelta(days=days)
    return {"obs_id": i, "value": v, "observed_at": t, "received_at": t + timedelta(hours=1), "source_type": src}


def build(obs, irr=(), rain=(), cov=None, **kw):
    cov = cov if cov is not None else (T0 - timedelta(days=1), T0 + timedelta(days=10))
    return L.build_window_labels(obs, list(irr), list(rain), cov, ETC, 0.18, **kw)


def test_valid_window_value():
    r = build([ob(1, 0, -5), ob(2, 2, -12)])
    assert len(r) == 1 and r[0]["validity"] == "VALID"
    assert abs(r[0]["residual_mm_day"] - (10 * 0.18 * 7 / 2 - 5.0)) < 1e-9


def test_irrigation_in_middle_rejected_even_if_ends_dry():
    r = build([ob(1, 0, -5), ob(2, 2, -12)], irr=[{"arrived_at": T0 + timedelta(days=1), "ended_at": T0 + timedelta(days=1, hours=2)}])
    assert r[0]["validity"] == "IRRIGATION_IN_WINDOW"


def test_rain_unknown_vs_rain_present():
    assert build([ob(1, 0, -5), ob(2, 2, -12)], cov=(T0 + timedelta(days=1), T0 + timedelta(days=5)))[0]["validity"] == "RAIN_UNKNOWN"
    r = build([ob(1, 0, -5), ob(2, 2, -12)], rain=[{"observed_at": T0 + timedelta(days=1), "value_mm": 3.0}])
    assert r[0]["validity"] == "RAIN_IN_WINDOW"


def test_rise_and_zero_crossing_and_dummy():
    labs = build([ob(1, 0, -5), ob(2, 1, -2), ob(3, 2, -9)])
    assert any(l["validity"] == "RISE_IN_WINDOW" for l in labs)
    assert build([ob(1, 0, 2), ob(2, 2, -3)])[0]["validity"] == "CROSSES_ZERO"
    assert build([ob(1, 0, -5, "DUMMY"), ob(2, 2, -12)])[0]["validity"] == "NON_REAL_SOURCE"


def test_window_length_bounds():
    assert build([ob(1, 0, -5), ob(2, 1, -8)]) == []
    assert build([ob(1, 0, -5), ob(2, 5, -20)]) == []


def test_negative_label_flagged_not_clipped():
    r = build([ob(1, 0, -5), ob(2, 2, -5.1)])
    assert r[0]["residual_mm_day"] < 0 and r[0]["negative_label_review"]


def test_split_drops_crossing():
    labs = build([ob(1, 0, -1), ob(2, 2, -3), ob(3, 4, -6), ob(4, 6, -9)])
    s = L.split_temporal(labs, T0 + timedelta(days=3), T0 + timedelta(days=5))
    assert s["dropped"] and all(l["end"] <= T0 + timedelta(days=3) for l in s["train"])
