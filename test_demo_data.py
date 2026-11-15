"""Data demo: 6 petak, >=30 hari riwayat, skenario dihasilkan mesin, deterministik, idempoten, reset/clear aman."""
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import demo_data
import demo_mode
import demo_repository as drepo
import demo_service as ds

EXPECT = {"DEMO-P01": ("OK", True), "DEMO-P02": ("OK", False), "DEMO-P03": ("OK", False), "DEMO-P04": ("STALE_OBSERVATION", None),
          "DEMO-P05": ("MISSING_PARAMETER", None), "DEMO-P06": ("TARGET_NOT_REACHABLE", True)}


def _counts():
    return {t: drepo.q(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in
            ("plots", "plot_profile_versions", "plot_parameters", "phase_rules", "crop_cycles", "observations",
             "recommendation_runs", "decisions", "irrigation_events")}


def test_six_plots_with_30_days_history(demo):
    plots = drepo.list_plots()
    assert [p["plot_id"] for p in plots] == [f"DEMO-P0{i}" for i in range(1, 7)]
    now = drepo.now_utc()
    for p in plots:
        hs = drepo.list_h_observations(p["plot_id"], 500)
        span = (max(h["observed_at"] for h in hs) - min(h["observed_at"] for h in hs)).days
        assert span >= 30 and len(hs) >= 31, (p["plot_id"], span)
        assert all(h["origin"] == "SEED" and h["is_demo"] for h in hs)
        for var in ("soil_moisture", "canal_level", "rainfall"):
            assert drepo.series(p["plot_id"], var, 40), var
        assert drepo.get_active_cycle(p["plot_id"]) and drepo.get_active_profile(p["plot_id"], now)


@pytest.mark.parametrize("pid", list(EXPECT))
def test_scenarios_are_engine_driven(demo, pid):
    plot = drepo.get_plot(pid)
    out, snap = ds.compute_for_plot(pid, drepo.now_utc(), demo_data.default_weather(pid))
    status, irrigate = EXPECT[pid]
    assert out["status"] == status, (pid, out["status"], out.get("reasons"))
    assert out["irrigate"] is irrigate
    assert snap["is_demo"] is True and plot["scenario"]
    if status in ("OK", "TARGET_NOT_REACHABLE"):
        assert out["run_mode"] == "DEMO"
    else:
        assert out["run_mode"] == "MANUAL_REQUIRED"


def test_rain_scenario_changes_p03_outcome(demo):
    now = drepo.now_utc()
    rain, _ = ds.compute_for_plot("DEMO-P03", now, demo_data.default_weather("DEMO-P03"))
    dry, _ = ds.compute_for_plot("DEMO-P03", now, {**demo_data.default_weather("DEMO-P03"), "rain": "NONE"})
    assert rain["irrigate"] is False and dry["irrigate"] is True
    assert rain["h_arrival_cm"] > dry["h_arrival_cm"]
    assert rain["rain_scenario"].startswith("SYNTHETIC_RAIN") and dry["rain_scenario"] == "NO_RAIN_SCENARIO"


def test_seed_is_deterministic(tmp_path):
    demo_mode.force("DEMO", ("demo_admin", "admin"))
    anchor = datetime(2026, 5, 20, 3, tzinfo=timezone.utc)
    dumps = []
    for i in range(2):
        drepo.configure(tmp_path / f"d{i}.sqlite3")
        demo_data.load(anchor)
        dumps.append([(r["plot_id"], r["observed_at"], r["value"]) for r in
                      drepo.q("SELECT plot_id, observed_at, value FROM observations ORDER BY plot_id, variable, observed_at, obs_id")])
    demo_mode.force(None, None)
    assert dumps[0] == dumps[1] and len(dumps[0]) > 1000


def test_load_is_idempotent_no_duplicate_seeds(demo):
    before = _counts()
    r = demo_data.load()
    assert r["status"] == "ALREADY_LOADED"
    assert _counts() == before
    assert drepo.q("SELECT COUNT(*) AS n FROM plots")[0]["n"] == 6


def test_reset_restores_initial_scenario_and_is_repeatable(demo):
    base = _counts()
    # perubahan pengguna
    drepo.add_h_observation("DEMO-P02", -9.0, drepo.now_utc() - timedelta(minutes=5), "demo_admin", "uji")
    res = ds.publish("DEMO-P01", "demo_admin")
    ds.decide(res["rec_id"], "demo_admin", "DELAY", 0.0, 0.0, "", "k-reset-1")
    assert drepo.is_dirty() and sum(drepo.count_user_rows().values()) >= 3
    demo_data.reset_initial()
    after1 = _counts()
    assert after1 == base and not drepo.is_dirty()
    demo_data.reset_initial()
    assert _counts() == base                              # idempoten: dua kali reset = sama
    assert drepo.q("SELECT COUNT(*) AS n FROM decisions WHERE idempotency_key='k-reset-1'")[0]["n"] == 0


def test_clear_is_idempotent_and_leaves_loadable(demo):
    demo_data.clear()
    assert not drepo.is_loaded() and all(v == 0 for v in _counts().values())
    demo_data.clear()
    assert all(v == 0 for v in _counts().values())
    assert demo_data.load()["status"] == "LOADED"
    assert _counts()["plots"] == 6


def test_history_chain_is_linked_and_labelled_simulation(demo):
    ev = drepo.list_irrigation_events(limit=200)
    assert ev and all(e["is_simulation"] and e["origin"] == "SEED" for e in ev)
    for e in ev:
        d = drepo.q("SELECT source, rec_id FROM decisions WHERE id=?", (e["decision_id"],))[0]
        assert d["source"] == "DEMO" and d["rec_id"] == e["rec_id"]
    rows = drepo.evaluation_rows()
    assert rows and all(r["predicted_h_arrival"] is not None and r["observed_h_at_arrival"] is not None for r in rows)


def test_shift_times_keeps_relationships(demo):
    plot = "DEMO-P01"
    before = drepo.latest_h(plot, drepo.now_utc() + timedelta(days=400))
    cyc = drepo.get_active_cycle(plot)
    demo_data.refresh_time(datetime.now(timezone.utc) + timedelta(days=3))
    after = drepo.latest_h(plot, drepo.now_utc() + timedelta(days=400))
    assert (after["observed_at"] - before["observed_at"]) == timedelta(days=3)
    assert (drepo.get_active_cycle(plot)["planting_date"] - cyc["planting_date"]).days == 3
