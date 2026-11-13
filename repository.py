"""repository.py - akses data Neon untuk entitas Grand Framework v2 (tanpa Streamlit).

Prinsip: pencatatan penelitian tidak diedit/dihapus di tempat. Koreksi memakai record baru yang menggantikan
(`supersedes_id`) dan pembatalan memakai status VOID dengan alasan. Rekomendasi yang sudah terbit tidak
berubah; hanya statusnya (PUBLISHED -> DECIDED/SUPERSEDED/EXPIRED).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import db
from db import db_query, transaction

try:
    from psycopg2.extras import Json
except Exception:                                  # pragma: no cover
    Json = None

WIB = timezone(timedelta(hours=7))
PARAM_STATUSES = ("CALIBRATED", "LITERATURE", "EXAMPLE", "PENDING")
SENSOR_VARIABLE_UNITS = {"soil_moisture": "%", "water_level": "m", "rainfall": "mm"}


class DecisionError(Exception):
    """Keputusan ditolak dengan kode yang dapat diterjemahkan UI."""

    def __init__(self, code, **info):
        super().__init__(code)
        self.code, self.info = code, info


# ----------------------------------------------------------------------------------------------
# utilitas
# ----------------------------------------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_json(obj):
    """Ubah objek menjadi struktur JSON sah: datetime -> ISO, NaN/Inf -> None, numpy -> Python."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int,)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean_json(v) for v in obj]
    if hasattr(obj, "item"):                         # numpy scalar
        try:
            return clean_json(obj.item())
        except Exception:
            pass
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def J(obj):
    return Json(clean_json(obj), dumps=lambda o: json.dumps(o, ensure_ascii=False))


def inputs_hash(snapshot: dict) -> str:
    canon = json.dumps(clean_json(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def as_utc(ts) -> datetime:
    """Nilai waktu apa pun -> datetime berzona UTC. Naive dianggap waktu WIB (zona lokal aplikasi)."""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=WIB)
    return ts.astimezone(timezone.utc)


# ----------------------------------------------------------------------------------------------
# audit dan log ingest
# ----------------------------------------------------------------------------------------------
def audit(action, detail="", username="-", entity=None, entity_id=None, old=None, new=None):
    try:
        db_query(
            "INSERT INTO audit_log (ts, username, action, detail, entity, entity_id, old_value, new_value) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (now_utc(), username or "-", action, str(detail)[:500], entity,
             None if entity_id is None else str(entity_id),
             J(old) if old is not None else None, J(new) if new is not None else None))
    except Exception:
        pass


def log_ingest(source: str, ok: bool, rows: int = 0, message: str = ""):
    try:
        db_query("INSERT INTO ingest_log (source, ok, rows, message) VALUES (%s,%s,%s,%s)",
                 (source, bool(ok), int(rows), str(message)[:300]))
        db_query("DELETE FROM ingest_log WHERE id < (SELECT COALESCE(MAX(id),0) - 1000 FROM ingest_log)")
    except Exception:
        pass


def recent_ingest(limit=50):
    return db_query("SELECT ts, source, ok, rows, message FROM ingest_log ORDER BY id DESC LIMIT %s", (int(limit),))


# ----------------------------------------------------------------------------------------------
# petak, profil berversi, siklus tanam
# ----------------------------------------------------------------------------------------------
def list_plots(active_only=True):
    return db_query("SELECT * FROM plots " + ("WHERE active " if active_only else "") + "ORDER BY plot_id")


def get_plot(plot_id):
    rows = db_query("SELECT * FROM plots WHERE plot_id=%s", (plot_id,))
    return rows[0] if rows else None


