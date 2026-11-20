"""H13: otorisasi keputusan = daftar yang diizinkan (mode, status hasil, kedaluwarsa, versi profil/pengamatan)."""
import pytest

import physics_engine as pe
from repository import DecisionError          # noqa: F401  (kelas sama dipakai demo_repository)
import demo_repository as drepo
import demo_service as ds


def test_only_listed_modes_and_statuses_pass():
    ok = dict(status_code="OK")
    for m in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED"):
        assert pe.decision_blockers(run_mode=m, **ok) == []
    for m in ("DEMO", "MANUAL_REQUIRED", "ML_SHADOW", "MISSING_PARAMETER", "INCOMPLETE_FORECAST", None, ""):
        assert pe.decision_blockers(run_mode=m, **ok) == ["not_operational"], m
    assert pe.decision_blockers(run_mode="BASELINE_PROVISIONAL", status_code="TARGET_NOT_REACHABLE") == []
    for s in ("MISSING_PARAMETER", "INCOMPLETE_FORECAST", "STALE_OBSERVATION", "INVALID_PARAMETER", None):
        assert pe.decision_blockers(run_mode="BASELINE_PROVISIONAL", status_code=s) == ["not_decidable_status"], s


def test_blockers_are_ordered_and_cumulative():
    got = pe.decision_blockers(run_mode="DEMO", status_code="STALE_OBSERVATION", expired=True,
                               profile_changed=True, inputs_changed=True)
    assert got == ["expired", "not_operational", "not_decidable_status", "profile_changed", "inputs_changed"]


def test_ml_shadow_never_authorizes_ml_output():
    assert "not_operational" in pe.decision_blockers(run_mode="ML_SHADOW", status_code="OK")


def test_operational_repository_uses_central_list():
    src = open("repository.py", encoding="utf-8").read()
    assert "decision_blockers(" in src and "profile_changed" in src
    assert '"BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED")' not in src.split("def record_decision")[1].split("def list_decisions")[0]


def test_profile_change_after_publish_blocks_decision(demo):
    rid, out = ds.publish("DEMO-P01", "demo_operator")["rec_id"], None
    out = drepo.get_run(rid)["output"]
    demo.as_("admin", "demo_admin")
    drepo.save_profile_version("DEMO-P01", [{"name": "mu_dry", "value": 0.3, "status": "EXAMPLE"}], [], "demo_admin")
    demo.as_("operator", "demo_operator")
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "DELAY", 0.0, 0.0, "", "pc-1")
    assert e.value.code == "profile_changed"
