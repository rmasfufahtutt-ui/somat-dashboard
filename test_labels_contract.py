"""Regresi audit 16 Nov 2026 (K01-K03, K05): kontrak label jalur PENELITIAN vs DEMO sintetis."""
import math
from datetime import date, datetime, timedelta, timezone

import labels as L

UTC = timezone.utc
TZ7 = timezone(timedelta(hours=7))
T0 = datetime(2026, 1, 1, 7, tzinfo=UTC)
ETC = lambda a, b: 5.0
COV = (T0 - timedelta(days=1), T0 + timedelta(days=30))


def ob(i, days, v, **kw):
    t = T0 + timedelta(days=days)
    d = {"obs_id": i, "value": v, "observed_at": t, "received_at": t + timedelta(hours=1), "source_type": "MANUAL",
         "record_status": "ACTIVE", "quality_flag": "OK", "is_demo": False}
    d.update(kw)
    return d


def build(obs, irr=(), rain=(), cov=COV, **kw):
    return L.build_window_labels(obs, list(irr), list(rain), cov, ETC, 0.18, **kw)


def first(obs, **kw):
    return build(obs, **kw)[0]


# ------------------------------------------------------------------ K01: kematangan label vs cutoff
def test_k01_label_not_yet_available_never_enters_train():
    lab = first([ob(1, 0, -5), ob(2, 2, -12, received_at=T0 + timedelta(days=4))])    # tersedia 5 Jan 07:00
    assert lab["validity"] == "VALID" and lab["available_at"] == T0 + timedelta(days=4)
    s = L.split_temporal([lab], train_end=T0 + timedelta(days=3, hours=17), valid_end=T0 + timedelta(days=7))
    assert not s["train"] and lab in s["dropped"]


def test_k01_available_at_covers_all_label_ingredients():
    far_irr = {"arrived_at": T0 + timedelta(days=10), "ended_at": T0 + timedelta(days=10, hours=1),
               "received_at": T0 + timedelta(days=12)}                               # di luar jendela: tidak menunda label
    lab = first([ob(1, 0, -5), ob(2, 2, -12)], irr=[far_irr],
                rain=[{"observed_at": T0 + timedelta(days=1), "value_mm": 0.0, "received_at": T0 + timedelta(days=3)}])
    assert lab["available_at"] == T0 + timedelta(days=3)
    near_irr = {"arrived_at": T0 + timedelta(days=5), "ended_at": T0 + timedelta(days=5, hours=1), "received_at": T0 + timedelta(days=6)}
    assert first([ob(1, 0, -5), ob(2, 2, -12)], irr=[near_irr])["available_at"] == T0 + timedelta(days=2, hours=1)
    in_irr = {"arrived_at": T0 + timedelta(days=1), "ended_at": T0 + timedelta(days=1, hours=1), "received_at": T0 + timedelta(days=6)}
    assert first([ob(1, 0, -5), ob(2, 2, -12)], irr=[in_irr])["validity"] == "IRRIGATION_IN_WINDOW"
    lab2 = first([ob(1, 0, -5), ob(2, 1, -8, received_at=T0 + timedelta(days=9)), ob(3, 2, -12)])
    assert lab2["available_at"] >= T0 + timedelta(days=9)                              # pengamatan antara ikut dihitung
    lab3 = first([ob(1, 0, -5), ob(2, 2, -12)], inputs_available_at=T0 + timedelta(days=20))
    assert lab3["available_at"] == T0 + timedelta(days=20)


def test_k01_valid_set_also_requires_maturity():
    lab = first([ob(1, 0, -5), ob(2, 2, -12, received_at=T0 + timedelta(days=9))])
    s = L.split_temporal([lab], train_end=T0 - timedelta(days=1), valid_end=T0 + timedelta(days=5))
    assert not s["valid"] and lab in s["dropped"]


def test_k01_embargo_between_sets():
    labs = build([ob(1, 0, -1), ob(2, 2, -3), ob(3, 4, -6), ob(4, 6, -9)])
    s0 = L.split_temporal(labs, T0 + timedelta(days=2), T0 + timedelta(days=6))
    s3 = L.split_temporal(labs, T0 + timedelta(days=2), T0 + timedelta(days=6), embargo_days=3.0)
    assert len(s3["valid"]) < len(s0["valid"]) or len(s3["test"]) < len(s0["test"])
    assert all(l["start"] >= T0 + timedelta(days=5) for l in s3["valid"])