def upsert_plot(plot_id, name, actor, latitude=None, longitude=None, elevation_m=None, datum="", pipe_count=None,
                pipe_location="", soil_sensor_id=None, canal_sensor_id=None, rain_source_id=None, temp_source_id=None,
                coordinate_source="", active=True):
    before = get_plot(plot_id)
    db_query(
        """INSERT INTO plots (plot_id, name, latitude, longitude, elevation_m, datum, pipe_count, pipe_location,
               soil_sensor_id, canal_sensor_id, rain_source_id, temp_source_id, coordinate_source, active, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
           ON CONFLICT (plot_id) DO UPDATE SET name=EXCLUDED.name, latitude=EXCLUDED.latitude,
               longitude=EXCLUDED.longitude, elevation_m=EXCLUDED.elevation_m, datum=EXCLUDED.datum,
               pipe_count=EXCLUDED.pipe_count, pipe_location=EXCLUDED.pipe_location,
               soil_sensor_id=EXCLUDED.soil_sensor_id, canal_sensor_id=EXCLUDED.canal_sensor_id,
               rain_source_id=EXCLUDED.rain_source_id, temp_source_id=EXCLUDED.temp_source_id,
               coordinate_source=EXCLUDED.coordinate_source, active=EXCLUDED.active, updated_at=NOW()""",
        (plot_id, name, latitude, longitude, elevation_m, datum, pipe_count, pipe_location, soil_sensor_id or None,
         canal_sensor_id or None, rain_source_id or None, temp_source_id or None, coordinate_source, bool(active)))
    audit("plot_upsert", plot_id, actor, "plot", plot_id, old=before,
          new={"name": name, "latitude": latitude, "longitude": longitude, "active": active})


def _profile_params(profile_id):
    rows = db_query("SELECT name, value, unit, status, source, assessment_method, checked_by, measured_at "
                    "FROM plot_parameters WHERE profile_id=%s ORDER BY name", (profile_id,))
    return {r["name"]: r for r in rows}


def get_active_profile(plot_id, at=None):
    """Profil yang berlaku pada waktu `at` (default: sekarang) beserta parameter dan jendela fase."""
    at = at or now_utc()
    rows = db_query(
        "SELECT * FROM plot_profile_versions WHERE plot_id=%s AND effective_from <= %s "
        "AND (effective_to IS NULL OR effective_to > %s) ORDER BY version DESC LIMIT 1", (plot_id, at, at))
    if not rows:
        return None
    p = dict(rows[0])
    p["params"] = _profile_params(p["profile_id"])
    p["phases"] = db_query("SELECT phase, from_das, to_das, protected, protocol_version FROM phase_rules "
                           "WHERE profile_id=%s ORDER BY from_das", (p["profile_id"],))
    return p


def get_profile_by_id(profile_id):
    rows = db_query("SELECT * FROM plot_profile_versions WHERE profile_id=%s", (profile_id,))
    if not rows:
        return None
    p = dict(rows[0])
    p["params"] = _profile_params(profile_id)
    p["phases"] = db_query("SELECT phase, from_das, to_das, protected, protocol_version FROM phase_rules "
                           "WHERE profile_id=%s ORDER BY from_das", (profile_id,))
    return p


def list_profile_versions(plot_id):
    return db_query("SELECT profile_id, version, effective_from, effective_to, approved_by, note, validation_status, "
                    "protocol_version FROM plot_profile_versions WHERE plot_id=%s ORDER BY version DESC", (plot_id,))


