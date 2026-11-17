"""Metrik evaluasi SOMAT: satuan fisik, sampel identik, selang pengamatan, acuan independen."""
import math
from datetime import datetime, timedelta, timezone

import pytest

import evaluation as ev

T = datetime(2026, 3, 1, 7, tzinfo=timezone.utc)


def h(x):
    return T + timedelta(hours=x)


# ---- galat dasar
def test_error_metrics_values_and_bias_sign():
    m = ev.error_metrics([(1.0, 0.0), (3.0, 0.0), (-2.0, 0.0)], min_n=1)
    assert m["n"] == 3 and m["mae"] == pytest.approx(2.0) and m["bias"] == pytest.approx(2 / 3)
    assert m["rmse"] == pytest.approx(math.sqrt((1 + 9 + 4) / 3))
    assert ev.error_metrics([(2.0, 1.0)], min_n=1)["bias"] == 1.0                    # prediksi melebihi pengamatan -> bias positif


def test_non_finite_pairs_dropped_and_counted_not_hidden():
    m = ev.error_metrics([(1.0, 1.0), (float("nan"), 1.0), (None, 2.0), (float("inf"), 1.0), (2.0, 1.0)], min_n=1)
    assert m["n"] == 2 and m["n_dropped"] == 3


def test_small_sample_is_flagged_not_hidden():
    m = ev.error_metrics([(1.0, 0.0)] * 3)
    assert m["insufficient_n"] is True and m["mae"] == 1.0
    assert ev.error_metrics([])["mae"] is None and ev.error_metrics(x for x in [(1.0, 0.0)])["n"] == 1


def test_by_horizon_groups_and_counts_plots():
    recs = [{"horizon_h": 24, "pred": 1.0, "obs": 0.0, "plot_id": "A"}, {"horizon_h": 24, "pred": -1.0, "obs": 0.0, "plot_id": "B"},
            {"horizon_h": 48, "pred": 4.0, "obs": 0.0, "plot_id": "A"}]
    out = ev.by_horizon(recs, min_n=1)
    assert out[24]["mae"] == 1.0 and out[24]["n_plots"] == 2 and out[48]["rmse"] == 4.0 and out[48]["n_plots"] == 1


# ---- skill & sampel identik
def test_skill_score_definition_and_zero_denominator():
    assert ev.skill_score(0.5, 1.0) == pytest.approx(0.5) and ev.skill_score(1.0, 1.0) == 0.0 and ev.skill_score(2.0, 1.0) == -1.0
    assert ev.skill_score(0.5, 0.0) is None and ev.skill_score(None, 1.0) is None


def test_paired_comparison_uses_only_common_keys():
    obs = {k: float(k) for k in range(10)}
    m2 = {k: (obs[k] + 0.1, obs[k]) for k in range(10)}
    m1b = {k: (obs[k] + 0.4, obs[k]) for k in range(2, 12) if k in obs}          # kunci 10,11 tidak ada di M2
    m1b.update({10: (1.0, 10.0)})
    r = ev.paired_comparison(m2, m1b, min_n=1)
    assert r["n_common"] == 8 and r["n_model_only"] == 2 and r["n_reference_only"] == 1
    assert r["skill_rmse"] == pytest.approx(1 - 0.1 / 0.4)


def test_paired_comparison_rejects_different_observations():
    with pytest.raises(ValueError):
        ev.paired_comparison({1: (1.0, 5.0)}, {1: (1.0, 6.0)})


def test_model_table_compares_each_model_to_reference_on_same_sample():
    obs = {k: 0.0 for k in range(10)}
    rec = {"M1B": {k: (1.0, 0.0) for k in obs}, "M2": {k: (0.5, 0.0) for k in obs}, "PERSISTENCE": {k: (2.0, 0.0) for k in range(5)}}
    rows = {r["model"]: r for r in ev.model_table(rec, reference="M1B", min_n=1)}
    assert rows["M1B"]["skill_vs_reference"] is None and rows["M2"]["skill_vs_reference"] == pytest.approx(0.5)
    assert rows["PERSISTENCE"]["n_common"] == 5 and rows["PERSISTENCE"]["skill_vs_reference"] == pytest.approx(-1.0)


# ---- waktu mencapai ambang
def test_trigger_timing_within_early_late_missed():
    br = (h(10), h(34))                                                           # pengamatan manual: selang 24 jam
    evs = [dict(event_id=i, plot_id="A", observed_bracket=br, predicted_at=t) for i, t in
           enumerate([h(20), h(4), h(40), None])]
    out = ev.trigger_timing(evs)
    assert [o["status"] for o in out] == ["WITHIN_BRACKET", "EARLY", "LATE", "MISSED"]
    assert out[0]["error_h"] == 0.0 and out[1]["error_h"] == pytest.approx(-6.0) and out[2]["error_h"] == pytest.approx(6.0)
    assert out[3]["error_h"] is None and out[0]["bracket_h"] == 24.0
    s = ev.trigger_summary(out)
    assert s["n_events"] == 4 and s["MISSED"] == 1 and s["mae_h"] == pytest.approx(4.0) and s["bias_h"] == pytest.approx(0.0)


def test_invalid_bracket_is_reported():
    out = ev.trigger_timing([dict(event_id=1, plot_id="A", observed_bracket=(h(5), h(1)), predicted_at=h(2))])
    assert out[0]["status"] == "BRACKET_INVALID"


def test_late_irrigation_vs_no_irrigation():
    br = (h(10), h(34))
    evs = [dict(event_id=1, observed_bracket=br, irrigation_arrived_at=h(40)), dict(event_id=2, observed_bracket=br, irrigation_arrived_at=h(30)),
           dict(event_id=3, observed_bracket=br, irrigation_arrived_at=None)]
    out = ev.late_irrigation(evs, tolerance_h=2.0)
    assert [o["status"] for o in out] == ["LATE", "ON_TIME", "NO_IRRIGATION"] and out[0]["delay_h"] == pytest.approx(6.0)


# ---- volume
def test_volume_requires_independent_documented_reference():
    good = [dict(recommended_mm=30.0, reference_mm=25.0, reference_source="rekonstruksi h teramati + ETc", independent=True, plot_id="A")] * 3
    m = ev.volume_errors(good, min_n=1)
    assert m["bias"] == pytest.approx(5.0) and m["unit"] == "mm" and m["n_plots"] == 1
    for bad in (dict(good[0], independent=False), dict(good[0], reference_source=""), {k: v for k, v in good[0].items() if k != "independent"}):
        with pytest.raises(ValueError):
            ev.volume_errors([bad])


# ---- batas
def test_limit_violations_only_checks_given_limits():
    recs = [dict(h_pred_max=9.0, h_pred_min=-20.0, sensitive_phase=True), dict(h_pred_max=4.0, h_pred_min=-10.0, sensitive_phase=False),
            dict(h_pred_max=6.0, h_pred_min=-3.0, sensitive_phase=True)]
    r = ev.limit_violations(recs, h_max_cm=7.0, sensitive_floor_cm=-5.0)
    assert r["overflow"] == 1 and r["below_sensitive_floor"] == 1 and r["below_floor"] == 0 and r["checked"] == ["overflow", "below_sensitive_floor"]
    assert ev.limit_violations(recs)["checked"] == []                               # tanpa batas dari protokol: tidak ada angka karangan
