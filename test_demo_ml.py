"""Model AI demo: pelaksanaan label temporal tanpa kebocoran, M1 vs M2 tanpa SPconstant ganda, fallback tanpa model."""
from datetime import datetime, timedelta

import pytest

import demo_ml as ml
import demo_repository as drepo
import demo_weather as dw

pytestmark = pytest.mark.skipif(not ml.HAS_SKLEARN, reason="scikit-learn tidak terpasang")


@pytest.fixture(scope="module")
def corpus():
    return ml.generate_corpus(seed=7, n_plots=4, n_days=260)


def test_corpus_uses_label_rules_and_is_synthetic(corpus):
    meta = corpus["meta"]
    assert meta["n_valid"] > 200 and "SINTETIS" in meta["source"]
    assert set(meta["rejected"]) <= {"CROSSES_ZERO", "IRRIGATION_IN_WINDOW", "RISE_IN_WINDOW", "RAIN_IN_WINDOW"}
    for lab in corpus["labels"]:
        if lab["validity"] == "VALID":
            assert 2.0 <= lab["w_days"] <= 3.0 and len(lab["x"]) == len(ml.FEATURES)


def test_temporal_split_has_no_leakage(corpus):
    import labels as lb
    t0 = datetime(ml.BASE_DATE.year, ml.BASE_DATE.month, ml.BASE_DATE.day, 8, tzinfo=dw.TZ)
    te, ve = t0 + timedelta(days=ml.TRAIN_DAYS), t0 + timedelta(days=ml.VALID_DAYS)
    sp = lb.split_temporal(corpus["labels"], te, ve)
    assert all(l["end"] <= te for l in sp["train"])
    assert all(l["start"] >= te and l["end"] <= ve for l in sp["valid"])
    assert all(l["start"] >= ve for l in sp["test"])
    assert sp["train"] and sp["valid"] and sp["test"]


def test_train_requires_admin(demo):
    demo.as_("operator")
    with pytest.raises(PermissionError):
        ml.train()


@pytest.fixture
def trained(demo):
    r = ml.train("demo_admin")
    assert r["status"] == "TRAINED", r
    return r


def test_train_reports_test_metrics_and_notice(trained):
    m = trained["metrics"]
    assert m["notice"].startswith("MODEL AI DEMONSTRASI") and "sintetis" in m["notice"]
    assert m["test"]["n"] > 50 and m["split"]["test"] == m["test"]["n"]
    assert m["better_on_test"] in ("M1", "M2") and "feature_importance" in m
    assert ml.status()["trained"] is True and ml.status()["model_id"] == trained["model_id"]


def test_m2_does_not_double_count_spconstant(trained, demo):
    from datetime import timezone
    now = drepo.now_utc()
    cmp_ = ml.compare_models("DEMO-P01", now, __import__("demo_data").default_weather("DEMO-P01"), bias=0.2)
    m1, m2, r = cmp_["M1"]["output"], cmp_["M2"]["output"], cmp_["residual"]
    assert m1["r_adj_mm_day"] == pytest.approx(1.5)                       # M1 = SPconstant profil
    assert m2["r_adj_mm_day"] == pytest.approx(r["residual"] + 0.2)       # M2 = residual ML + bias, TANPA + SPconstant
    assert m2["r_adj_mm_day"] != pytest.approx(r["residual"] + 0.2 + 1.5)
    assert cmp_["M2"]["snapshot"]["ml_residual_mm_day"] == pytest.approx(r["residual"])


def test_same_inputs_for_both_models(trained, demo):
    cmp_ = ml.compare_models("DEMO-P01", drepo.now_utc(), __import__("demo_data").default_weather("DEMO-P01"))
    a, b = cmp_["M1"]["snapshot"], cmp_["M2"]["snapshot"]
    assert a["h_observation"] == b["h_observation"] and a["et0_daily"] == b["et0_daily"] and a["parameters"] == b["parameters"]


def test_without_model_m2_is_unavailable_and_m1_still_works(demo):
    cmp_ = ml.compare_models("DEMO-P01", drepo.now_utc(), __import__("demo_data").default_weather("DEMO-P01"))
    assert cmp_["M2"] is None and cmp_["residual"]["available"] is False
    assert cmp_["M1"]["output"]["status"] == "OK"


def test_corrupt_model_blob_falls_back_without_crash(trained, demo):
    ml._CACHE.clear()
    con = drepo._connect()
    con.execute("UPDATE demo_models SET blob=?", (b"corrupt",))
    con.close()
    model, rec = ml.load_model()
    assert model is None
    assert ml.predict_residual({f: 1.0 for f in ml.FEATURES})["available"] is False


def test_model_loaded_once_not_retrained_on_use(trained, demo):
    ml._CACHE.clear()
    m1, _ = ml.load_model()
    m2, _ = ml.load_model()
    assert m1 is m2
    n = drepo.q("SELECT COUNT(*) AS n FROM demo_models")[0]["n"]
    ml.compare_models("DEMO-P01", drepo.now_utc(), __import__("demo_data").default_weather("DEMO-P01"))
    assert drepo.q("SELECT COUNT(*) AS n FROM demo_models")[0]["n"] == n
