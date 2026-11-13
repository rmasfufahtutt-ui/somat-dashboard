"""Uji integrasi DB. Hanya jalan bila TEST_DATABASE_URL diisi (nama database WAJIB mengandung 'test').
PERINGATAN: skema public pada database itu DIHAPUS lalu dibuat ulang.

Contoh: TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5544/somat_test pytest test_db_integration.py"""
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif("test" not in URL.rsplit("/", 1)[-1], reason="TEST_DATABASE_URL (nama DB mengandung 'test') tidak diisi")


def test_full_flow():
    import psycopg2
    c = psycopg2.connect(URL)
    c.autocommit = True
    c.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    c.close()
    import db
    import repository as repo
    import recommendation_service as rsvc
    db.configure(URL)
    assert db.ensure_ready(), db.last_error()
    db.run_migrations()
    NOW = datetime.now(timezone.utc)
    repo.upsert_plot("P1", "Petak 1", "admin", -6.7, 108.2, 10, "MSL", 1, "", "SM-01", "WL-01")
    params = [{"name": n, "value": v, "unit": "", "status": "LITERATURE", "source": "uji"} for n, v in
              (("area_ha", 1.0), ("mu_dry", .18), ("mu_fill", .18), ("lead_time_h", 24.0), ("sp_constant", 2.0), ("q_plot_m3s", .05),
               ("kc_vegetatif", 1.1), ("trigger_h_vegetatif", -15.0), ("target_h_vegetatif", 5.0))]
    phases = [{"phase": "vegetatif", "from_das": 0, "to_das": 90, "protected": False}]
    repo.save_profile_version("P1", params, phases, "admin", "v1")
    repo.save_profile_version("P1", params, phases, "admin", "v2")
    prof = repo.get_active_profile("P1")
    assert prof["version"] == 2 and len(prof["params"]) == 9 and prof["phases"][0]["phase"] == "vegetatif", prof["version"]
    assert len(repo.list_profile_versions("P1")) == 2
    repo.add_crop_cycle("P1", date.today() - timedelta(days=20), "x", "admin")
    assert repo.get_active_cycle("P1")
    # h manual + koreksi + void
    o1 = repo.add_h_observation("P1", -14.0, NOW - timedelta(hours=3), "admin", "a")
    o2 = repo.add_h_observation("P1", -13.0, NOW - timedelta(hours=3), "admin", "koreksi", supersedes_id=o1)
    lh = repo.latest_h("P1"); assert lh["obs_id"] == o2 and lh["value"] == -13.0
    assert repo.void_observation(o2, "admin", "salah") and repo.latest_h("P1") is None
    repo.add_h_observation("P1", -14.0, NOW - timedelta(hours=2), "admin")
    # sensor archive idempoten
    df = pd.DataFrame({"timestamp": pd.date_range("2026-11-13 06:00", periods=4, freq="h"), "sensor_id": "SM-01", "sensor_type": "soil_moisture",
                       "location": "A", "value": [30., 31., None, 33.], "unit": "%", "status": "OK", "measurement_mode": "m", "device_id": "d",
                       "sequence": range(4), "source_type": "DUMMY"})
    assert repo.archive_sensor_rows(df, {}) == 4
    repo.archive_sensor_rows(df, {})
    cnt = db.db_query("SELECT COUNT(*) c FROM observations WHERE sensor_id='SM-01'")[0]["c"]
    assert cnt == 4
    back = repo.load_recent_sensor_frame(days=3650)
    assert back.shape[0] == 4 and "timestamp" in back.columns
    # forecast archive
    rows = [{"local_datetime": f"2026-11-1{d} {h:02d}:00:00", "utc_datetime": "", "temperature": t, "humidity": 80, "wind_speed": 5, "cloud_cover": 50, "precipitation_tp": 0}
            for d in (3, 4) for h, t in ((1, 24), (7, 26), (13, 32), (19, 27))]
    res = {"adm4": "32.10.15.2003", "rows": rows, "issued_at": NOW, "fetched_at": NOW, "payload_hash": uuid.uuid4().hex, "raw": {"a": 1}}
    r1 = repo.archive_forecast_run(res); r2 = repo.archive_forecast_run(res)
    assert r1[1] and not r2[1] and r1[0] == r2[0]
    slots = repo.load_forecast_slots("32.10.15.2003", since_hours=24 * 3650)
    assert len(slots) == 8
    # rekomendasi + keputusan atomik
    import recommendation_service as rsvc
    class S: max_h_age_hours = 30.0; rec_expiry_hours = 6.0
    class Snap: forecast = res
    pts_rows = [{"local_datetime": f"{(date.today()+timedelta(days=d)):%Y-%m-%d} {h:02d}:00:00", "utc_datetime": "", "temperature": t}
                for d in range(-1, 6) for h, t in ((1, 24), (4, 23), (7, 26), (10, 30), (13, 32), (16, 31), (19, 27), (22, 25))]
    res2 = dict(res, rows=pts_rows, payload_hash=uuid.uuid4().hex)
    class Snap2: forecast = res2
    out = rsvc.run_and_publish(repo, "P1", Snap2, "admin", S())
    rec_id = out["rec_id"]; print("rec", rec_id, out["output"]["status"], out["output"]["run_mode"])
    run = repo.get_run(rec_id); assert run["status"] == "PUBLISHED"
    did, dup = repo.record_decision(rec_id, "admin", "APPROVE", run["output"]["total_mm"], run["output"]["duration_h"], "ok", "key-1")
    did2, dup2 = repo.record_decision(rec_id, "admin", "APPROVE", 1, 1, "ok", "key-1")
    assert did == did2 and dup2
    with pytest.raises(repo.DecisionError) as ei:
        repo.record_decision(rec_id, "bob", "DELAY", 0, 0, "", "key-2")
    assert ei.value.code == "already_handled"
    # rekomendasi baru lalu observasi h baru -> inputs_changed
    out2 = rsvc.run_and_publish(repo, "P1", Snap2, "admin", S())
    assert repo.get_run(rec_id)["status"] == "DECIDED"
    repo.add_h_observation("P1", -15.0, NOW - timedelta(minutes=5), "admin")
    with pytest.raises(repo.DecisionError) as ei:
        repo.record_decision(out2["rec_id"], "admin", "APPROVE", 5, 1, "", "key-3")
    assert ei.value.code == "inputs_changed"
    # koreksi keputusan
    nid = repo.supersede_decision(did, "admin", "MODIFY", 20.0, 3.0, "n", "salah ketik")
    st = {r["id"]: r["record_status"] for r in repo.list_decisions(50)}
    assert st[did] == "SUPERSEDED" and st[nid] == "ACTIVE"
    ev = repo.add_irrigation_event("P1", nid, rec_id, NOW, NOW, NOW + timedelta(hours=3), 300.0, .05, "FLOW_METER", -2.0, NOW + timedelta(hours=4), "n", "admin")
    assert not repo.decisions_awaiting_execution()
    repo.void_irrigation_event(ev, "admin", "uji")
    repo.log_ingest("sensor", True, 4, "t")
    assert len(repo.recent_ingest()) == 1

