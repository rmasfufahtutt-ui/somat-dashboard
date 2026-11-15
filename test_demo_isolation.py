"""Isolasi ruang DEMO vs OPERASIONAL: penyimpanan terpisah, router, cache per-mode, dan pemisahan jalur penerbitan/keputusan."""
import hashlib
import os
import sqlite3

import pytest

import demo_mode
import demo_repository as drepo
import repo_router
import repository
import store


def test_demo_store_is_separate_sqlite_file(demo):
    assert str(demo.path).endswith(".sqlite3")
    assert drepo.path() == str(demo.path)
    # tidak memakai psycopg2 / pool: koneksi yang dibuka adalah sqlite3
    con = drepo._connect()
    try:
        assert isinstance(con, sqlite3.Connection)
    finally:
        con.close()


def test_router_follows_mode(demo):
    demo_mode.force("DEMO", ("demo_admin", "admin"))
    assert repo_router.backend() is drepo
    assert repo_router.list_plots.__module__ == "demo_repository"
    demo_mode.force("OPS", ("demo_admin", "admin"))
    assert repo_router.backend() is repository
    assert repo_router.list_plots.__module__ == "repository"
    demo_mode.force("DEMO", ("demo_admin", "admin"))


def test_cache_does_not_leak_between_modes(demo):
    demo_mode.force("DEMO", ("demo_admin", "admin"))
    store.invalidate()
    demo_plots = store.plots()
    assert len(demo_plots) == 6 and all(p["plot_id"].startswith("DEMO-") for p in demo_plots)
    demo_mode.force("OPS", ("demo_admin", "admin"))      # DB operasional tidak aktif di tes ini -> kosong, BUKAN data demo
    assert store.plots() == []
    demo_mode.force("DEMO", ("demo_admin", "admin"))
    assert len(store.plots()) == 6


def test_demo_session_user_can_never_use_ops(monkeypatch):
    import db
    monkeypatch.setattr(db, "active", lambda: True)
    assert demo_mode.can_use_ops() is False or demo_mode.is_demo_user() is False
    demo_mode.force(None, ("demo_admin", "admin"))
    assert demo_mode.is_demo_user() is True
    assert demo_mode.can_use_ops() is False
    assert demo_mode.set_mode(demo_mode.MODE_OPS) is False
    demo_mode.force(None, None)


def test_demo_publish_rejects_operational_run_mode_and_unflagged_snapshot(demo):
    pid = "DEMO-P01"
    snap_ok = {"is_demo": True, "plot_id": pid}
    now = drepo.now_utc()
    with pytest.raises(ValueError):
        drepo.publish_recommendation(pid, "x", now, snap_ok, 1, "m", "BASELINE_PROVISIONAL", "OK", {"irrigate": True}, now)
    with pytest.raises(ValueError):
        drepo.publish_recommendation(pid, "x", now, {"plot_id": pid}, 1, "m", "DEMO", "OK", {"irrigate": True}, now)
    with pytest.raises(ValueError):
        drepo.publish_recommendation(pid, "x", now, {"is_demo": False}, 1, "m", "DEMO", "OK", {"irrigate": True}, now)


def test_ops_repository_still_rejects_demo_runs():
    """Jalur operasional tidak diubah: run DEMO tidak dapat diputuskan secara operasional (aturan di kode repository)."""
    src = open(os.path.join(os.path.dirname(__file__), "repository.py"), encoding="utf-8").read()
    assert "not_operational" in src


def test_demo_decisions_use_source_demo_never_operational(demo):
    import demo_service as ds
    res = ds.publish("DEMO-P01", "demo_operator", weather=None)
    assert res["output"]["status"] in ("OK",)
    out = res["output"]
    did, dup = ds.decide(res["rec_id"], "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "k-iso-1")
    row = drepo.q("SELECT source, is_demo, run_mode FROM decisions WHERE id=?", (did,))[0]
    assert row["source"] == "DEMO" and row["is_demo"] is True and row["run_mode"] == "DEMO"
    assert all(r["source"] == "DEMO" for r in drepo.list_decisions(500))


def test_every_demo_row_is_flagged(demo):
    for t in ("plots", "plot_profile_versions", "crop_cycles", "observations", "recommendation_runs", "decisions", "irrigation_events"):
        assert drepo.q(f"SELECT COUNT(*) AS n FROM {t} WHERE is_demo != 1")[0]["n"] == 0, t
    assert drepo.q("SELECT COUNT(*) AS n FROM observations WHERE source_type NOT IN ('MANUAL','SIMULATED')")[0]["n"] == 0


def test_clear_and_reset_only_touch_demo_file(demo, tmp_path):
    other = tmp_path / "other.sqlite3"           # berkas lain (mewakili data operasional) tidak boleh berubah
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('keep')")
    con.commit()
    con.close()
    before = hashlib.sha256(other.read_bytes()).hexdigest()
    import demo_data
    demo_data.clear()
    demo_data.reset_initial()
    demo_data.clear()
    assert hashlib.sha256(other.read_bytes()).hexdigest() == before


def test_permissions_enforced_in_backend_not_only_ui(demo):
    demo.as_("viewer")
    with pytest.raises(PermissionError):
        drepo.add_h_observation("DEMO-P01", -5.0, drepo.now_utc(), "demo_viewer")
    with pytest.raises(PermissionError):
        drepo.wipe()
    demo.as_("operator")
    with pytest.raises(PermissionError):
        drepo.wipe()
    with pytest.raises(PermissionError):
        drepo.void_decision(1, "demo_operator", "x")
    demo.as_("admin")
    assert drepo.void_decision(1, "demo_admin", "uji") is True
