"""Alur demo lengkap: pengamatan (koreksi/VOID) -> rekomendasi -> keputusan APPROVE/MODIFY/DELAY -> pelaksanaan -> evaluasi."""
from datetime import timedelta

import pytest

import demo_mode
import demo_repository as drepo
import demo_service as ds
from repository import DecisionError


def _pub(pid="DEMO-P01", actor="demo_operator", **kw):
    res = ds.publish(pid, actor, **kw)
    return res["rec_id"], res["output"]


def test_publish_is_immutable_and_supersedes_previous(demo):
    r1, _ = _pub()
    r2, _ = _pub()
    assert drepo.get_run(r1)["status"] == "SUPERSEDED" and drepo.get_run(r2)["status"] == "PUBLISHED"
    assert drepo.get_run(r2)["run_mode"] == "DEMO" and drepo.get_run(r2)["inputs_hash"]
    pend = drepo.list_pending_runs("DEMO-P01")
    assert [p["rec_id"] for p in pend] == [r2]


def test_approve_requires_same_amount(demo):
    rid, out = _pub()
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"] + 5, out["duration_h"], "", "k1")
    assert e.value.code == "approve_invalid"
    did, dup = drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "k2")
    assert dup is False and drepo.get_run(rid)["status"] == "DECIDED"


def test_modify_must_change_amount(demo):
    rid, out = _pub()
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "MODIFY", out["total_mm"], out["duration_h"], "alasan", "m1")
    assert e.value.code == "amount_unchanged"
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "MODIFY", -3, 1, "alasan", "m2")
    assert e.value.code == "bad_amount"
    did, _ = drepo.record_decision(rid, "demo_operator", "MODIFY", out["total_mm"] * 0.8, out["duration_h"] * 0.8, "kurangi", "m3")
    d = drepo.list_decisions(5)[0]
    assert d["id"] == did and d["decision"] == "MODIFY" and d["operator_mm"] != d["recommended_mm"] and d["source"] == "DEMO"


def test_delay_recorded_and_marked_for_reevaluation(demo):
    rid, out = _pub()
    did, _ = drepo.record_decision(rid, "demo_operator", "DELAY", 0.0, 0.0, "tunda", "d1")
    row = drepo.q("SELECT context, decision FROM decisions WHERE id=?", (did,))[0]
    assert row["decision"] == "DELAY" and row["context"]["needs_reevaluation"] is True
    assert drepo.decisions_awaiting_execution("DEMO-P01") == [] or all(r["id"] != did for r in drepo.decisions_awaiting_execution("DEMO-P01"))


def test_decision_is_atomic_and_idempotent(demo):
    rid, out = _pub()
    a = drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "same-key")
    b = drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "same-key")
    assert a[0] == b[0] and b[1] is True
    with pytest.raises(DecisionError) as e:                     # kunci lain pada rekomendasi yang sudah diputuskan
        drepo.record_decision(rid, "demo_operator", "DELAY", 0, 0, "", "other-key")
    assert e.value.code == "already_handled"
    assert drepo.q("SELECT COUNT(*) AS n FROM decisions WHERE rec_id=?", (rid,))[0]["n"] == 1


def test_new_h_observation_invalidates_pending_decision(demo):
    rid, out = _pub()
    drepo.add_h_observation("DEMO-P01", -17.0, drepo.now_utc() - timedelta(minutes=1), "demo_operator", "baru")
    assert drepo.list_pending_runs("DEMO-P01")[0]["needs_recalc"] is True
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "x1")
    assert e.value.code == "inputs_changed"


def test_expired_recommendation_is_rejected(demo):
    rid, out = _pub(expiry_hours=0.0001)
    import time
    time.sleep(0.5)
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "e1")
    assert e.value.code == "expired"


def test_manual_required_run_cannot_be_approved_or_modified(demo):
    rid, out = _pub("DEMO-P04")                                  # pengamatan usang
    assert out["status"] == "STALE_OBSERVATION" and out["engine_run_mode"] == "MANUAL_REQUIRED"
    for dec in ("APPROVE", "MODIFY"):
        with pytest.raises(DecisionError) as e:
            ds.decide(rid, "demo_operator", dec, 10.0, 1.0, "x", f"k-{dec}")
        assert e.value.code == "approve_invalid"


def test_no_irrigation_run_only_allows_delay(demo):
    rid, out = _pub("DEMO-P02")                                  # aman: tidak perlu irigasi
    assert out["irrigate"] is False
    with pytest.raises(DecisionError):
        drepo.record_decision(rid, "demo_operator", "APPROVE", 5.0, 1.0, "", "s1")
    drepo.record_decision(rid, "demo_operator", "DELAY", 0.0, 0.0, "", "s2")


