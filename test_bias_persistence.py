"""H14: state bias adaptif per petak DAN model disimpan di DB: tahan restart, label dipakai paling banyak sekali, parameter dibeku-
kan. Bagian murni selalu jalan; bagian SQL butuh DB uji (fixture pgdb)."""
import math
from datetime import datetime, timedelta, timezone

import pytest

import bias_state
import physics_engine as pe

U = timezone.utc
D0 = datetime(2026, 12, 1, 0, 0, tzinfo=U)
CFG = bias_state.BiasConfig(alpha=0.3, lam=0.10, bmax=1.5, max_age_days=7.0, frozen_from="uji: dibekukan dari kalibrasi X")


def label(i, day0, residual, mature_days=2.0):
    s, e = D0 + timedelta(days=day0), D0 + timedelta(days=day0 + 2)
    return {"label_id": i, "start": s, "end": e, "available_at": e + timedelta(days=mature_days - 2 + 0.0) if mature_days >= 2 else e,
            "residual_mm_day": residual, "validity": "VALID"}


def prior(label_start, r_base=2.0, pid=None):
    return {"issued_at": label_start - timedelta(hours=6), "r_base_mm_day": r_base, "prediction_id": pid,
            "prior_ref": {"kind": "SPconstant", "profile_id": 7}}


def seed_labels(repo, ids):
    for i in ids:
        repo.db_query("INSERT INTO residual_labels (label_id, plot_id, support_start, support_end, available_at, validity) "
                      "VALUES (%s, 'P1', %s, %s, %s, 'VALID')", (i, D0, D0 + timedelta(days=2), D0 + timedelta(days=2)))


def test_demo_config_and_missing_freeze_are_refused_for_research_path(monkeypatch):
    import repository as repo
    with pytest.raises(repo.BiasConfigError):
        repo.apply_bias_labels("P1", "M1B", bias_state.DEMO_CONFIG, [])
    with pytest.raises(repo.BiasConfigError):
        repo.apply_bias_labels("P1", "M1B", bias_state.BiasConfig(0.3, 0.1, 1.5, 7.0, frozen_from=""), [])


# ----------------------------------------------------------------------------------------------- SQL
def test_state_survives_restart_and_label_is_used_once(pgdb):
    repo = pgdb
    seed_labels(repo, [1, 2])
    L1, L2 = label(1, 0, 3.0), label(2, 3, 3.5)
    now = D0 + timedelta(days=6)
    r = repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L1, "prior": prior(L1["start"])}], now)
    assert r[0]["applied"]
    # "restart": semua objek memori hilang; state dibaca ulang dari DB
    st, cfg, ver = repo.get_bias_state("P1", "M1B")
    b_expected, _ = pe.update_bias(0.0, 0.0, 3.0, 2.0, CFG.alpha, CFG.lam, CFG.bmax)
    assert st.b == pytest.approx(b_expected) and st.consumed == {1} and ver == 1 and st.last_window_end == L1["end"]
    # label yang sama dikirim lagi setelah restart: tidak dipakai dua kali
    r2 = repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L1, "prior": prior(L1["start"])}], now + timedelta(hours=1))
    assert r2[0]["applied"] is False and r2[0]["reason"] == "ALREADY_USED"
    st2, _, ver2 = repo.get_bias_state("P1", "M1B")
    assert st2.b == st.b and ver2 == 1
    # label kedua memakai state yang tersimpan (bukan mulai dari nol)
    r3 = repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L2, "prior": prior(L2["start"])}], now + timedelta(days=2))
    elapsed = (L2["end"] - L1["end"]).total_seconds() / 86400
    b2, _ = pe.update_bias(b_expected, elapsed, 3.5, 2.0, CFG.alpha, CFG.lam, CFG.bmax)
    assert r3[0]["applied"] and repo.get_bias_state("P1", "M1B")[0].b == pytest.approx(b2)
    n = repo.db_query("SELECT COUNT(*) AS n FROM bias_update_log WHERE applied")[0]["n"]
    assert int(n) == 2 and repo.db_query("SELECT n_updates FROM bias_state")[0]["n_updates"] == 2


def test_state_is_separate_per_plot_and_model(pgdb):
    repo = pgdb
    seed_labels(repo, [1])
    L = label(1, 0, 3.0)
    now = D0 + timedelta(days=6)
    repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L, "prior": prior(L["start"], 2.0)}], now)
    repo.apply_bias_labels("P1", "M2", CFG, [{"label": L, "prior": prior(L["start"], 2.8)}], now)      # prior ML berbeda
    repo.apply_bias_labels("P2", "M1B", CFG, [{"label": L, "prior": prior(L["start"], 2.0)}], now)
    b1 = repo.get_bias_state("P1", "M1B")[0].b
    b2 = repo.get_bias_state("P1", "M2")[0].b
    assert b1 != b2 and b1 == repo.get_bias_state("P2", "M1B")[0].b
    assert repo.get_bias_state("P3", "M1B") is None


