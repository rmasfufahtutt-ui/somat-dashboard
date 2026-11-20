"""demo_repository.py - penyimpanan RUANG DEMO (SQLite) dengan kontrak yang kompatibel dengan repository.py.

Tidak memerlukan database produksi. Semua baris membawa `is_demo`, `dataset_id`, dan `origin` (SEED = data awal,
USER = diketik/diputuskan pengguna, SCENARIO = dibuat oleh pemilih skenario). Aturan integritas yang sama dengan
operasional (immutable, supersede, VOID, idempotensi, atomik) tetap berlaku; yang berbeda hanya JALURNYA:

* publikasi hanya menerima run_mode == 'DEMO' dan snapshot is_demo (operasional menolak DEMO; di sini sebaliknya);
* keputusan disimpan dengan source='DEMO' (BUKAN 'OPERATIONAL') sehingga tidak pernah tercampur;
* hak akses diperiksa ulang di backend (`demo_mode.require`).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import demo_mode
from repository import DecisionError, PARAM_STATUSES, WIB, as_utc, clean_json, inputs_hash, now_utc  # noqa: F401  (kontrak sama)

_LOCK = threading.RLock()
_PATH = {"p": None}
_READY = {}
SCHEMA_VERSION = 1

TS_COLS = {"created_at", "updated_at", "effective_from", "effective_to", "observed_at", "received_at", "decision_at",
           "expires_at", "decided_at", "ts", "edited_at", "voided_at", "arrived_at", "started_at", "ended_at",
           "h_after_at", "recorded_at", "ts_ingest"}
JSON_COLS = {"inputs_snapshot", "output", "context", "meta", "old_value", "new_value", "metrics", "config", "feature_names"}
BOOL_COLS = {"active", "protected", "ok", "is_demo", "is_simulation"}
DATE_COLS = {"planting_date", "measured_at"}
TS_TABLE_COLS = {  # kolom waktu per tabel (untuk geser waktu demo)
    "plots": ("created_at", "updated_at"), "plot_profile_versions": ("effective_from", "effective_to", "created_at"),
    "crop_cycles": ("created_at",), "observations": ("observed_at", "received_at"),
    "recommendation_runs": ("created_at", "decision_at", "expires_at", "decided_at"),
    "decisions": ("ts", "edited_at", "voided_at"),
    "irrigation_events": ("arrived_at", "started_at", "ended_at", "h_after_at", "recorded_at"),
    "audit_log": ("ts",), "ingest_log": ("ts",)}

DDL = [
    "CREATE TABLE IF NOT EXISTS demo_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS plots (plot_id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL, longitude REAL,
        elevation_m REAL, datum TEXT NOT NULL DEFAULT '', pipe_count INTEGER, pipe_location TEXT NOT NULL DEFAULT '',
        soil_sensor_id TEXT, canal_sensor_id TEXT, rain_source_id TEXT, temp_source_id TEXT,
        coordinate_source TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1, dataset_id TEXT, scenario TEXT, note TEXT DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS plot_profile_versions (profile_id INTEGER PRIMARY KEY AUTOINCREMENT, plot_id TEXT NOT NULL,
        version INTEGER NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT, approved_by TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED',
        protocol_version TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1,
        dataset_id TEXT, origin TEXT NOT NULL DEFAULT 'SEED', UNIQUE (plot_id, version))""",
    """CREATE TABLE IF NOT EXISTS plot_parameters (id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
        name TEXT NOT NULL, value REAL, unit TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'PENDING',
        source TEXT NOT NULL DEFAULT '', assessment_method TEXT NOT NULL DEFAULT '', checked_by TEXT NOT NULL DEFAULT '',
        measured_at TEXT, UNIQUE (profile_id, name))""",
    """CREATE TABLE IF NOT EXISTS crop_cycles (cycle_id INTEGER PRIMARY KEY AUTOINCREMENT, plot_id TEXT NOT NULL,
        planting_date TEXT NOT NULL, variety TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_by TEXT,
        created_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1, dataset_id TEXT, origin TEXT NOT NULL DEFAULT 'SEED')""",
    """CREATE TABLE IF NOT EXISTS phase_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
        phase TEXT NOT NULL, from_das INTEGER NOT NULL, to_das INTEGER NOT NULL, protected INTEGER NOT NULL DEFAULT 0,
        protocol_version TEXT NOT NULL DEFAULT '', UNIQUE (profile_id, phase))""",
    """CREATE TABLE IF NOT EXISTS observations (obs_id INTEGER PRIMARY KEY AUTOINCREMENT, plot_id TEXT, station_id TEXT,
        sensor_id TEXT, variable TEXT NOT NULL, value REAL, unit TEXT NOT NULL DEFAULT '', observed_at TEXT NOT NULL,
        received_at TEXT NOT NULL, recorded_by TEXT, source_type TEXT NOT NULL, quality_flag TEXT NOT NULL DEFAULT 'OK',
        note TEXT NOT NULL DEFAULT '', record_status TEXT NOT NULL DEFAULT 'ACTIVE', supersedes_id INTEGER, ext_key TEXT,
        meta TEXT, void_reason TEXT, method TEXT NOT NULL DEFAULT 'MANUAL', is_demo INTEGER NOT NULL DEFAULT 1,
        dataset_id TEXT, origin TEXT NOT NULL DEFAULT 'SEED')""",
    "CREATE INDEX IF NOT EXISTS ix_obs_var_plot_time ON observations(variable, plot_id, observed_at)",
    """CREATE TABLE IF NOT EXISTS recommendation_runs (rec_id INTEGER PRIMARY KEY AUTOINCREMENT, plot_id TEXT NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL, decision_at TEXT NOT NULL, inputs_snapshot TEXT NOT NULL,
        inputs_hash TEXT NOT NULL, profile_id INTEGER, model_version TEXT NOT NULL DEFAULT '', run_mode TEXT NOT NULL,
        status_code TEXT NOT NULL, output TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PUBLISHED',
        decided_at TEXT, decided_by TEXT, is_demo INTEGER NOT NULL DEFAULT 1, dataset_id TEXT,
        origin TEXT NOT NULL DEFAULT 'SEED')""",
    """CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT NOT NULL,
        decision TEXT NOT NULL, recommended_mm REAL, operator_mm REAL, duration_h REAL, note TEXT NOT NULL DEFAULT '',
        new_moisture REAL, status TEXT, learning_kind TEXT, learning_diff REAL, context TEXT,
        source TEXT NOT NULL DEFAULT 'DEMO', edited_by TEXT, edited_at TEXT, rec_id INTEGER, plot_id TEXT,
        supersedes_id INTEGER, record_status TEXT NOT NULL DEFAULT 'ACTIVE', run_mode TEXT, void_reason TEXT,
        voided_by TEXT, voided_at TEXT, idempotency_key TEXT UNIQUE, is_demo INTEGER NOT NULL DEFAULT 1, dataset_id TEXT,
        origin TEXT NOT NULL DEFAULT 'SEED')""",
    """CREATE TABLE IF NOT EXISTS irrigation_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, plot_id TEXT NOT NULL,
        decision_id INTEGER, rec_id INTEGER, arrived_at TEXT, started_at TEXT, ended_at TEXT, actual_volume_m3 REAL,
        actual_discharge_m3s REAL, measurement_method TEXT NOT NULL DEFAULT '', h_before_cm REAL, h_after_cm REAL,
        h_after_at TEXT, note TEXT NOT NULL DEFAULT '', recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        record_status TEXT NOT NULL DEFAULT 'ACTIVE', supersedes_id INTEGER, is_simulation INTEGER NOT NULL DEFAULT 1,
        is_demo INTEGER NOT NULL DEFAULT 1, dataset_id TEXT, origin TEXT NOT NULL DEFAULT 'SEED')""",
    """CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT NOT NULL,
        action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', entity TEXT, entity_id TEXT, old_value TEXT, new_value TEXT,
        is_demo INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS ingest_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, source TEXT NOT NULL,
        ok INTEGER NOT NULL, rows INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS demo_models (model_id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
        created_by TEXT, dataset_hash TEXT, config TEXT, metrics TEXT, feature_names TEXT, blob BLOB,
        status TEXT NOT NULL DEFAULT 'DEMO_SYNTHETIC')""",
]
DATA_TABLES = ("plots", "plot_profile_versions", "plot_parameters", "crop_cycles", "phase_rules", "observations",
               "recommendation_runs", "decisions", "irrigation_events", "audit_log", "ingest_log")