def save_profile_version(plot_id, params, phases, actor, note="", validation_status="UNVALIDATED",
                         protocol_version=""):
    """Buat versi profil baru (profil lama ditutup). params: [{name,value,unit,status,source,assessment_method,
    checked_by,measured_at}], phases: [{phase,from_das,to_das,protected}]. Mengembalikan profile_id baru."""
    for p in params:
        if p.get("status") not in PARAM_STATUSES:
            raise ValueError(f"status parameter tidak dikenal: {p.get('status')}")
    now = now_utc()
    with transaction() as cur:
        cur.execute("SELECT 1 FROM plots WHERE plot_id=%s FOR UPDATE", (plot_id,))          # serialisasi versi per petak
        cur.execute("SELECT COALESCE(MAX(version),0) AS v FROM plot_profile_versions WHERE plot_id=%s", (plot_id,))
        version = int(cur.fetchone()["v"]) + 1
        cur.execute("UPDATE plot_profile_versions SET effective_to=%s WHERE plot_id=%s AND effective_to IS NULL",
                    (now, plot_id))
        cur.execute(
            "INSERT INTO plot_profile_versions (plot_id, version, effective_from, approved_by, note, validation_status, "
            "protocol_version) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING profile_id",
            (plot_id, version, now, actor, note, validation_status, protocol_version))
        pid = int(cur.fetchone()["profile_id"])
        for p in params:
            v = p.get("value")
            v = None if (v is None or (isinstance(v, float) and not math.isfinite(v))) else float(v)
            status = p["status"] if v is not None else "PENDING"
            cur.execute(
                "INSERT INTO plot_parameters (profile_id, name, value, unit, status, source, assessment_method, "
                "checked_by, measured_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (pid, p["name"], v, p.get("unit", ""), status, p.get("source", ""), p.get("assessment_method", ""),
                 p.get("checked_by", actor), p.get("measured_at")))
        for ph in phases:
            cur.execute(
                "INSERT INTO phase_rules (profile_id, phase, from_das, to_das, protected, protocol_version) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (pid, ph["phase"], int(ph["from_das"]), int(ph["to_das"]), bool(ph.get("protected", False)),
                 protocol_version))
    audit("profile_version", f"{plot_id} v{version}", actor, "plot_profile", pid,
          new={"version": version, "validation_status": validation_status, "n_params": len(params)})
    return pid


def get_active_cycle(plot_id):
    rows = db_query("SELECT * FROM crop_cycles WHERE plot_id=%s AND active ORDER BY planting_date DESC LIMIT 1", (plot_id,))
    return rows[0] if rows else None


def list_crop_cycles(plot_id):
    return db_query("SELECT * FROM crop_cycles WHERE plot_id=%s ORDER BY planting_date DESC", (plot_id,))


def add_crop_cycle(plot_id, planting_date, variety, actor):
    with transaction() as cur:
        cur.execute("UPDATE crop_cycles SET active=FALSE WHERE plot_id=%s AND active", (plot_id,))
        cur.execute("INSERT INTO crop_cycles (plot_id, planting_date, variety, created_by) VALUES (%s,%s,%s,%s) "
                    "RETURNING cycle_id", (plot_id, planting_date, variety, actor))
        cid = cur.fetchone()["cycle_id"]
    audit("crop_cycle_add", f"{plot_id} {planting_date}", actor, "crop_cycle", cid)
    return cid


# ----------------------------------------------------------------------------------------------
# observations: h manual
# ----------------------------------------------------------------------------------------------
def add_h_observation(plot_id, value_cm, observed_at, actor, note="", quality_flag="OK", supersedes_id=None):
    """Simpan h manual. observed_at (waktu kejadian) dan received_at (waktu input) dicatat terpisah."""
    obs_utc = as_utc(observed_at)
    with transaction() as cur:
        cur.execute(
            "INSERT INTO observations (plot_id, variable, value, unit, observed_at, received_at, recorded_by, "
            "source_type, quality_flag, note, supersedes_id) VALUES (%s,'h_cm',%s,'cm',%s,NOW(),%s,'MANUAL',%s,%s,%s) "
            "RETURNING obs_id", (plot_id, float(value_cm), obs_utc, actor, quality_flag, note[:500], supersedes_id))
        new_id = int(cur.fetchone()["obs_id"])
        if supersedes_id:
            cur.execute("UPDATE observations SET record_status='SUPERSEDED' WHERE obs_id=%s AND record_status='ACTIVE'",
                        (supersedes_id,))
    audit("h_observation" if not supersedes_id else "h_observation_correct", f"{plot_id}: {value_cm} cm", actor,
          "observation", new_id, new={"plot_id": plot_id, "h_cm": value_cm, "observed_at": obs_utc,
                                      "supersedes_id": supersedes_id})
    return new_id


def void_observation(obs_id, actor, reason):
    rows = db_query("UPDATE observations SET record_status='VOID', note = LEFT(note || ' [VOID: ' || %s || ']', 500) "
                    "WHERE obs_id=%s AND record_status='ACTIVE' RETURNING obs_id, plot_id, value", (reason[:200], obs_id))
    if rows:
        audit("h_observation_void", f"#{obs_id}: {reason[:120]}", actor, "observation", obs_id, old=rows[0])
    return bool(rows)