def test_correct_and_void_decision_rights(demo):
    rid, out = _pub()
    did, _ = drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "c1")
    demo.as_("operator", "demo_operator")
    new_id = drepo.supersede_decision(did, "demo_operator", "MODIFY", out["total_mm"] * 0.9, out["duration_h"], "ubah", "koreksi")
    assert drepo.q("SELECT record_status FROM decisions WHERE id=?", (did,))[0]["record_status"] == "SUPERSEDED"
    with pytest.raises(PermissionError):                          # operator tidak boleh VOID
        drepo.void_decision(new_id, "demo_operator", "x")
    demo.as_("operator", "operator_lain")                          # operator lain tidak boleh mengoreksi catatan orang lain
    with pytest.raises(DecisionError) as e:
        drepo.supersede_decision(new_id, "operator_lain", "DELAY", 0, 0, "", "x")
    assert e.value.code == "forbidden"
    demo.as_("admin")
    assert drepo.void_decision(new_id, "demo_admin", "salah input") is True
    row = drepo.q("SELECT record_status, void_reason FROM decisions WHERE id=?", (new_id,))[0]
    assert row["record_status"] == "VOID" and row["void_reason"] == "salah input"        # tidak dihapus
    assert drepo.void_decision(new_id, "demo_admin", "lagi") is False                      # idempoten


def test_observation_correct_and_void(demo):
    t = drepo.now_utc() - timedelta(hours=1)
    o1 = drepo.add_h_observation("DEMO-P02", -9.0, t, "demo_operator")
    o2 = drepo.add_h_observation("DEMO-P02", -8.0, t, "demo_operator", "koreksi", supersedes_id=o1)
    st = {r["obs_id"]: r["record_status"] for r in drepo.list_h_observations("DEMO-P02", 5)}
    assert st[o1] == "SUPERSEDED" and st[o2] == "ACTIVE"
    assert drepo.latest_h("DEMO-P02")["value"] == -8.0
    assert drepo.void_observation(o2, "demo_operator", "salah baca") is True
    assert drepo.latest_h("DEMO-P02")["value"] != -8.0
    assert drepo.q("SELECT COUNT(*) AS n FROM observations WHERE obs_id=?", (o2,))[0]["n"] == 1  # masih tersimpan


def test_execution_simulation_and_evaluation_chain(demo):
    rid, out = _pub()
    did, _ = ds.decide(rid, "demo_operator", "MODIFY", out["total_mm"] * 0.9, out["duration_h"] * 0.9, "kurangi 10%", "ex1")
    assert any(r["id"] == did for r in drepo.decisions_awaiting_execution("DEMO-P01"))
    now = drepo.now_utc()
    h_after = ds.simulated_h_after("DEMO-P01", out["h_arrival_cm"], out["total_mm"] * 0.9)
    eid = ds.record_execution(did, "demo_operator", arrived_at=now, started_at=now, ended_at=now + timedelta(hours=3),
                              actual_volume_m3=out["volume_m3"] * 0.88, h_after_cm=h_after, h_after_at=now + timedelta(hours=4))
    ev = drepo.list_irrigation_events("DEMO-P01", 1)[0]
    assert ev["event_id"] == eid and ev["is_simulation"] is True and "[SIMULASI]" in ev["note"] and ev["is_demo"] is True
    assert not any(r["id"] == did for r in drepo.decisions_awaiting_execution("DEMO-P01"))
    chain = [r for r in drepo.evaluation_rows("DEMO-P01") if r["event_id"] == eid][0]
    assert chain["decision"] == "MODIFY" and chain["recommended_mm"] == pytest.approx(out["total_mm"])
    assert chain["decision_mm"] == pytest.approx(out["total_mm"] * 0.9) and chain["h_after_cm"] == pytest.approx(h_after)
    with pytest.raises(ValueError):
        ds.record_execution(did, "demo_operator", arrived_at=now, started_at=now - timedelta(hours=1), ended_at=now,
                            actual_volume_m3=1.0, h_after_cm=None, h_after_at=None)
    assert drepo.void_irrigation_event(eid, "demo_operator", "salah") is True


def test_viewer_cannot_do_anything_mutating(demo):
    rid, out = _pub()
    demo.as_("viewer")
    for fn in (lambda: ds.publish("DEMO-P01", "demo_viewer"),
               lambda: drepo.add_h_observation("DEMO-P01", -3.0, drepo.now_utc(), "demo_viewer")):
        with pytest.raises(PermissionError):
            fn()
    with pytest.raises(DecisionError) as e:
        drepo.record_decision(rid, "demo_viewer", "DELAY", 0, 0, "", "v1")
    assert e.value.code == "forbidden"
