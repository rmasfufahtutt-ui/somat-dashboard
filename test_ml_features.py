"""Audit K04: pelatihan dan inferensi memakai satu pembentuk fitur dengan dukungan waktu yang sama."""
from datetime import date, datetime, timedelta, timezone

import pytest

import demo_ml as ml
import demo_weather as dw
import ml_features as mf

TZ = dw.TZ


def rows(vals):
    """vals: {date: (tmin, tmax, et0)} -> baris snapshot et0_daily."""
    return [{"date": d, "status": "OK", "tmin": a, "tmax": b, "et0_mm_day": e} for d, (a, b, e) in vals.items()]


D1, D2, D3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)


def test_feature_order_is_the_model_contract():
    assert ml.FEATURES == mf.FEATURES == ("tmean", "dtr", "et0", "etc", "h_start", "kc")


def test_window_starts_at_decision_not_at_earlier_observation_day():
    r = rows({date(2026, 2, 28): (10.0, 50.0, 99.0), D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, 5.0), D3: (24.0, 34.0, 6.0)})
    t0 = datetime(2026, 3, 1, 0, tzinfo=TZ)
    x, why = mf.features_for_decision(r, t0, -4.0, 1.2, TZ)                  # 00:00-00:00 -> tepat D1, D2
    assert why is None
    assert x["et0"] == pytest.approx(4.5) and x["tmean"] == pytest.approx(26.0) and x["dtr"] == pytest.approx(10.0)
    assert x["etc"] == pytest.approx(1.2 * 4.5) and x["h_start"] == -4.0 and x["kc"] == 1.2


def test_mid_day_decision_is_duration_weighted():
    r = rows({D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, 5.0), D3: (24.0, 34.0, 6.0)})
    t0 = datetime(2026, 3, 1, 12, tzinfo=TZ)                                  # 12 j D1, 24 j D2, 12 j D3
    x, _ = mf.features_for_decision(r, t0, -4.0, 1.0, TZ)
    assert x["et0"] == pytest.approx((12 * 4 + 24 * 5 + 12 * 6) / 48)


def test_missing_or_not_ok_day_makes_features_unavailable_without_guessing():
    r = rows({D1: (20.0, 30.0, 4.0)})
    t0 = datetime(2026, 3, 1, 0, tzinfo=TZ)
    x, why = mf.features_for_decision(r, t0, -4.0, 1.0, TZ)
    assert x is None and "tidak lengkap" in why
    r2 = rows({D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, 5.0)})
    r2[1]["status"] = "INCOMPLETE"
    assert mf.features_for_decision(r2, t0, -4.0, 1.0, TZ)[0] is None
    r3 = rows({D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, float("nan"))})
    assert mf.features_for_decision(r3, t0, -4.0, 1.0, TZ)[0] is None


def test_missing_h_or_kc_gives_reason():
    r = rows({D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, 5.0)})
    t0 = datetime(2026, 3, 1, 0, tzinfo=TZ)
    assert mf.features_for_decision(r, t0, None, 1.0, TZ)[1] == "h awal tidak tersedia"
    assert mf.features_for_decision(r, t0, -3.0, None, TZ)[1] == "Kc tidak tersedia"


def test_train_serve_parity_on_corpus_windows():
    """Untuk label latih mana pun, inferensi dengan masukan yang sama menghasilkan vektor fitur yang IDENTIK."""
    corpus = ml.generate_corpus(seed=5, n_plots=2, n_days=120)
    valid = [l for l in corpus["labels"] if l["validity"] == "VALID"]
    assert len(valid) > 50
    for lab in valid[::7]:
        kc = lab["x"][ml.FEATURES.index("kc")]
        x, why = mf.features_for_decision(lab["snapshot_days"], lab["start"], lab["h_start"], kc, TZ, w_days=lab["w_days"])
        assert why is None
        assert [x[f] for f in ml.FEATURES] == pytest.approx(lab["x"], rel=1e-12, abs=1e-12)


def test_features_from_output_uses_decision_window():
    r = rows({D1: (20.0, 30.0, 4.0), D2: (22.0, 32.0, 5.0), D3: (24.0, 34.0, 6.0)})
    t0 = datetime(2026, 3, 2, 0, tzinfo=TZ)
    x, why = ml.features_from_output({"h_decision_cm": -6.0}, {"et0_daily": r, "decision_at": t0}, 1.1)
    assert why is None and x["et0"] == pytest.approx(5.5) and x["h_start"] == -6.0
    assert ml.features_from_output({"h_decision_cm": -6.0}, {"et0_daily": r}, 1.1)[1] == "waktu keputusan tidak tersedia"