def list_h_observations(plot_id, limit=100, include_inactive=True):
    cond = "" if include_inactive else "AND record_status='ACTIVE'"
    return db_query(
        f"SELECT obs_id, plot_id, value, observed_at, received_at, recorded_by, quality_flag, note, record_status, "
        f"supersedes_id FROM observations WHERE variable='h_cm' AND plot_id=%s {cond} "
        f"ORDER BY observed_at DESC, obs_id DESC LIMIT %s", (plot_id, int(limit)))


def latest_h(plot_id, not_after=None):
    """Pengamatan h aktif terbaru (menurut waktu kejadian) pada atau sebelum `not_after`."""
    not_after = not_after or now_utc()
    rows = db_query(
        "SELECT obs_id, plot_id, value, observed_at, received_at, recorded_by, quality_flag FROM observations "
        "WHERE variable='h_cm' AND plot_id=%s AND record_status='ACTIVE' AND observed_at <= %s "
        "ORDER BY observed_at DESC, obs_id DESC LIMIT 1", (plot_id, not_after))
    return rows[0] if rows else None


def h_series(plot_id, days=30):
    return db_query(
        "SELECT obs_id, value, observed_at, quality_flag FROM observations WHERE variable='h_cm' AND plot_id=%s "
        "AND record_status='ACTIVE' AND observed_at >= %s ORDER BY observed_at", (plot_id, now_utc() - timedelta(days=days)))


# ----------------------------------------------------------------------------------------------
# observations: sensor (arsip dari data_hub)
# ----------------------------------------------------------------------------------------------
def last_sensor_times():
    rows = db_query("SELECT sensor_id, MAX(observed_at) AS last FROM observations "
                    "WHERE sensor_id IS NOT NULL AND record_status='ACTIVE' GROUP BY sensor_id")
    return {r["sensor_id"]: r["last"] for r in rows}


def archive_sensor_rows(df: pd.DataFrame, since: dict | None = None) -> int:
    """Simpan pembacaan sensor baru (idempoten via ext_key). `since` {sensor_id: waktu UTC terakhir terarsip}
    membatasi baris yang dikirim. Mengembalikan jumlah baris yang dikirim ke DB."""
    if df is None or df.empty:
        return 0
    rows = []
    since = since or {}
    for r in df.itertuples(index=False):
        obs_utc = as_utc(r.timestamp)
        last = since.get(r.sensor_id)
        if last is not None and obs_utc <= last:
            continue
        value = None if pd.isna(r.value) else float(r.value)
        flag = str(r.status or "OK")
        rows.append((None, r.sensor_id, r.sensor_type, value, r.unit or "", obs_utc, "sensor-sheet",
                     r.source_type, flag, f"{r.source_type}:{r.sensor_id}:{obs_utc.isoformat()}",
                     J({"location": r.location, "measurement_mode": r.measurement_mode,
                        "device_id": r.device_id, "sequence": r.sequence})))
    return db.execute_values(
        "INSERT INTO observations (plot_id, sensor_id, variable, value, unit, observed_at, recorded_by, source_type, "
        "quality_flag, ext_key, meta) VALUES %s ON CONFLICT (ext_key) WHERE ext_key IS NOT NULL DO NOTHING", rows)