def test_k01_derive_embargo_from_protocol_not_constant():
    assert L.derive_embargo_days(feature_lookback_days=3.0, target_extension_days=1.0) == 4.0
    assert L.derive_embargo_days(0.0) == 0.0


# ------------------------------------------------------------------ K02: hujan kosong != tidak hujan
def test_k02_none_nan_inf_negative_rain_is_unknown():
    for bad in (None, float("nan"), float("inf"), -1.0, "x"):
        lab = first([ob(1, 0, -5), ob(2, 2, -12)], rain=[{"observed_at": T0 + timedelta(days=1), "value_mm": bad}])
        assert lab["validity"] == "RAIN_UNKNOWN", bad


def test_k02_missing_key_is_unknown():
    assert first([ob(1, 0, -5), ob(2, 2, -12)], rain=[{"observed_at": T0 + timedelta(days=1)}])["validity"] == "RAIN_UNKNOWN"


def test_k02_coverage_gap_in_middle_is_unknown():
    gap = [(T0 - timedelta(days=1), T0 + timedelta(hours=20)), (T0 + timedelta(days=1, hours=5), T0 + timedelta(days=9))]
    assert first([ob(1, 0, -5), ob(2, 2, -12)], cov=gap)["validity"] == "RAIN_UNKNOWN"
    whole = [(T0 - timedelta(days=1), T0 + timedelta(days=9))]
    assert first([ob(1, 0, -5), ob(2, 2, -12)], cov=whole)["validity"] == "VALID"


def test_k02_zero_rain_proven_by_coverage_is_valid():
    lab = first([ob(1, 0, -5), ob(2, 2, -12)], rain=[{"observed_at": T0 + timedelta(days=1), "value_mm": 0.0}])
    assert lab["validity"] == "VALID"
    assert first([ob(1, 0, -5), ob(2, 2, -12)])["validity"] == "VALID"                 # tak ada catatan + coverage sah


def test_k02_no_coverage_is_unknown():
    assert first([ob(1, 0, -5), ob(2, 2, -12)], cov=None)["validity"] == "RAIN_UNKNOWN"
    assert first([ob(1, 0, -5), ob(2, 2, -12)], cov=[])["validity"] == "RAIN_UNKNOWN"


# ------------------------------------------------------------------ K03: pagar sumber & status
def test_k03_research_rejects_demo_void_superseded_badqc_unknown_provenance():
    cases = {"is_demo": dict(is_demo=True), "VOID": dict(record_status="VOID"), "SUPERSEDED": dict(record_status="SUPERSEDED"),
             "BAD": dict(quality_flag="BAD"), "SUSPECT": dict(quality_flag="SUSPECT"), "SIM": dict(source_type="SIMULATED"),
             "NOSRC": dict(source_type=None)}
    for name, kw in cases.items():
        for which in (0, 1):                                                           # ujung awal / akhir
            o = [ob(1, 0, -5), ob(2, 2, -12)]
            o[which] = ob(which + 1, which * 2, o[which]["value"], **kw)
            assert first(o)["validity"] == "NON_RESEARCH_SOURCE", (name, which)


def test_k03_middle_observation_also_checked():
    o = [ob(1, 0, -5), ob(2, 1, -8, record_status="VOID"), ob(3, 2, -12)]
    assert all(l["validity"] == "NON_RESEARCH_SOURCE" for l in build(o) if l["end_obs_id"] == 3)


def test_k03_missing_status_fields_are_not_trusted():
    o = [ob(1, 0, -5), ob(2, 2, -12)]
    for x in o:
        x.pop("record_status")
    assert first(o)["validity"] == "NON_RESEARCH_SOURCE"


