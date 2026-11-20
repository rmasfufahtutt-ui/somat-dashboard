"""H07: hasil QC disimpan terpisah dari nilai mentah, berversi, dan penilaian retrospektif tidak mengubah apa yang tersedia pada
keputusan historis. Bagian murni selalu jalan; bagian SQL butuh DB uji (fixture pgdb)."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import sensor_qc

T0 = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)


def frame(values, start=0, sid="SM-01", status="OK"):
    base = pd.Timestamp("2026-11-10 07:00:00")                      # WIB naif = 00:00 UTC
    ts = [base + pd.Timedelta(minutes=30 * (start + i)) for i in range(len(values))]
    return pd.DataFrame({"timestamp": ts, "sensor_id": sid, "sensor_type": "soil_moisture", "location": "P1",
                         "value": values, "unit": "%", "status": status, "measurement_mode": "instantaneous",
                         "device_id": "d1", "sequence": range(start, start + len(values)), "source_type": "SENSOR"})


# ----------------------------------------------------------------------------------------------- bagian murni
def test_asof_cannot_see_spike_but_retrospective_can():
    df = frame([40.0, 41.0, 90.0, 41.0, 40.0])
    assert sensor_qc.assess(df)["qc_codes"].tolist() == ["", "", "SPIKE", "", ""]
    assert sensor_qc.assess_asof(df)["qc_codes"].tolist() == ["", "", "", "", ""]
    assert sensor_qc.assess_asof(df.iloc[:3])["qc_codes"].tolist() == ["", "", ""]          # titik terakhir: belum ada pembanding


def test_asof_flatline_flags_only_from_the_point_the_run_qualifies():
    df = frame([55.0] * 14)                                           # 14 bacaan identik, 6,5 jam
    online = sensor_qc.assess_asof(df)["qc_codes"].tolist()
    assert online[:12] == [""] * 12 and online[12:] == ["FLATLINE"] * 2     # lolos pada bacaan ke-13: 12 bacaan DAN >= 6 jam
    assert sensor_qc.assess(df)["qc_codes"].tolist() == ["FLATLINE"] * 14


def test_asof_range_checks_match_retrospective_and_values_untouched():
    df = frame([150.0, None, 40.0])
    a, b = sensor_qc.assess_asof(df), sensor_qc.assess(df)
    assert a["qc_codes"].tolist() == b["qc_codes"].tolist() == ["OUT_OF_RANGE", "NO_VALUE", ""]
    assert df["value"].iloc[0] == 150.0 and pd.isna(df["value"].iloc[1])


def test_rule_version_is_stable_and_changes_with_thresholds():
    v = sensor_qc.rule_version()
    assert v == sensor_qc.rule_version() and v.startswith("qc-")
    changed = dict(sensor_qc.DEFAULT_RULES)
    changed["soil_moisture"] = sensor_qc.Rule(lo=0.0, hi=100.0, max_jump=20.0, flat_n=12, flat_hours=6.0)
    assert sensor_qc.rule_version(changed) != v


def _keys(df):
    import repository as repo
    return [repo.sensor_ext_key(r.source_type, r.sensor_id, repo.as_utc(r.timestamp)) for r in df.itertuples(index=False)]


def test_plan_first_batch_is_online_and_later_batch_adds_retrospective_spike(monkeypatch):
    import repository as repo
    monkeypatch.setattr(repo, "J", lambda o: o)
    b1 = frame([40.0, 41.0, 90.0])
    k1 = _keys(b1)
    plan1 = repo.plan_qc_rows(b1, {}, set(k1), T0)
    assert {p[1] for p in plan1} == {"ONLINE"} and all(p[3] == "NONE" and p[4] == "USE" for p in plan1)
    stored = {k: frozenset() for k in k1}
    b2 = frame([40.0, 41.0, 90.0, 41.0, 40.0])
    k2 = _keys(b2)
    plan2 = repo.plan_qc_rows(b2, stored, set(k2[3:]), T0 + timedelta(hours=1))
    retro = [p for p in plan2 if p[1] == "RETROSPECTIVE"]
    assert len(retro) == 1 and retro[0][0] == k2[2] and retro[0][3] == "SPIKE" and retro[0][4] == "EXCLUDE_FROM_AUTOMATIC_USE"
    assert retro[0][6] == retro[0][7] == T0 + timedelta(hours=1)                  # evaluated_at = available_at = saat informasi ada
    assert {p[0] for p in plan2 if p[1] == "ONLINE"} == set(k2[3:])             # hanya titik baru yang dinilai online
    # idempoten: evaluasi yang sama tidak dibuat lagi
    stored2 = {k: frozenset() for k in k2}
    stored2[k2[2]] = frozenset({"SPIKE"})
    assert repo.plan_qc_rows(b2, stored2, set(), T0 + timedelta(hours=2)) == []


def test_plan_points_without_any_stored_qc_get_retrospective_baseline(monkeypatch):
    import repository as repo
    df = frame([40.0, 41.0, 90.0, 41.0, 40.0])
    plan = repo.plan_qc_rows(df, {}, set(), T0)
    assert {p[1] for p in plan} == {"RETROSPECTIVE"} and [p[3] for p in plan].count("SPIKE") == 1


def test_raw_archive_rows_carry_no_qc_result(monkeypatch):
    import repository as repo
    monkeypatch.setattr(repo, "J", lambda o: o)
    rows = repo.build_sensor_archive_rows(frame([150.0, 40.0]))
    assert rows[0][3] == 150.0 and rows[0][8] == "OK"                 # nilai mentah utuh; quality_flag = status perangkat
    assert "qc_codes" not in rows[0][10] and "qc_action" not in rows[0][10]
    assert repo.build_sensor_archive_rows(frame([40.0], status="ERROR"))[0][8] == "ERROR"


# ----------------------------------------------------------------------------------------------- bagian SQL
def _count(repo, sql):
    return int(repo.db_query(sql)[0]["n"])


def test_sql_online_then_retrospective_keeps_historical_availability(pgdb):
    repo = pgdb
    t1, t2 = T0 + timedelta(hours=1), T0 + timedelta(hours=3)
    assert repo.archive_sensor_rows(frame([40.0, 41.0, 90.0]), None, t1) == 3
    first = {r["ext_key"]: r for r in repo.load_qc_asof(t1)}
    assert len(first) == 3 and all(r["qc_type"] == "ONLINE" and r["action"] == "USE" for r in first.values())
    since = repo.last_sensor_times()
    assert repo.archive_sensor_rows(frame([40.0, 41.0, 90.0, 41.0, 40.0]), since, t2) == 2
    spike_key = _keys(frame([40.0, 41.0, 90.0]))[2]
    # pada t1 (saat keputusan lama) titik itu tetap OK; baru pada t2 ia SPIKE
    at_t1 = {r["ext_key"]: r for r in repo.load_qc_asof(t1)}
    at_t2 = {r["ext_key"]: r for r in repo.load_qc_asof(t2)}
    assert at_t1[spike_key]["action"] == "USE" and at_t1[spike_key]["reasons"] == []
    assert at_t2[spike_key]["action"] == "EXCLUDE_FROM_AUTOMATIC_USE" and at_t2[spike_key]["reasons"] == ["SPIKE"]
    assert at_t2[spike_key]["qc_type"] == "RETROSPECTIVE" and at_t2[spike_key]["available_at"] == t2
    assert len(at_t2) == 5 and at_t2[spike_key]["rule_version"] == sensor_qc.rule_version()
    # nilai mentah tidak berubah
    raw = repo.db_query("SELECT value, quality_flag FROM observations WHERE ext_key = %s", (spike_key,))
    assert raw[0]["value"] == 90.0 and raw[0]["quality_flag"] == "OK"


def test_sql_rerun_is_idempotent_and_append_only(pgdb):
    repo = pgdb
    df = frame([40.0, 41.0, 90.0, 41.0, 40.0])
    repo.archive_sensor_rows(df, None, T0 + timedelta(hours=1))
    n1 = _count(repo, "SELECT COUNT(*) AS n FROM observation_qc")
    repo.archive_sensor_rows(df, None, T0 + timedelta(hours=2))
    repo.archive_sensor_rows(df, repo.last_sensor_times(), T0 + timedelta(hours=3))
    assert _count(repo, "SELECT COUNT(*) AS n FROM observation_qc") == n1
    assert _count(repo, "SELECT COUNT(*) AS n FROM observations") == 5
    with pytest.raises(Exception):
        repo.db_query("UPDATE observation_qc SET qc_flag='OK'")
    with pytest.raises(Exception):
        repo.db_query("DELETE FROM observation_qc")
    assert _count(repo, "SELECT COUNT(*) AS n FROM observation_qc") == n1


def test_sql_qc_flag_constraints_and_device_error_kept(pgdb):
    repo = pgdb
    repo.archive_sensor_rows(frame([40.0, 41.0], status="ERROR"), None, T0)
    assert repo.db_query("SELECT DISTINCT quality_flag FROM observations")[0]["quality_flag"] == "ERROR"
    with pytest.raises(Exception):
        repo.db_query("INSERT INTO observation_qc (obs_id, qc_type, qc_flag, reason_code, action, rule_version, evaluated_at, "
                      "available_at) SELECT obs_id, 'ONLINE', 'WEIRD', 'X', 'USE', 'v', NOW(), NOW() FROM observations LIMIT 1")