def load_recent_sensor_frame(days=14) -> pd.DataFrame:
    """Pembacaan sensor terarsip -> DataFrame berskema sama dengan sensor_sheet (untuk awal dingin yang cepat)."""
    rows = db_query(
        "SELECT observed_at, sensor_id, variable, value, unit, quality_flag, source_type, meta FROM observations "
        "WHERE sensor_id IS NOT NULL AND record_status='ACTIVE' AND observed_at >= %s ORDER BY observed_at",
        (now_utc() - timedelta(days=days),))
    cols = ["timestamp", "sensor_id", "sensor_type", "location", "value", "unit", "status", "measurement_mode",
            "device_id", "sequence", "source_type"]
    if not rows:
        return pd.DataFrame(columns=cols)
    out = []
    for r in rows:
        meta = r["meta"] or {}
        out.append((r["observed_at"], r["sensor_id"], r["variable"], r["value"], r["unit"], r["quality_flag"],
                    meta.get("location"), meta.get("measurement_mode"), meta.get("device_id"), meta.get("sequence"),
                    r["source_type"]))
    df = pd.DataFrame(out, columns=["ts", "sensor_id", "sensor_type", "value", "unit", "status", "location",
                                    "measurement_mode", "device_id", "sequence", "source_type"])
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Jakarta").dt.tz_localize(None)
    return df[cols]


# ----------------------------------------------------------------------------------------------
# arsip prakiraan dan ET0 harian
# ----------------------------------------------------------------------------------------------
_FORECAST_VARS = (("temperature", "temperature_c", "°C"), ("humidity", "humidity_pct", "%"),
                  ("wind_speed", "wind_speed_kmh", "km/jam"), ("cloud_cover", "cloud_cover_pct", "%"),
                  ("precipitation_tp", "precipitation_tp", "unspecified"))


def archive_forecast_run(result: dict) -> tuple:
    """Simpan prakiraan per penerbitan (result = hasil fetch_bmkg_forecast). Payload identik (hash sama)
    tidak disimpan ulang. Mengembalikan (run_id, baru:bool)."""
    from et0 import normalize_forecast_rows
    loc = result["adm4"]
    vals = []
    for src in result["rows"]:
        norm = normalize_forecast_rows([src])
        if not norm:
            continue
        valid_utc = norm[0]["utc"]
        for key, var, unit in _FORECAST_VARS:
            try:
                v = float(src.get(key))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                vals.append((valid_utc, var, v, unit))
    with transaction() as cur:
        cur.execute(
            "INSERT INTO weather_forecast_runs (source, location_id, issued_at, fetched_at, payload_hash, raw_payload) "
            "VALUES ('BMKG',%s,%s,%s,%s,%s) ON CONFLICT (location_id, payload_hash) DO NOTHING RETURNING run_id",
            (loc, result.get("issued_at"), result["fetched_at"], result["payload_hash"], J(result.get("raw"))))
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT run_id FROM weather_forecast_runs WHERE location_id=%s AND payload_hash=%s",
                        (loc, result["payload_hash"]))
            return int(cur.fetchone()["run_id"]), False
        run_id = int(row["run_id"])
        import psycopg2.extras
        psycopg2.extras.execute_values(
            cur, "INSERT INTO weather_forecast_values (run_id, valid_at, variable, value, unit) VALUES %s "
                 "ON CONFLICT DO NOTHING", [(run_id, *v) for v in vals], page_size=500)
    return run_id, True


def load_forecast_slots(location_id, since_hours=72):
    """Slot suhu komposit: nilai TERBARU per waktu berlaku dari arsip beberapa penerbitan (untuk hari berjalan)."""
    rows = db_query(
        "SELECT DISTINCT ON (v.valid_at) v.valid_at, v.value AS temp, v.run_id, r.issued_at, r.fetched_at "
        "FROM weather_forecast_values v JOIN weather_forecast_runs r ON r.run_id=v.run_id "
        "WHERE r.location_id=%s AND v.variable='temperature_c' AND v.valid_at >= %s "
        "ORDER BY v.valid_at, r.fetched_at DESC", (location_id, now_utc() - timedelta(hours=since_hours)))
    return rows


def save_et0_daily(plot_id, latitude, series: list, forecast_run_id=None):
    """Simpan ET0 harian prakiraan (terpisah dari ET0 pengamatan). Idempoten per (petak, tanggal, run, config)."""
    if not series:
        return 0
    rows = []
    for e in series:
        rows.append((plot_id, e["date"], forecast_run_id, None, e["temperature_source"], e["method_version"],
                     e["config_hash"], e.get("et0_mm_day"), e.get("tmin"), e.get("tmax"), e.get("n"), e["status"],
                     e.get("reason", "")[:200], latitude))
    return db.execute_values(
        "INSERT INTO et0_daily (plot_id, date, forecast_run_id, observation_snapshot_id, temperature_source, "
        "method_version, config_hash, et0_mm_day, tmin, tmax, n_slots, status, quality, latitude) VALUES %s "
        "ON CONFLICT DO NOTHING", rows)


