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
import rights
from db import db_query, transaction
from physics_engine import decision_blockers

try:
    from psycopg2.extras import Json
except Exception:                                  # pragma: no cover
    Json = None

WIB = timezone(timedelta(hours=7))
PARAM_STATUSES = ("CALIBRATED", "LITERATURE", "EXAMPLE", "PENDING")
SENSOR_VARIABLE_UNITS = {"soil_moisture": "%", "water_level": "m", "rainfall": "mm"}


def _owner_of(table, id_col, id_, user_col):
    """Pemilik rekaman (untuk aturan koreksi/VOID: pemilik atau admin). None bila rekaman tidak ada."""
    if id_ is None:
        return None
    rows = db_query(f"SELECT {user_col} AS u FROM {table} WHERE {id_col}=%s", (int(id_),))
    return rows[0]["u"] if rows else None


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
    rights.authorize("plot.upsert", actor)
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
    rights.authorize("profile.save", actor)
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
    rights.authorize("cycle.add", actor)
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
    if supersedes_id:
        rights.authorize("observation.correct", actor, _owner_of("observations", "obs_id", supersedes_id, "recorded_by"))
    else:
        rights.authorize("observation.add", actor)
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
    rights.authorize("observation.void", actor, _owner_of("observations", "obs_id", obs_id, "recorded_by"))
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


def sensor_ext_key(source_type, sensor_id, obs_utc) -> str:
    return f"{source_type}:{sensor_id}:{obs_utc.isoformat()}"


def build_sensor_archive_rows(df: pd.DataFrame, since: dict | None = None) -> list:
    """Baris NILAI MENTAH siap-simpan (tanpa DB). quality_flag = status perangkat apa adanya (OK/ERROR/...); TIDAK ada hasil QC di
    baris ini: QC disimpan terpisah, berversi, di observation_qc (H07). Nilai mentah tidak diubah."""
    if df is None or df.empty:
        return []
    rows = []
    since = since or {}
    for r in df.itertuples(index=False):
        obs_utc = as_utc(r.timestamp)
        last = since.get(r.sensor_id)
        if last is not None and obs_utc <= last:
            continue
        value = None if pd.isna(r.value) else float(r.value)
        flag = str(r.status or "OK").upper()
        rows.append((None, r.sensor_id, r.sensor_type, value, r.unit or "", obs_utc, "sensor-sheet",
                     r.source_type, flag, sensor_ext_key(r.source_type, r.sensor_id, obs_utc),
                     J({"location": r.location, "measurement_mode": r.measurement_mode,
                        "device_id": r.device_id, "sequence": r.sequence})))
    return rows


def _qc_eval_rows(ext_key, qc_type, codes, rv, now, basis):
    """Satu evaluasi -> baris per reason_code (atau satu baris 'NONE' bila lolos)."""
    import sensor_qc
    if not codes:
        return [(ext_key, qc_type, "OK", "NONE", "USE", rv, now, now, basis)]
    return [(ext_key, qc_type, sensor_qc.CODES[c][0], c, sensor_qc.CODES[c][1], rv, now, now, basis) for c in sorted(codes)]


