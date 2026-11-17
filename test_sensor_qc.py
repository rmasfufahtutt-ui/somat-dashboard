"""P2: QC sensor dengan tindakan eksplisit; nilai mentah tidak pernah diubah."""
import math

import pandas as pd
import pytest

import sensor_qc as qc

T0 = pd.Timestamp("2026-03-01 00:00")


def frame(vals, sid="SM-01", stype="soil_moisture", step_min=30, status="OK"):
    return pd.DataFrame({"timestamp": [T0 + pd.Timedelta(minutes=step_min * i) for i in range(len(vals))],
                         "sensor_id": sid, "sensor_type": stype, "value": vals, "status": status, "source_type": "DUMMY"})


def run(vals, **kw):
    df = frame(vals, **kw)
    return df, qc.assess(df)


def test_raw_values_never_modified():
    df, out = run([40.0, 150.0, float("nan"), 41.0])
    assert out["value"].tolist()[0] == 40.0 and out["value"].tolist()[1] == 150.0 and math.isnan(out["value"].tolist()[2])
    assert list(out.columns)[: len(df.columns)] == list(df.columns)


def test_range_and_no_value_are_bad_and_excluded():
    _, out = run([40.0, 150.0, -3.0, float("nan"), 41.0])
    assert out["qc_flag"].tolist() == ["OK", "BAD", "BAD", "BAD", "OK"]
    assert out["qc_codes"].tolist()[1] == "OUT_OF_RANGE" and out["qc_codes"].tolist()[3] == "NO_VALUE"
    assert set(out["qc_action"][[1, 2, 3]]) == {"EXCLUDE_FROM_AUTOMATIC_USE"}
    assert out["qc_action"][0] == "USE"


def test_isolated_spike_is_suspect_but_level_shift_is_not():
    _, spike = run([40.0, 41.0, 90.0, 41.0, 40.0])
    assert spike["qc_codes"].tolist()[2] == "SPIKE" and spike["qc_flag"][2] == "SUSPECT"
    _, shift = run([40.0, 41.0, 90.0, 91.0, 90.0])                     # pergeseran tingkat nyata: bukan spike
    assert "SPIKE" not in "".join(shift["qc_codes"])


def test_last_point_and_big_gap_are_not_judged_as_spike():
    _, last = run([40.0, 41.0, 95.0])
    assert last["qc_flag"].tolist() == ["OK", "OK", "OK"]
    df = frame([40.0, 41.0, 90.0, 41.0, 40.0], step_min=300)             # celah 5 jam > max_gap_h
    assert "SPIKE" not in "".join(qc.assess(df)["qc_codes"])


def test_flatline_requires_count_and_duration():
    _, out = run([42.0] * 14)                                           # 14 bacaan identik selama 6,5 jam
    assert set(out["qc_codes"]) == {"FLATLINE"} and set(out["qc_action"]) == {"USE_WITH_WARNING"} and set(out["qc_flag"]) == {"SUSPECT"}
    _, few = run([42.0] * 6)
    assert set(few["qc_flag"]) == {"OK"}
    _, short = run([42.0] * 14, step_min=5)                             # 14 bacaan tetapi hanya 65 menit
    assert set(short["qc_flag"]) == {"OK"}


def test_rainfall_zero_repeats_are_fine_but_negative_is_bad():
    _, out = run([0.0] * 20 + [-1.0], sid="RF-01", stype="rainfall")
    assert out["qc_flag"].tolist() == ["OK"] * 20 + ["BAD"]


def test_water_level_has_no_invented_range():
    _, out = run([-500.0, 900.0, 3.0], sid="WL-01", stype="water_level")
    assert set(out["qc_flag"]) == {"OK"}                               # datum/satuan belum final -> tidak ada batas karangan


def test_sensors_are_assessed_independently():
    a = frame([40.0, 41.0, 90.0, 41.0, 40.0], sid="A")
    b = frame([40.0, 41.0, 42.0, 41.0, 40.0], sid="B")
    out = qc.assess(pd.concat([a, b], ignore_index=True))
    assert out[out.sensor_id == "A"]["qc_flag"].tolist()[2] == "SUSPECT" and set(out[out.sensor_id == "B"]["qc_flag"]) == {"OK"}