# ----------------------------------------------------------------------------------------------
# rekomendasi, keputusan, pelaksanaan
# ----------------------------------------------------------------------------------------------
def publish_recommendation(plot_id, created_by, decision_at, snapshot, profile_id, model_version, run_mode,
                           status_code, output, expires_at):
    """Terbitkan rekomendasi (tidak berubah). Yang PUBLISHED lama untuk petak sama menjadi SUPERSEDED."""
    h = inputs_hash(snapshot)
    with transaction() as cur:
        cur.execute("UPDATE recommendation_runs SET status='SUPERSEDED' WHERE plot_id=%s AND status='PUBLISHED'", (plot_id,))
        cur.execute(
            "INSERT INTO recommendation_runs (plot_id, created_by, decision_at, inputs_snapshot, inputs_hash, profile_id, "
            "model_version, run_mode, status_code, output, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING rec_id", (plot_id, created_by, as_utc(decision_at), J(snapshot), h, profile_id, model_version,
                                  run_mode, status_code, J(output), as_utc(expires_at)))
        rec_id = int(cur.fetchone()["rec_id"])
    audit("recommendation_publish", f"{plot_id} #{rec_id} {run_mode}", created_by, "recommendation", rec_id)
    return rec_id


def get_run(rec_id):
    rows = db_query("SELECT * FROM recommendation_runs WHERE rec_id=%s", (int(rec_id),))
    return rows[0] if rows else None


def list_pending_runs(plot_id=None):
    """Rekomendasi PUBLISHED terbaru per petak. Yang melewati expires_at ditandai EXPIRED (bukan dihapus)."""
    db_query("UPDATE recommendation_runs SET status='EXPIRED' WHERE status='PUBLISHED' AND expires_at <= NOW()")
    cond, params = ("AND plot_id=%s", (plot_id,)) if plot_id else ("", ())
    return db_query(f"SELECT * FROM recommendation_runs WHERE status='PUBLISHED' {cond} ORDER BY created_at DESC", params)


def record_decision(rec_id, user, decision, operator_mm, duration_h, note, idempotency_key,
                    duration_verified=False):
    """Catat keputusan operator secara ATOMIK: kunci baris rekomendasi, periksa status/expiry/versi input, tulis
    keputusan, tandai DECIDED. Kunci idempotensi yang sama mengembalikan hasil sebelumnya (klik ganda aman)."""
    with transaction() as cur:
        cur.execute("SELECT id FROM decisions WHERE idempotency_key=%s", (idempotency_key,))
        dup = cur.fetchone()
        if dup:
            return int(dup["id"]), True
        cur.execute("SELECT * FROM recommendation_runs WHERE rec_id=%s FOR UPDATE", (int(rec_id),))
        run = cur.fetchone()
        if not run:
            raise DecisionError("not_found")
        if run["status"] != "PUBLISHED":
            raise DecisionError("already_handled", status=run["status"])
        cur.execute("SELECT NOW() AS now")
        if run["expires_at"] <= cur.fetchone()["now"]:
            cur.execute("UPDATE recommendation_runs SET status='EXPIRED' WHERE rec_id=%s", (int(rec_id),))
            raise DecisionError("expired")
        if run["run_mode"] not in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED"):
            raise DecisionError("not_operational", run_mode=run["run_mode"])
        snap = run["inputs_snapshot"] or {}
        snap_obs = (snap.get("h_observation") or {}).get("obs_id")
        cur.execute("SELECT obs_id FROM observations WHERE variable='h_cm' AND plot_id=%s AND record_status='ACTIVE' "
                    "ORDER BY received_at DESC, obs_id DESC LIMIT 1", (run["plot_id"],))
        newest = cur.fetchone()
        if newest and snap_obs is not None and int(newest["obs_id"]) != int(snap_obs):
            raise DecisionError("inputs_changed")
        out = run["output"] or {}
        cur.execute(
            "INSERT INTO decisions (ts, username, decision, recommended_mm, operator_mm, duration_h, note, source, rec_id, "
            "plot_id, run_mode, idempotency_key, context) VALUES (NOW(),%s,%s,%s,%s,%s,%s,'OPERATIONAL',%s,%s,%s,%s,%s) "
            "RETURNING id",
            (user, decision, out.get("total_mm"), float(operator_mm), None if duration_h is None else float(duration_h),
             (note or "")[:1000], int(rec_id), run["plot_id"], run["run_mode"], idempotency_key,
             J({"duration_verified": bool(duration_verified), "inputs_hash": run["inputs_hash"],
                "profile_id": run["profile_id"]})))
        did = int(cur.fetchone()["id"])
        cur.execute("UPDATE recommendation_runs SET status='DECIDED', decided_at=NOW(), decided_by=%s WHERE rec_id=%s",
                    (user, int(rec_id)))
    audit("decision", f"#{did} rec#{rec_id} {decision} {operator_mm} mm", user, "decision", did)
    return did, False


