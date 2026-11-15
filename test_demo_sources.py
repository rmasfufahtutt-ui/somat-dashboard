"""Integritas sumber data: BMKG asli dan cuaca sintetis tidak pernah dicampur atau dikarang; M2 tanpa SPconstant ganda."""
from datetime import date, datetime, timedelta, timezone

import pytest

import demo_data
import demo_repository as drepo
import demo_service as ds
import demo_weather as dw
import recommendation_service as rs


def test_bmkg_driver_without_forecast_is_incomplete_not_invented(demo):
    out, snap = ds.compute_for_plot("DEMO-P01", drepo.now_utc(), {**demo_data.default_weather("DEMO-P01"), "driver": dw.DRIVER_BMKG}, forecast=None)
    assert out["status"] == "INCOMPLETE_FORECAST" and out["irrigate"] is None
    assert snap["weather"]["available"] is False and snap["weather"]["driver"] == "BMKG" and snap["weather"]["n_points"] == 0
    assert out["total_mm"] is None                                # tidak ada angka karangan


def test_bmkg_driver_uses_only_forecast_rows_and_labels_source(demo):
    now = drepo.now_utc()
    local = now.astimezone(rs.TZ)
    rows = []
    for k in range(0, 12):
        d = local.date() + timedelta(days=k - 1)
        for hr, t in zip((1, 4, 7, 10, 13, 16, 19, 22), (24, 23.5, 25, 29, 33, 32, 28, 25)):
            rows.append({"local_datetime": f"{d.isoformat()} {hr:02d}:00:00", "temperature": t})
    fc = {"rows": rows, "issued_at": "x", "fetched_at": now.isoformat(), "adm4": "TEST"}
    out, snap = ds.compute_for_plot("DEMO-P01", now, {**demo_data.default_weather("DEMO-P01"), "driver": dw.DRIVER_BMKG}, forecast=fc)
    assert snap["weather"]["driver"] == "BMKG" and snap["weather"]["label"] == dw.LABEL_BMKG and snap["weather"]["n_points"] == len(rows)
    temps = {(e["tmin"], e["tmax"]) for e in snap["et0_daily"] if e["status"] == "OK"}
    assert temps == {(23.5, 33.0)}                               # persis dari baris BMKG; tidak ada suhu sintetis tercampur
    assert out["status"] == "OK"


def test_synthetic_driver_is_always_labelled_and_never_claims_bmkg(demo):
    out, snap = ds.compute_for_plot("DEMO-P02", drepo.now_utc(), demo_data.default_weather("DEMO-P02"))
    assert snap["weather"]["driver"] == "SYNTHETIC" and "bukan data BMKG" in snap["weather"]["label"]
    assert snap["weather_driver"] == "SYNTHETIC" and snap["et0_daily"]
    assert all(e["source"] != "BMKG" for e in snap["et0_daily"])


def test_driver_points_single_source_per_call():
    pts, meta = dw.driver_points(dw.DRIVER_SYNTHETIC, today=date(2026, 1, 1), days=3)
    assert meta["driver"] == "SYNTHETIC" and len(pts) == 24
    pts2, meta2 = dw.driver_points(dw.DRIVER_BMKG, today=date(2026, 1, 1), days=3, composite_points_fn=lambda rows, arch: [], forecast=None)
    assert pts2 == [] and meta2["available"] is False and meta2["driver"] == "BMKG"
    with pytest.raises(ValueError):
        dw.driver_points("MIXED", today=date(2026, 1, 1), days=1)


def test_synthetic_weather_deterministic_and_shift_invariant():
    a = dw.synthetic_points(date(2026, 1, 1), 5, "NORMAL", "s", base=date(2026, 1, 1))
    b = dw.synthetic_points(date(2026, 3, 1), 5, "NORMAL", "s", base=date(2026, 3, 1))
    assert [t for _, t in a] == [t for _, t in b]                 # geser tanggal jangkar tidak mengubah cuaca relatif
    assert a == dw.synthetic_points(date(2026, 1, 1), 5, "NORMAL", "s", base=date(2026, 1, 1))


def test_snapshots_and_outputs_carry_demo_flags(demo):
    res = ds.publish("DEMO-P01", "demo_operator")
    run = drepo.get_run(res["rec_id"])
    assert run["is_demo"] is True and run["run_mode"] == "DEMO" and run["inputs_snapshot"]["is_demo"] is True
    assert run["inputs_snapshot"]["run_label"] == "DEMO" and run["inputs_snapshot"]["rain_kind"] in dw.RAIN_KINDS
    assert run["output"]["weather"]["label"]


def test_example_parameters_never_calibrated(demo):
    for pid in [p["plot_id"] for p in drepo.list_plots()]:
        prof = drepo.get_active_profile(pid)
        assert prof["validation_status"] == "UNVALIDATED"
        assert {p["status"] for p in prof["params"].values()} <= {"EXAMPLE", "PENDING"}
    with pytest.raises(ValueError):
        drepo.save_profile_version("DEMO-P01", [{"name": "mu_dry", "value": 0.3, "status": "CALIBRATED"}], [], "demo_admin")


def test_export_is_labelled_demo(demo):
    exp = drepo.export_all()
    assert "DEMO PENELITIAN" in exp["label"] and exp["dataset_id"] and len(exp["plots"]) == 6
    assert all(p["is_demo"] for p in exp["plots"]) and all(o["is_demo"] for o in exp["observations"])


def test_synthetic_sensors_not_marked_as_real(demo):
    kinds = {r["source_type"] for r in drepo.q("SELECT DISTINCT source_type FROM observations WHERE variable != 'h_cm'")}
    assert kinds == {"SIMULATED"}