def plan_qc_rows(df: pd.DataFrame, stored: dict, new_keys: set, now: datetime, rules: dict | None = None) -> list:
    """Rencana baris observation_qc (tanpa DB), idempoten terhadap evaluasi yang sudah tersimpan.
      df     : seluruh jendela yang diterima (agar tetangga tersedia);  stored: {ext_key: frozenset(kode)} evaluasi TERAKHIR;
      new_keys: ext_key baris yang baru masuk pada pengiriman ini;  now: waktu informasi ini tersedia (= evaluated_at = available_at).
    Aturan: titik baru tanpa evaluasi -> ONLINE (informasi sampai titik itu). Titik tanpa evaluasi tersimpan yang bukan baru
    (sebelum migrasi) -> RETROSPECTIVE. Sesudah itu, bila penilaian retrospektif (jendela penuh) berbeda dari evaluasi terakhir,
    tambahkan evaluasi RETROSPECTIVE baru. Evaluasi lama tidak diubah. available_at = now: tidak pernah lebih awal dari saat
    informasi itu benar-benar ada, sehingga keputusan historis tidak berubah."""
    if df is None or df.empty:
        return []
    import sensor_qc
    rv = sensor_qc.rule_version(rules)
    retro = sensor_qc.assess(df, rules).reset_index(drop=True)
    online = sensor_qc.assess_asof(df, rules).reset_index(drop=True)
    out = []
    for i, r in enumerate(retro.itertuples(index=False)):
        key = sensor_ext_key(r.source_type, r.sensor_id, as_utc(r.timestamp))
        a = frozenset(c for c in str(r.qc_codes or "").split(",") if c)
        b = frozenset(c for c in str(online["qc_codes"].iloc[i] or "").split(",") if c)
        last = stored.get(key)
        if last is None:
            if key in new_keys:
                out += _qc_eval_rows(key, "ONLINE", b, rv, now, {"basis": "info up to this reading"})
                last = b
            else:
                out += _qc_eval_rows(key, "RETROSPECTIVE", a, rv, now, {"basis": "baseline, no earlier QC stored"})
                continue
        if a != last:
            out += _qc_eval_rows(key, "RETROSPECTIVE", a, rv, now, {"basis": "full window incl. later neighbours"})
    return out


_QC_INSERT = ("INSERT INTO observation_qc (obs_id, qc_type, qc_flag, reason_code, action, rule_version, evaluated_at, available_at, meta) "
              "SELECT o.obs_id, v.qc_type, v.qc_flag, v.reason_code, v.action, v.rule_version, v.evaluated_at::timestamptz, "
              "v.available_at::timestamptz, v.meta::jsonb FROM (VALUES %s) AS v(ext_key, qc_type, qc_flag, reason_code, action, "
              "rule_version, evaluated_at, available_at, meta) JOIN observations o ON o.ext_key = v.ext_key "
              "ON CONFLICT DO NOTHING")


def latest_qc_codes(ext_keys: list) -> dict:
    """{ext_key: frozenset(kode)} dari evaluasi TERAKHIR per pengamatan (retrospektif menang atas online bila waktu sama)."""
    if not ext_keys:
        return {}
    rows = db_query(
        "WITH latest AS (SELECT DISTINCT ON (q.obs_id) q.obs_id, q.available_at, q.qc_type FROM observation_qc q "
        "JOIN observations o ON o.obs_id = q.obs_id WHERE o.ext_key = ANY(%s) "
        "ORDER BY q.obs_id, q.available_at DESC, (q.qc_type = 'RETROSPECTIVE') DESC) "
        "SELECT o.ext_key, q.reason_code FROM latest l JOIN observation_qc q ON q.obs_id = l.obs_id "
        "AND q.available_at = l.available_at AND q.qc_type = l.qc_type JOIN observations o ON o.obs_id = l.obs_id",
        (list(ext_keys),))
    out: dict = {}
    for r in rows:
        out.setdefault(r["ext_key"], set())
        if r["reason_code"] != "NONE":
            out[r["ext_key"]].add(r["reason_code"])
    return {k: frozenset(v) for k, v in out.items()}


def archive_sensor_rows(df: pd.DataFrame, since: dict | None = None, now: datetime | None = None) -> int:
    """Simpan pembacaan sensor baru (idempoten via ext_key) lalu hasil QC-nya di observation_qc. `since` {sensor_id: waktu UTC
    terakhir terarsip} membatasi baris yang dikirim. Mengembalikan jumlah baris mentah yang dikirim ke DB."""
    rows = build_sensor_archive_rows(df, since)
    if not rows:
        return 0
    n = db.execute_values(
        "INSERT INTO observations (plot_id, sensor_id, variable, value, unit, observed_at, recorded_by, source_type, "
        "quality_flag, ext_key, meta) VALUES %s ON CONFLICT (ext_key) WHERE ext_key IS NOT NULL DO NOTHING", rows)
    now = now or now_utc()
    keys = [sensor_ext_key(r.source_type, r.sensor_id, as_utc(r.timestamp)) for r in df.itertuples(index=False)]
    qc = plan_qc_rows(df, latest_qc_codes(keys), {r[9] for r in rows}, now)
    if qc:
        db.execute_values(_QC_INSERT, [q[:8] + (json.dumps(q[8]),) for q in qc])
    return n