def list_decisions(limit=200, plot_id=None, only_active=False):
    conds, params = [], []
    if plot_id:
        conds.append("(plot_id=%s OR plot_id IS NULL)")
        params.append(plot_id)
    if only_active:
        conds.append("record_status='ACTIVE'")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    return db_query(
        f"SELECT id, ts, username, decision, recommended_mm, operator_mm, duration_h, note, new_moisture, status, "
        f"edited_by, source, rec_id, plot_id, run_mode, record_status, supersedes_id, void_reason "
        f"FROM decisions {where} ORDER BY ts DESC, id DESC LIMIT %s", (*params, int(limit)))


def supersede_decision(decision_id, actor, decision, operator_mm, duration_h, note, reason):
    """Koreksi keputusan: record baru menggantikan yang lama (yang lama tetap tersimpan, status SUPERSEDED)."""
    with transaction() as cur:
        cur.execute("SELECT * FROM decisions WHERE id=%s FOR UPDATE", (int(decision_id),))
        old = cur.fetchone()
        if not old:
            return None
        if old["record_status"] != "ACTIVE":
            raise DecisionError("not_active")
        cur.execute(
            "INSERT INTO decisions (ts, username, decision, recommended_mm, operator_mm, duration_h, note, source, rec_id, "
            "plot_id, run_mode, supersedes_id, edited_by, edited_at, context) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s) RETURNING id",
            (old["ts"], old["username"], decision, old["recommended_mm"], float(operator_mm),
             None if duration_h is None else float(duration_h), (note or "")[:1000], old["source"], old["rec_id"],
             old["plot_id"], old["run_mode"], int(decision_id), actor, J({"correction_reason": reason})))
        new_id = int(cur.fetchone()["id"])
        cur.execute("UPDATE decisions SET record_status='SUPERSEDED' WHERE id=%s", (int(decision_id),))
    audit("decision_correct", f"#{decision_id} -> #{new_id}: {reason[:120]}", actor, "decision", new_id,
          old={"decision": old["decision"], "operator_mm": old["operator_mm"], "duration_h": old["duration_h"]},
          new={"decision": decision, "operator_mm": operator_mm, "duration_h": duration_h})
    return new_id


def void_decision(decision_id, actor, reason):
    rows = db_query(
        "UPDATE decisions SET record_status='VOID', void_reason=%s, voided_by=%s, voided_at=NOW() "
        "WHERE id=%s AND record_status='ACTIVE' RETURNING id, username, decision, operator_mm", (reason[:300], actor, int(decision_id)))
    if rows:
        audit("decision_void", f"#{decision_id}: {reason[:120]}", actor, "decision", decision_id, old=rows[0])
    return bool(rows)