# ---------------------------------------------------------------------------------------------- koneksi
def configure(path):
    """Tetapkan berkas SQLite demo (tes memakai berkas sementara)."""
    with _LOCK:
        _PATH["p"] = None if path is None else str(path)


def path() -> str:
    if _PATH["p"]:
        return _PATH["p"]
    env = os.environ.get("SOMAT_DEMO_DB")
    if env:
        return env
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".demo_data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "somat_demo.sqlite3")


def _connect():
    p = path()
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(p, timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    if not _READY.get(p):
        with _LOCK:
            for stmt in DDL:
                con.execute(stmt)
            _READY[p] = True
    return con


def _ts(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return as_utc(v).isoformat()


def _de(col, v):
    if v is None:
        return None
    if col in JSON_COLS and isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    if col in TS_COLS and isinstance(v, str):
        try:
            d = datetime.fromisoformat(v)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return v
    if col in DATE_COLS and isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return v
    if col in BOOL_COLS:
        return bool(v)
    return v


def _row(r):
    return {k: _de(k, r[k]) for k in r.keys()} if r is not None else None


def q(sql, params=()):
    """Jalankan SQL dan kembalikan daftar dict (kolom waktu -> datetime berzona UTC, JSON -> dict)."""
    con = _connect()
    try:
        cur = con.execute(sql, params)
        return [_row(r) for r in cur.fetchall()] if cur.description else []
    finally:
        con.close()


@contextmanager
def transaction():
    con = _connect()
    try:
        with _LOCK:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
    finally:
        con.close()


def _one(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return _row(r)


def _j(obj):
    return json.dumps(clean_json(obj), ensure_ascii=False)


# ---------------------------------------------------------------------------------------------- meta
def get_meta(key, default=None):
    rows = q("SELECT value FROM demo_meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def set_meta(key, value):
    con = _connect()
    try:
        con.execute("INSERT INTO demo_meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))
    finally:
        con.close()


def dataset_id():
    return get_meta("dataset_id", "")


def is_loaded() -> bool:
    return bool(get_meta("dataset_id")) and bool(q("SELECT 1 FROM plots LIMIT 1"))


# ---------------------------------------------------------------------------------------------- audit & ingest
def audit(action, detail="", username="-", entity=None, entity_id=None, old=None, new=None):
    try:
        con = _connect()
        try:
            con.execute("INSERT INTO audit_log (ts, username, action, detail, entity, entity_id, old_value, new_value) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (_ts(now_utc()), username or "-", action, str(detail)[:500], entity,
                         None if entity_id is None else str(entity_id),
                         _j(old) if old is not None else None, _j(new) if new is not None else None))
        finally:
            con.close()
    except Exception:
        pass


def fetch_audit(limit=200):
    return q("SELECT ts, username, action, detail FROM audit_log ORDER BY ts DESC, id DESC LIMIT ?", (int(limit),))


def log_ingest(source, ok, rows=0, message=""):
    con = _connect()
    try:
        con.execute("INSERT INTO ingest_log (ts, source, ok, rows, message) VALUES (?,?,?,?,?)",
                    (_ts(now_utc()), source, 1 if ok else 0, int(rows), str(message)[:300]))
    finally:
        con.close()


def recent_ingest(limit=50):
    return q("SELECT ts, source, ok, rows, message FROM ingest_log ORDER BY id DESC LIMIT ?", (int(limit),))


# ---------------------------------------------------------------------------------------------- petak, profil, siklus
def list_plots(active_only=True):
    return q("SELECT * FROM plots " + ("WHERE active=1 " if active_only else "") + "ORDER BY plot_id")


def get_plot(plot_id):
    rows = q("SELECT * FROM plots WHERE plot_id=?", (plot_id,))
    return rows[0] if rows else None


def upsert_plot(plot_id, name, actor, latitude=None, longitude=None, elevation_m=None, datum="", pipe_count=None,
                pipe_location="", soil_sensor_id=None, canal_sensor_id=None, rain_source_id=None, temp_source_id=None,
                coordinate_source="", active=True, scenario=None, note=None):
    """Edit identitas petak demo. Petak yang sudah punya riwayat tidak dihapus: gunakan active=False (arsip)."""
    demo_mode.require("admin")
    before = get_plot(plot_id)
    if before is None and not str(plot_id).startswith("DEMO-"):
        raise ValueError("ID petak demo harus berawalan 'DEMO-'")
    now = _ts(now_utc())
    con = _connect()
    try:
        con.execute(
            """INSERT INTO plots (plot_id, name, latitude, longitude, elevation_m, datum, pipe_count, pipe_location,
                   soil_sensor_id, canal_sensor_id, rain_source_id, temp_source_id, coordinate_source, active, created_at,
                   updated_at, dataset_id, scenario, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(plot_id) DO UPDATE SET name=excluded.name, latitude=excluded.latitude, longitude=excluded.longitude,
                   elevation_m=excluded.elevation_m, datum=excluded.datum, pipe_count=excluded.pipe_count,
                   pipe_location=excluded.pipe_location, soil_sensor_id=excluded.soil_sensor_id,
                   canal_sensor_id=excluded.canal_sensor_id, rain_source_id=excluded.rain_source_id,
                   temp_source_id=excluded.temp_source_id, coordinate_source=excluded.coordinate_source,
                   active=excluded.active, updated_at=excluded.updated_at,
                   scenario=COALESCE(excluded.scenario, plots.scenario), note=COALESCE(excluded.note, plots.note)""",
            (plot_id, name, latitude, longitude, elevation_m, datum, pipe_count, pipe_location, soil_sensor_id or None,
             canal_sensor_id or None, rain_source_id or None, temp_source_id or None, coordinate_source, 1 if active else 0,
             now, now, dataset_id(), scenario, note))
    finally:
        con.close()
    audit("plot_upsert", plot_id, actor, "plot", plot_id, old=before, new={"name": name, "active": active})


def _profile_params(con, profile_id):
    rows = con.execute("SELECT name, value, unit, status, source, assessment_method, checked_by, measured_at "
                       "FROM plot_parameters WHERE profile_id=? ORDER BY name", (profile_id,)).fetchall()
    return {r["name"]: _row(r) for r in rows}


def _phases(con, profile_id):
    return [_row(r) for r in con.execute("SELECT phase, from_das, to_das, protected, protocol_version FROM phase_rules "
                                         "WHERE profile_id=? ORDER BY from_das", (profile_id,)).fetchall()]


def get_active_profile(plot_id, at=None):
    at = _ts(at or now_utc())
    con = _connect()
    try:
        r = con.execute("SELECT * FROM plot_profile_versions WHERE plot_id=? AND effective_from <= ? "
                        "AND (effective_to IS NULL OR effective_to > ?) ORDER BY version DESC LIMIT 1",
                        (plot_id, at, at)).fetchone()
        if not r:
            return None
        p = _row(r)
        p["params"] = _profile_params(con, p["profile_id"])
        p["phases"] = _phases(con, p["profile_id"])
        return p
    finally:
        con.close()


def get_profile_by_id(profile_id):
    con = _connect()
    try:
        r = con.execute("SELECT * FROM plot_profile_versions WHERE profile_id=?", (profile_id,)).fetchone()
        if not r:
            return None
        p = _row(r)
        p["params"] = _profile_params(con, profile_id)
        p["phases"] = _phases(con, profile_id)
        return p
    finally:
        con.close()


def list_profile_versions(plot_id):
    return q("SELECT profile_id, version, effective_from, effective_to, approved_by, note, validation_status, "
             "protocol_version, origin FROM plot_profile_versions WHERE plot_id=? ORDER BY version DESC", (plot_id,))


def save_profile_version(plot_id, params, phases, actor, note="", validation_status="UNVALIDATED",
                         protocol_version="", origin="USER", at=None):
    """Versi profil baru (yang lama ditutup). Parameter demo tidak boleh berstatus CALIBRATED."""
    demo_mode.require("admin")
    for p in params:
        if p.get("status") not in PARAM_STATUSES:
            raise ValueError(f"status parameter tidak dikenal: {p.get('status')}")
        if p.get("status") == "CALIBRATED":
            raise ValueError("parameter demo tidak boleh CALIBRATED (hanya EXAMPLE/LITERATURE/PENDING)")
    now = _ts(at or now_utc())
    with transaction() as con:
        v = con.execute("SELECT COALESCE(MAX(version),0) AS v FROM plot_profile_versions WHERE plot_id=?", (plot_id,)).fetchone()["v"] + 1
        con.execute("UPDATE plot_profile_versions SET effective_to=? WHERE plot_id=? AND effective_to IS NULL", (now, plot_id))
        cur = con.execute("INSERT INTO plot_profile_versions (plot_id, version, effective_from, approved_by, note, validation_status, "
                          "protocol_version, created_at, dataset_id, origin) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (plot_id, v, now, actor, note, "UNVALIDATED", protocol_version, now, dataset_id(), origin))
        pid = cur.lastrowid
        for p in params:
            val = p.get("value")
            val = None if (val is None or (isinstance(val, float) and not math.isfinite(val))) else float(val)
            status = p["status"] if val is not None else "PENDING"
            con.execute("INSERT INTO plot_parameters (profile_id, name, value, unit, status, source, assessment_method, checked_by, measured_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, p["name"], val, p.get("unit", ""), status, p.get("source", ""), p.get("assessment_method", ""),
                         p.get("checked_by", actor), None if p.get("measured_at") is None else str(p["measured_at"])))
        for ph in phases:
            con.execute("INSERT INTO phase_rules (profile_id, phase, from_das, to_das, protected, protocol_version) VALUES (?,?,?,?,?,?)",
                        (pid, ph["phase"], int(ph["from_das"]), int(ph["to_das"]), 1 if ph.get("protected") else 0, protocol_version))
    audit("profile_version", f"{plot_id} v{v}", actor, "plot_profile", pid, new={"version": v, "n_params": len(params)})
    return pid


def get_active_cycle(plot_id):
    rows = q("SELECT * FROM crop_cycles WHERE plot_id=? AND active=1 ORDER BY planting_date DESC LIMIT 1", (plot_id,))
    return rows[0] if rows else None


def list_crop_cycles(plot_id):
    return q("SELECT * FROM crop_cycles WHERE plot_id=? ORDER BY planting_date DESC", (plot_id,))


def add_crop_cycle(plot_id, planting_date, variety, actor, origin="USER"):
    demo_mode.require("admin")
    with transaction() as con:
        con.execute("UPDATE crop_cycles SET active=0 WHERE plot_id=? AND active=1", (plot_id,))
        cur = con.execute("INSERT INTO crop_cycles (plot_id, planting_date, variety, created_by, created_at, dataset_id, origin) "
                          "VALUES (?,?,?,?,?,?,?)", (plot_id, str(planting_date), variety, actor, _ts(now_utc()), dataset_id(), origin))
        cid = cur.lastrowid
    audit("crop_cycle_add", f"{plot_id} {planting_date}", actor, "crop_cycle", cid)
    return cid


# ---------------------------------------------------------------------------------------------- pengamatan
def add_h_observation(plot_id, value_cm, observed_at, actor, note="", quality_flag="OK", supersedes_id=None, origin="USER"):
    """h manual (MANUAL) dengan penanda is_demo. Waktu kejadian dan waktu input terpisah."""
    demo_mode.require("observations")
    obs_utc = _ts(as_utc(observed_at))
    now = _ts(now_utc())
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO observations (plot_id, variable, value, unit, observed_at, received_at, recorded_by, source_type, "
            "quality_flag, note, supersedes_id, method, dataset_id, origin) VALUES (?,'h_cm',?,'cm',?,?,?,'MANUAL',?,?,?,'MANUAL',?,?)",
            (plot_id, float(value_cm), obs_utc, now, actor, quality_flag, note[:500], supersedes_id, dataset_id(), origin))
        new_id = cur.lastrowid
        if supersedes_id:
            con.execute("UPDATE observations SET record_status='SUPERSEDED' WHERE obs_id=? AND record_status='ACTIVE'", (supersedes_id,))
    audit("h_observation" if not supersedes_id else "h_observation_correct", f"{plot_id}: {value_cm} cm", actor, "observation", new_id,
          new={"plot_id": plot_id, "h_cm": value_cm, "observed_at": obs_utc, "supersedes_id": supersedes_id, "is_demo": True})
    return new_id


def void_observation(obs_id, actor, reason):
    demo_mode.require("observations")
    with transaction() as con:
        r = con.execute("SELECT obs_id, plot_id, value FROM observations WHERE obs_id=? AND record_status='ACTIVE'", (obs_id,)).fetchone()
        if not r:
            return False
        con.execute("UPDATE observations SET record_status='VOID', void_reason=?, note=substr(note || ' [VOID: ' || ? || ']', 1, 500) "
                    "WHERE obs_id=?", (reason[:200], reason[:200], obs_id))
    audit("h_observation_void", f"#{obs_id}: {reason[:120]}", actor, "observation", obs_id, old=_row(r))
    return True


def list_h_observations(plot_id, limit=100, include_inactive=True):
    cond = "" if include_inactive else "AND record_status='ACTIVE'"
    return q(f"SELECT obs_id, plot_id, value, observed_at, received_at, recorded_by, quality_flag, note, record_status, "
             f"supersedes_id, void_reason, method, source_type, is_demo, dataset_id, origin FROM observations "
             f"WHERE variable='h_cm' AND plot_id=? {cond} ORDER BY observed_at DESC, obs_id DESC LIMIT ?", (plot_id, int(limit)))


def latest_h(plot_id, not_after=None):
    not_after = _ts(not_after or now_utc())
    rows = q("SELECT obs_id, plot_id, value, observed_at, received_at, recorded_by, quality_flag, source_type, is_demo FROM observations "
             "WHERE variable='h_cm' AND plot_id=? AND record_status='ACTIVE' AND observed_at <= ? "
             "ORDER BY observed_at DESC, obs_id DESC LIMIT 1", (plot_id, not_after))
    return rows[0] if rows else None


def h_series(plot_id, days=30):
    return q("SELECT obs_id, value, observed_at, quality_flag FROM observations WHERE variable='h_cm' AND plot_id=? "
             "AND record_status='ACTIVE' AND observed_at >= ? ORDER BY observed_at", (plot_id, _ts(now_utc() - timedelta(days=days))))


def series(plot_id, variable, days=30):
    """Seri sensor/pengamatan non-h (soil_moisture %, water_level m, rainfall mm) untuk grafik."""
    return q("SELECT value, observed_at, unit, source_type, sensor_id FROM observations WHERE variable=? AND plot_id=? "
             "AND record_status='ACTIVE' AND observed_at >= ? ORDER BY observed_at", (variable, plot_id, _ts(now_utc() - timedelta(days=days))))


def last_sensor_times():
    rows = q("SELECT sensor_id, MAX(observed_at) AS last FROM observations WHERE sensor_id IS NOT NULL AND record_status='ACTIVE' "
             "GROUP BY sensor_id")
    out = {}
    for r in rows:
        v = r["last"]
        out[r["sensor_id"]] = datetime.fromisoformat(v) if isinstance(v, str) else v
    return out


def load_forecast_slots(location_id, since_hours=72, as_of=None):
    """Ruang demo tidak mengarsipkan prakiraan BMKG (sumber asli hanya dari data hub)."""
    return []


# ---------------------------------------------------------------------------------------------- rekomendasi
def _needs_recalc(con, run):
    snap = run.get("inputs_snapshot") or {}
    snap_obs = (snap.get("h_observation") or {}).get("obs_id")
    newest = con.execute("SELECT obs_id FROM observations WHERE variable='h_cm' AND plot_id=? AND record_status='ACTIVE' "
                         "ORDER BY received_at DESC, obs_id DESC LIMIT 1", (run["plot_id"],)).fetchone()
    return bool(newest and snap_obs is not None and int(newest["obs_id"]) != int(snap_obs))


def _profile_changed(con, run):
    """True bila profil parameter aktif petak sudah berbeda dari profil yang dipakai rekomendasi (H13)."""
    if run.get("profile_id") is None:
        return False
    cur = con.execute("SELECT profile_id FROM plot_profile_versions WHERE plot_id=? AND effective_to IS NULL "
                      "ORDER BY version DESC LIMIT 1", (run["plot_id"],)).fetchone()
    return bool(cur and int(cur["profile_id"]) != int(run["profile_id"]))


def publish_recommendation(plot_id, created_by, decision_at, snapshot, profile_id, model_version, run_mode,
                           status_code, output, expires_at, origin="USER"):
    """JALUR PENERBITAN KHUSUS DEMO. Menolak run operasional dan snapshot tanpa penanda is_demo."""
    demo_mode.require("operator")
    if run_mode != "DEMO":
        raise ValueError("ruang demo hanya menerima run_mode 'DEMO'")
    if not (isinstance(snapshot, dict) and snapshot.get("is_demo") is True):
        raise ValueError("snapshot rekomendasi demo harus bertanda is_demo=True")
    h = inputs_hash(snapshot)
    with transaction() as con:
        con.execute("UPDATE recommendation_runs SET status='SUPERSEDED' WHERE plot_id=? AND status='PUBLISHED'", (plot_id,))
        cur = con.execute(
            "INSERT INTO recommendation_runs (plot_id, created_at, created_by, decision_at, inputs_snapshot, inputs_hash, profile_id, "
            "model_version, run_mode, status_code, output, expires_at, dataset_id, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plot_id, _ts(now_utc()), created_by, _ts(decision_at), _j(snapshot), h, profile_id, model_version, run_mode, status_code,
             _j(output), _ts(expires_at), dataset_id(), origin))
        rec_id = cur.lastrowid
    audit("recommendation_publish", f"{plot_id} #{rec_id} DEMO", created_by, "recommendation", rec_id)
    return rec_id


def get_run(rec_id):
    rows = q("SELECT * FROM recommendation_runs WHERE rec_id=?", (int(rec_id),))
    return rows[0] if rows else None


def list_pending_runs(plot_id=None):
    now = _ts(now_utc())
    con = _connect()
    try:
        con.execute("UPDATE recommendation_runs SET status='EXPIRED' WHERE status='PUBLISHED' AND expires_at <= ?", (now,))
        cond, params = ("AND plot_id=?", (plot_id,)) if plot_id else ("", ())
        rows = [_row(r) for r in con.execute(f"SELECT * FROM recommendation_runs WHERE status='PUBLISHED' {cond} "
                                             f"ORDER BY created_at DESC", params).fetchall()]
        for r in rows:
            r["needs_recalc"] = _needs_recalc(con, r)
        return rows
    finally:
        con.close()


def list_runs(limit=100, plot_id=None):
    """Riwayat rekomendasi semua status (untuk evaluasi/ekspor)."""
    cond, params = ("WHERE plot_id=?", (plot_id,)) if plot_id else ("", ())
    return q(f"SELECT * FROM recommendation_runs {cond} ORDER BY created_at DESC, rec_id DESC LIMIT ?", (*params, int(limit)))


def record_decision(rec_id, user, decision, operator_mm, duration_h, note, idempotency_key, duration_verified=False, origin="USER"):
    """Keputusan simulasi, ATOMIK dan idempoten. Disimpan dengan source='DEMO' (bukan OPERATIONAL)."""
    try:
        demo_mode.require("operator")
    except PermissionError:
        raise DecisionError("forbidden")
    if decision not in ("APPROVE", "MODIFY", "DELAY"):
        raise DecisionError("bad_decision")
    with transaction() as con:
        dup = con.execute("SELECT id FROM decisions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if dup:
            return int(dup["id"]), True
        run = _one(con, "SELECT * FROM recommendation_runs WHERE rec_id=?", (int(rec_id),))
        if not run:
            raise DecisionError("not_found")
        if run["status"] != "PUBLISHED":
            raise DecisionError("already_handled", status=run["status"])
        if run["expires_at"] <= now_utc():
            con.execute("UPDATE recommendation_runs SET status='EXPIRED' WHERE rec_id=?", (int(rec_id),))
            con.execute("COMMIT")
            con.execute("BEGIN IMMEDIATE")
            raise DecisionError("expired")
        if run["run_mode"] != "DEMO" or not (run["inputs_snapshot"] or {}).get("is_demo"):
            raise DecisionError("not_demo", run_mode=run["run_mode"])
        if _profile_changed(con, run):
            raise DecisionError("profile_changed")
        if _needs_recalc(con, run):
            raise DecisionError("inputs_changed")
        out = run["output"] or {}
        rec_mm = out.get("total_mm")
        if decision == "APPROVE" and (not out.get("irrigate") or rec_mm is None or abs(float(operator_mm) - float(rec_mm)) > 0.05):
            raise DecisionError("approve_invalid")
        if decision == "MODIFY":
            if not out.get("irrigate") or rec_mm is None:
                raise DecisionError("approve_invalid")
            if not (0 <= float(operator_mm) <= 1000):
                raise DecisionError("bad_amount")
            if abs(float(operator_mm) - float(rec_mm)) < 0.1 - 1e-12:
                raise DecisionError("amount_unchanged")
        cur = con.execute(
            "INSERT INTO decisions (ts, username, decision, recommended_mm, operator_mm, duration_h, note, source, rec_id, plot_id, "
            "run_mode, idempotency_key, context, dataset_id, origin) VALUES (?,?,?,?,?,?,?,'DEMO',?,?,?,?,?,?,?)",
            (_ts(now_utc()), user, decision, rec_mm, float(operator_mm), None if duration_h is None else float(duration_h),
             (note or "")[:1000], int(rec_id), run["plot_id"], run["run_mode"], idempotency_key,
             _j({"duration_verified": bool(duration_verified), "inputs_hash": run["inputs_hash"], "profile_id": run["profile_id"],
                 "simulation": True, "needs_reevaluation": decision == "DELAY"}), dataset_id(), origin))
        did = cur.lastrowid
        con.execute("UPDATE recommendation_runs SET status='DECIDED', decided_at=?, decided_by=? WHERE rec_id=?",
                    (_ts(now_utc()), user, int(rec_id)))
    audit("decision", f"DEMO #{did} rec#{rec_id} {decision} {operator_mm} mm", user, "decision", did)
    return did, False


def list_decisions(limit=200, plot_id=None, only_active=False):
    conds, params = [], []
    if plot_id:
        conds.append("(plot_id=? OR plot_id IS NULL)")
        params.append(plot_id)
    if only_active:
        conds.append("record_status='ACTIVE'")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    return q(f"SELECT id, ts, username, decision, recommended_mm, operator_mm, duration_h, note, new_moisture, status, edited_by, "
             f"source, rec_id, plot_id, run_mode, record_status, supersedes_id, void_reason, context, is_demo, dataset_id, origin "
             f"FROM decisions {where} ORDER BY ts DESC, id DESC LIMIT ?", (*params, int(limit)))


def supersede_decision(decision_id, actor, decision, operator_mm, duration_h, note, reason):
    try:
        demo_mode.require("operator")
    except PermissionError:
        raise DecisionError("forbidden")
    with transaction() as con:
        old = _one(con, "SELECT * FROM decisions WHERE id=?", (int(decision_id),))
        if not old:
            return None
        if old["record_status"] != "ACTIVE":
            raise DecisionError("not_active")
        if not demo_mode.can("admin") and old["username"] != actor:
            raise DecisionError("forbidden")
        cur = con.execute(
            "INSERT INTO decisions (ts, username, decision, recommended_mm, operator_mm, duration_h, note, source, rec_id, plot_id, "
            "run_mode, supersedes_id, edited_by, edited_at, context, dataset_id, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_ts(old["ts"]), old["username"], decision, old["recommended_mm"], float(operator_mm),
             None if duration_h is None else float(duration_h), (note or "")[:1000], old["source"], old["rec_id"], old["plot_id"],
             old["run_mode"], int(decision_id), actor, _ts(now_utc()), _j({"correction_reason": reason, "simulation": True}),
             dataset_id(), "USER"))
        new_id = cur.lastrowid
        con.execute("UPDATE decisions SET record_status='SUPERSEDED' WHERE id=?", (int(decision_id),))
    audit("decision_correct", f"DEMO #{decision_id} -> #{new_id}: {reason[:120]}", actor, "decision", new_id,
          old={"decision": old["decision"], "operator_mm": old["operator_mm"], "duration_h": old["duration_h"]},
          new={"decision": decision, "operator_mm": operator_mm, "duration_h": duration_h})
    return new_id


def void_decision(decision_id, actor, reason):
    demo_mode.require("admin")
    with transaction() as con:
        r = con.execute("SELECT id, username, decision, operator_mm FROM decisions WHERE id=? AND record_status='ACTIVE'",
                        (int(decision_id),)).fetchone()
        if not r:
            return False
        con.execute("UPDATE decisions SET record_status='VOID', void_reason=?, voided_by=?, voided_at=? WHERE id=?",
                    (reason[:300], actor, _ts(now_utc()), int(decision_id)))
    audit("decision_void", f"DEMO #{decision_id}: {reason[:120]}", actor, "decision", decision_id, old=_row(r))
    return True


def decisions_awaiting_execution(plot_id=None):
    cond, params = ("AND d.plot_id=?", (plot_id,)) if plot_id else ("", ())
    return q(f"SELECT d.id, d.ts, d.plot_id, d.decision, d.operator_mm, d.duration_h, d.rec_id FROM decisions d "
             f"WHERE d.record_status='ACTIVE' AND d.decision IN ('APPROVE','MODIFY') AND d.source='DEMO' {cond} "
             f"AND NOT EXISTS (SELECT 1 FROM irrigation_events e WHERE e.decision_id=d.id AND e.record_status='ACTIVE') "
             f"ORDER BY d.ts DESC LIMIT 50", params)


# ---------------------------------------------------------------------------------------------- pelaksanaan simulasi
def add_irrigation_event(plot_id, decision_id, rec_id, arrived_at, started_at, ended_at, actual_volume_m3,
                         actual_discharge_m3s, measurement_method, h_after_cm, h_after_at, note, actor,
                         supersedes_id=None, h_before_cm=None, origin="USER"):
    demo_mode.require("execution")
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO irrigation_events (plot_id, decision_id, rec_id, arrived_at, started_at, ended_at, actual_volume_m3, "
            "actual_discharge_m3s, measurement_method, h_before_cm, h_after_cm, h_after_at, note, recorded_by, recorded_at, "
            "supersedes_id, dataset_id, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plot_id, decision_id, rec_id, _ts(arrived_at), _ts(started_at), _ts(ended_at), actual_volume_m3, actual_discharge_m3s,
             measurement_method, h_before_cm, h_after_cm, _ts(h_after_at), note[:500], actor, _ts(now_utc()), supersedes_id,
             dataset_id(), origin))
        eid = cur.lastrowid
        if supersedes_id:
            con.execute("UPDATE irrigation_events SET record_status='SUPERSEDED' WHERE event_id=?", (supersedes_id,))
    audit("irrigation_event", f"DEMO {plot_id} event#{eid} (simulasi)", actor, "irrigation_event", eid)
    return eid


def void_irrigation_event(event_id, actor, reason):
    demo_mode.require("execution")
    with transaction() as con:
        r = con.execute("SELECT event_id FROM irrigation_events WHERE event_id=? AND record_status='ACTIVE'", (int(event_id),)).fetchone()
        if not r:
            return False
        con.execute("UPDATE irrigation_events SET record_status='VOID', note=substr(note || ' [VOID: ' || ? || ']', 1, 500) WHERE event_id=?",
                    (reason[:200], int(event_id)))
    audit("irrigation_event_void", f"DEMO #{event_id}: {reason[:120]}", actor, "irrigation_event", event_id)
    return True


def list_irrigation_events(plot_id=None, limit=100):
    cond, params = ("WHERE plot_id=?", (plot_id,)) if plot_id else ("", ())
    return q(f"SELECT * FROM irrigation_events {cond} ORDER BY COALESCE(arrived_at, recorded_at) DESC LIMIT ?", (*params, int(limit)))


def evaluation_rows(plot_id=None, limit=200):
    """Prediksi h saat air tiba vs h terukur (simulasi) + rantai rekomendasi -> keputusan -> pelaksanaan."""
    events = [e for e in list_irrigation_events(plot_id, limit) if e["record_status"] == "ACTIVE"]
    out = []
    for e in events:
        run = get_run(e["rec_id"]) if e.get("rec_id") else None
        o = (run or {}).get("output") or {}
        dec = q("SELECT id, decision, operator_mm, duration_h, record_status FROM decisions WHERE id=?", (e["decision_id"],)) if e.get("decision_id") else []
        obs = None
        if e.get("arrived_at"):
            t0 = _ts(e["arrived_at"] - timedelta(hours=3))
            t1 = _ts(e["arrived_at"] + timedelta(hours=1))
            cand = q("SELECT value, observed_at FROM observations WHERE variable='h_cm' AND plot_id=? AND record_status='ACTIVE' "
                     "AND observed_at BETWEEN ? AND ?", (e["plot_id"], t0, t1))
            if cand:
                obs = min(cand, key=lambda c: abs((c["observed_at"] - e["arrived_at"]).total_seconds()))["value"]
        out.append({"event_id": e["event_id"], "plot_id": e["plot_id"], "arrived_at": e["arrived_at"],
                    "actual_volume_m3": e["actual_volume_m3"], "h_before_cm": e.get("h_before_cm"), "h_after_cm": e["h_after_cm"],
                    "h_after_at": e["h_after_at"], "rec_id": e.get("rec_id"), "run_mode": (run or {}).get("run_mode"),
                    "predicted_h_arrival": o.get("h_arrival_cm"), "recommended_mm": o.get("total_mm"),
                    "recommended_volume_m3": o.get("volume_m3"), "recommended_duration_h": o.get("duration_h"),
                    "observed_h_at_arrival": obs if obs is not None else e.get("h_before_cm"),
                    "h_source": "OBSERVATION" if obs is not None else "EXECUTION_RECORD", "decision": dec[0]["decision"] if dec else None,
                    "decision_mm": dec[0]["operator_mm"] if dec else None, "decision_duration_h": dec[0]["duration_h"] if dec else None,
                    "actual_duration_h": ((e["ended_at"] - e["started_at"]).total_seconds() / 3600.0) if e.get("ended_at") and e.get("started_at") else None})
    return out


# ---------------------------------------------------------------------------------------------- model demo
def save_model(model_id, kind, created_by, dataset_hash, config, metrics, feature_names, blob, status="DEMO_SYNTHETIC"):
    demo_mode.require("admin")
    con = _connect()
    try:
        con.execute("UPDATE demo_models SET status='SUPERSEDED' WHERE status != 'SUPERSEDED' AND kind=?", (kind,))
        con.execute("INSERT OR REPLACE INTO demo_models (model_id, kind, created_at, created_by, dataset_hash, config, metrics, feature_names, blob, status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (model_id, kind, _ts(now_utc()), created_by, dataset_hash, _j(config), _j(metrics), _j(feature_names), blob, status))
    finally:
        con.close()
    audit("demo_model_train", f"{kind} {model_id}", created_by, "model", model_id)


def get_model(kind="RF_RESIDUAL"):
    rows = q("SELECT * FROM demo_models WHERE kind=? AND status != 'SUPERSEDED' ORDER BY created_at DESC LIMIT 1", (kind,))
    return rows[0] if rows else None


# ---------------------------------------------------------------------------------------------- pemeliharaan (hanya demo)
def count_user_rows() -> dict:
    """Jumlah perubahan yang dibuat pengguna/pemilih skenario (bukan data awal)."""
    out = {}
    for t in ("observations", "recommendation_runs", "decisions", "irrigation_events", "plot_profile_versions", "crop_cycles"):
        out[t] = q(f"SELECT COUNT(*) AS n FROM {t} WHERE origin != 'SEED'")[0]["n"]
    return out


def is_dirty() -> bool:
    return sum(count_user_rows().values()) > 0


def wipe(keep_models=False):
    """Hapus SELURUH isi ruang demo (hanya berkas SQLite demo). Tidak menyentuh database operasional."""
    demo_mode.require("admin")
    with transaction() as con:
        for t in DATA_TABLES:
            con.execute(f"DELETE FROM {t}")
            con.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))
        con.execute("DELETE FROM demo_meta")
        if not keep_models:
            con.execute("DELETE FROM demo_models")


def bulk_insert(table, rows):
    """Penyisipan massal (seed). rows: daftar dict; nilai datetime/dict dikonversi."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    marks = ",".join("?" * len(cols))
    data = []
    for r in rows:
        data.append(tuple(_ts(r[c]) if c in TS_COLS else (_j(r[c]) if c in JSON_COLS and not isinstance(r[c], str) and r[c] is not None
                                                         else (str(r[c]) if c in DATE_COLS and r[c] is not None else r[c]))
                          for c in cols))
    with transaction() as con:
        con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({marks})", data)
    return len(data)


def shift_times(delta: timedelta):
    """Geser SEMUA waktu data demo sebesar delta (menjaga hubungan antar-catatan). Hanya ruang demo."""
    demo_mode.require("admin")
    with transaction() as con:
        for t, cols in TS_TABLE_COLS.items():
            for c in cols:
                rows = con.execute(f"SELECT rowid AS rid, {c} AS v FROM {t} WHERE {c} IS NOT NULL").fetchall()
                con.executemany(f"UPDATE {t} SET {c}=? WHERE rowid=?",
                                [(_ts(datetime.fromisoformat(r["v"]) + delta), r["rid"]) for r in rows])
        # tanggal tanam ikut bergeser agar DAS (hari setelah tanam) tetap sama
        rows = con.execute("SELECT cycle_id, planting_date FROM crop_cycles").fetchall()
        con.executemany("UPDATE crop_cycles SET planting_date=? WHERE cycle_id=?",
                        [(str(date.fromisoformat(r["planting_date"][:10]) + timedelta(days=round(delta.total_seconds() / 86400))), r["cycle_id"])
                         for r in rows])


def export_all() -> dict:
    """Seluruh data + riwayat demo (JSON-serializable) untuk diunduh."""
    out = {"exported_at": _ts(now_utc()), "dataset_id": dataset_id(), "meta": {r["key"]: r["value"] for r in q("SELECT key, value FROM demo_meta")},
           "label": "DEMO PENELITIAN — data sintetis, bukan hasil penelitian"}
    for t in DATA_TABLES:
        out[t] = clean_json(q(f"SELECT * FROM {t}"))
    out["demo_models"] = clean_json([{k: v for k, v in r.items() if k != "blob"} for r in q("SELECT * FROM demo_models")])
    return out


# ---------------------------------------------------------------------------------------------- tidak dipakai di demo
def archive_sensor_rows(df, since=None) -> int:
    return 0  # sensor demo = baris sintetis di tabel observations; sumber asli tidak diarsipkan ke ruang demo


def load_recent_sensor_frame(days=14):
    import pandas as pd
    return pd.DataFrame()


def archive_forecast_run(result):
    return (None, 0)


def save_et0_daily(plot_id, latitude, series, forecast_run_id=None):
    return None
