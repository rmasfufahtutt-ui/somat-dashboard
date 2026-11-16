"""Audit K06: M1B terhubung ke jalur layanan + state bias adaptif yang adil dan dapat diaudit."""
import math
from datetime import datetime, timedelta, timezone

import pytest

import bias_state as bs
import physics_engine as pe

UTC = timezone.utc
T0 = datetime(2026, 3, 1, tzinfo=UTC)
CFG = bs.BiasConfig(alpha=0.3, lam=0.1, bmax=1.5, max_age_days=7.0, frozen_from="uji")


def lab(i, start_d, w=2.0, r=3.0, avail_extra_h=1.0, validity="VALID"):
    s = T0 + timedelta(days=start_d)
    e = s + timedelta(days=w)
    return {"label_id": i, "start": s, "end": e, "available_at": e + timedelta(hours=avail_extra_h), "residual_mm_day": r,
            "validity": validity}


def prior(start_d, r_base, issued_before_h=2.0):
    return {"issued_at": T0 + timedelta(days=start_d) - timedelta(hours=issued_before_h), "r_base_mm_day": r_base}


NOW = T0 + timedelta(days=30)


# ------------------------------------------------------------------ M1B terhubung ke mesin rekomendasi
def test_recommend_timed_m1b_uses_bias_and_m1_ignores_it():
    from test_physics_timed import run
    m1 = run(model="M1")
    m1_b = run(model="M1", bias=0.7)
    m1b0 = run(model="M1B", bias=0.0)
    m1b = run(model="M1B", bias=0.7)
    assert m1["f_mm_day_arrival"] == pytest.approx(m1_b["f_mm_day_arrival"])        # M1 mengabaikan bias
    assert m1b0["f_mm_day_arrival"] == pytest.approx(m1["f_mm_day_arrival"])        # M1B tanpa bias = M1
    assert m1b["f_mm_day_arrival"] - m1b0["f_mm_day_arrival"] == pytest.approx(0.7)  # bias masuk ke F tepat sekali
    assert m1b["h_arrival_cm"] < m1b0["h_arrival_cm"]                               # kehilangan lebih besar -> h turun


def test_r_adj_forms_and_no_double_sp():
    assert pe.r_adj_for_model("M1B", 2.0, 0.5, None) == 2.5
    assert pe.r_adj_for_model("M2", None, 0.5, 1.2) == 1.7


# ------------------------------------------------------------------ state bias
def test_first_update_matches_formula_and_records_audit():
    st = bs.BiasState("P1", "M1B")
    r = bs.apply_label(st, CFG, lab(1, 0, r=3.0), prior(0, 2.0), NOW)
    assert r["applied"] and st.b == pytest.approx(0.3 * (3.0 - 2.0))
    assert st.history[-1]["e_base_mm_day"] == pytest.approx(1.0) and st.consumed == {1}


def test_label_used_once_only():
    st = bs.BiasState("P1", "M1B")
    bs.apply_label(st, CFG, lab(1, 0), prior(0, 2.0), NOW)
    b = st.b
    r = bs.apply_label(st, CFG, lab(1, 0), prior(0, 2.0), NOW)
    assert not r["applied"] and r["reason"] == "ALREADY_USED" and st.b == b


def test_overlapping_windows_are_not_independent_evidence():
    st = bs.BiasState("P1", "M2")
    assert bs.apply_label(st, CFG, lab(1, 0), prior(0, 2.0), NOW)["applied"]
    r = bs.apply_label(st, CFG, lab(2, 1), prior(1, 2.0), NOW)                    # mulai hari-1 < akhir jendela pertama (hari-2)
    assert not r["applied"] and r["reason"] == "OVERLAPS_USED_WINDOW"
    assert bs.apply_label(st, CFG, lab(3, 2), prior(2, 2.0), NOW)["applied"]      # berurutan tanpa tumpang tindih


def test_immature_invalid_and_non_apriori_are_rejected_without_changing_state():
    st = bs.BiasState("P1", "M1B")
    assert bs.apply_label(st, CFG, lab(1, 0), prior(0, 2.0), T0 + timedelta(days=1))["reason"] == "LABEL_NOT_MATURE"
    assert bs.apply_label(st, CFG, lab(2, 0, validity="RAIN_IN_WINDOW"), prior(0, 2.0), NOW)["reason"] == "LABEL_NOT_VALID"
    late = {"issued_at": T0 + timedelta(days=0, hours=5), "r_base_mm_day": 2.0}   # terbit setelah jendela mulai
    assert bs.apply_label(st, CFG, lab(3, 0), late, NOW)["reason"] == "PRIOR_NOT_A_PRIORI"
    assert bs.apply_label(st, CFG, lab(4, 0), None, NOW)["reason"] == "NO_PRIOR"
    assert bs.apply_label(st, CFG, {**lab(5, 0), "label_id": None}, prior(0, 2.0), NOW)["reason"] == "LABEL_ID_MISSING"
    assert st.b == 0.0 and not st.consumed


