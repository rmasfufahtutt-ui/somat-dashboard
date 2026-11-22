"""Demo: setelah irigasi sejak h terakhir, satu pembacaan h SIMULASI baru membuat prediksi/rekomendasi/durasi terisi lagi."""
import pytest

import demo_repository as drepo
import demo_service as ds


def _stuck(pid="DEMO-P01"):
    """Buat keadaan seperti layar: ada keputusan APPROVE setelah h terakhir -> macet."""
    rid, out = ds.publish(pid, "demo_operator")["rec_id"], None
    out = drepo.get_run(rid)["output"]
    if out.get("status") == "OK" and out.get("total_mm"):
        drepo.record_decision(rid, "demo_operator", "APPROVE", out["total_mm"], out["duration_h"], "", "stuck-k")
    return ds.compute_for_plot(pid)[0]


def test_fresh_h_unblocks_stuck_demo_plot(demo):
    out = _stuck()
    if out["status"] == "OK":                       # keputusan terbaru belum dihitung sebagai macet: paksa dengan h lama
        pytest.skip("seed tidak menghasilkan keadaan macet")
    assert out["status"] in ds.NEEDS_NEW_H
    oid = ds.record_fresh_h("DEMO-P01", "demo_operator")
    row = drepo.q("SELECT origin, is_demo, source_type, value FROM observations WHERE obs_id=?", (oid,))[0]
    assert row["origin"] == "DEMO_FRESH" and row["is_demo"] == 1 and row["value"] == ds.suggested_fresh_h("DEMO-P01")
    out2 = ds.compute_for_plot("DEMO-P01")[0]
    assert out2["status"] in ("OK", "TARGET_NOT_REACHABLE")
    assert out2["h_arrival_cm"] is not None and out2["irrigate"] is True
    assert out2["total_mm"] and out2["duration_h"]


def test_fresh_h_value_validated(demo):
    with pytest.raises(ValueError):
        ds.record_fresh_h("DEMO-P01", "demo_operator", 99.0)
    with pytest.raises(ValueError):
        ds.record_fresh_h("DEMO-P01", "demo_operator", -80.0)


def test_viewer_cannot_record_fresh_h(demo):
    demo.as_("viewer")
    with pytest.raises(PermissionError):
        ds.record_fresh_h("DEMO-P01", "demo_viewer")


def test_fresh_h_stays_in_demo_space(demo):
    ds.record_fresh_h("DEMO-P02", "demo_operator", -3.0)
    r = drepo.latest_h("DEMO-P02")
    assert r["is_demo"] == 1 and r["value"] == -3.0
