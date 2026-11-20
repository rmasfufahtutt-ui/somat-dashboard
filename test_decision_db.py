"""H13 pada jalur operasional (SQL sungguhan): profil berubah / status tak layak memblokir keputusan. Butuh DB uji (pgdb)."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)


def _setup(repo):
    repo.upsert_plot("P1", "Petak 1", "admin", -6.7, 108.2, 10, "MSL", 1, "", "SM-01", "WL-01")
    params = [{"name": n, "value": v, "unit": "", "status": "LITERATURE", "source": "uji"} for n, v in
              (("area_ha", 1.0), ("mu_dry", .18), ("mu_fill", .18), ("lead_time_h", 24.0), ("sp_constant", 2.0),
               ("q_plot_m3s", .05), ("kc_vegetatif", 1.1), ("trigger_h_vegetatif", -15.0), ("target_h_vegetatif", 5.0))]
    phases = [{"phase": "vegetatif", "from_das": 0, "to_das": 90, "protected": False}]
    repo.save_profile_version("P1", params, phases, "admin", "v1")
    repo.add_crop_cycle("P1", date.today() - timedelta(days=20), "x", "admin")
    repo.add_h_observation("P1", -14.0, NOW - timedelta(hours=2), "admin")
    return params, phases


def _publish(repo):
    import recommendation_service as rsvc

    class S:
        max_h_age_hours = 30.0
        rec_expiry_hours = 6.0

    rows = [{"local_datetime": f"{(date.today() + timedelta(days=d)):%Y-%m-%d} {h:02d}:00:00", "utc_datetime": "", "temperature": t}
            for d in range(-1, 6) for h, t in ((1, 24), (4, 23), (7, 26), (10, 30), (13, 32), (16, 31), (19, 27), (22, 25))]

    class Snap:
        forecast = {"adm4": "32.10.15.2003", "rows": rows, "issued_at": NOW, "fetched_at": NOW,
                    "payload_hash": uuid.uuid4().hex, "raw": {"a": 1}}
        sensor_df = None

    return rsvc.run_and_publish(repo, "P1", Snap, "admin", S())


def test_profile_change_after_publish_blocks_operational_decision(pgdb):
    repo = pgdb
    params, phases = _setup(repo)
    out = _publish(repo)
    run = repo.get_run(out["rec_id"])
    assert run["status"] == "PUBLISHED" and run["run_mode"] in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED")
    repo.save_profile_version("P1", params, phases, "admin", "v2")                 # profil aktif berganti
    with pytest.raises(repo.DecisionError) as e:
        repo.record_decision(out["rec_id"], "admin", "DELAY", 0, 0, "", "k1")
    assert e.value.code == "profile_changed"


def test_undecidable_status_is_blocked_and_normal_decision_passes(pgdb):
    repo = pgdb
    _setup(repo)
    out = _publish(repo)
    did, dup = repo.record_decision(out["rec_id"], "admin", "DELAY", 0, 0, "", "k2")        # profil tidak berubah: lolos
    assert did and not dup
    out2 = _publish(repo)
    rid = out2["rec_id"]
    repo.db_query("UPDATE recommendation_runs SET status_code='MISSING_PARAMETER' WHERE rec_id=%s", (rid,))
    with pytest.raises(repo.DecisionError) as e:
        repo.record_decision(rid, "admin", "APPROVE", 5, 1, "", "k3")
    assert e.value.code == "not_decidable_status"