def test_skipped_labels_are_logged_with_reason_and_do_not_change_state(pgdb):
    repo = pgdb
    seed_labels(repo, [1, 2, 3, 4])
    now = D0 + timedelta(days=6)
    L1 = label(1, 0, 3.0)
    repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L1, "prior": prior(L1["start"])}], now)
    b = repo.get_bias_state("P1", "M1B")[0].b
    overlap = label(2, 1, 4.0)                                              # mulai sebelum akhir jendela terpakai
    late_prior = {"issued_at": D0 + timedelta(days=4), "r_base_mm_day": 2.0}
    L3 = label(3, 3, 4.0)
    immature = dict(label(4, 4, 4.0), available_at=now + timedelta(days=5))
    res = repo.apply_bias_labels("P1", "M1B", CFG, [
        {"label": overlap, "prior": prior(overlap["start"])},
        {"label": L3, "prior": late_prior},
        {"label": immature, "prior": prior(immature["start"])}], now)
    assert [r["reason"] for r in res] == ["OVERLAPS_USED_WINDOW", "PRIOR_NOT_A_PRIORI", "LABEL_NOT_MATURE"]
    assert repo.get_bias_state("P1", "M1B")[0].b == b
    rows = repo.db_query("SELECT label_id, reason FROM bias_update_log WHERE NOT applied ORDER BY label_id")
    assert [(int(r["label_id"]), r["reason"]) for r in rows] == [(2, "OVERLAPS_USED_WINDOW"), (3, "PRIOR_NOT_A_PRIORI"),
                                                                 (4, "LABEL_NOT_MATURE")]
    # rerun yang sama tidak menggandakan catatan lewati
    repo.apply_bias_labels("P1", "M1B", CFG, [{"label": immature, "prior": prior(immature["start"])}], now)
    assert int(repo.db_query("SELECT COUNT(*) AS n FROM bias_update_log WHERE NOT applied")[0]["n"]) == 3
    # label yang tadinya belum matang dapat dipakai nanti (catatan lewati tidak memblokirnya)
    later = now + timedelta(days=6)
    r = repo.apply_bias_labels("P1", "M1B", CFG, [{"label": immature, "prior": prior(immature["start"])}], later)
    assert r[0]["applied"] is True


def test_config_is_frozen_after_first_update(pgdb):
    repo = pgdb
    seed_labels(repo, [1])
    L = label(1, 0, 3.0)
    repo.apply_bias_labels("P1", "M1B", CFG, [], D0)                       # membuat state tanpa pembaruan
    other = bias_state.BiasConfig(0.5, 0.1, 1.5, 7.0, frozen_from="uji: kalibrasi Y")
    repo.apply_bias_labels("P1", "M1B", other, [], D0)                      # belum ada pembaruan: boleh ditetapkan ulang
    repo.apply_bias_labels("P1", "M1B", other, [{"label": L, "prior": prior(L["start"])}], D0 + timedelta(days=6))
    with pytest.raises(repo.BiasConfigError):
        repo.apply_bias_labels("P1", "M1B", CFG, [], D0 + timedelta(days=7))
    assert repo.get_bias_state("P1", "M1B")[1].alpha == 0.5


def test_bias_for_issue_active_expired_and_none(pgdb):
    repo = pgdb
    seed_labels(repo, [1])
    L = label(1, 0, 3.0)
    assert repo.bias_for_issue_db("P1", "M1B", D0) == (0.0, "NO_BIAS_YET", None)
    repo.apply_bias_labels("P1", "M1B", CFG, [{"label": L, "prior": prior(L["start"])}], D0 + timedelta(days=6))
    b, status, snap = repo.bias_for_issue_db("P1", "M1B", L["end"] + timedelta(days=2))
    assert status == "ACTIVE" and b != 0 and snap["n_updates"] == 1 and snap["config"]["frozen_from"].startswith("uji")
    b2, status2, _ = repo.bias_for_issue_db("P1", "M1B", L["end"] + timedelta(days=9))
    assert (b2, status2) == (0.0, "EXPIRED")


def test_log_keeps_prior_identity_and_is_append_only(pgdb):
    repo = pgdb
    seed_labels(repo, [1])
    repo.db_query("INSERT INTO prediction_log (prediction_id, model_version, plot_id, residual_mm_day, mode) "
                  "VALUES (55, 'm-1', 'P1', 2.0, 'ML_SHADOW')")
    L = label(1, 0, 3.0)
    repo.apply_bias_labels("P1", "M2", CFG, [{"label": L, "prior": prior(L["start"], 2.0, pid=55)}], D0 + timedelta(days=6))
    row = repo.db_query("SELECT label_id, prediction_id, prior_issued_at, r_base_mm_day, b_after, config FROM bias_update_log")[0]
    assert int(row["label_id"]) == 1 and int(row["prediction_id"]) == 55 and row["r_base_mm_day"] == 2.0
    assert row["prior_issued_at"] == L["start"] - timedelta(hours=6) and row["config"]["alpha"] == 0.3
    with pytest.raises(Exception):
        repo.db_query("UPDATE bias_update_log SET b_after = 0")
    with pytest.raises(Exception):
        repo.db_query("DELETE FROM bias_update_log")
