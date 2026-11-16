"""Audit K08: prakiraan dikunci pada waktu keputusan (as-of) + provenansi per slot."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import recommendation_service as rs

UTC = timezone.utc
T = datetime(2026, 3, 10, 0, tzinfo=UTC)


def slot(h, temp, run, issued_h, fetched_h):
    return {"valid_at": T + timedelta(hours=h), "temp": temp, "run_id": run, "issued_at": T + timedelta(hours=issued_h),
            "fetched_at": T + timedelta(hours=fetched_h)}


def test_provenance_marks_archive_vs_latest_and_newest_wins():
    latest = [{"utc_datetime": "2026-03-10 06:00:00", "temperature": 30.0}]
    pts, prov = rs.composite_with_provenance(latest, [slot(6, 25.0, 1, -3, -2), slot(3, 24.0, 1, -3, -2)],
                                             {"payload_hash": "H2", "issued_at": T, "fetched_at": T})
    by = {p["valid_at"][:13]: p for p in prov}
    assert by["2026-03-10T06"]["origin"] == "LATEST" and by["2026-03-10T03"]["origin"] == "ARCHIVE"
    assert dict((u.astimezone(UTC).hour, v) for u, v in pts)[6] == 30.0


def test_composite_points_backward_compatible():
    pts = rs.composite_points([], [slot(3, 24.0, 1, -3, -2), slot(6, 26.0, 1, -3, -2)])
    assert [v for _, v in pts] == [24.0, 26.0]


def test_summarize_groups_by_run():
    _, prov = rs.composite_with_provenance([], [slot(3, 24.0, 1, -3, -2), slot(6, 26.0, 1, -3, -2), slot(9, 27.0, 2, 0, 1)])
    runs = rs.summarize_provenance(prov)
    assert sorted((r["run_id"], r["n_slots"]) for r in runs) == [(1, 2), (2, 1)]


class FakeRepo:
    def __init__(self):
        self.asof = "unset"

    def get_plot(self, pid): return {"plot_id": pid}
    def get_active_profile(self, pid, t): return None
    def get_active_cycle(self, pid): return None
    def latest_h(self, pid, t): return None

    def load_forecast_slots(self, loc, since_hours=72, as_of=None):
        self.asof = as_of
        return [slot(3, 24.0, 1, -3, -2)]


def snap_with(fetched):
    return SimpleNamespace(forecast={"adm4": "X", "rows": [], "payload_hash": "H", "issued_at": T, "fetched_at": fetched})


def test_gather_inputs_passes_decision_time_to_archive_query():
    repo = FakeRepo()
    d = T + timedelta(hours=5)
    out = rs.gather_inputs(repo, "P1", snap_with(T), d)
    assert repo.asof == d and out["forecast_meta"]["as_of"] == d


def test_latest_forecast_fetched_after_decision_is_excluded_for_replay():
    repo = FakeRepo()
    out = rs.gather_inputs(repo, "P1", snap_with(T + timedelta(days=5)), T + timedelta(hours=5))
    assert out["forecast_meta"]["latest_excluded_not_yet_available"] is True
    out2 = rs.gather_inputs(repo, "P1", snap_with(T), T + timedelta(hours=5))
    assert out2["forecast_meta"]["latest_excluded_not_yet_available"] is False


def test_snapshot_records_which_runs_formed_the_slots():
    out = rs.gather_inputs(FakeRepo(), "P1", snap_with(T), T + timedelta(hours=5))
    assert out["forecast_meta"]["slot_runs"] and out["forecast_meta"]["slot_runs"][0]["run_id"] == 1