def test_k03_demo_synthetic_purpose_allows_demo_but_not_void_or_bad():
    kw = dict(purpose="DEMO_SYNTHETIC")
    assert first([ob(1, 0, -5, is_demo=True), ob(2, 2, -12, is_demo=True)], **kw)["validity"] == "VALID"
    assert first([ob(1, 0, -5, is_demo=True), ob(2, 2, -12, record_status="VOID")], **kw)["validity"] == "NON_RESEARCH_SOURCE"
    assert first([ob(1, 0, -5), ob(2, 2, -12, quality_flag="BAD")], **kw)["validity"] == "NON_RESEARCH_SOURCE"
    assert first([ob(1, 0, -5, is_demo=True), ob(2, 2, -12, is_demo=True)], **kw)["purpose"] == "DEMO_SYNTHETIC"


def test_k03_default_purpose_is_research_and_unknown_purpose_rejected():
    assert first([ob(1, 0, -5), ob(2, 2, -12)])["purpose"] == "RESEARCH"
    try:
        build([ob(1, 0, -5), ob(2, 2, -12)], purpose="WHATEVER")
        raise AssertionError("harus ditolak")
    except ValueError:
        pass


def test_k03_split_refuses_mixed_purposes():
    a = first([ob(1, 0, -5, is_demo=True), ob(2, 2, -12, is_demo=True)], purpose="DEMO_SYNTHETIC")
    b = first([ob(1, 0, -5), ob(2, 2, -12)])
    try:
        L.split_temporal([a, b], T0, T0 + timedelta(days=9))
        raise AssertionError("harus ditolak")
    except ValueError:
        pass


# ------------------------------------------------------------------ K05: rerata berbobot durasi pada interval yang sama
def test_k05_interval_mean_weighted_by_duration():
    daily = {date(2026, 1, 1): 10.0, date(2026, 1, 2): 20.0, date(2026, 1, 3): 40.0}
    t0, t1 = datetime(2026, 1, 1, 8, tzinfo=TZ7), datetime(2026, 1, 3, 8, tzinfo=TZ7)   # 2 hari
    # bobot: 1 Jan 16 j, 2 Jan 24 j, 3 Jan 8 j
    assert abs(L.mean_over_interval(daily, t0, t1, TZ7) - (16 * 10 + 24 * 20 + 8 * 40) / 48) < 1e-12


def test_k05_midnight_aligned_window_uses_exactly_its_dates():
    daily = {date(2026, 1, 1): 10.0, date(2026, 1, 2): 20.0, date(2026, 1, 3): 999.0}
    t0, t1 = datetime(2026, 1, 1, 0, tzinfo=TZ7), datetime(2026, 1, 3, 0, tzinfo=TZ7)
    assert abs(L.mean_over_interval(daily, t0, t1, TZ7) - 15.0) < 1e-12                # tanggal akhir TIDAK ikut


def test_k05_sharp_temperature_change_and_fractional_day():
    daily = {date(2026, 1, 1): 0.0, date(2026, 1, 2): 100.0}
    t0, t1 = datetime(2026, 1, 1, 18, tzinfo=TZ7), datetime(2026, 1, 2, 6, tzinfo=TZ7)
    assert abs(L.mean_over_interval(daily, t0, t1, TZ7) - 50.0) < 1e-12                # 6 jam vs 6 jam


def test_k05_missing_day_or_bad_interval_gives_none():
    daily = {date(2026, 1, 1): 10.0}
    t0, t1 = datetime(2026, 1, 1, 8, tzinfo=TZ7), datetime(2026, 1, 2, 8, tzinfo=TZ7)
    assert L.mean_over_interval(daily, t0, t1, TZ7) is None
    assert L.mean_over_interval(daily, t1, t0, TZ7) is None
    assert L.mean_over_interval({date(2026, 1, 1): math.nan, date(2026, 1, 2): 1.0}, t0, t1, TZ7) is None


def test_k05_utc_inputs_converted_to_local_days():
    daily = {date(2026, 1, 1): 10.0, date(2026, 1, 2): 30.0}
    t0, t1 = datetime(2026, 1, 1, 17, tzinfo=UTC), datetime(2026, 1, 2, 17, tzinfo=UTC)   # 2 Jan 00:00 - 3 Jan 00:00 WIB
    assert abs(L.mean_over_interval(daily, t0, t1, TZ7) - 30.0) < 1e-12