def load_qc_asof(as_of: datetime, since: datetime | None = None, sensor_id: str | None = None) -> list:
    """Penilaian QC yang TERSEDIA pada `as_of` (available_at <= as_of), satu dict per pengamatan: evaluasi dengan available_at
    terbesar menang (retrospektif menang atas online bila sama). Penilaian yang baru tersedia sesudah as_of tidak ikut."""
    rows = db_query(
        "WITH ranked AS (SELECT q.*, dense_rank() OVER (PARTITION BY q.obs_id ORDER BY q.available_at DESC, "
        "(q.qc_type = 'RETROSPECTIVE') DESC) AS rk FROM observation_qc q WHERE q.available_at <= %s) "
        "SELECT r.obs_id, o.ext_key, o.sensor_id, o.observed_at, r.qc_type, r.qc_flag, r.reason_code, r.action, r.rule_version, "
        "r.evaluated_at, r.available_at FROM ranked r JOIN observations o ON o.obs_id = r.obs_id WHERE r.rk = 1 "
        "AND (%s::timestamptz IS NULL OR o.observed_at >= %s) AND (%s::text IS NULL OR o.sensor_id = %s) "
        "ORDER BY o.observed_at, r.obs_id", (as_of, since, since, sensor_id, sensor_id))
    order = {"USE": 0, "USE_WITH_WARNING": 1, "EXCLUDE_FROM_AUTOMATIC_USE": 2}
    flags = {"OK": 0, "SUSPECT": 1, "BAD": 2}
    by: dict = {}
    for r in rows:
        d = by.setdefault(r["obs_id"], {"obs_id": r["obs_id"], "ext_key": r["ext_key"], "sensor_id": r["sensor_id"],
                                        "observed_at": r["observed_at"], "qc_type": r["qc_type"], "qc_flag": "OK",
                                        "action": "USE", "reasons": [], "rule_version": r["rule_version"],
                                        "evaluated_at": r["evaluated_at"], "available_at": r["available_at"]})
        if r["reason_code"] != "NONE":
            d["reasons"].append(r["reason_code"])
        if flags[r["qc_flag"]] > flags[d["qc_flag"]]:
            d["qc_flag"] = r["qc_flag"]
        if order[r["action"]] > order[d["action"]]:
            d["action"] = r["action"]
    return list(by.values())


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