def decisions_awaiting_execution(plot_id=None):
    cond, params = ("AND d.plot_id=%s", (plot_id,)) if plot_id else ("", ())
    return db_query(
        f"SELECT d.id, d.ts, d.plot_id, d.decision, d.operator_mm, d.duration_h, d.rec_id FROM decisions d "
        f"WHERE d.record_status='ACTIVE' AND d.decision IN ('APPROVE','MODIFY') AND d.source='OPERATIONAL' {cond} "
        f"AND NOT EXISTS (SELECT 1 FROM irrigation_events e WHERE e.decision_id=d.id AND e.record_status='ACTIVE') "
        f"ORDER BY d.ts DESC LIMIT 50", params)


def add_irrigation_event(plot_id, decision_id, rec_id, arrived_at, started_at, ended_at, actual_volume_m3,
                         actual_discharge_m3s, measurement_method, h_after_cm, h_after_at, note, actor,
                         supersedes_id=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO irrigation_events (plot_id, decision_id, rec_id, arrived_at, started_at, ended_at, actual_volume_m3, "
            "actual_discharge_m3s, measurement_method, h_after_cm, h_after_at, note, recorded_by, supersedes_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id",
            (plot_id, decision_id, rec_id, _u(arrived_at), _u(started_at), _u(ended_at), actual_volume_m3,
             actual_discharge_m3s, measurement_method, h_after_cm, _u(h_after_at), note[:500], actor, supersedes_id))
        eid = int(cur.fetchone()["event_id"])
        if supersedes_id:
            cur.execute("UPDATE irrigation_events SET record_status='SUPERSEDED' WHERE event_id=%s", (supersedes_id,))
    audit("irrigation_event", f"{plot_id} event#{eid}", actor, "irrigation_event", eid)
    return eid


def _u(ts):
    return None if ts is None else as_utc(ts)


def void_irrigation_event(event_id, actor, reason):
    rows = db_query("UPDATE irrigation_events SET record_status='VOID', note=LEFT(note || ' [VOID: ' || %s || ']',500) "
                    "WHERE event_id=%s AND record_status='ACTIVE' RETURNING event_id", (reason[:200], int(event_id)))
    if rows:
        audit("irrigation_event_void", f"#{event_id}: {reason[:120]}", actor, "irrigation_event", event_id)
    return bool(rows)


def list_irrigation_events(plot_id=None, limit=100):
    cond, params = ("WHERE plot_id=%s", (plot_id,)) if plot_id else ("", ())
    return db_query(f"SELECT * FROM irrigation_events {cond} ORDER BY COALESCE(arrived_at, recorded_at) DESC LIMIT %s",
                    (*params, int(limit)))


def evaluation_rows(plot_id=None, limit=200):
    """Galat prediksi h saat air tiba vs h terukur: pelaksanaan aktual + rekomendasi + pengamatan h terdekat."""
    cond, params = ("AND e.plot_id=%s", (plot_id,)) if plot_id else ("", ())
    return db_query(
        f"""SELECT e.event_id, e.plot_id, e.arrived_at, e.actual_volume_m3, e.h_after_cm, e.h_after_at,
                   r.rec_id, r.run_mode, (r.output->>'h_arrival_cm')::float AS predicted_h_arrival,
                   (r.output->>'total_mm')::float AS recommended_mm, (r.output->>'volume_m3')::float AS recommended_volume_m3,
                   (SELECT o.value FROM observations o WHERE o.variable='h_cm' AND o.plot_id=e.plot_id
                      AND o.record_status='ACTIVE' AND e.arrived_at IS NOT NULL
                      AND o.observed_at BETWEEN e.arrived_at - INTERVAL '3 hours' AND e.arrived_at + INTERVAL '1 hour'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (o.observed_at - e.arrived_at))) LIMIT 1) AS observed_h_at_arrival
            FROM irrigation_events e LEFT JOIN recommendation_runs r ON r.rec_id = e.rec_id
            WHERE e.record_status='ACTIVE' {cond} ORDER BY e.arrived_at DESC NULLS LAST LIMIT %s""", (*params, int(limit)))
