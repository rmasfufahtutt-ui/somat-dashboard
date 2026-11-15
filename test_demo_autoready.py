"""Ruang DEMO harus terisi sendiri: tanpa admin menekan tombol apa pun."""
from datetime import datetime, timedelta, timezone

import pytest

import demo_data
import demo_mode
import demo_repository as drepo


@pytest.fixture()
def fresh(tmp_path):
    drepo.configure(tmp_path / "auto.sqlite3")
    demo_mode.force("DEMO", ("demo_viewer", "viewer"))
    yield
    demo_mode.force(None, None)
    drepo.configure(None)


def test_empty_space_fills_itself_even_for_viewer(fresh):
    r = demo_data.ensure_ready(train_model=False)
    assert "loaded" in r["actions"]
    assert len(drepo.list_plots()) == 6
    pend = {p["plot_id"]: p for p in drepo.list_pending_runs()}
    assert set(pend) == {"DEMO-P01", "DEMO-P03"}
    assert pend["DEMO-P01"]["output"]["irrigate"] is True
    assert pend["DEMO-P01"]["output"]["run_mode"] == "DEMO"


def test_second_call_is_noop(fresh):
    demo_data.ensure_ready(train_model=False)
    assert demo_data.ensure_ready(train_model=False)["actions"] == []


def test_stale_anchor_shifts_time_and_keeps_pending(fresh):
    demo_data.ensure_ready(train_model=False)
    later = datetime.now(timezone.utc) + timedelta(hours=8)
    r = demo_data.ensure_ready(later, train_model=False)
    assert "time_shifted" in r["actions"]
    assert {p["plot_id"] for p in drepo.list_pending_runs()} >= {"DEMO-P01"}


def test_user_actions_still_need_admin(fresh):
    demo_data.ensure_ready(train_model=False)
    with pytest.raises(PermissionError):
        demo_data.clear()