def load_forecast_slots(location_id, since_hours=72, as_of=None):
    """Slot suhu komposit dari arsip penerbitan, DIKUNCI pada waktu keputusan (`as_of`, default sekarang): hanya penerbitan yang
    sudah tersedia saat itu (fetched_at <= as_of dan, bila ada, issued_at <= as_of). Nilai TERBARU yang tersedia per waktu berlaku
    menang. Tiap baris membawa provenansi penerbitan (run_id, issued_at, fetched_at) agar replay evaluasi historis dapat diaudit.
    Suhu prakiraan masa lalu yang diarsipkan BUKAN pengamatan suhu."""
    t = as_utc(as_of) if as_of is not None else now_utc()
    rows = db_query(
        "SELECT DISTINCT ON (v.valid_at) v.valid_at, v.value AS temp, v.run_id, r.issued_at, r.fetched_at "
        "FROM weather_forecast_values v JOIN weather_forecast_runs r ON r.run_id=v.run_id "
        "WHERE r.location_id=%s AND v.variable='temperature_c' AND v.valid_at >= %s "
        "AND r.fetched_at <= %s AND (r.issued_at IS NULL OR r.issued_at <= %s) "
        "ORDER BY v.valid_at, r.fetched_at DESC, r.run_id DESC", (location_id, t - timedelta(hours=since_hours), t, t))
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
    keputusan, tandai DECIDED. Kunci idempotensi yang sama mengembalikan hasil sebelumnya (klik ganda aman).
    Hak pengguna diperiksa di sini (backend), sebelum database disentuh."""
    rights.authorize("decision.record", user)
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
        snap = run["inputs_snapshot"] or {}
        cur.execute("SELECT profile_id FROM plot_profile_versions WHERE plot_id=%s AND effective_to IS NULL "
                    "ORDER BY version DESC LIMIT 1", (run["plot_id"],))
        cur_prof = cur.fetchone()
        profile_changed = bool(run.get("profile_id") is not None and cur_prof
                               and int(cur_prof["profile_id"]) != int(run["profile_id"]))
        blockers = decision_blockers(run_mode=run["run_mode"], status_code=run.get("status_code"),
                                     profile_changed=profile_changed)
        if blockers:
            raise DecisionError(blockers[0], run_mode=run["run_mode"], status_code=run.get("status_code"))
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
    rights.authorize("decision.correct", actor, _owner_of("decisions", "id", decision_id, "username"))
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
    rights.authorize("decision.void", actor)
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
    if supersedes_id:
        rights.authorize("execution.correct", actor, _owner_of("irrigation_events", "event_id", supersedes_id, "recorded_by"))
    else:
        rights.authorize("execution.add", actor)
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
    rights.authorize("execution.void", actor, _owner_of("irrigation_events", "event_id", event_id, "recorded_by"))
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


# ====================================================================================================== H14: state bias adaptif
class BiasConfigError(Exception):
    """Konfigurasi bias tidak sah untuk jalur riset/operasional, atau berbeda dari yang sudah dibekukan untuk (petak, model)."""


def _cfg_dict(cfg) -> dict:
    return {"alpha": cfg.alpha, "lam": cfg.lam, "bmax": cfg.bmax, "max_age_days": cfg.max_age_days, "frozen_from": cfg.frozen_from}


def _cfg_from(d: dict):
    import bias_state
    return bias_state.BiasConfig(alpha=float(d["alpha"]), lam=float(d["lam"]), bmax=float(d["bmax"]),
                                 max_age_days=float(d["max_age_days"]), frozen_from=str(d.get("frozen_from") or ""))


def _check_research_cfg(cfg) -> None:
    ff = str(cfg.frozen_from or "").strip()
    if not ff or ff.upper().startswith("ILUSTRASI"):
        raise BiasConfigError("parameter bias untuk jalur riset/operasional harus dibekukan dari kalibrasi (frozen_from terisi, "
                              "bukan ILUSTRASI DEMO)")


def get_bias_state(plot_id: str, model: str):
    """-> (BiasState, BiasConfig, version) dari DB, atau None bila belum ada. consumed = label yang sudah dipakai."""
    import bias_state
    rows = db_query("SELECT * FROM bias_state WHERE plot_id=%s AND model=%s", (plot_id, model.upper()))
    if not rows:
        return None
    r = rows[0]
    used = db_query("SELECT label_id FROM bias_update_log WHERE plot_id=%s AND model=%s AND applied",
                    (plot_id, model.upper()))
    st = bias_state.BiasState(plot_id, model, b=float(r["b"]), last_update_at=r["last_update_at"],
                              last_window_end=r["last_window_end"], consumed={int(u["label_id"]) for u in used})
    return st, _cfg_from(r["config"]), int(r["version"])


def apply_bias_labels(plot_id: str, model: str, cfg, items: list, now: datetime | None = None) -> list:
    """Terapkan label matang ke state bias (petak, model) secara ATOMIK dan tahan restart.
    items: [{"label": {label_id, start, end, available_at, residual_mm_day, validity},
             "prior": {issued_at, r_base_mm_day, prediction_id?, prior_ref?}}]  (waktu berzona).
    State dikunci (SELECT ... FOR UPDATE), label yang sudah pernah dipakai dibaca dari bias_update_log (bukan dari memori),
    sehingga restart/rerun tidak mereset bias dan tidak memakai label dua kali. Parameter bias dibekukan per (petak, model):
    berbeda dari yang tersimpan -> BiasConfigError (perubahan = deviasi protokol, bukan tombol kalibrasi)."""
    import bias_state
    _check_research_cfg(cfg)
    now = now or now_utc()
    model = model.upper()
    results = []
    with transaction() as cur:
        cur.execute("INSERT INTO bias_state (plot_id, model, config, updated_at) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (plot_id, model) DO NOTHING", (plot_id, model, J(_cfg_dict(cfg)), now))
        cur.execute("SELECT * FROM bias_state WHERE plot_id=%s AND model=%s FOR UPDATE", (plot_id, model))
        row = cur.fetchone()
        stored = row["config"]
        if _cfg_dict(cfg) != {k: stored.get(k) for k in _cfg_dict(cfg)}:
            if int(row["n_updates"]) == 0:                       # belum ada pembaruan: konfigurasi boleh ditetapkan ulang
                cur.execute("UPDATE bias_state SET config=%s WHERE plot_id=%s AND model=%s",
                            (J(_cfg_dict(cfg)), plot_id, model))
            else:
                raise BiasConfigError("parameter bias sudah dibekukan untuk petak/model ini dan berbeda dari yang diberikan")
        cur.execute("SELECT label_id FROM bias_update_log WHERE plot_id=%s AND model=%s AND applied", (plot_id, model))
        state = bias_state.BiasState(plot_id, model, b=float(row["b"]), last_update_at=row["last_update_at"],
                                     last_window_end=row["last_window_end"],
                                     consumed={int(u["label_id"]) for u in cur.fetchall()})
        n_applied = 0
        for it in sorted(items, key=lambda i: (i["label"]["end"], str(i["label"].get("label_id")))):
            lab, prior = it["label"], it.get("prior")
            rec = bias_state.apply_label(state, cfg, lab, prior, now)
            results.append(rec)
            lid = lab.get("label_id")
            if lid is None or rec["reason"] == "ALREADY_USED":
                continue                                          # tidak dicatat ulang (tak ada kunci / sudah tercatat)
            pr = prior or {}
            cur.execute(
                "INSERT INTO bias_update_log (plot_id, model, label_id, applied, reason, prediction_id, prior_ref, prior_issued_at, "
                "window_start, window_end, residual_mm_day, r_base_mm_day, e_base_mm_day, b_before, b_after, elapsed_days, "
                "clipped, config, at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (plot_id, model, int(lid), bool(rec["applied"]), rec["reason"], pr.get("prediction_id"),
                 J(pr.get("prior_ref")) if pr.get("prior_ref") is not None else None, pr.get("issued_at"),
                 lab.get("start"), lab.get("end"), lab.get("residual_mm_day"), pr.get("r_base_mm_day"),
                 rec.get("e_base_mm_day"), rec.get("b_before"), rec.get("b_after"), rec.get("elapsed_days"),
                 rec.get("clipped"), J(_cfg_dict(cfg)), now))
            n_applied += 1 if rec["applied"] else 0
        if n_applied:
            cur.execute("UPDATE bias_state SET b=%s, last_update_at=%s, last_window_end=%s, n_updates=n_updates+%s, "
                        "version=version+1, updated_at=%s WHERE plot_id=%s AND model=%s",
                        (state.b, state.last_update_at, state.last_window_end, n_applied, now, plot_id, model))
    return results


def bias_for_issue_db(plot_id: str, model: str, issue_at: datetime) -> tuple:
    """-> (bias yang dipakai, status, ringkasan audit). Tanpa state tersimpan: (0.0, "NO_BIAS_YET", None). Tidak memperbarui apa pun."""
    import bias_state
    got = get_bias_state(plot_id, model)
    if got is None:
        return 0.0, "NO_BIAS_YET", None
    st, cfg, _ = got
    b, status = bias_state.bias_for_issue(st, cfg, issue_at)
    snap = bias_state.snapshot(st, cfg, issue_at)
    snap["n_updates"] = len(st.consumed)          # riwayat memori kosong setelah restart; jumlah pembaruan = label terpakai di DB
    return b, status, snap