def test_bias_is_clipped_and_decays_between_updates():
    st = bs.BiasState("P1", "M1B")
    bs.apply_label(st, CFG, lab(1, 0, r=100.0), prior(0, 0.0), NOW)
    assert st.b == pytest.approx(1.5)                                             # dipotong bmax
    b1 = st.b
    bs.apply_label(st, CFG, lab(2, 12, r=2.0), prior(12, 2.0), NOW)               # e=0 -> hanya meluruh: akhir jendela-1 (hari 2) -> akhir jendela-2 (hari 14) = 12 hari
    assert st.b == pytest.approx(0.7 * b1 * math.exp(-0.1 * 12))


def test_expired_bias_is_not_used():
    st = bs.BiasState("P1", "M1B")
    bs.apply_label(st, CFG, lab(1, 0, r=3.0), prior(0, 2.0), NOW)
    assert bs.bias_for_issue(st, CFG, st.last_update_at + timedelta(days=3))[1] == "ACTIVE"
    assert bs.bias_for_issue(st, CFG, st.last_update_at + timedelta(days=8)) == (0.0, "EXPIRED")
    assert bs.bias_for_issue(bs.BiasState("P1", "M2"), CFG, NOW) == (0.0, "NO_BIAS_YET")
    with pytest.raises(ValueError):
        bs.bias_for_issue(st, CFG, st.last_update_at - timedelta(days=1))


def test_same_rule_same_params_but_separate_state_per_model():
    labels = [lab(i, 2 * i, r=3.0) for i in range(4)]
    p_m1b = {l["label_id"]: prior(l["start"].day - 1, 1.5) for l in labels}       # prior M1B = SPconstant
    p_m2 = {l["label_id"]: prior(l["start"].day - 1, 2.7) for l in labels}         # prior M2 = residual ML
    a, b = bs.BiasState("P1", "M1B"), bs.BiasState("P1", "M2")
    bs.replay(a, CFG, labels, p_m1b, NOW)
    bs.replay(b, CFG, labels, p_m2, NOW)
    assert a.b != b.b and a.b > b.b                                                # galat apriori M1B lebih besar
    # aturan identik: dengan prior sama, kedua state identik
    c, d = bs.BiasState("P1", "M1B"), bs.BiasState("P1", "M2")
    bs.replay(c, CFG, labels, p_m1b, NOW)
    bs.replay(d, CFG, labels, p_m1b, NOW)
    assert c.b == pytest.approx(d.b)
    assert bs.BiasState("P1", "M1B").b == 0.0 and bs.BiasState("P2", "M1B").b == 0.0   # petak lain tak terpengaruh


def test_replay_is_chronological_regardless_of_input_order():
    labels = [lab(i, 2 * i, r=3.0 + i) for i in range(4)]
    pri = {l["label_id"]: prior(2 * l["label_id"] - 0.0, 2.0) for l in labels}
    a, b = bs.BiasState("P1", "M1B"), bs.BiasState("P1", "M1B")
    bs.replay(a, CFG, labels, pri, NOW)
    bs.replay(b, CFG, list(reversed(labels)), pri, NOW)
    assert a.b == pytest.approx(b.b)


def test_config_validation_and_no_research_default():
    for kw in (dict(alpha=0.0), dict(alpha=1.5), dict(lam=-1), dict(bmax=0), dict(max_age_days=0), dict(alpha=float("nan"))):
        base = dict(alpha=0.3, lam=0.1, bmax=1.5, max_age_days=7.0)
        base.update(kw)
        with pytest.raises(ValueError):
            bs.BiasConfig(**base)
    assert "ILUSTRASI" in bs.DEMO_CONFIG.frozen_from
    with pytest.raises(TypeError):
        bs.BiasConfig()                                                            # tidak ada nilai bawaan penelitian
    with pytest.raises(ValueError):
        bs.BiasState("P1", "M1")                                                   # hanya M1B/M2 yang punya bias adaptif


def test_snapshot_is_auditable():
    st = bs.BiasState("P1", "M2")
    bs.apply_label(st, CFG, lab(1, 0, r=3.0), prior(0, 2.0), NOW)
    s = bs.snapshot(st, CFG, st.last_update_at + timedelta(days=1))
    assert s["model"] == "M2" and s["n_updates"] == 1 and s["status"] == "ACTIVE" and s["config"]["frozen_from"] == "uji"