def test_unsorted_input_gives_same_result():
    df = frame([40.0, 41.0, 90.0, 41.0, 40.0])
    shuffled = df.sample(frac=1.0, random_state=3)
    out = qc.assess(shuffled).sort_values("timestamp")
    assert out["qc_codes"].tolist() == qc.assess(df)["qc_codes"].tolist()


def test_empty_frame_ok():
    out = qc.assess(frame([]))
    assert out.empty and "qc_flag" in out.columns


def test_combine_flag_never_overrides_device_status():
    assert qc.combine_flag("OK", "SUSPECT") == "SUSPECT"
    assert qc.combine_flag("OK", "OK") == "OK"
    assert qc.combine_flag("ERROR", "OK") == "ERROR"
    assert qc.combine_flag(None, "BAD") == "BAD"


def test_coverage_report_actions():
    sensors = [dict(sensor_id="SM-01", sensor_type="soil_moisture", expected_interval_min=30, offline_after_min=180),
               dict(sensor_id="SM-02", sensor_type="soil_moisture", expected_interval_min=30, offline_after_min=180),
               dict(sensor_id="SM-03", sensor_type="soil_moisture", expected_interval_min=30, offline_after_min=180)]
    now = T0 + pd.Timedelta(hours=24)
    good = frame([40.0 + (i % 3) for i in range(48)], sid="SM-01")             # penuh dan segar
    sparse = frame([40.0, 41.0, 42.0], sid="SM-02", step_min=300)              # jarang, terakhir 14 j lalu
    df = qc.assess(pd.concat([good, sparse], ignore_index=True))
    rep = qc.coverage_report(df, sensors, now).set_index("sensor_id")
    assert rep.loc["SM-01", "action"] == "USE" and rep.loc["SM-01", "coverage"] == pytest.approx(1.0, abs=0.03)
    assert "STALE" in rep.loc["SM-02", "codes"] and rep.loc["SM-02", "action"] == "EXCLUDE_FROM_AUTOMATIC_USE"
    assert rep.loc["SM-03", "codes"] == "NO_DATA" and rep.loc["SM-03", "action"] == "EXCLUDE_FROM_AUTOMATIC_USE"


def test_low_coverage_only_warns():
    sensors = [dict(sensor_id="SM-01", sensor_type="soil_moisture", expected_interval_min=30, offline_after_min=180)]
    now = T0 + pd.Timedelta(hours=24)
    df = qc.assess(frame([40.0 + i for i in range(10)], sid="SM-01", step_min=30).assign(
        timestamp=lambda d: [now - pd.Timedelta(minutes=30 * (9 - i)) for i in range(10)]))
    rep = qc.coverage_report(df, sensors, now)
    assert rep.loc[0, "codes"] == "LOW_COVERAGE" and rep.loc[0, "action"] == "USE_WITH_WARNING"


def test_every_code_has_flag_action_and_bilingual_text():
    for code, (flag, action, en, idn) in qc.CODES.items():
        assert flag in ("SUSPECT", "BAD") and action in ("USE_WITH_WARNING", "EXCLUDE_FROM_AUTOMATIC_USE") and en and idn
        assert qc.describe(code, "en") == en and qc.describe(code, "id") == idn
    for code in qc.SENSOR_CODES:
        assert qc.describe(code, "en") and qc.describe(code, "id")


# ------------------------------------------------------------------ sambungan ke penyimpanan (tanpa DB)
def _archive_frame(vals, status="OK"):
    df = frame(vals, status=status)
    for c, v in (("unit", "%"), ("location", "P1"), ("measurement_mode", "auto"), ("device_id", "d1"), ("sequence", 1)):
        df[c] = v
    return df


def test_archive_rows_carry_qc_flag_codes_and_keep_raw_value(monkeypatch):
    import repository as repo
    monkeypatch.setattr(repo, "J", lambda o: o)          # adaptor Json psycopg2 tidak ada di sandbox
    rows = repo.build_sensor_archive_rows(_archive_frame([40.0, 41.0, 90.0, 41.0, 150.0, 40.0]))
    by_val = {r[3]: r for r in rows}
    assert by_val[90.0][8] == "SUSPECT" and by_val[150.0][8] == "BAD" and by_val[40.0][8] == "OK"   # nilai mentah tersimpan
    meta = by_val[150.0][10]
    assert "OUT_OF_RANGE" in meta["qc_codes"].split(",") and meta["qc_action"] == "EXCLUDE_FROM_AUTOMATIC_USE"


def test_archive_rows_keep_device_error_status_and_respect_since(monkeypatch):
    import repository as repo
    monkeypatch.setattr(repo, "J", lambda o: o)
    rows = repo.build_sensor_archive_rows(_archive_frame([40.0, 41.0], status="ERROR"))
    assert [r[8] for r in rows] == ["ERROR", "ERROR"]
    first = repo.as_utc(T0)
    assert len(repo.build_sensor_archive_rows(_archive_frame([40.0, 41.0, 42.0]), {"SM-01": first})) == 2
    assert repo.build_sensor_archive_rows(None) == [] and repo.build_sensor_archive_rows(frame([])) == []


# ------------------------------------------------------------------ QC -> keputusan otomatis (derive/sensor_logic)
def _live(vals, sid="SM-01", stype="soil_moisture", end=None):
    end = end or pd.Timestamp.now(tz="Asia/Jakarta").tz_localize(None).floor("min")
    n = len(vals)
    return pd.DataFrame({"timestamp": [end - pd.Timedelta(minutes=30 * (n - 1 - i)) for i in range(n)], "sensor_id": sid,
                         "sensor_type": stype, "location": "P1", "value": vals, "unit": "%", "status": "OK",
                         "measurement_mode": "auto", "device_id": "d", "sequence": 1, "source_type": "SENSOR"})


def test_gate_excludes_bad_points_but_keeps_raw_values_and_original_df():
    df = _live([40.0, 41.0, 40.5, 150.0])
    g, n = qc.gate_for_decisions(df)
    assert n == 1 and g["status"].tolist() == ["OK", "OK", "OK", "QC_EXCLUDED"] and g["value"].tolist() == df["value"].tolist()
    assert df["status"].tolist() == ["OK"] * 4                           # df asli tidak berubah
    assert qc.gate_for_decisions(df.iloc[0:0])[1] == 0 and qc.gate_for_decisions(None) == (None, 0)


def test_warning_only_flags_stay_in_automatic_use():
    g, n = qc.gate_for_decisions(_live([42.0] * 14))                     # FLATLINE = USE_WITH_WARNING
    assert n == 0 and set(g["status"]) == {"OK"}


def test_device_error_status_is_not_relabelled():
    df = _live([40.0, 41.0, 150.0])
    df.loc[2, "status"] = "ERROR"
    g, n = qc.gate_for_decisions(df)
    assert n == 0 and g["status"].tolist() == ["OK", "OK", "ERROR"]


def test_summary_ignores_out_of_range_latest_reading():
    import sensor_logic as sl
    df = _live([40.0, 41.0, 40.5, 150.0])
    raw = sl.summarize_sensors(df)
    gated = sl.summarize_sensors(qc.gate_for_decisions(df)[0])
    assert raw["soil_moisture"] == pytest.approx(150.0)                  # tanpa QC angka ngawur ikut keputusan
    assert gated["soil_moisture"] == pytest.approx(40.5)                 # dengan QC memakai pembacaan sah terbaru


def test_status_table_uses_gated_frame():
    import sensor_logic as sl
    df = _live([150.0, 150.0])                                           # semua pembacaan di luar rentang
    sensors = [dict(sensor_id="SM-01", sensor_type="soil_moisture", location="P1", expected_interval_min=30, offline_after_min=180)]
    assert sl.sensor_status_table(df, sensors).loc[0, "Status"] == "Online"
    assert sl.sensor_status_table(qc.gate_for_decisions(df)[0], sensors).loc[0, "Status"] == "Offline"


def test_derive_compute_uses_gate_and_exposes_count(monkeypatch):
    import types
    import derive
    df = _live([40.0, 41.0, 40.5, 150.0])
    src = types.SimpleNamespace(origin="live", configured=True, ok=True, attempted_at=None)
    snap = types.SimpleNamespace(version=1, sensor_df=df, sensor_meta={"sensors": [
        dict(sensor_id="SM-01", sensor_type="soil_moisture", location="P1", expected_interval_min=30, offline_after_min=180)]},
        source=lambda name: src)
    d = derive.compute(snap)
    assert d.n_qc_excluded == 1 and d.sensor_summary["soil_moisture"] == pytest.approx(40.5)
    assert d.sensor_df["value"].tolist()[-1] == 150.0                    # tampilan mentah tetap
