# ============================================================
# SOMAT - Smart Adaptive Irrigation Management System
# PROTOTYPE: seluruh data di bawah adalah DATA SIMULASI,
# bukan data penelitian aktual.
# ============================================================
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets as pysecrets
import time
from urllib.parse import quote

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

st.set_page_config(
    page_title="SOMAT Dashboard",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="auto",
)

# ---------------- Language (EN / ID) ----------------
# Bahasa awal: English (untuk juri). Pengguna dapat pindah ke Indonesia lewat tombol EN/ID.
if "lang" not in st.session_state:
    _q = st.query_params.get("lang", "en")
    st.session_state["lang"] = _q if _q in ("en", "id") else "en"
LANG = st.session_state["lang"]


def L(en, id_):
    """Pilih teks sesuai bahasa aktif: L("English", "Indonesia")."""
    return en if st.session_state.get("lang", "en") == "en" else id_

# ---------------- ASSUMPTIONS (angka contoh, bukan data lapangan) ----------------
# Semua nilai di bawah adalah ASUMSI PROTOTYPE. Ubah di sini saja,
# lalu seluruh fungsi di bawah otomatis memakai nilai yang sama.
ASSUMPTIONS = {
    "area_ha": 50,                # luas areal layanan (ha)
    "delivery_hours": 8,          # lama pemberian air (jam)
    "min_water_level": 0.90,      # batas minimum muka air (m)
    "gate_max_discharge": 0.45,   # kapasitas maksimum pintu (m3/s)
}


@st.cache_data(ttl=300, show_spinner=False)
def generate_simulated_data(days=30, seed=42):
    """Membuat tabel data harian simulasi untuk prototype SOMAT."""
    # "seed" membuat angka acak selalu sama setiap dijalankan,
    # jadi hasil demo ke dosen konsisten.
    rng = np.random.default_rng(seed)

    # Daftar tanggal: 30 hari berakhir hari ini
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days)

    # Hujan: kebanyakan hari kering, kadang hujan
    is_rainy = rng.random(days) < 0.25
    rainfall = np.where(is_rainy, rng.gamma(2.0, 6.0, days), 0.0)

    # Evapotranspirasi acuan (ET0): sekitar 4-5 mm/hari + sedikit variasi
    et0 = np.clip(rng.normal(4.5, 0.6, days), 2.5, 6.5)

    # Kelembapan tanah: turun karena penguapan, naik saat hujan
    soil_moisture = np.zeros(days)
    soil_moisture[0] = 32.0
    for i in range(1, days):
        change = -0.9 * et0[i] / 4.5 + 0.35 * rainfall[i]
        soil_moisture[i] = np.clip(soil_moisture[i - 1] + change, 12, 45)

    # Tinggi muka air saluran (m): naik saat hujan, ada variasi kecil
    water_level = np.clip(1.10 + 0.012 * rainfall + rng.normal(0, 0.05, days), 0.6, 1.8)

    # Debit tersedia (m3/s): terkait tinggi muka air
    available_discharge = np.clip(0.30 * (water_level / 1.10) ** 1.5, 0.05, 0.80)

    # Kebutuhan air tanaman (mm/hari): naik saat ET0 tinggi,
    # turun saat tanah sudah lembap atau hujan
    crop_water_requirement = np.clip(
        et0 * 1.1 - 0.08 * (soil_moisture - 25) - 0.4 * rainfall, 0, None
    )

    return pd.DataFrame({
        "date": dates,
        "soil_moisture": soil_moisture.round(1),
        "rainfall": rainfall.round(1),
        "et0": et0.round(2),
        "water_level": water_level.round(2),
        "available_discharge": available_discharge.round(3),
        "crop_water_requirement": crop_water_requirement.round(1),
    })


# ---------------- Prediction logic (PROTOTYPE) ----------------
def predict_irrigation_requirement(
    soil_moisture,      # kelembapan tanah hari ini (%)
    rainfall,           # hujan hari ini (mm)
    et0,                # evapotranspirasi acuan (mm/hari)
    kc=1.1,             # koefisien tanaman (padi fase tengah, contoh)
    target_moisture=30, # target kelembapan tanah (%)
    root_depth_mm=300,  # kedalaman zona akar (mm)
    effective_rain=0.8, # fraksi hujan yang efektif
):
    """
    PROTOTYPE PREDICTION LOGIC - bukan model AI final tesis.

    Rumus sederhana berbasis aturan (rule-based) untuk menghasilkan
    estimasi kebutuhan irigasi (mm). Fungsi ini sengaja dipisah dari
    tampilan dashboard agar nanti dapat diganti dengan model prediksi
    yang lebih baik tanpa mengubah bagian lain.
    """
    # 1. Kebutuhan air tanaman dasar
    base_demand = et0 * kc

    # 2. Kekurangan air di tanah (dikonversi dari % ke mm)
    moisture_deficit = max(0.0, target_moisture - soil_moisture)
    deficit_mm = moisture_deficit / 100 * root_depth_mm

    # 3. Hujan yang benar-benar bermanfaat
    useful_rain = rainfall * effective_rain

    # 4. Hasil akhir, tidak boleh negatif
    requirement = max(0.0, base_demand + deficit_mm - useful_rain)

    return {
        "irrigation_mm": round(requirement, 1),
        "base_demand": round(base_demand, 1),
        "deficit_mm": round(deficit_mm, 1),
        "useful_rain": round(useful_rain, 1),
    }


# ---------------- Hydraulic feasibility (PROTOTYPE) ----------------
def check_hydraulic_feasibility(
    irrigation_mm,                                   # kebutuhan irigasi hasil prediksi (mm)
    available_discharge,                             # debit tersedia di saluran (m3/s)
    water_level,                                     # tinggi muka air saluran (m)
    area_ha=ASSUMPTIONS["area_ha"],                  # luas areal layanan (ha) - CONTOH
    delivery_hours=ASSUMPTIONS["delivery_hours"],    # lama pemberian air (jam) - CONTOH
    min_water_level=ASSUMPTIONS["min_water_level"],  # batas minimum muka air (m) - CONTOH
    gate_max_discharge=ASSUMPTIONS["gate_max_discharge"],  # kapasitas pintu (m3/s) - CONTOH
):
    """
    PROTOTYPE HYDRAULIC LOGIC - aturan sederhana (rule-based),
    bukan model hidraulik final tesis. Semua batas di atas adalah
    angka contoh. Fungsi ini sengaja dipisah agar nanti dapat diganti
    dengan model hidraulik yang lebih baik.
    """
    # 1. Ubah mm menjadi debit yang dibutuhkan (m3/s)
    volume_m3 = irrigation_mm * area_ha * 10
    required_discharge = volume_m3 / (delivery_hours * 3600)

    # 2. Tiga aturan cek
    checks = [
        {
            "Pemeriksaan": L("Canal water level", "Tinggi muka air saluran"),
            "Nilai": f"{water_level:.2f} m",
            "Batas": f">= {min_water_level:.2f} m",
            "Result": "PASS" if water_level >= min_water_level else "FAIL",
        },
        {
            "Pemeriksaan": L("Available discharge", "Debit tersedia"),
            "Nilai": L(f"{available_discharge:.3f} m3/s (required {required_discharge:.3f})", f"{available_discharge:.3f} m3/s (dibutuhkan {required_discharge:.3f})"),
            "Batas": L("available >= required", "tersedia >= dibutuhkan"),
            "Result": "PASS" if available_discharge >= required_discharge else "FAIL",
        },
        {
            "Pemeriksaan": L("Gate operating limit", "Batas operasi pintu"),
            "Nilai": f"{required_discharge:.3f} m3/s",
            "Batas": f"<= {gate_max_discharge:.2f} m3/s",
            "Result": "PASS" if required_discharge <= gate_max_discharge else "FAIL",
        },
    ]

    # 3. FEASIBLE hanya jika semua cek lolos
    feasible = all(c["Result"] == "PASS" for c in checks)

    return {
        "feasible": feasible,
        "status": "FEASIBLE" if feasible else "NOT FEASIBLE",
        "required_discharge": round(required_discharge, 3),
        "checks": checks,
    }


# ---------------- SOMAT recommendation engine (PROTOTYPE) ----------------
def generate_recommendation(
    prediction,                 # hasil predict_irrigation_requirement()
    hydraulic,                  # hasil check_hydraulic_feasibility()
    available_discharge,        # debit tersedia (m3/s)
    soil_moisture,              # kelembapan tanah (%)
    area_ha=ASSUMPTIONS["area_ha"],
    delivery_hours=ASSUMPTIONS["delivery_hours"],
    gate_max_discharge=ASSUMPTIONS["gate_max_discharge"],
):
    """
    PROTOTYPE RECOMMENDATION LOGIC - aturan sederhana, bukan keputusan final.
    Menggabungkan prediksi kebutuhan air dan cek hidraulik menjadi saran
    operasi. Operator tetap pengambil keputusan akhir.
    """
    demand_mm = prediction["irrigation_mm"]
    reasons = []

    # Apakah muka air saluran cukup? (cek pertama pada hasil hidraulik)
    level_ok = hydraulic["checks"][0]["Result"] == "PASS"

    # Debit yang benar-benar bisa dipakai
    if level_ok:
        usable_discharge = min(available_discharge, gate_max_discharge)
    else:
        usable_discharge = 0.0

    # Jumlah air maksimum (mm) yang bisa dialirkan dalam jam pemberian air
    max_deliverable_mm = usable_discharge * delivery_hours * 3600 / (area_ha * 10)

    # Tentukan jumlah irigasi yang direkomendasikan
    if demand_mm <= 0:
        recommended_mm = 0.0
        reasons.append(L("Predicted need is 0 mm, so irrigation is not required yet.", "Prediksi kebutuhan 0 mm, sehingga irigasi belum diperlukan."))
    elif hydraulic["feasible"]:
        recommended_mm = demand_mm
        reasons.append(L(
            f"Predicted need is {demand_mm} mm and all hydraulic checks passed, "
            "so the full amount is recommended.",
            f"Prediksi kebutuhan {demand_mm} mm dan semua cek hidraulik lolos, "
            "sehingga kebutuhan penuh disarankan.",
        ))
    else:
        recommended_mm = min(demand_mm, max_deliverable_mm)
        reasons.append(L(
            f"Predicted need is {demand_mm} mm, but the hydraulic check is NOT FEASIBLE.",
            f"Prediksi kebutuhan {demand_mm} mm, tetapi cek hidraulik TIDAK LAYAK.",
        ))
        if not level_ok:
            reasons.append(L("Canal water level is below the minimum limit.", "Tinggi muka air saluran di bawah batas minimum."))
        reasons.append(L(
            f"Only about {max_deliverable_mm:.1f} mm can be delivered within "
            f"{delivery_hours} hours, so the recommendation is reduced.",
            f"Hanya sekitar {max_deliverable_mm:.1f} mm yang dapat dialirkan dalam "
            f"{delivery_hours} jam, sehingga rekomendasi dikurangi.",
        ))
    recommended_mm = round(recommended_mm, 1)

    # Hitung durasi pemberian air (jam)
    if recommended_mm > 0 and usable_discharge > 0:
        duration_hours = recommended_mm * area_ha * 10 / (usable_discharge * 3600)
    else:
        duration_hours = 0.0

    # Tentukan prioritas
    if soil_moisture < 20 or demand_mm >= 20:
        priority = "HIGH"
        reasons.append(L("Soil is very dry or the need is large, so priority is HIGH.", "Tanah sangat kering atau kebutuhan besar, sehingga prioritas TINGGI."))
    elif demand_mm >= 3:
        priority = "NORMAL"
        reasons.append(L("Moderate need, so priority is NORMAL.", "Kebutuhan sedang, sehingga prioritas NORMAL."))
    else:
        priority = "LOW"
        reasons.append(L("Very small need, so priority is LOW.", "Kebutuhan sangat kecil, sehingga prioritas RENDAH."))

    return {
        "recommended_mm": recommended_mm,
        "duration_hours": round(duration_hours, 1),
        "feasibility": hydraulic["status"],
        "priority": priority,
        "reasons": reasons,
    }


# ============================================================
# DATABASE (Neon Postgres) + LOGIN
# - Login wajib sebelum dashboard ditampilkan.
# - Database Neon diperlukan untuk autentikasi, role, profil, dan penyimpanan keputusan.
# - Jika database belum tersedia, aplikasi berhenti di halaman login dan dashboard terkunci.
# Kata sandi TIDAK pernah disimpan polos: hanya hash PBKDF2-SHA256 + salt.
# ============================================================
try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
except Exception:  # paket belum terpasang
    psycopg2 = None


def _secret(section, key, default=""):
    try:
        return st.secrets[section][key]
    except Exception:
        return default


DB_URL = str(_secret("neon", "url", "") or os.environ.get("DATABASE_URL", ""))
SYSTEM_ROLES = ("admin", "operator", "viewer")
APP_PAGE_KEYS = ("overview", "monitoring", "prediction", "alerts", "operator")
DEFAULT_ROLE_PERMISSIONS = {
    "admin": APP_PAGE_KEYS,
    "operator": APP_PAGE_KEYS,
    "viewer": ("overview", "monitoring", "prediction", "alerts"),
}
MAX_FAILS, LOCK_SECONDS = 5, 300       # 5x salah sandi -> akun dikunci 5 menit
PBKDF2_ITERS = 310_000

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'viewer',
        password_hash TEXT NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        failed_count INTEGER NOT NULL DEFAULT 0,
        locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS decisions (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        username TEXT NOT NULL,
        decision TEXT NOT NULL,
        recommended_mm DOUBLE PRECISION,
        operator_mm DOUBLE PRECISION,
        duration_h DOUBLE PRECISION,
        note TEXT NOT NULL DEFAULT '',
        new_moisture DOUBLE PRECISION,
        status TEXT,
        learning_kind TEXT,
        learning_diff DOUBLE PRECISION,
        context JSONB,
        source TEXT NOT NULL DEFAULT 'simulation'
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data TEXT",
    """CREATE TABLE IF NOT EXISTS roles (
        role_key TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        is_system BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS role_permissions (
        role_key TEXT NOT NULL REFERENCES roles(role_key) ON DELETE CASCADE,
        page_key TEXT NOT NULL,
        can_access BOOLEAN NOT NULL DEFAULT TRUE,
        PRIMARY KEY (role_key, page_key)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS edited_by TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ",
]


def _now():
    return datetime.now(timezone.utc)


@st.cache_resource(show_spinner=False)
def _pool(url):
    """Pool koneksi yang dipakai ulang antar-rerun. Membuka koneksi baru ke Neon
    (TCP + TLS + login) memakan waktu ~0,3-1 detik; dengan pool, query berikutnya
    hanya satu kali bolak-balik jaringan."""
    return psycopg2.pool.ThreadedConnectionPool(
        1, 5, dsn=url, connect_timeout=10,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
    )


def db_query(sql, params=()):
    """Jalankan satu query berparameter (aman dari SQL injection). SELECT -> list of dict.

    Koneksi diambil dari pool. Jika koneksi basi (Neon menidurkan komputasi setelah
    5 menit tidak aktif), koneksi dibuang dan query diulang sekali dengan koneksi baru.
    """
    for attempt in (1, 2):
        pool = _pool(DB_URL)
        con = pool.getconn()
        try:
            with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            con.commit()
            pool.putconn(con)
            return rows
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try:
                pool.putconn(con, close=True)
            except Exception:
                pass
            if attempt == 2:
                raise
        except Exception:
            try:
                con.rollback()
            finally:
                pool.putconn(con)
            raise


# ---------- kata sandi ----------
def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _dummy_hash():
    return hash_password("dummy-password-for-timing")


def valid_username(u):
    return bool(re.fullmatch(r"[a-z0-9._-]{3,32}", u or ""))


def valid_password(p):
    return isinstance(p, str) and len(p) >= 8


# ---------- inisialisasi (sekali per proses; kegagalan TIDAK di-cache) ----------
@st.cache_resource(show_spinner=False)
def _init_db(url):
    for stmt in SCHEMA_SQL:
        db_query(stmt)

    # Seed built-in roles without overwriting administrator customizations.
    for _key, _name in (("admin", "Administrator"), ("operator", "Operator"), ("viewer", "Viewer")):
        db_query(
            "INSERT INTO roles (role_key, display_name, is_system) VALUES (%s,%s,TRUE) "
            "ON CONFLICT (role_key) DO NOTHING",
            (_key, _name),
        )
    for _role, _pages in DEFAULT_ROLE_PERMISSIONS.items():
        for _page in APP_PAGE_KEYS:
            db_query(
                "INSERT INTO role_permissions (role_key, page_key, can_access) VALUES (%s,%s,%s) "
                "ON CONFLICT (role_key, page_key) DO NOTHING",
                (_role, _page, _page in _pages),
            )

    if not db_query("SELECT 1 FROM users LIMIT 1"):
        bu = str(_secret("bootstrap_admin", "username", "")).strip().lower()
        bp = str(_secret("bootstrap_admin", "password", ""))
        if valid_username(bu) and valid_password(bp):
            db_query(
                "INSERT INTO users (username, display_name, role, password_hash, created_at) "
                "VALUES (%s,%s,'admin',%s,%s)",
                (bu, bu, hash_password(bp), _now()),
            )
            db_query(
                "INSERT INTO audit_log (ts, username, action, detail) VALUES (%s,%s,%s,%s)",
                (_now(), "system", "bootstrap_admin", f"admin '{bu}' dibuat dari secrets"),
            )
    return True


DB_OK = False
if psycopg2 is not None and DB_URL:
    try:
        DB_OK = bool(_init_db(DB_URL))
    except Exception:
        DB_OK = False
DB_ACTIVE = bool(DB_URL) and DB_OK


# ---------- audit ----------
def current_user():
    return st.session_state.get("user")


def audit(action, detail="", username=None):
    if not DB_ACTIVE:
        return
    try:
        who = username or (current_user() or {}).get("username", "-")
        db_query(
            "INSERT INTO audit_log (ts, username, action, detail) VALUES (%s,%s,%s,%s)",
            (_now(), who, action, str(detail)[:500]),
        )
    except Exception:
        pass


# ---------- role and permission helpers ----------
_ROLE_ACCESS_CACHE = {}
_ROLE_LABEL_CACHE = {}


def list_roles():
    return db_query(
        "SELECT role_key, display_name, is_system, created_at FROM roles "
        "ORDER BY CASE role_key WHEN 'admin' THEN 0 WHEN 'operator' THEN 1 WHEN 'viewer' THEN 2 ELSE 3 END, display_name"
    )


def role_exists(role_key):
    if not DB_ACTIVE:
        return False
    return bool(db_query("SELECT 1 FROM roles WHERE role_key=%s", (role_key,)))


def role_label(role):
    if role in _ROLE_LABEL_CACHE:
        return _ROLE_LABEL_CACHE[role]
    fallback = {
        "admin": L("Administrator", "Administrator"),
        "operator": L("Operator", "Operator"),
        "viewer": L("Viewer (read-only)", "Pengamat (hanya lihat)"),
    }
    if DB_ACTIVE:
        try:
            rows = db_query("SELECT display_name FROM roles WHERE role_key=%s", (role,))
            if rows:
                _ROLE_LABEL_CACHE[role] = rows[0]["display_name"]
                return _ROLE_LABEL_CACHE[role]
        except Exception:
            pass
    _ROLE_LABEL_CACHE[role] = fallback.get(role, role)
    return _ROLE_LABEL_CACHE[role]


def page_label(page_key):
    return {
        "overview": L("Overview", "Ringkasan"),
        "monitoring": L("Sensor Monitoring", "Monitoring Sensor"),
        "prediction": L("Prediction & Recommendation", "Prediksi & Rekomendasi"),
        "alerts": L("Alerts", "Peringatan"),
        "operator": L("Operator Decision", "Keputusan Operator"),
    }.get(page_key, page_key)


def get_role_pages(role_key):
    """Ambil daftar tab yang diizinkan untuk role; admin selalu memiliki akses penuh."""
    if role_key == "admin":
        return list(APP_PAGE_KEYS)
    if role_key in _ROLE_ACCESS_CACHE:
        return list(_ROLE_ACCESS_CACHE[role_key])
    if not DB_ACTIVE:
        return []
    rows = db_query(
        "SELECT page_key FROM role_permissions WHERE role_key=%s AND can_access=TRUE",
        (role_key,),
    )
    _ROLE_ACCESS_CACHE[role_key] = [r["page_key"] for r in rows if r["page_key"] in APP_PAGE_KEYS]
    return list(_ROLE_ACCESS_CACHE[role_key])


def can_access_page(page_key, user=None):
    u = user or current_user()
    if not u:
        return False
    if page_key == "account":
        return True
    if page_key == "admin":
        return u.get("role") == "admin"
    if page_key not in APP_PAGE_KEYS:
        return False
    if u.get("role") == "admin":
        return True
    try:
        return page_key in get_role_pages(u.get("role", ""))
    except Exception:
        return False


def _first_accessible_page(user=None):
    u = user or current_user()
    for _key in APP_PAGE_KEYS:
        if can_access_page(_key, u):
            return _key
    return "account"


def create_role(display_name, pages):
    """Buat role custom; role_key dibuat otomatis dari nama role."""
    if not is_admin():
        return "forbidden", None
    name = (display_name or "").strip()
    if len(name) < 2 or len(name) > 60:
        return "bad_role_name", None
    role_key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32].strip("_")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,31}", role_key or ""):
        return "bad_role_name", None
    if role_exists(role_key):
        return "role_exists", None
    allowed = [p for p in (pages or []) if p in APP_PAGE_KEYS]
    try:
        db_query(
            "INSERT INTO roles (role_key, display_name, is_system) VALUES (%s,%s,FALSE)",
            (role_key, name),
        )
        for page_key in APP_PAGE_KEYS:
            db_query(
                "INSERT INTO role_permissions (role_key, page_key, can_access) VALUES (%s,%s,%s)",
                (role_key, page_key, page_key in allowed),
            )
        _ROLE_ACCESS_CACHE[role_key] = list(allowed)
        _ROLE_LABEL_CACHE[role_key] = name
        audit("role_create", f"{role_key}: {','.join(allowed)}")
        return None, role_key
    except Exception:
        return "db", None


def save_role_access(role_key, pages):
    """Simpan daftar tab untuk role. Hak admin tidak dapat dikurangi."""
    if not is_admin():
        return "forbidden"
    if not role_exists(role_key):
        return "bad_role"
    if role_key == "admin":
        return "system_role"
    allowed = list(dict.fromkeys(p for p in (pages or []) if p in APP_PAGE_KEYS))
    try:
        db_query("DELETE FROM role_permissions WHERE role_key=%s", (role_key,))
        for page_key in APP_PAGE_KEYS:
            db_query(
                "INSERT INTO role_permissions (role_key, page_key, can_access) VALUES (%s,%s,%s)",
                (role_key, page_key, page_key in allowed),
            )
        _ROLE_ACCESS_CACHE[role_key] = list(allowed)
        audit("role_permissions_update", f"{role_key}: {','.join(allowed)}")
        return None
    except Exception:
        return "db"


def delete_role(role_key):
    if not is_admin():
        return "forbidden"
    try:
        row = db_query("SELECT is_system FROM roles WHERE role_key=%s", (role_key,))
        if not row:
            return "bad_role"
        if row[0]["is_system"] or role_key in SYSTEM_ROLES:
            return "system_role"
        used = db_query("SELECT COUNT(*) AS n FROM users WHERE role=%s", (role_key,))
        if int(used[0]["n"]) > 0:
            return "role_in_use"
        db_query("DELETE FROM roles WHERE role_key=%s", (role_key,))
        _ROLE_ACCESS_CACHE.pop(role_key, None)
        _ROLE_LABEL_CACHE.pop(role_key, None)
        audit("role_delete", role_key)
        return None
    except Exception:
        return "db"


# ---------- pengguna ----------
def get_user(username):
    rows = db_query("SELECT * FROM users WHERE username=%s", ((username or "").strip().lower(),))
    return rows[0] if rows else None


def authenticate(username, password):
    """Kembalikan (user | None, kode_error). Kode: 'invalid', 'locked', 'db'."""
    try:
        u = (username or "").strip().lower()
        row = get_user(u)
        if row is None:
            verify_password(password or "", _dummy_hash())
            audit("login_fail", "username tidak dikenal", username=u or "-")
            return None, "invalid"
        if time.time() < float(row["locked_until"]):
            audit("login_blocked", "akun terkunci sementara", username=u)
            return None, "locked"
        if row["active"] and verify_password(password or "", row["password_hash"]):
            db_query("UPDATE users SET failed_count=0, locked_until=0 WHERE username=%s", (u,))
            audit("login_ok", "", username=u)
            return {
                "username": row["username"],
                "display_name": row["display_name"] or row["username"],
                "role": row["role"],
                "avatar_data": row.get("avatar_data"),
            }, None
        fails = int(row["failed_count"]) + 1
        locked = time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0
        db_query("UPDATE users SET failed_count=%s, locked_until=%s WHERE username=%s",
                 (0 if locked else fails, locked, u))
        audit("login_fail", "sandi salah" if row["active"] else "akun nonaktif", username=u)
        return None, "locked" if locked else "invalid"
    except Exception:
        return None, "db"


USER_CHECK_TTL = 30  # detik; perubahan peran/status oleh admin berlaku maksimal setelah ini


def refresh_user(force=False):
    """Cek ulang status, role, nama, dan foto pengguna dari database.

    Hanya menyentuh database setiap USER_CHECK_TTL detik (kecuali force=True),
    supaya pindah tab tidak menunggu query ke database.
    """
    u = current_user()
    if not u or not DB_ACTIVE:
        return u
    now = time.time()
    if not force and now - st.session_state.get("_user_checked", 0) < USER_CHECK_TTL:
        return u
    try:
        row = get_user(u["username"])
    except Exception:
        return u
    if not row or not row["active"]:
        st.session_state["user"] = None
        return None
    u["role"] = row["role"]
    u["display_name"] = row["display_name"] or row["username"]
    u["avatar_data"] = row.get("avatar_data")
    st.session_state["_user_checked"] = now
    return u


def is_admin():
    u = current_user()
    return bool(u) and DB_ACTIVE and u.get("role") == "admin"


def can_decide():
    u = current_user()
    return bool(u) and DB_ACTIVE and can_access_page("operator", u)


SESSION_DAYS = 7          # batas mutlak umur token
IDLE_SECONDS = 30 * 60    # tidak aktif lebih dari 30 menit -> sesi berakhir


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()   # hanya hash yang disimpan di database


def create_session_token(username):
    """Buat token sesi acak (disimpan di localStorage browser). Database hanya menyimpan hash-nya."""
    token = pysecrets.token_urlsafe(32)
    now = _now()
    db_query("DELETE FROM sessions WHERE expires_at < %s", (now,))
    db_query(
        "INSERT INTO sessions (token_hash, username, created_at, expires_at, last_seen) VALUES (%s,%s,%s,%s,%s)",
        (_token_hash(token), username, now, now + timedelta(days=SESSION_DAYS), now),
    )
    return token


def session_user(token):
    """Pengguna aktif pemilik token yang belum kedaluwarsa DAN aktif dalam 30 menit terakhir, atau None."""
    now = _now()
    rows = db_query(
        "SELECT u.username, u.display_name, u.role, u.avatar_data FROM sessions s "
        "JOIN users u ON u.username = s.username "
        "WHERE s.token_hash=%s AND s.expires_at > %s AND s.last_seen > %s AND u.active",
        (_token_hash(token), now, now - timedelta(seconds=IDLE_SECONDS)),
    )
    if not rows:
        return None
    db_query("UPDATE sessions SET last_seen=%s WHERE token_hash=%s", (now, _token_hash(token)))
    r = rows[0]
    return {"username": r["username"], "display_name": r["display_name"] or r["username"],
            "role": r["role"], "avatar_data": r.get("avatar_data")}


def touch_session(token):
    db_query("UPDATE sessions SET last_seen=%s WHERE token_hash=%s", (_now(), _token_hash(token)))


def revoke_sessions(username, keep_token=None):
    if keep_token:
        db_query("DELETE FROM sessions WHERE username=%s AND token_hash<>%s", (username, _token_hash(keep_token)))
    else:
        db_query("DELETE FROM sessions WHERE username=%s", (username,))


# Komponen kecil (folder somat_session/ di samping app.py) yang menyimpan token di localStorage browser.
try:
    _SESS_COMPONENT = components.declare_component(
        "somat_session", path=str(Path(__file__).resolve().parent / "somat_session"))
except Exception:
    _SESS_COMPONENT = None


def start_session(user):
    """Dipanggil setelah login berhasil: simpan pengguna di sesi + minta browser menyimpan token."""
    now = time.time()
    st.session_state["user"] = user
    st.session_state["page"] = "overview"
    st.session_state["_user_checked"] = now
    st.session_state["_last_activity"] = now
    try:
        token = create_session_token(user["username"])
        st.session_state["_session_token"] = token
        st.session_state["_sess_args"] = {"action": "set", "token": token, "nonce": "set-" + token[:12]}
    except Exception:
        pass   # login tetap berhasil; hanya tidak "diingat" setelah refresh


def sync_browser_session():
    """Pasang komponen penyimpan token; pulihkan sesi dari token jika masih berlaku."""
    if _SESS_COMPONENT is None or not DB_ACTIVE:
        return
    args = st.session_state.setdefault("_sess_args", {"action": "read", "token": "", "nonce": "read"})
    res = _SESS_COMPONENT(**args, key="somat_sess", default=None)
    if st.session_state.get("_restore_tried") or not isinstance(res, dict) or res.get("nonce") != "read":
        return
    st.session_state["_restore_tried"] = True
    tok = res.get("token") or ""
    if st.session_state.get("user") is not None or not tok:
        return
    try:
        restored = session_user(tok)
    except Exception:
        restored = None
    if restored:
        now = time.time()
        st.session_state["user"] = restored
        st.session_state["_session_token"] = tok
        st.session_state["_user_checked"] = now
        st.session_state["_last_activity"] = now
        st.session_state["page"] = st.session_state.pop("_want_page", "overview")
    else:   # token basi (tidak aktif > 30 menit / dicabut): hapus dari browser
        st.session_state["_sess_args"] = {"action": "clear", "token": "", "nonce": "clear-" + pysecrets.token_hex(4)}


def logout():
    token = st.session_state.pop("_session_token", None)
    audit("logout")
    if token and DB_ACTIVE:
        try:
            db_query("DELETE FROM sessions WHERE token_hash=%s", (_token_hash(token),))
        except Exception:
            pass
    st.session_state["_sess_args"] = {"action": "clear", "token": "", "nonce": "clear-" + pysecrets.token_hex(4)}
    st.session_state["user"] = None
    st.session_state["page"] = "login"
    for _k in ("pending_recommendation", "show_modify", "_last_activity", "_touched"):
        st.session_state.pop(_k, None)


def update_own_profile(display_name, avatar_data):
    u = current_user()
    if not u or not DB_ACTIVE:
        return "forbidden"
    name = (display_name or "").strip()
    if not name or len(name) > 60:
        return "bad_display_name"
    try:
        db_query(
            "UPDATE users SET display_name=%s, avatar_data=%s WHERE username=%s",
            (name, avatar_data, u["username"]),
        )
        u["display_name"] = name
        u["avatar_data"] = avatar_data
        audit("profile_update", "display name and profile photo updated")
        return None
    except Exception:
        return "db"


def avatar_data_from_upload(uploaded_file):
    """Validasi, resize, dan kompres foto profil menjadi data URL JPEG."""
    if uploaded_file is None:
        return None, None
    raw = uploaded_file.getvalue()
    if len(raw) > 5 * 1024 * 1024:
        return None, "image_too_large"
    try:
        with Image.open(io.BytesIO(raw)) as source_image:
            image = ImageOps.exif_transpose(source_image)
            image.thumbnail((512, 512))
            if image.mode in ("RGBA", "LA"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=84, optimize=True)
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", None
    except Exception:
        return None, "invalid_image"

def auth_msg(code):
    return {
        "invalid": L("Wrong username or password.", "Nama pengguna atau kata sandi salah."),
        "locked": L(f"Too many failed attempts. Try again in {LOCK_SECONDS // 60} minutes.",
                    f"Terlalu banyak percobaan gagal. Coba lagi dalam {LOCK_SECONDS // 60} menit."),
        "db": L("The database is unreachable. Please try again shortly.",
                "Database tidak dapat dihubungi. Coba lagi sebentar lagi."),
        "bad_username": L("Username: 3-32 characters, lowercase letters, digits, . _ -",
                          "Nama pengguna: 3-32 karakter, huruf kecil, angka, . _ -"),
        "bad_password": L("Password must be at least 8 characters.", "Kata sandi minimal 8 karakter."),
        "exists": L("That username already exists.", "Nama pengguna itu sudah ada."),
        "bad_role": L("Invalid role.", "Peran tidak valid."),
        "bad_role_name": L("Role name must contain 2-60 characters and produce a valid role key.", "Nama role harus 2-60 karakter dan menghasilkan kode role yang valid."),
        "role_exists": L("A role with this name already exists.", "Role dengan nama tersebut sudah ada."),
        "role_in_use": L("This role is assigned to one or more users. Reassign those users before deleting it.", "Role ini masih digunakan satu atau lebih pengguna. Pindahkan pengguna tersebut sebelum menghapusnya."),
        "system_role": L("This built-in role cannot be deleted or edited here.", "Role bawaan ini tidak dapat dihapus atau diubah di sini."),
        "bad_display_name": L("Display name is required and must be 60 characters or fewer.", "Display name wajib diisi dan maksimal 60 karakter."),
        "image_too_large": L("Image is larger than 5 MB. Choose a smaller image.", "Ukuran foto lebih dari 5 MB. Pilih foto yang lebih kecil."),
        "invalid_image": L("The selected file is not a supported image.", "File yang dipilih bukan gambar yang didukung."),
        "last_admin": L("You cannot remove the last active administrator.",
                        "Administrator aktif terakhir tidak boleh dihapus/dinonaktifkan."),
        "self": L("You cannot change your own role or deactivate yourself here.",
                  "Anda tidak dapat mengubah peran atau menonaktifkan diri sendiri di sini."),
        "mismatch": L("The new passwords do not match.", "Kata sandi baru tidak sama."),
        "wrong_current": L("Current password is incorrect.", "Kata sandi saat ini salah."),
        "forbidden": L("You do not have permission for this action.", "Anda tidak punya izin untuk aksi ini."),
        "bad_value": L("Invalid value. Check the decision type, amount (0-1000 mm) and duration (0-240 h).",
                       "Nilai tidak valid. Periksa jenis keputusan, jumlah (0-1000 mm) dan durasi (0-240 jam)."),
        "not_found": L("Record not found (it may already be deleted).", "Catatan tidak ditemukan (mungkin sudah dihapus)."),
    }.get(code, code)


def create_user(username, display_name, role, password):
    """Hanya admin. Kembalikan None jika berhasil, selain itu kode error."""
    if not is_admin():
        return "forbidden"
    username = (username or "").strip().lower()
    if not valid_username(username):
        return "bad_username"
    if not valid_password(password):
        return "bad_password"
    if not role_exists(role):
        return "bad_role"
    try:
        if get_user(username):
            return "exists"
        db_query(
            "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (%s,%s,%s,%s,%s)",
            (username, (display_name or username).strip()[:60], role, hash_password(password), _now()),
        )
        audit("user_create", f"{username} ({role})")
        return None
    except Exception:
        return "db"


def _active_admin_count():
    return int(db_query("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active")[0]["n"])


def update_user(username, role=None, active=None):
    """Hanya admin. Tidak boleh mengubah diri sendiri / menghapus admin aktif terakhir."""
    if not is_admin():
        return "forbidden"
    try:
        target = get_user(username)
        if not target:
            return "invalid"
        if username == current_user()["username"]:
            return "self"
        if role is not None and not role_exists(role):
            return "bad_role"
        new_role = role if role is not None else target["role"]
        new_active = active if active is not None else bool(target["active"])
        losing_admin = target["role"] == "admin" and target["active"] and (new_role != "admin" or not new_active)
        if losing_admin and _active_admin_count() <= 1:
            return "last_admin"
        db_query("UPDATE users SET role=%s, active=%s WHERE username=%s", (new_role, new_active, username))
        if not new_active:
            revoke_sessions(username)
        audit("user_update", f"{username}: role={new_role}, active={new_active}")
        return None
    except Exception:
        return "db"


def reset_password(username, new_password):
    """Hanya admin. Juga membuka kunci akun."""
    if not is_admin():
        return "forbidden"
    if not valid_password(new_password):
        return "bad_password"
    try:
        db_query("UPDATE users SET password_hash=%s, failed_count=0, locked_until=0 WHERE username=%s",
                 (hash_password(new_password), username))
        revoke_sessions(username)
        audit("password_reset", username)
        return None
    except Exception:
        return "db"


def change_own_password(current, new, confirm):
    u = current_user()
    if not u or not DB_ACTIVE:
        return "forbidden"
    if new != confirm:
        return "mismatch"
    if not valid_password(new):
        return "bad_password"
    try:
        row = get_user(u["username"])
        if not row or not verify_password(current or "", row["password_hash"]):
            audit("password_change_fail", "sandi saat ini salah")
            return "wrong_current"
        db_query("UPDATE users SET password_hash=%s WHERE username=%s", (hash_password(new), u["username"]))
        revoke_sessions(u["username"], keep_token=st.session_state.get("_session_token"))
        audit("password_change")
        return None
    except Exception:
        return "db"


def list_users():
    return db_query("SELECT username, display_name, role, active, created_at FROM users ORDER BY username")


# ---------- keputusan operator (permanen) ----------
def save_decision_db(user, decision, rec_mm, op_mm, dur_h, note, feedback, context):
    db_query(
        "INSERT INTO decisions (ts, username, decision, recommended_mm, operator_mm, duration_h, note, "
        "new_moisture, status, learning_kind, learning_diff, context, source) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (_now(), user, decision, float(rec_mm), float(op_mm), float(dur_h), str(note or "")[:1000],
         float(feedback["new_moisture"]), feedback["status"], feedback["learning"]["kind"],
         float(feedback["learning"].get("diff", 0.0)), json.dumps(context), "simulation"),
    )


def load_decisions_db(limit=200):
    return db_query(
        "SELECT id, ts, username, decision, recommended_mm, operator_mm, duration_h, note, new_moisture, status, edited_by "
        "FROM decisions ORDER BY ts DESC LIMIT %s", (int(limit),))


DECISION_TYPES = ("APPROVE", "MODIFY", "DELAY")


def update_decision(decision_id, decision, operator_mm, duration_h, note):
    """Hanya admin. Mengubah isian keputusan operator; rekomendasi SOMAT & konteks tidak diubah."""
    refresh_user(force=True)
    if not is_admin():
        return "forbidden"
    try:
        mm, hours = float(operator_mm), float(duration_h)
    except (TypeError, ValueError):
        return "bad_value"
    if decision not in DECISION_TYPES or not (0 <= mm <= 1000) or not (0 <= hours <= 240):
        return "bad_value"
    try:
        before = db_query("SELECT decision, operator_mm, duration_h, note FROM decisions WHERE id=%s", (int(decision_id),))
        if not before:
            return "not_found"
        db_query(
            "UPDATE decisions SET decision=%s, operator_mm=%s, duration_h=%s, note=%s, edited_by=%s, edited_at=%s WHERE id=%s",
            (decision, mm, hours, str(note or "")[:1000], current_user()["username"], _now(), int(decision_id)),
        )
        b = before[0]
        audit("decision_edit", f"#{decision_id}: {b['decision']}/{b['operator_mm']}mm/{b['duration_h']}h -> {decision}/{mm}mm/{hours}h")
        return None
    except Exception:
        return "db"


def delete_decision(decision_id):
    """Hanya admin. Menghapus satu catatan keputusan (ringkasannya tetap tercatat di audit log)."""
    refresh_user(force=True)
    if not is_admin():
        return "forbidden"
    try:
        before = db_query("SELECT username, decision, operator_mm FROM decisions WHERE id=%s", (int(decision_id),))
        if not before:
            return "not_found"
        db_query("DELETE FROM decisions WHERE id=%s", (int(decision_id),))
        b = before[0]
        audit("decision_delete", f"#{decision_id}: {b['username']} {b['decision']} {b['operator_mm']}mm")
        return None
    except Exception:
        return "db"


def fetch_audit(limit=200):
    return db_query("SELECT ts, username, action, detail FROM audit_log ORDER BY ts DESC LIMIT %s", (int(limit),))


def fmt_ts(ts):
    """Waktu UTC dari database -> WIB (Asia/Jakarta) sebagai teks."""
    try:
        return pd.to_datetime(ts, utc=True).tz_convert("Asia/Jakarta").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def render_login_form(key="login_form"):
    st.subheader(L("🔐 Sign in", "🔐 Masuk"))
    if not DB_ACTIVE:
        st.error(auth_msg("db"))
        return
    with st.form(key):
        uname = st.text_input(L("Username", "Nama pengguna"))
        pwd = st.text_input(L("Password", "Kata sandi"), type="password")
        go = st.form_submit_button(L("Sign in", "Masuk"), type="primary")
    if go:
        user, err = authenticate(uname, pwd)
        if user:
            start_session(user)
            st.rerun()
        else:
            st.error(auth_msg(err))


# ---------------- Decision log (database jika aktif, kalau tidak: selama sesi) ----------------
def log_decision(decision, recommendation, irrigation_mm, duration_hours, note):
    """Menambahkan satu catatan keputusan operator.

    - Selalu disimpan di sesi (dipakai tampilan feedback dan sebagai cadangan).
    - Jika database aktif: disimpan PERMANEN beserta konteks (kelembapan, hujan, ET0, dst.)
      sebagai fondasi data pembelajaran, dan dicatat di audit log.
    Yang disimpan adalah kode/angka (bukan kalimat), supaya riwayat tampil dalam
    bahasa yang sedang aktif walaupun bahasa diganti setelahnya.
    """
    st.session_state.pop("pending_recommendation", None)
    feedback = simulate_field_response(
        decision=decision,
        operator_mm=irrigation_mm,
        recommended_mm=recommendation["recommended_mm"],
        soil_moisture=float(latest["soil_moisture"]),
    )
    st.session_state["last_feedback"] = {
        "decision": decision,
        "recommended_mm": recommendation["recommended_mm"],
        "operator_mm": irrigation_mm,
        "feedback": feedback,
    }
    who = (current_user() or {}).get("username", "demo")
    st.session_state["decision_log"].append({
        "time": pd.Timestamp.now(tz="Asia/Jakarta").strftime("%Y-%m-%d %H:%M:%S"),
        "operator": who,
        "decision": decision,
        "recommended_mm": recommendation["recommended_mm"],
        "operator_mm": irrigation_mm,
        "duration_h": duration_hours,
        "note": note,
        "new_moisture": feedback["new_moisture"],
        "status": feedback["status"],
    })
    if DB_ACTIVE:
        context = {
            "soil_moisture": float(latest["soil_moisture"]),
            "rainfall": float(latest["rainfall"]),
            "et0": float(latest["et0"]),
            "water_level": float(latest["water_level"]),
            "available_discharge": float(latest["available_discharge"]),
            "predicted_mm": float(prediction["irrigation_mm"]),
            "feasible": bool(hydraulic["feasible"]),
            "priority": recommendation.get("priority"),
        }
        try:
            save_decision_db(who, decision, recommendation["recommended_mm"], irrigation_mm,
                             duration_hours, note, feedback, context)
            audit("decision", f"{decision}: {irrigation_mm} mm / {duration_hours} h")
        except Exception:
            st.session_state["db_error"] = True


def field_status_text(code):
    """Teks status respons lapangan simulasi sesuai bahasa."""
    return {
        "below": L("Below target", "Di bawah target"),
        "on": L("On target", "Sesuai target"),
        "above": L("Above target, risk of over-irrigation", "Di atas target, risiko irigasi berlebih"),
    }[code]


def feedback_learning_text(info):
    """Pesan umpan balik ke SOMAT sesuai bahasa."""
    kind, diff = info["kind"], info.get("diff", 0.0)
    if kind == "approve":
        return L("The operator approved the recommendation. No adjustment needed.",
                 "Operator menyetujui rekomendasi. Tidak perlu penyesuaian.")
    if kind == "delay":
        return L("The operator postponed irrigation. SOMAT records the reason for review.",
                 "Operator menunda irigasi. SOMAT mencatat alasannya untuk ditinjau.")
    if kind == "more":
        return L(f"The operator applied {diff:.1f} mm MORE than recommended. "
                 "SOMAT may need to account for a higher demand.",
                 f"Operator memberi {diff:.1f} mm LEBIH BANYAK dari rekomendasi. "
                 "SOMAT mungkin perlu memperhitungkan kebutuhan yang lebih tinggi.")
    return L(f"The operator applied {abs(diff):.1f} mm LESS than recommended. "
             "SOMAT may be overestimating the demand or the hydraulic limit.",
             f"Operator memberi {abs(diff):.1f} mm LEBIH SEDIKIT dari rekomendasi. "
             "SOMAT mungkin melebih-lebihkan kebutuhan atau batas hidraulik.")


def decision_log_df():
    """Riwayat keputusan sebagai tabel (judul kolom mengikuti bahasa aktif).

    Sumber: database (permanen) jika aktif; jika tidak/gagal: sesi ini saja.
    """
    cols = {
        "time": L("Time (WIB)", "Waktu (WIB)"),
        "operator": L("Operator", "Operator"),
        "decision": L("Decision", "Keputusan"),
        "recommended_mm": L("SOMAT recommendation (mm)", "Rekomendasi SOMAT (mm)"),
        "operator_mm": L("Operator irrigation (mm)", "Irigasi operator (mm)"),
        "duration_h": L("Operator duration (h)", "Durasi operator (jam)"),
        "note": L("Reason / note", "Alasan / catatan"),
        "new_moisture": L("Soil moisture after (simulated, %)", "Kelembapan tanah setelah (simulasi, %)"),
        "status": L("Field response (simulated)", "Respons lapangan (simulasi)"),
        "edited_by": L("Edited by", "Diedit oleh"),
    }
    if is_admin():   # ID hanya ditampilkan untuk admin (dipakai saat mengubah/menghapus)
        cols = {"id": "ID", **cols}
    source = None
    if DB_ACTIVE:
        try:
            source = [
                dict(r, time=fmt_ts(r["ts"]), operator=r["username"]) for r in load_decisions_db()
            ]
        except Exception:
            st.session_state["db_error"] = True
    if source is None:
        source = [dict(r) for r in st.session_state["decision_log"][::-1]]
    rows = []
    for r in source:
        r["status"] = field_status_text(r["status"]) if r.get("status") in ("below", "on", "above") else r.get("status")
        rows.append({cols[k]: r.get(k) for k in cols})
    return pd.DataFrame(rows, columns=list(cols.values()))


# ---------------- Alerts / anomaly (PROTOTYPE) ----------------
def detect_alerts(
    soil_moisture,          # kelembapan tanah (%)
    water_level,            # tinggi muka air saluran (m)
    rainfall,               # hujan hari ini (mm)
    prediction,             # hasil predict_irrigation_requirement()
    recommendation,         # hasil generate_recommendation()
    low_moisture=20,        # batas kelembapan tanah rendah (%) - CONTOH
    min_water_level=ASSUMPTIONS["min_water_level"],
    heavy_rain=20,          # batas hujan tinggi (mm/hari) - CONTOH
):
    """
    PROTOTYPE ALERT LOGIC - aturan sederhana (rule-based), bukan
    metode deteksi anomali final tesis. Semua batas adalah angka contoh.
    """
    alerts = []

    if soil_moisture < low_moisture:
        alerts.append({
            "level": "warning",
            "title": L("Soil moisture too low", "Kelembapan tanah terlalu rendah"),
            "detail": L(f"Soil moisture {soil_moisture}% is below the {low_moisture}% limit.", f"Kelembapan tanah {soil_moisture}% di bawah batas {low_moisture}%."),
        })

    if water_level < min_water_level:
        alerts.append({
            "level": "error",
            "title": L("Canal water level too low", "Muka air saluran terlalu rendah"),
            "detail": L(f"Water level {water_level} m is below the {min_water_level} m limit.", f"Tinggi muka air {water_level} m di bawah batas {min_water_level} m."),
        })

    if rainfall >= heavy_rain:
        alerts.append({
            "level": "warning",
            "title": L("Heavy rain", "Hujan lebat"),
            "detail": L(f"Rainfall of {rainfall} mm reaches the {heavy_rain} mm limit.", f"Curah hujan {rainfall} mm mencapai batas {heavy_rain} mm."),
        })

    if recommendation["recommended_mm"] < prediction["irrigation_mm"]:
        alerts.append({
            "level": "error",
            "title": L("Demand exceeds hydraulic capacity", "Kebutuhan melebihi kapasitas hidraulik"),
            "detail": L(
                f"Predicted need is {prediction['irrigation_mm']} mm, but only "
                f"{recommendation['recommended_mm']} mm is recommended.",
                f"Kebutuhan prediksi {prediction['irrigation_mm']} mm, tetapi hanya "
                f"{recommendation['recommended_mm']} mm yang direkomendasikan.",
            ),
        })

    return alerts


# ---------------- Simulated field response / feedback (PROTOTYPE) ----------------
def simulate_field_response(
    decision,               # "APPROVE", "MODIFY", atau "DELAY"
    operator_mm,            # jumlah irigasi yang diputuskan operator (mm)
    recommended_mm,         # jumlah yang disarankan SOMAT (mm)
    soil_moisture,          # kelembapan tanah sebelum irigasi (%)
    target_moisture=30,     # target kelembapan tanah (%) - CONTOH
    root_depth_mm=300,      # kedalaman zona akar (mm) - CONTOH
):
    """
    PROTOTYPE FEEDBACK LOGIC - simulasi sederhana, bukan model tanaman
    atau tanah yang sesungguhnya. Tujuannya menunjukkan alur
    Recommendation -> Operator Decision -> Simulated Field Response.
    """
    # Kenaikan kelembapan tanah (%) dari irigasi (konversi mm -> %)
    moisture_gain = operator_mm / root_depth_mm * 100
    new_moisture = min(45.0, soil_moisture + moisture_gain)

    if new_moisture < target_moisture - 2:
        status = "below"
    elif new_moisture <= target_moisture + 5:
        status = "on"
    else:
        status = "above"

    # Pesan umpan balik ke sistem SOMAT (kode + selisih; teks dibuat saat tampil)
    difference = operator_mm - recommended_mm
    if decision == "APPROVE":
        learning = {"kind": "approve", "diff": 0.0}
    elif decision == "DELAY":
        learning = {"kind": "delay", "diff": 0.0}
    elif difference > 0:
        learning = {"kind": "more", "diff": float(difference)}
    else:
        learning = {"kind": "less", "diff": float(difference)}

    return {
        "new_moisture": round(new_moisture, 1),
        "status": status,
        "learning": learning,
    }


# ---------------- Sensor simulasi (PROTOTYPE) ----------------
SENSORS = [
    {"sensor_id": "SM-01", "sensor_type": "soil_moisture", "location": "Petak 1", "unit": "%"},
    {"sensor_id": "SM-02", "sensor_type": "soil_moisture", "location": "Petak 2", "unit": "%"},
    {"sensor_id": "SM-03", "sensor_type": "soil_moisture", "location": "Petak 3", "unit": "%"},
    {"sensor_id": "SM-04", "sensor_type": "soil_moisture", "location": "Petak 4", "unit": "%"},
    {"sensor_id": "SM-05", "sensor_type": "soil_moisture", "location": "Petak 5", "unit": "%"},
    {"sensor_id": "SM-06", "sensor_type": "soil_moisture", "location": "Petak 6", "unit": "%"},
    {"sensor_id": "WL-01", "sensor_type": "water_level", "location": "Depan pintu tersier", "unit": "m"},
    {"sensor_id": "RF-01", "sensor_type": "rainfall",
     "location": "Stasiun hujan eksternal (simulasi; nanti BMKG/BBWS)", "unit": "mm"},
]


@st.cache_data(ttl=300, show_spinner=False)
def generate_sensor_readings(hours=168, seed=7):
    """
    PROTOTYPE: membangkitkan pembacaan sensor SIMULASI per jam.
    Bukan data sensor nyata. Saat sensor sungguhan tersedia, fungsi ini
    diganti dengan pembaca data sensor; bagian lain tidak perlu berubah.
    """
    rng = np.random.default_rng(seed)
    times = pd.date_range(end=pd.Timestamp.now().floor("h"), periods=hours, freq="h")

    # Hujan per jam: jarang terjadi, kadang deras
    rain = np.where(rng.random(hours) < 0.04, rng.gamma(2.0, 3.0, hours), 0.0)

    values = {}

    # 6 sensor kelembapan tanah: turun karena penguapan, naik saat hujan
    for k in range(1, 7):
        sm = np.zeros(hours)
        sm[0] = rng.normal(31, 2)
        for i in range(1, hours):
            evap = 0.05 if 8 <= times[i].hour <= 16 else 0.02  # siang lebih cepat
            sm[i] = np.clip(sm[i - 1] - evap + 0.3 * rain[i], 12, 45)
        values[f"SM-{k:02d}"] = sm + rng.normal(0, 0.15, hours)

    # Muka air: naik sedikit setelah hujan + gelombang pelan + noise
    recent_rain = pd.Series(rain).rolling(6, min_periods=1).sum().to_numpy()
    wl = 1.10 + 0.015 * recent_rain + 0.03 * np.sin(np.arange(hours) / 12)
    wl = wl + rng.normal(0, 0.01, hours)
    values["WL-01"] = np.clip(wl, 0.6, 1.8)

    values["RF-01"] = rain

    # Susun menjadi satu tabel panjang
    frames = []
    for s in SENSORS:
        v = values[s["sensor_id"]].copy()
        missing = rng.random(hours) < 0.01      # sekitar 1% data hilang
        if s["sensor_id"] == "SM-04":
            missing[-5:] = True                 # SM-04 mati 5 jam terakhir
        v[missing] = np.nan
        frames.append(pd.DataFrame({
            "timestamp": times,
            "sensor_id": s["sensor_id"],
            "sensor_type": s["sensor_type"],
            "location": s["location"],
            "value": np.round(v, 2),
            "unit": s["unit"],
            "status": np.where(np.isnan(v), "NO DATA", "OK"),
        }))
    return pd.concat(frames, ignore_index=True)


# ---------------- Ringkasan sensor -> kondisi terbaru ----------------
def summarize_sensors(sensor_df):
    """Mengubah pembacaan sensor per jam menjadi kondisi terbaru untuk SOMAT."""
    ok = sensor_df[sensor_df["status"] == "OK"]

    # Kelembapan tanah: ambil pembacaan valid terakhir tiap sensor, lalu rata-rata
    sm_last = (
        ok[ok["sensor_type"] == "soil_moisture"]
        .sort_values("timestamp")
        .groupby("sensor_id")
        .tail(1)
    )
    soil_moisture = float(sm_last["value"].mean())

    # Muka air: pembacaan valid terakhir WL-01
    wl = ok[ok["sensor_type"] == "water_level"].sort_values("timestamp")
    water_level = float(wl["value"].iloc[-1])

    # Hujan: jumlah 24 jam terakhir
    rf = ok[ok["sensor_type"] == "rainfall"].sort_values("timestamp")
    rainfall_24h = float(rf["value"].tail(24).sum())

    # Kualitas data: persentase pembacaan valid
    data_quality = 100 * len(ok) / len(sensor_df)

    return {
        "soil_moisture": round(soil_moisture, 1),
        "water_level": round(water_level, 2),
        "rainfall": round(rainfall_24h, 1),
        "sensors_used": int(sm_last["sensor_id"].nunique()),
        "data_quality": round(data_quality, 1),
    }


# ---------------- Status sensor (online/offline) ----------------
def sensor_status_table(sensor_df, offline_after_hours=3):
    """Menentukan tiap sensor Online atau Offline dari pembacaan valid terakhir."""
    now = sensor_df["timestamp"].max()
    ok = sensor_df[sensor_df["status"] == "OK"]
    last_ok = ok.groupby("sensor_id")["timestamp"].max()

    rows = []
    for s in SENSORS:
        last = last_ok.get(s["sensor_id"])
        if last is None or (now - last) > pd.Timedelta(hours=offline_after_hours):
            state = "Offline"
        else:
            state = "Online"
        rows.append({
            "Sensor": s["sensor_id"],
            "Jenis": s["sensor_type"],
            "Lokasi": s["location"],
            "Status": state,
            "Data valid terakhir": last,
        })
    return pd.DataFrame(rows)


# ============================================================
# SOMAT UI v2 — responsive layout, light/dark mode, animated
# metrics, modern navigation, and interactive sensor donut.
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "assets" / "somat_logo.png"
IRRIGATION_LOGIN_PATH = BASE_DIR / "assets" / "irrigation_login.jpg"
PLOTLY_CONFIG = {
    # Semua kontrol modebar tetap tersedia kecuali tombol Zoom (ikon kaca pembesar).
    # Drag default tetap untuk zoom timeframe; tombol Pan bersifat toggle.
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["zoom2d"],
    "displaylogo": False,
    "responsive": False,
    "scrollZoom": False,
}

if "page" not in st.session_state:
    st.session_state["page"] = "login"
if "light_mode" not in st.session_state:
    st.session_state["light_mode"] = False
if "decision_log" not in st.session_state:
    st.session_state["decision_log"] = []
if "show_modify" not in st.session_state:
    st.session_state["show_modify"] = False
if "sb_collapsed" not in st.session_state:
    st.session_state["sb_collapsed"] = False
if "user" not in st.session_state:
    st.session_state["user"] = None

# ---- Pulihkan sesi setelah refresh browser ----
# 1) Preferensi tampilan dari URL (?page=...&theme=...&sb=...&lang=...) sekali per sesi browser.
# 2) Pengguna dari cookie sesi (token acak; di database hanya hash-nya tersimpan).
_PAGES_OK = APP_PAGE_KEYS + ("account", "admin")
if not st.session_state.get("_prefs_loaded"):
    st.session_state["_prefs_loaded"] = True
    _qp = st.query_params
    if _qp.get("theme") in ("light", "dark"):
        st.session_state["light_mode"] = _qp.get("theme") == "light"
    if _qp.get("sb") in ("0", "1"):
        st.session_state["sb_collapsed"] = _qp.get("sb") == "1"
    if _qp.get("page") in _PAGES_OK:
        st.session_state["_want_page"] = _qp.get("page")
sync_browser_session()   # pulihkan sesi dari token di browser (localStorage), bila ada

# Batas tidak aktif: tanpa interaksi > 30 menit -> keluar otomatis.
if st.session_state.get("user"):
    _t = time.time()
    if _t - st.session_state.get("_last_activity", _t) > IDLE_SECONDS:
        audit("session_timeout")
        logout()
        st.session_state["_expired"] = True
    else:
        st.session_state["_last_activity"] = _t
        _stok = st.session_state.get("_session_token")
        if DB_ACTIVE and _stok and _t - st.session_state.get("_touched", 0) > 60:
            try:
                touch_session(_stok)
            except Exception:
                pass
            st.session_state["_touched"] = _t
# Status sidebar (False = lebar penuh, True = mini-sidebar ikon saja). Dipakai CSS & menu.
COLLAPSED = bool(st.session_state["sb_collapsed"])

IS_DARK = not bool(st.session_state.get("light_mode", False))
THEME = {
    "dark": IS_DARK,
    "bg": "#0B1220" if IS_DARK else "#F4F7FB",
    "panel": "#111B2C" if IS_DARK else "#FFFFFF",
    "panel2": "#0F1A2A" if IS_DARK else "#F8FAFD",
    "sidebar": "#080F1A" if IS_DARK else "#FFFFFF",
    "text": "#E8EEF8" if IS_DARK else "#172033",
    "muted": "#94A3B8" if IS_DARK else "#667085",
    "border": "#24324A" if IS_DARK else "#DCE3ED",
    "grid": "rgba(148,163,184,.12)" if IS_DARK else "rgba(71,85,105,.12)",
}

# Ikon tombol tema (SVG di-encode untuk dipakai di CSS).
# Mode gelap -> ikon matahari (pindah ke terang); mode terang -> ikon bulan.
# FIX 2: kedua ikon digambar simetris di kanvas 24x24 dengan pusat (12,12),
# stroke & ukuran sama, tanpa rotasi, supaya tepat di tengah tombol bulat.
if IS_DARK:
    _theme_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='#F59E0B' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
        "<circle cx='12' cy='12' r='4' fill='#FBBF24'/>"
        "<path d='M12 2v2M12 20v2M2 12h2M20 12h2"
        "M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41"
        "M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41'/></svg>"
    )
else:
    # Bulan sabit (Lucide "moon"); digeser sedikit agar pusat visualnya di (12,12).
    _theme_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke-linecap='round' stroke-linejoin='round'>"
        "<g transform='translate(.9 -.9)'>"
        "<path d='M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z' fill='#F8D96B' "
        "stroke='#EAB308' stroke-width='2'/></g></svg>"
    )
THEME_ICON = quote(_theme_svg, safe="")


def _chevron_icon(direction):
    """Ikon panah ganda (chevrons-left / chevrons-right) untuk tombol sidebar."""
    path = ("m11 17-5-5 5-5M18 17l-5-5 5-5" if direction == "left"
            else "m6 17 5-5-5-5M13 17l5-5-5-5")
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        f"stroke='{THEME['text']}' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>"
        f"<path d='{path}'/></svg>"
    )
    return quote(svg, safe="")


@st.cache_resource(show_spinner=False)
def _logo_b64():
    """Logo diperkecil (maks. 160 px) lalu di-cache. Sebelumnya file asli ~118 KB di-embed
    beberapa kali pada setiap rerun, memperlambat perpindahan tab."""
    for cand in (
        LOGO_PATH,
        Path.cwd() / "assets" / "somat_logo.png",
        BASE_DIR / "somat_logo.png",
        Path.cwd() / "somat_logo.png",
    ):
        try:
            if cand.exists():
                data = cand.read_bytes()
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        im = im.convert("RGBA")
                        im.thumbnail((160, 160))
                        buf = io.BytesIO()
                        im.save(buf, "PNG", optimize=True)
                        data = buf.getvalue()
                except Exception:
                    pass
                return base64.b64encode(data).decode("ascii")
        except OSError:
            pass
    return ""


# Logo cadangan (SVG) jika file assets/somat_logo.png belum ada.
LOGO_FALLBACK = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='0' y2='1'%3E"
    "%3Cstop offset='0' stop-color='%2338BDF8'/%3E%3Cstop offset='1' stop-color='%232F80ED'/%3E"
    "%3C/linearGradient%3E%3C/defs%3E"
    "%3Cpath d='M32 3C32 3 11 26 11 40a21 21 0 0 0 42 0C53 26 32 3 32 3Z' fill='url(%23g)'/%3E"
    "%3Cpath d='M32 52c0-10 3-17 12-22-1 11-5 19-12 22Z' fill='%2322A55B'/%3E"
    "%3Cpath d='M32 52c0-8-3-13-10-16 0 8 4 14 10 16Z' fill='%2384CC16'/%3E"
    "%3C/svg%3E"
)


logo_b64 = _logo_b64()
LOGO_SRC = f"data:image/png;base64,{logo_b64}" if logo_b64 else LOGO_FALLBACK


@st.cache_resource(show_spinner=False)
def _irrigation_image_b64():
    for candidate in (IRRIGATION_LOGIN_PATH, BASE_DIR / "irrigation_login.jpg", Path.cwd() / "assets" / "irrigation_login.jpg"):
        try:
            if candidate.exists():
                return base64.b64encode(candidate.read_bytes()).decode("ascii")
        except OSError:
            pass
    return ""


_irrigation_b64 = _irrigation_image_b64()
IRRIGATION_SRC = f"data:image/jpeg;base64,{_irrigation_b64}" if _irrigation_b64 else ""

# Warna seri yang jelas terlihat di mode gelap maupun terang.
SERIES_COLORS = ["#22A55B", "#2F80ED", "#E87924", "#A855F7", "#E4565C", "#06B6D4"]


def apply_plot_theme(fig, height=None):
    """Terapkan tema terang/gelap SOMAT ke grafik Plotly.

    Semua warna (judul, sumbu, legenda, garis) ditulis eksplisit supaya tetap
    terbaca di mode gelap maupun terang, dan judul tidak terlalu besar.
    """
    fig.update_layout(
        template="plotly_dark" if IS_DARK else "plotly_white",
        colorway=SERIES_COLORS,
        paper_bgcolor=THEME["panel"],
        plot_bgcolor=THEME["panel"],
        font=dict(color=THEME["text"], size=12),
        title=dict(
            font=dict(size=15, color=THEME["text"]),
            x=0.02, xanchor="left", y=0.97, yanchor="top",
        ),
        legend=dict(font=dict(size=11, color=THEME["text"]), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=THEME["panel2"], font=dict(color=THEME["text"]), bordercolor=THEME["border"]),
        dragmode="zoom",
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=THEME["muted"],
            activecolor="#2F80ED",
        ),
    )
    if height:
        fig.update_layout(height=height)
    axis_style = dict(
        gridcolor=THEME["grid"], zerolinecolor=THEME["grid"],
        linecolor=THEME["border"],
        tickfont=dict(color=THEME["muted"], size=11),
        title_font=dict(color=THEME["text"], size=12),
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    return fig


def make_combo_chart(data):
    """Grafik kondisi terbaru: garis (kelembapan, muka air) + batang (hujan)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=data["date"], y=data["rainfall"], name=L("Rainfall (mm)", "Curah hujan (mm)"),
            marker_color="#7C93B5" if IS_DARK else "#9FB3CF", opacity=0.85,
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["soil_moisture"], mode="lines+markers",
            name=L("Soil moisture (%)", "Kelembapan tanah (%)"), line=dict(color="#22A55B", width=3),
        ),
        secondary_y=False,
    )
    # Muka air dikali 30 agar sebanding di sumbu kiri; nilai asli tampil saat hover.
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["water_level"] * 30, mode="lines+markers",
            name=L("Water level (m, x30 scale)", "Tinggi muka air (m, skala x30)"),
            line=dict(color="#2F80ED", width=3),
            customdata=data["water_level"],
            hovertemplate="%{customdata:.2f} m<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.update_layout(
        height=360,
        # Ruang ekstra di dalam grafik agar sumbu kanan dan batang terakhir tidak terpotong.
        margin=dict(l=76, r=84, t=44, b=58),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    if len(data):
        x0 = pd.to_datetime(data["date"]).min() - pd.Timedelta(hours=12)
        x1 = pd.to_datetime(data["date"]).max() + pd.Timedelta(hours=12)
        fig.update_xaxes(range=[x0, x1], automargin=True)
    fig.update_yaxes(
        title=dict(text=L("Soil moisture (%) / water level (scaled)", "Kelembapan (%) / muka air (skala)"), font=dict(size=12, color=THEME["text"]), standoff=8),
        secondary_y=False, automargin=True,
    )
    fig.update_yaxes(
        title=dict(text=L("Rainfall (mm)", "Curah hujan (mm)"), font=dict(size=12, color=THEME["text"]), standoff=8),
        secondary_y=True, automargin=True,
    )
    return apply_plot_theme(fig)


def make_animated_line(data, column, title, y_label, color="#22A55B"):
    """Grafik garis tren.

    FIX 3: grafik langsung tampil LENGKAP (seluruh data sudah tergambar) tanpa
    animasi masuk. `frames` hanya dipakai oleh tombol "Replay" yang SENGAJA
    ditekan pengguna; tidak ada autoplay dan tidak ada transisi otomatis.
    """
    x = list(data["date"])
    y = [float(v) for v in data[column]]
    n = len(x)
    fig = go.Figure(
        data=[go.Scatter(
            x=x, y=y, mode="lines+markers",
            line=dict(color=color, width=3), marker=dict(size=6),
            name=title,
        )],
        frames=[
            go.Frame(data=[go.Scatter(
                x=x[:k], y=y[:k], mode="lines+markers",
                line=dict(color=color, width=3), marker=dict(size=6),
            )])
            for k in range(1, n + 1)
        ],
    )
    pad = (max(y) - min(y)) * 0.15 or 1
    fig.update_layout(
        title=title,
        height=320,
        margin=dict(l=10, r=10, t=64, b=10),
        transition=dict(duration=0),
        xaxis=dict(range=[x[0], x[-1]], title=L("Date", "Tanggal")),
        yaxis=dict(range=[min(y) - pad, max(y) + pad], title=y_label),
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.02, y=1.0, xanchor="left", yanchor="bottom",
            bgcolor=THEME["panel2"], bordercolor=THEME["border"],
            font=dict(color=THEME["text"], size=11),
            buttons=[dict(
                label=L("▶ Replay", "▶ Putar ulang"), method="animate",
                args=[None, dict(
                    frame=dict(duration=55, redraw=True),
                    transition=dict(duration=0),
                    fromcurrent=False,
                )],
            )],
        )],
    )
    return apply_plot_theme(fig)


def render_plotly_interactive(fig, height=None, auto_play=False, animation_opts=None, key_prefix="chart"):
    """Render Plotly in a fixed-height responsive SOMAT frame.

    The frame never changes size when modebar tools are toggled. Only the
    plot viewport/range changes. A ResizeObserver keeps the plot responsive
    when the Streamlit sidebar is collapsed/expanded and also scales the
    modebar just enough to keep every available button inside the frame.
    """
    if not hasattr(render_plotly_interactive, "_seq"):
        render_plotly_interactive._seq = 0
    render_plotly_interactive._seq += 1
    div_id = f"somatPlot_{key_prefix}_{render_plotly_interactive._seq}"
    h = int(height or getattr(fig.layout, "height", None) or 340)
    frame_h = h + 8
    apply_plot_theme(fig, height=h)
    fig.update_layout(autosize=True, transition=dict(duration=0))
    plot_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        auto_play=auto_play,
        animation_opts=animation_opts,
        config=PLOTLY_CONFIG,
        div_id=div_id,
    )
    body = f"""
    <style>
      *{{box-sizing:border-box}}
      html,body{{margin:0;padding:0;width:100%;height:{frame_h}px;background:transparent;overflow:hidden;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}}
      .chart-shell{{position:relative;height:{frame_h}px!important;min-height:{frame_h}px!important;max-height:{frame_h}px!important;width:100%!important;min-width:0;border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});padding:2px 3px 1px;}}
      .chart-shell .js-plotly-plot{{position:relative!important;width:100%!important;max-width:100%!important;height:{h}px!important;min-height:{h}px!important;max-height:{h}px!important;}}
      .chart-shell .plot-container,.chart-shell .svg-container{{width:100%!important;max-width:100%!important;height:{h}px!important;min-height:{h}px!important;max-height:{h}px!important;}}
      .modebar{{top:7px!important;right:7px!important;left:auto!important;display:flex!important;flex-wrap:nowrap!important;justify-content:flex-end!important;align-items:center!important;width:max-content!important;max-width:none!important;gap:0!important;white-space:nowrap!important;transform-origin:top right!important;z-index:20!important;}}
      .modebar-group{{display:flex!important;align-items:center!important;margin:0 0 0 1px!important;white-space:nowrap!important;flex:0 0 auto!important;}}
      .modebar-btn{{width:25px!important;height:25px!important;padding:2px!important;border-radius:7px!important;display:grid!important;place-items:center!important;flex:0 0 25px!important;}}
      .modebar-btn svg{{width:16px!important;height:16px!important;}}
      .modebar-btn:hover{{background:{THEME['panel2']}!important;}}
      @media(max-width:460px){{
        .modebar{{top:5px!important;right:5px!important}}
        .modebar-btn{{width:22px!important;height:22px!important;padding:1px!important;flex-basis:22px!important}}
        .modebar-btn svg{{width:14px!important;height:14px!important}}
        .modebar-group{{margin-left:0!important}}
      }}
    </style>
    <div class="chart-shell" id="shell_{div_id}">{plot_html}</div>
    <script>
      (() => {{
        const gd = document.getElementById('{div_id}');
        const shell = document.getElementById('shell_{div_id}');
        if (!gd || !shell) return;
        const FIXED_H = {h};
        let resizeRAF = 0;

        const lockGeometry = () => {{
          shell.style.height = '{frame_h}px';
          shell.style.minHeight = '{frame_h}px';
          shell.style.maxHeight = '{frame_h}px';
          gd.style.height = FIXED_H + 'px';
          gd.style.minHeight = FIXED_H + 'px';
          gd.style.maxHeight = FIXED_H + 'px';
          gd.style.width = '100%';
          const pc = gd.querySelector('.plot-container');
          const svg = gd.querySelector('.svg-container');
          [pc, svg].forEach(el => {{
            if (!el) return;
            el.style.height = FIXED_H + 'px';
            el.style.minHeight = FIXED_H + 'px';
            el.style.maxHeight = FIXED_H + 'px';
            el.style.width = '100%';
            el.style.maxWidth = '100%';
          }});
        }};

        const fitModebar = () => {{
          const mb = gd.querySelector('.modebar');
          if (!mb) return;
          mb.style.transform = 'none';
          mb.style.transformOrigin = 'top right';
          const available = Math.max(1, gd.clientWidth - 16);
          const needed = Math.max(mb.scrollWidth || 0, mb.getBoundingClientRect().width || 0);
          if (needed > available) {{
            const scale = Math.max(0.56, Math.min(1, available / needed));
            mb.style.transform = `scale(${{scale}})`;
          }}
        }};

        let lastWidth = 0;
        const resizePlot = () => {{
          cancelAnimationFrame(resizeRAF);
          resizeRAF = requestAnimationFrame(() => {{
            const w = Math.round(shell.getBoundingClientRect().width || 0);
            lockGeometry();
            if (w > 0 && Math.abs(w - lastWidth) > 1) {{
              lastWidth = w;
              try {{ Plotly.Plots.resize(gd); }} catch (_) {{}}
            }}
            lockGeometry();
            fitModebar();
          }});
        }};

        const bindDragToggles = () => {{
          const btns = [...gd.querySelectorAll('.modebar-btn')];
          const specs = [
            {{rx:/(^|\\s)pan(\\s|$)/i, mode:'pan'}},
            {{rx:/box select/i, mode:'select'}},
            {{rx:/lasso select/i, mode:'lasso'}},
          ];
          specs.forEach(spec => {{
            const btn = btns.find(b => spec.rx.test((b.getAttribute('data-title')||b.title||'').trim()));
            if (!btn || btn.dataset.somatBound === '1') return;
            btn.dataset.somatBound = '1';
            let wasActive = false;
            btn.addEventListener('pointerdown', () => {{
              wasActive = ((gd._fullLayout && gd._fullLayout.dragmode) || gd.layout.dragmode) === spec.mode;
            }}, true);
            btn.addEventListener('click', () => {{
              if (wasActive) requestAnimationFrame(() => Plotly.relayout(gd, {{dragmode:'zoom'}}));
              requestAnimationFrame(() => {{ lockGeometry(); fitModebar(); }});
            }});
          }});
        }};

        const settle = () => {{ lockGeometry(); bindDragToggles(); fitModebar(); }};
        setTimeout(settle, 40);
        setTimeout(settle, 160);
        setTimeout(settle, 360);
        gd.on('plotly_afterplot', () => requestAnimationFrame(settle));
        gd.on('plotly_relayout', () => requestAnimationFrame(() => {{ lockGeometry(); bindDragToggles(); fitModebar(); }}));

        if ('ResizeObserver' in window) {{
          const ro = new ResizeObserver(() => resizePlot());
          ro.observe(shell);
        }}
        window.addEventListener('resize', resizePlot, {{passive:true}});
      }})();
    </script>
    """
    components.html(body, height=frame_h + 6, scrolling=False)


def show_animated(fig, height=340):
    """Grafik tren dengan bingkai & perilaku pan yang sama.

    FIX 3: tanpa autoplay dan tanpa animation_opts, sehingga grafik langsung
    tampil dalam kondisi akhir setiap kali halaman dibuka / Streamlit rerun.
    """
    render_plotly_interactive(
        fig,
        height=height,
        auto_play=False,
        key_prefix="animated",
    )


def make_line_chart(data, column, title, y_label, bar=False):
    if bar:
        fig = px.bar(data, x="date", y=column, title=title, color_discrete_sequence=["#38A3F5"])
    else:
        fig = px.line(data, x="date", y=column, title=title, markers=True, color_discrete_sequence=["#22A55B"])
        fig.update_traces(line=dict(width=3), marker=dict(size=6))
    fig.update_layout(
        xaxis_title=L("Date", "Tanggal"),
        yaxis_title=y_label,
        height=320,
        margin=dict(l=10, r=10, t=56, b=10),
    )
    return apply_plot_theme(fig)


def render_counter_card(
    icon,
    title,
    note="",
    badge_text="",
    badge_kind="info",
    color="blue",
    target=None,
    decimals=0,
    prefix="",
    suffix="",
    value_text=None,
):
    """Card with a fresh 0→value counter animation on every Streamlit rerun/tab switch."""
    palette = {
        "green": ("#22A55B", "#0F2A24" if IS_DARK else "#F0FBF4"),
        "blue": ("#2F80ED", "#0F2440" if IS_DARK else "#F1F6FE"),
        "orange": ("#E87924", "#302012" if IS_DARK else "#FFF7ED"),
        "red": ("#E4565C", "#32191C" if IS_DARK else "#FFF1F2"),
    }
    accent, bg = palette.get(color, palette["blue"])
    badge_colors = {
        "ok": "#16884A",
        "warn": "#D85A10",
        "info": "#256FD1",
    }
    badge_bg = badge_colors.get(badge_kind, badge_colors["info"])
    safe_icon = html.escape(str(icon))
    safe_title = html.escape(str(title))
    safe_note = html.escape(str(note))
    safe_badge = html.escape(str(badge_text))
    safe_prefix = html.escape(str(prefix))
    safe_suffix = html.escape(str(suffix))

    if target is not None:
        numeric = float(target)
        value_html = (
            f'<span class="counter" data-target="{numeric}" data-decimals="{int(decimals)}" '
            f'data-prefix="{safe_prefix}" data-suffix="{safe_suffix}">{safe_prefix}0{safe_suffix}</span>'
        )
    else:
        value_html = html.escape(str(value_text if value_text is not None else ""))

    badge_html = f'<span class="badge">{safe_badge}</span>' if badge_text else ""

    card = f'''
    <div class="metric-card">
      <div class="title"><span class="ico">{safe_icon}</span>{safe_title}</div>
      <div class="value">{value_html}</div>
      <div class="foot">
        {badge_html}
        <span class="note">{safe_note}</span>
      </div>
    </div>
    <style>
      *{{box-sizing:border-box}}
      body{{margin:0;background:transparent;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:{THEME['text']};}}
      .metric-card{{height:150px;background:{bg};border:1px solid {THEME['border']};border-top:3px solid {accent};border-radius:16px;padding:14px 16px;box-shadow:0 8px 24px rgba(2,8,23,{'.20' if IS_DARK else '.06'});overflow:hidden;animation:up .45s ease-out both}}
      .title{{font-size:.82rem;color:{THEME['muted']};font-weight:750;line-height:1.25;min-height:34px;display:flex;gap:7px;align-items:flex-start}}
      .ico{{font-size:1rem;line-height:1}}
      .value{{font-size:1.8rem;font-weight:850;line-height:1.15;color:{THEME['text']};margin:5px 0 9px;white-space:nowrap}}
      .foot{{display:flex;gap:7px;align-items:center;min-height:24px;overflow:hidden}}
      .badge{{background:{badge_bg};color:white;padding:3px 8px;border-radius:999px;font-size:.68rem;font-weight:800;white-space:nowrap}}
      .note{{font-size:.72rem;color:{THEME['muted']};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
      @keyframes up{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
      @media(max-width:480px){{.metric-card{{height:142px}}.value{{font-size:1.65rem}}}}
      @media(prefers-reduced-motion:reduce){{.metric-card{{animation:none}}}}
    </style>
    <script>
      const el=document.querySelector('.counter');
      if(el){{
        const target=parseFloat(el.dataset.target||'0');
        const dec=parseInt(el.dataset.decimals||'0');
        const pre=el.dataset.prefix||''; const suf=el.dataset.suffix||'';
        const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const duration=reduced?0:850;
        const start=performance.now();
        const fmt=(v)=>pre+v.toFixed(dec)+suf;
        function tick(now){{
          const p=duration===0?1:Math.min(1,(now-start)/duration);
          const eased=1-Math.pow(1-p,3);
          el.textContent=fmt(target*eased);
          if(p<1)requestAnimationFrame(tick); else el.textContent=fmt(target);
        }}
        requestAnimationFrame(tick);
      }}
    </script>
    '''
    components.html(card, height=154, scrolling=False)


def render_card_rows(cards, columns=4):
    """Render card specs in Streamlit columns; columns stack naturally on mobile."""
    for start in range(0, len(cards), columns):
        batch = cards[start:start + columns]
        cols = st.columns(len(batch), gap="small")
        for col, spec in zip(cols, batch):
            with col:
                render_counter_card(**spec)


def show_sensor_donut(n_online, n_offline):
    """Donut status sensor di bingkai yang sama dengan grafik tren (tanpa animasi masuk)."""
    total = max(1, int(n_online + n_offline))
    online_pct = 100 * n_online / total
    offline_pct = 100 * n_offline / total
    fig = go.Figure(
        data=[go.Pie(
            labels=["Online", "Offline", ""],
            values=[n_online, n_offline, 0],
            hole=0.62,
            sort=False,
            direction="clockwise",
            rotation=0,
            marker=dict(colors=["#55C985", "#8F8B80", "rgba(0,0,0,0)"]),
            pull=[0, 0, 0],
            showlegend=False,
            customdata=[f"{online_pct:.1f}%", f"{offline_pct:.1f}%", ""],
            text=[f"{online_pct:.1f}%", f"{offline_pct:.1f}%", ""],
            textinfo="text",
            textfont=dict(color=THEME["text"], size=14),
            hovertemplate="%{label}: %{customdata}<extra></extra>",
        )],
    )
    fig.update_layout(
        title=dict(text=L("Sensor Status Distribution", "Distribusi Status Sensor"), x=0.02, xanchor="left", font=dict(size=15, color=THEME["text"])),
        height=315,
        autosize=True,
        transition=dict(duration=0),
        margin=dict(l=8, r=8, t=55, b=5),
        annotations=[dict(
            text=f"{total}<br>Sensor", x=0.5, y=0.5,
            showarrow=False, font=dict(size=19, color=THEME["text"]),
        )],
    )
    apply_plot_theme(fig)
    plot_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        auto_play=False,
        config=PLOTLY_CONFIG,
        div_id="sensorDonut",
    )
    body = f'''
    <style>
      *{{box-sizing:border-box}}
      html,body{{margin:0;padding:0;width:100%;height:376px;background:transparent;overflow:hidden;font-family:Inter,ui-sans-serif,system-ui;color:{THEME['text']}}}
      .chart-shell{{position:relative;height:376px!important;min-height:376px!important;max-height:376px!important;width:100%!important;min-width:0;border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};padding:2px 3px 1px;overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});transition:box-shadow .22s ease}}
      .chart-shell:hover{{box-shadow:0 10px 30px rgba(2,8,23,{'.22' if IS_DARK else '.08'})}}
      #sensorDonut,.plot-container,.svg-container{{height:315px!important;min-height:315px!important;max-height:315px!important;width:100%!important;max-width:100%!important}}
      .modebar{{top:7px!important;right:7px!important;left:auto!important;width:max-content!important;max-width:none!important;display:flex!important;flex-wrap:nowrap!important;justify-content:flex-end!important;white-space:nowrap!important;transform-origin:top right!important}}
      .modebar-group{{display:flex!important;margin-left:1px!important;flex:0 0 auto!important}}
      .modebar-btn{{width:25px!important;height:25px!important;padding:2px!important;border-radius:7px!important;flex:0 0 25px!important}}
      .modebar-btn svg{{width:16px!important;height:16px!important}}
      .legend{{display:flex;justify-content:center;gap:8px;margin-top:-5px}}
      .legend button{{appearance:none;border:1px solid {THEME['border']};background:{THEME['panel2']};color:{THEME['text']};padding:6px 10px;border-radius:999px;cursor:pointer;font-size:12px;font-weight:750;transition:.18s ease}}
      .legend button:hover,.legend button.active{{transform:translateY(-1px);border-color:#2F80ED;box-shadow:0 5px 12px rgba(47,128,237,.16)}}
      .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
    </style>
    <div class="chart-shell" id="donutShell">
      {plot_html}
      <div class="legend">
        <button data-i="0"><span class="dot" style="background:#55C985"></span>Online&nbsp; {online_pct:.1f}%</button>
        <button data-i="1"><span class="dot" style="background:#8F8B80"></span>Offline&nbsp; {offline_pct:.1f}%</button>
      </div>
    </div>
    <script>
      const gd=document.getElementById('sensorDonut');
      const shell=document.getElementById('donutShell');
      const buttons=[...document.querySelectorAll('.legend button')];
      let selected=-1, hover=-1, currentPull=[0,0,0], raf=null, resizeRAF=0;
      const ease=t=>t<.5 ? 4*t*t*t : 1-Math.pow(-2*t+2,3)/2;
      function lockGeometry(){{
        shell.style.height='376px'; shell.style.minHeight='376px'; shell.style.maxHeight='376px';
        gd.style.height='315px'; gd.style.minHeight='315px'; gd.style.maxHeight='315px'; gd.style.width='100%';
      }}
      function fitModebar(){{
        const mb=gd.querySelector('.modebar'); if(!mb)return;
        mb.style.transform='none';
        const room=Math.max(1,gd.clientWidth-16), need=Math.max(mb.scrollWidth||0,mb.getBoundingClientRect().width||0);
        if(need>room)mb.style.transform=`scale(${{Math.max(.56,Math.min(1,room/need))}})`;
      }}
      function resizePlot(){{
        cancelAnimationFrame(resizeRAF);
        resizeRAF=requestAnimationFrame(()=>{{lockGeometry();try{{Plotly.Plots.resize(gd)}}catch(_){{}}lockGeometry();fitModebar();}});
      }}
      function desiredPull(){{
        const p=[0,0,0];
        if(selected>=0)p[selected]=0.14;
        if(hover>=0 && hover!==selected)p[hover]=0.052;
        return p;
      }}
      function animatePull(target,duration=300){{
        if(raf)cancelAnimationFrame(raf);
        const start=currentPull.slice(), t0=performance.now();
        const step=now=>{{
          const q=Math.min(1,(now-t0)/duration), e=ease(q);
          currentPull=start.map((v,i)=>v+(target[i]-v)*e);
          Plotly.restyle(gd,{{pull:[currentPull]}},[0]);
          if(q<1)raf=requestAnimationFrame(step); else {{currentPull=target.slice();raf=null;}}
        }};
        raf=requestAnimationFrame(step);
      }}
      function sync(duration=300){{animatePull(desiredPull(),duration);}}
      function select(idx){{
        selected=(selected===idx)?-1:idx;
        buttons.forEach((b,j)=>b.classList.toggle('active',j===selected));
        sync(340);
      }}
      gd.on('plotly_hover',e=>{{const i=e.points?.[0]?.pointNumber;hover=(i<2?i:-1);sync(170);}});
      gd.on('plotly_unhover',()=>{{hover=-1;sync(200);}});
      gd.on('plotly_click',e=>{{const i=e.points?.[0]?.pointNumber;if(i<2)select(i);}});
      gd.on('plotly_afterplot',()=>requestAnimationFrame(()=>{{lockGeometry();fitModebar();}}));
      buttons.forEach(b=>b.addEventListener('click',()=>select(parseInt(b.dataset.i))));
      if('ResizeObserver' in window){{const ro=new ResizeObserver(resizePlot);ro.observe(shell);ro.observe(document.documentElement);}}
      window.addEventListener('resize',resizePlot,{{passive:true}});
      setTimeout(()=>{{lockGeometry();fitModebar();}},60);
      setTimeout(resizePlot,240);
    </script>
    '''
    components.html(body, height=382, scrolling=False)


# ---------------- Universal interactive table ----------------
# Terjemahan nama kolom dan nilai tabel (hanya untuk tampilan; data asli tidak berubah).
# Format: kunci -> (English, Indonesia)
COLUMN_LABELS = {
    "date": ("Date", "Tanggal"), "timestamp": ("Time", "Waktu"),
    "soil_moisture": ("Soil moisture (%)", "Kelembapan tanah (%)"),
    "rainfall": ("Rainfall (mm)", "Curah hujan (mm)"),
    "et0": ("ET0 (mm/day)", "ET0 (mm/hari)"),
    "water_level": ("Water level (m)", "Tinggi muka air (m)"),
    "available_discharge": ("Available discharge (m³/s)", "Debit tersedia (m³/s)"),
    "crop_water_requirement": ("Crop water requirement (mm/day)", "Kebutuhan air tanaman (mm/hari)"),
    "sensor_id": ("Sensor ID", "ID Sensor"), "sensor_type": ("Sensor type", "Jenis sensor"),
    "location": ("Location", "Lokasi"), "unit": ("Unit", "Satuan"),
    "value": ("Value", "Nilai"), "status": ("Status", "Status"), "Result": ("Result", "Hasil"),
    # kolom tabel status sensor
    "Sensor": ("Sensor", "Sensor"), "Jenis": ("Type", "Jenis"), "Lokasi": ("Location", "Lokasi"),
    "Status": ("Status", "Status"), "Data valid terakhir": ("Last valid data", "Data valid terakhir"),
    # kolom cek hidraulik dan kejadian
    "Pemeriksaan": ("Check", "Pemeriksaan"), "Nilai": ("Value", "Nilai"), "Batas": ("Limit", "Batas"),
    "Waktu": ("Time", "Waktu"), "Sumber": ("Source", "Sumber"),
    "Kejadian": ("Event", "Kejadian"), "Tingkat": ("Level", "Tingkat"),
}
VALUE_LABELS = {
    "soil_moisture": ("Soil moisture", "Kelembapan tanah"), "water_level": ("Water level", "Muka air"),
    "rainfall": ("Rainfall", "Curah hujan"),
    "OK": ("Valid", "Valid"), "NO DATA": ("No data", "Tidak ada data"),
    "PASS": ("PASS", "LOLOS"), "FAIL": ("FAIL", "GAGAL"),
    "Petak 1": ("Plot 1", "Petak 1"), "Petak 2": ("Plot 2", "Petak 2"), "Petak 3": ("Plot 3", "Petak 3"),
    "Petak 4": ("Plot 4", "Petak 4"), "Petak 5": ("Plot 5", "Petak 5"), "Petak 6": ("Plot 6", "Petak 6"),
    "Depan pintu tersier": ("In front of the tertiary gate", "Depan pintu tersier"),
    "Stasiun hujan eksternal (simulasi; nanti BMKG/BBWS)": (
        "External rain station (simulated; later BMKG/BBWS)",
        "Stasiun hujan eksternal (simulasi; nanti BMKG/BBWS)"),
}


def _val_label(v):
    pair = VALUE_LABELS.get(v)
    return L(*pair) if pair else v


def render_interactive_table(data, *, key="table", hide_index=True, max_height=420):
    """Tabel interaktif: urut, ubah lebar kolom, pilih kolom, cari, layar penuh, unduh CSV."""
    df_t = pd.DataFrame(data).copy()
    df_t = df_t.rename(columns={k: L(*v) for k, v in COLUMN_LABELS.items()})
    for c in df_t.columns:
        if pd.api.types.is_object_dtype(df_t[c]) or pd.api.types.is_string_dtype(df_t[c]):
            df_t[c] = df_t[c].map(lambda v: _val_label(v) if isinstance(v, str) else v)
    if not hide_index:
        idx_name = df_t.index.name or "No."
        df_t.insert(0, idx_name, df_t.index + 1 if pd.api.types.is_integer_dtype(df_t.index) else df_t.index)
    for c in df_t.columns:
        if pd.api.types.is_datetime64_any_dtype(df_t[c]):
            df_t[c] = df_t[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df_t[c] = df_t[c].map(lambda v: "" if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
    columns = [str(c) for c in df_t.columns]
    records = [{str(k): v for k, v in r.items()} for r in df_t.to_dict(orient="records")]
    payload = json.dumps({"columns": columns, "rows": records}, ensure_ascii=False, default=str).replace("</", "<\\/")
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key))
    visible_rows = min(max(len(records), 1), 9)
    outer_h = min(max_height, 122 + visible_rows * 39)
    T_LEFT, T_RIGHT = L("Scroll left", "Geser ke kiri"), L("Scroll right", "Geser ke kanan")
    T_NAV, T_COLS = L("Table navigation", "Navigasi tabel"), L("Choose columns", "Pilih kolom")
    T_CSV, T_FIND = L("Download CSV", "Unduh CSV"), L("Search", "Cari")
    T_ZOOM, T_PH = L("Zoom table", "Zoom tabel"), L("Search in table...", "Cari di tabel...")
    T_EMPTY, T_LOC = L("No matching data", "Tidak ada data yang cocok"), L("en-US", "id-ID")
    body = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>
    :root{{--panel:{THEME['panel']};--panel2:{THEME['panel2']};--text:{THEME['text']};--muted:{THEME['muted']};--border:{THEME['border']};--blue:#2F80ED;--shadow:0 12px 28px rgba(2,8,23,{'.24' if IS_DARK else '.08'});}}
    *{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:transparent;color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;overflow:hidden}}
    .frame{{position:relative;height:{outer_h-6}px;border:1px solid var(--border);border-radius:14px;background:var(--panel);overflow:hidden;box-shadow:var(--shadow)}}
    .viewport{{position:absolute;inset:0;overflow:auto;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,.45) transparent}}
    .viewport::-webkit-scrollbar{{width:5px;height:5px}}.viewport::-webkit-scrollbar-track{{background:transparent}}.viewport::-webkit-scrollbar-thumb{{background:rgba(148,163,184,.45);border-radius:999px}}
    table{{border-collapse:separate;border-spacing:0;table-layout:fixed;min-width:100%;width:max-content;font-size:13px;background:var(--panel)}}
    th,td{{height:38px;padding:8px 12px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:110px;max-width:520px}}
    th{{position:sticky;top:0;z-index:5;background:var(--panel2);font-weight:800;color:var(--text);cursor:pointer;user-select:none;padding-right:25px}}
    th:hover{{background:rgba(47,128,237,.12)}} tr:hover td{{background:rgba(47,128,237,.06)}}
    .sort{{position:absolute;right:9px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--muted)}}
    .resize{{position:absolute;right:-3px;top:0;width:8px;height:100%;cursor:col-resize;z-index:8}}.resize:hover{{background:rgba(47,128,237,.35)}}
    .toolbar{{position:absolute;right:12px;top:8px;z-index:30;display:flex;align-items:center;justify-content:center;gap:2px;height:42px;padding:5px 6px;border-radius:13px;background:var(--panel2);border:1px solid color-mix(in srgb,var(--border) 72%,transparent);box-shadow:0 12px 28px rgba(2,8,23,.28);opacity:0;transform:translateY(-8px) scale(.965);transform-origin:top right;pointer-events:none;transition:opacity .18s ease,transform .22s cubic-bezier(.2,.8,.2,1),box-shadow .18s ease}}
    .frame:hover .toolbar,.toolbar.open,.frame:fullscreen .toolbar{{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}}
    .tool{{width:32px;height:32px;min-width:32px;min-height:32px;padding:0;border:0;border-radius:9px;background:transparent;color:var(--muted);cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:0;transition:background .15s ease,color .15s ease,transform .15s ease}}
    .tool svg{{display:block;width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}}
    .tool:hover,.tool.active{{color:var(--text);background:rgba(47,128,237,.13)}}.tool:active{{transform:scale(.94)}}
    .searchbox{{position:absolute;right:10px;top:50px;z-index:22;width:min(310px,calc(100% - 20px));display:none;background:var(--panel2);border:1px solid var(--border);padding:7px;border-radius:10px;box-shadow:var(--shadow)}}
    .searchbox.open{{display:block}}.searchbox input{{width:100%;border:1px solid var(--border);border-radius:8px;background:var(--panel);color:var(--text);padding:8px 10px;outline:none}}.searchbox input:focus{{border-color:var(--blue)}}
    .chooser{{position:absolute;right:10px;top:50px;z-index:22;max-height:270px;min-width:235px;overflow:auto;display:none;background:var(--panel2);border:1px solid var(--border);padding:8px;border-radius:10px;box-shadow:var(--shadow)}}.chooser.open{{display:block}}
    .chooser label{{display:flex;align-items:center;gap:8px;padding:6px 5px;font-size:12px;cursor:pointer;border-radius:7px}}.chooser label:hover{{background:rgba(47,128,237,.1)}}
    .scrollbtn{{position:absolute;top:50%;transform:translateY(-50%);z-index:18;width:30px;height:54px;border:1px solid var(--border);background:var(--panel2);color:var(--text);border-radius:10px;box-shadow:var(--shadow);cursor:pointer;display:none;place-items:center;font-size:20px}}.frame:hover .scrollbtn.show{{display:grid}}.left{{left:7px}}.right{{right:7px}}
    .empty{{padding:40px;color:var(--muted);text-align:center}}
    .frame:fullscreen{{width:100vw;height:100vh;border-radius:0}}.frame:fullscreen .viewport{{inset:0}}.frame:fullscreen .toolbar{{opacity:1;pointer-events:auto}}
    </style></head><body><div class='frame' id='frame_{safe_key}'><div class='viewport' id='vp_{safe_key}'><table id='tbl_{safe_key}'><thead></thead><tbody></tbody></table></div>
    <button class='scrollbtn left' title='{T_LEFT}'>‹</button><button class='scrollbtn right' title='{T_RIGHT}'>›</button>
    <div class='toolbar' aria-label='{T_NAV}'>
      <button class='tool columns' title='{T_COLS}' aria-label='{T_COLS}'><svg viewBox='0 0 24 24'><path d='M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6S2.5 12 2.5 12Z'/><circle cx='12' cy='12' r='2.7'/></svg></button>
      <button class='tool download' title='{T_CSV}' aria-label='{T_CSV}'><svg viewBox='0 0 24 24'><path d='M12 3v11'/><path d='m8 10 4 4 4-4'/><path d='M5 19h14'/></svg></button>
      <button class='tool search' title='{T_FIND}' aria-label='{T_FIND}'><svg viewBox='0 0 24 24'><circle cx='10.5' cy='10.5' r='5.5'/><path d='m15 15 5 5'/></svg></button>
      <button class='tool full' title='{T_ZOOM}' aria-label='{T_ZOOM}'><svg viewBox='0 0 24 24'><path d='M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5'/></svg></button>
    </div>
    <div class='searchbox'><input type='search' placeholder='{T_PH}'></div><div class='chooser'></div></div>
    <script>
    const DATA={payload};const frame=document.getElementById('frame_{safe_key}'),vp=document.getElementById('vp_{safe_key}'),tbl=document.getElementById('tbl_{safe_key}');
    const thead=tbl.tHead||tbl.createTHead(),tbody=tbl.tBodies[0]||tbl.createTBody(),chooser=frame.querySelector('.chooser'),searchbox=frame.querySelector('.searchbox'),searchInput=searchbox.querySelector('input');
    let cols=DATA.columns.map((name,i)=>({{name,visible:true,width:Math.max(110,Math.min(260,String(name).length*8+44)),i}}));let rows=DATA.rows.slice(),sortCol=-1,sortDir=1,query='';
    function escCSV(v){{const s=String(v??'');return /[\\",\\n]/.test(s)?'\\"'+s.replaceAll('\\"','\\"\\"')+'\\"':s}}
    function parse(v){{if(v===null||v===undefined||v==='')return {{t:3,v:''}};const n=Number(v);if(Number.isFinite(n)&&String(v).trim()!=='')return {{t:0,v:n}};const d=Date.parse(v);if(!Number.isNaN(d)&&/[-/:]/.test(String(v)))return {{t:1,v:d}};return {{t:2,v:String(v).toLocaleLowerCase('{T_LOC}')}}}}
    function filtered(){{let a=rows.slice();if(query)a=a.filter(r=>cols.some(c=>c.visible&&String(r[c.name]??'').toLocaleLowerCase('{T_LOC}').includes(query)));if(sortCol>=0){{const c=cols[sortCol];a.sort((x,y)=>{{const aa=parse(x[c.name]),bb=parse(y[c.name]);if(aa.t!==bb.t)return (aa.t-bb.t)*sortDir;return (aa.v<bb.v?-1:aa.v>bb.v?1:0)*sortDir}})}}return a}}
    function renderHead(){{thead.innerHTML='';const tr=document.createElement('tr');cols.forEach((c,i)=>{{const th=document.createElement('th');th.dataset.i=i;th.style.width=c.width+'px';th.style.minWidth=c.width+'px';th.style.maxWidth=c.width+'px';th.style.display=c.visible?'table-cell':'none';const tx=document.createElement('span');tx.textContent=c.name;th.appendChild(tx);const si=document.createElement('span');si.className='sort';si.textContent=sortCol===i?(sortDir>0?'▲':'▼'):'↕';th.appendChild(si);const grip=document.createElement('span');grip.className='resize';th.appendChild(grip);th.onclick=e=>{{if(e.target===grip)return;sortDir=sortCol===i?-sortDir:1;sortCol=i;render()}};grip.onpointerdown=e=>{{e.preventDefault();e.stopPropagation();const x=e.clientX,w=c.width;grip.setPointerCapture(e.pointerId);grip.onpointermove=ev=>{{c.width=Math.max(90,Math.min(520,w+ev.clientX-x));applyWidths()}};grip.onpointerup=()=>{{grip.onpointermove=null;updateArrows()}}}};tr.appendChild(th)}});thead.appendChild(tr)}}
    function applyWidths(){{const hs=thead.querySelectorAll('th');hs.forEach((th,i)=>{{const c=cols[i];th.style.width=c.width+'px';th.style.minWidth=c.width+'px';th.style.maxWidth=c.width+'px';th.style.display=c.visible?'table-cell':'none'}});tbody.querySelectorAll('tr').forEach(tr=>[...tr.children].forEach((td,i)=>{{const c=cols[i];td.style.width=c.width+'px';td.style.minWidth=c.width+'px';td.style.maxWidth=c.width+'px';td.style.display=c.visible?'table-cell':'none'}}));updateArrows()}}
    function renderBody(){{tbody.innerHTML='';const data=filtered();if(!data.length){{const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=Math.max(1,cols.filter(c=>c.visible).length);td.className='empty';td.textContent='{T_EMPTY}';tr.appendChild(td);tbody.appendChild(tr);return}}data.forEach(r=>{{const tr=document.createElement('tr');cols.forEach(c=>{{const td=document.createElement('td');td.textContent=r[c.name]??'';td.title=String(r[c.name]??'');td.style.width=c.width+'px';td.style.minWidth=c.width+'px';td.style.maxWidth=c.width+'px';td.style.display=c.visible?'table-cell':'none';tr.appendChild(td)}});tbody.appendChild(tr)}})}}
    function renderChooser(){{chooser.innerHTML='';cols.forEach((c,i)=>{{const lab=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.checked=c.visible;cb.onchange=()=>{{if(!cb.checked&&cols.filter(x=>x.visible).length===1){{cb.checked=true;return}}c.visible=cb.checked;render()}};const sp=document.createElement('span');sp.textContent=c.name;lab.append(cb,sp);chooser.appendChild(lab)}})}}
    function render(){{renderHead();renderBody();renderChooser();requestAnimationFrame(updateArrows)}}
    function updateArrows(){{const ov=vp.scrollWidth>vp.clientWidth+2,l=frame.querySelector('.left'),r=frame.querySelector('.right');l.classList.toggle('show',ov&&vp.scrollLeft>2);r.classList.toggle('show',ov&&vp.scrollLeft<vp.scrollWidth-vp.clientWidth-2)}}
    frame.querySelector('.left').onclick=()=>vp.scrollBy({{left:-Math.max(220,vp.clientWidth*.55),behavior:'smooth'}});frame.querySelector('.right').onclick=()=>vp.scrollBy({{left:Math.max(220,vp.clientWidth*.55),behavior:'smooth'}});vp.addEventListener('scroll',updateArrows,{{passive:true}});
    const colBtn=frame.querySelector('.columns'),findBtn=frame.querySelector('.search');
    function syncToolState(){{colBtn.classList.toggle('active',chooser.classList.contains('open'));findBtn.classList.toggle('active',searchbox.classList.contains('open'));}}
    colBtn.onclick=e=>{{e.stopPropagation();chooser.classList.toggle('open');searchbox.classList.remove('open');syncToolState()}};findBtn.onclick=e=>{{e.stopPropagation();searchbox.classList.toggle('open');chooser.classList.remove('open');syncToolState();if(searchbox.classList.contains('open'))searchInput.focus()}};searchInput.oninput=()=>{{query=searchInput.value.trim().toLocaleLowerCase('{T_LOC}');renderBody();updateArrows()}};
    frame.querySelector('.download').onclick=()=>{{const visible=cols.filter(c=>c.visible),data=filtered(),csv=[visible.map(c=>escCSV(c.name)).join(','),...data.map(r=>visible.map(c=>escCSV(r[c.name])).join(','))].join('\\n');const b=new Blob([csv],{{type:'text/csv;charset=utf-8;'}}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='somat_{safe_key}.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};
    frame.querySelector('.full').onclick=async()=>{{try{{if(!document.fullscreenElement)await frame.requestFullscreen();else await document.exitFullscreen()}}catch(_){{}}}};
    document.addEventListener('click',e=>{{if(!chooser.contains(e.target)&&!e.target.closest('.columns'))chooser.classList.remove('open');if(!searchbox.contains(e.target)&&!e.target.closest('.search'))searchbox.classList.remove('open');syncToolState()}});document.addEventListener('fullscreenchange',()=>setTimeout(updateArrows,60));
    if('ResizeObserver'in window)new ResizeObserver(updateArrows).observe(frame);render();
    </script></body></html>"""
    components.html(body, height=outer_h, scrolling=False)


# ---------------- CSS tambahan: menu sidebar + mode terang ----------------
_EXTRA_CSS = """
/* ===== Menu sidebar: rata kiri, font lebih besar ===== */
[data-testid="stSidebar"] .stButton{width:100%;}
[data-testid="stSidebar"] .stButton button{
  justify-content:flex-start!important;text-align:left!important;
  padding:.62rem 1rem!important;min-height:50px!important;
  background:__PANEL2__;color:__TEXT__;border:1px solid __BORDER__;border-radius:12px;
}
[data-testid="stSidebar"] .stButton button>div,
[data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{
  width:100%!important;display:flex!important;justify-content:flex-start!important;text-align:left!important;
}
[data-testid="stSidebar"] .stButton button p{
  font-size:1rem!important;font-weight:700!important;line-height:1.25!important;
  text-align:left!important;width:100%;margin:0!important;color:inherit!important;
}
[data-testid="stSidebar"] .stButton button[kind="primary"],
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(135deg,#2F80ED,#1E63C8)!important;border-color:#2F80ED!important;
  box-shadow:0 6px 16px rgba(47,128,237,.32);
}
[data-testid="stSidebar"] .stButton button[kind="primary"] p,
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
[data-testid="stSidebar"] .stButton button:hover{border-color:#2F80ED!important;}
.side-brand{display:flex;align-items:center;gap:14px;padding:14px 2px 14px;}
.side-brand img{width:92px;height:auto;max-height:84px;object-fit:contain;flex:0 0 auto;}
.side-brand-name{font-size:2.1rem;font-weight:850;letter-spacing:-.02em;line-height:1.05;color:__TEXT__;}
.side-brand-sub{font-size:.92rem;line-height:1.35;color:__MUTED__;margin-top:4px;}
[data-testid="stSidebar"] h4{font-size:1.15rem!important;margin-top:.6rem!important;}
[data-testid="stSidebar"] [data-testid="stAlert"]{font-size:1.02rem!important;}
[data-testid="stSidebar"] [data-testid="stAlert"] p{font-size:1.02rem!important;}
[data-testid="stSidebar"] .stButton button{min-height:48px!important;padding:.5rem .9rem!important;}
[data-testid="stSidebar"] .stButton button p{font-size:1rem!important;}
.side-info-title{font-size:1.1rem!important;}
.side-info-muted{font-size:.9rem!important;}
.side-info-line{font-size:.98rem!important;}
.side-flow{font-size:.98rem!important;line-height:1.65!important;}
/* judul halaman lebih tenang */
.block-container h2,[data-testid="stHeading"] h2{font-size:1.9rem!important;line-height:1.25!important;}
.block-container h3,[data-testid="stHeading"] h3{font-size:1.35rem!important;}
/* tombol aksi operator */
.block-container [data-testid="stHorizontalBlock"] .stButton button{min-height:52px;border-radius:12px;font-weight:800;}
.block-container [data-testid="stHorizontalBlock"] .stButton button p{font-size:1.05rem!important;font-weight:800!important;letter-spacing:.04em;}
.block-container .stButton button[kind="primary"],.block-container .stButton button[data-testid="stBaseButton-primary"]{box-shadow:0 6px 16px rgba(47,128,237,.3);}
/* hanya satu tombol panah sidebar yang tampil */
.stApp:has([data-testid="stSidebar"][aria-expanded="true"]) [data-testid="stExpandSidebarButton"]{display:none!important;}
.stApp:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stSidebarCollapseButton"]{display:none!important;}

/* ===== HP / layar kecil: font dan jarak diperkecil ===== */
@media(max-width:800px){
  html{font-size:14px;}
  .block-container{padding:3.2rem .8rem 2rem!important;}
  h1{font-size:1.25rem!important;}
  h2,[data-testid="stHeading"] h2{font-size:1.3rem!important;line-height:1.25!important;}
  h3,[data-testid="stHeading"] h3{font-size:1.1rem!important;}
  [data-testid="stCaptionContainer"] p{font-size:.8rem!important;}
  [data-testid="stAlert"] p,[data-testid="stAlert"]{font-size:.85rem!important;}
  .somat-header{gap:10px;}
  .somat-header img{width:46px!important;height:auto!important;}
  .somat-header h1{font-size:1.15rem!important;line-height:1.2!important;}
  .somat-header p{font-size:.78rem!important;}
  .status-panel{padding:12px 14px;}
  .status-row{font-size:.85rem!important;}
  [data-testid="stSidebar"] .stButton button p{font-size:.95rem!important;}
  .side-brand img{width:64px;}
  .side-brand-name{font-size:1.6rem;}
  .side-brand-sub{font-size:.8rem;}
  .st-key-theme_icon{top:.5rem!important;right:.6rem!important;}
  .st-key-lang_btn{top:.5rem!important;right:calc(.6rem + 46px)!important;}
}
"""

_LIGHT_CSS = """
/* ===== Mode terang: paksa semua komponen Streamlit ikut berubah ===== */
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"]{
  background:__BG__!important;color:__TEXT__!important;color-scheme:light;
}
[data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;}
[data-testid="stToolbar"] *,[data-testid="stHeader"] svg{color:__TEXT__!important;fill:__TEXT__;}
h1,h2,h3,h4,h5,h6,[data-testid="stHeading"],[data-testid="stHeading"] *,
[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] *,
[data-testid="stWidgetLabel"],[data-testid="stWidgetLabel"] *,label,label *{color:__TEXT__!important;}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:__MUTED__!important;}
.somat-header h1{color:__TEXT__!important;}
.somat-header p{color:__MUTED__!important;}
.side-info-muted{color:__MUTED__!important;}
.status-title,.status-row,.status-row *{color:__TEXT__!important;}
.st-ok{color:#16884A!important;} .st-warn{color:#D85A10!important;}
/* kotak peringatan */
[data-testid="stAlert"]{border:1px solid __BORDER__;}
[data-testid="stAlert"] *{color:inherit!important;}
[data-testid="stAlertContentWarning"]{color:#7A4B00;}
[data-testid="stAlertContentSuccess"]{color:#14532D;}
[data-testid="stAlertContentInfo"]{color:#1E3A8A;}
[data-testid="stAlertContentError"]{color:#7F1D1D;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){background:#FFF6DD!important;border-color:#F3D98B;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){background:#E8F8EE!important;border-color:#A7E0BC;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]){background:#E8F1FD!important;border-color:#AFCBF5;}
div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){background:#FDECEC!important;border-color:#F3B4B4;}
/* expander */
div[data-testid="stExpander"],div[data-testid="stExpander"] details{background:__PANEL__!important;border-color:__BORDER__!important;}
div[data-testid="stExpander"] summary,div[data-testid="stExpander"] summary *{color:__TEXT__!important;}
/* input */
input,textarea,[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="base-input"]{
  background:__PANEL__!important;color:__TEXT__!important;border-color:__BORDER__!important;
}
[data-testid="stNumberInput"] button{background:__PANEL2__!important;color:__TEXT__!important;}
/* tombol (di luar sidebar) */
.stButton button,[data-testid="stFormSubmitButton"]>button{background:__PANEL__;color:__TEXT__!important;border:1px solid __BORDER__;}
.stButton button p,[data-testid="stFormSubmitButton"]>button p{color:inherit!important;}
.stButton button[kind="primary"],.stButton button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{background:#2F80ED!important;border-color:#2F80ED!important;}
.stButton button[kind="primary"] p,.stButton button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
/* sidebar */
[data-testid="stSidebar"],[data-testid="stSidebarContent"]{background:__SIDEBAR__!important;}
[data-testid="stSidebar"] *{color:__TEXT__;}
[data-testid="stSidebar"] [data-testid="stAlert"] *{color:inherit!important;}
[data-testid="stSidebar"] .stButton button[kind="primary"] *,
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] *{color:#FFFFFF!important;}
hr{border-color:__BORDER__!important;}
code{background:__PANEL2__!important;color:__TEXT__!important;}
"""


def _fill_css(css):
    return (css.replace("__BG__", THEME["bg"]).replace("__PANEL__", THEME["panel"])
               .replace("__PANEL2__", THEME["panel2"]).replace("__SIDEBAR__", THEME["sidebar"])
               .replace("__TEXT__", THEME["text"]).replace("__MUTED__", THEME["muted"])
               .replace("__BORDER__", THEME["border"]))


EXTRA_CSS = _fill_css(_EXTRA_CSS) + ("" if IS_DARK else _fill_css(_LIGHT_CSS))


# ---------------- Global responsive styling ----------------
# FIX 1 - lebar sidebar mengikuti status (penuh / mini-ikon). Di desktop sidebar
# SELALU tampil (tidak pernah disembunyikan); tombol panah bawaan Streamlit
# disembunyikan di desktop dan diganti satu tombol kustom (.st-key-sb_toggle).
SB_W = "72px" if COLLAPSED else "21rem"
MAIN_MAXW = "min(100%,1840px)!important" if COLLAPSED else "1540px"
SB_ICON = _chevron_icon("right" if COLLAPSED else "left")

SB_CSS = f"""
      @media(min-width:801px){{
        [data-testid="stSidebar"],[data-testid="stSidebar"][aria-expanded="false"],[data-testid="stSidebar"][aria-expanded="true"]{{
          width:{SB_W}!important;min-width:{SB_W}!important;max-width:{SB_W}!important;
          transform:none!important;margin-left:0!important;visibility:visible!important;
        }}
        [data-testid="stSidebarCollapseButton"],[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"]{{display:none!important;}}
      }}
"""

CONTROLS_CSS = f"""
      /* ===== FIX 2: tombol tema bulat sempurna, ikon tepat di tengah ===== */
      .st-key-theme_icon{{position:fixed!important;top:.62rem!important;right:.8rem!important;z-index:999999!important;width:38px!important;height:38px!important;pointer-events:auto!important;}}
      .st-key-theme_icon button{{
        position:relative!important;box-sizing:border-box!important;
        width:38px!important;height:38px!important;min-width:38px!important;min-height:38px!important;
        aspect-ratio:1/1;padding:0!important;margin:0!important;flex:none!important;
        border-radius:50%!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel']}!important;color:transparent!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:flex!important;align-items:center!important;justify-content:center!important;
        font-size:0!important;line-height:0!important;transform:none!important;
        transition:border-color .15s ease,box-shadow .15s ease!important;
      }}
      .st-key-theme_icon button>*{{display:none!important;}}
      .st-key-theme_icon button::before{{
        content:"";position:absolute;left:50%;top:50%;width:20px;height:20px;
        transform:translate(-50%,-50%);background:center/contain no-repeat url("data:image/svg+xml,{THEME_ICON}");
      }}
      .st-key-theme_icon button:hover,.st-key-theme_icon button:focus-visible{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;transform:none!important;}}
      /* ===== FIX 1: SATU tombol buka/tutup sidebar (ikon panah ganda) ===== */
      .st-key-sb_toggle{{position:fixed!important;top:.62rem!important;left:calc({SB_W} - 19px)!important;z-index:999998!important;width:38px!important;height:38px!important;}}
      .st-key-sb_toggle button{{
        position:relative!important;box-sizing:border-box!important;
        width:38px!important;height:38px!important;min-width:38px!important;min-height:38px!important;
        padding:0!important;margin:0!important;flex:none!important;border-radius:50%!important;
        border:1px solid {THEME['border']}!important;background:{THEME['panel2']}!important;color:transparent!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:flex!important;align-items:center!important;justify-content:center!important;
        font-size:0!important;line-height:0!important;transform:none!important;
        transition:border-color .15s ease,box-shadow .15s ease!important;
      }}
      .st-key-sb_toggle button>*{{display:none!important;}}
      .st-key-sb_toggle button::before{{
        content:"";position:absolute;left:50%;top:50%;width:18px;height:18px;
        transform:translate(-50%,-50%);background:center/contain no-repeat url("data:image/svg+xml,{SB_ICON}");
      }}
      .st-key-sb_toggle button:hover,.st-key-sb_toggle button:focus-visible{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;transform:none!important;}}
      @media(max-width:800px){{.st-key-sb_toggle{{display:none!important;}}}}
      /* ===== Tombol bahasa EN / ID ===== */
      .st-key-lang_btn{{position:fixed!important;top:.62rem!important;right:calc(.8rem + 46px)!important;z-index:999999!important;height:38px!important;width:auto!important;}}
      .st-key-lang_btn button{{
        box-sizing:border-box!important;height:38px!important;min-height:38px!important;padding:0 14px!important;
        border-radius:999px!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel']}!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:flex!important;align-items:center!important;justify-content:center!important;
        transform:none!important;
      }}
      .st-key-lang_btn button p{{font-size:.82rem!important;font-weight:800!important;letter-spacing:.04em;line-height:1!important;margin:0!important;color:{THEME['text']}!important;white-space:nowrap;}}
      .st-key-lang_btn button:hover{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;}}
"""

MINI_TEMPLATE = """
/* ===== FIX 1: mini-sidebar (hanya ikon) di desktop ===== */
@media(min-width:801px){
  [data-testid="stSidebarContent"]{overflow-x:hidden!important;}
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding:.4rem 0 1rem!important;}
  [data-testid="stSidebar"] [data-testid="stElementContainer"],
  [data-testid="stSidebar"] [data-testid="stMarkdown"]{width:100%!important;max-width:100%!important;display:flex!important;justify-content:center!important;}
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.55rem!important;}
  [data-testid="stSidebar"] .stButton,[data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"]{width:auto!important;display:flex;justify-content:center;}
  [data-testid="stSidebar"] .stButton button{
    width:46px!important;min-width:46px!important;height:46px!important;min-height:46px!important;
    padding:0!important;justify-content:center!important;border-radius:12px!important;
  }
  [data-testid="stSidebar"] .stButton button>div,
  [data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{width:auto!important;justify-content:center!important;}
  [data-testid="stSidebar"] .stButton button p{font-size:1.3rem!important;line-height:1!important;text-align:center!important;width:auto!important;}
  [data-testid="stSidebar"] .stButton button:hover{transform:none!important;}
  .side-brand.mini{justify-content:center;padding:10px 0 8px;gap:0;}
  .side-brand.mini img{width:34px!important;max-height:40px;}
}
"""
MINI_CSS = _fill_css(MINI_TEMPLATE) if COLLAPSED else ""

# Tooltip (help=...) ikut tema: latar panel, teks kontras (di mode terang sebelumnya teks gelap di latar gelap).
TOOLTIP_CSS = f"""
      [data-testid="stTooltipContent"],[data-baseweb="tooltip"] [data-testid="stTooltipContent"]{{
        background:{THEME['panel2']}!important;color:{THEME['text']}!important;
        border:1px solid {THEME['border']}!important;border-radius:8px!important;
        box-shadow:0 8px 24px rgba(2,8,23,{'.35' if IS_DARK else '.12'})!important;
      }}
      [data-testid="stTooltipContent"] *{{color:{THEME['text']}!important;}}
      .st-key-somat_sess{{position:absolute!important;width:0!important;height:0!important;overflow:hidden!important;margin:0!important;}}
      [data-baseweb="tooltip"] > div,[data-baseweb="popover"] > div{{background:transparent!important;}}
"""


st.markdown(
    f'''
    <style>
      :root{{--somat-bg:{THEME['bg']};--somat-panel:{THEME['panel']};--somat-text:{THEME['text']};--somat-muted:{THEME['muted']};--somat-border:{THEME['border']};}}
      .stApp{{background:var(--somat-bg);color:var(--somat-text);}}
      [data-testid="stHeader"]{{background:transparent;}}
      [data-testid="stSidebar"]{{background:{THEME['sidebar']};border-right:1px solid {THEME['border']};}}
      {SB_CSS}
      [data-testid="stSidebarContent"]{{padding-top:.35rem!important;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,.48) transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar{{width:5px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-track{{background:transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb{{background:rgba(148,163,184,.42);border-radius:999px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb:hover{{background:rgba(148,163,184,.68);}}
      [data-testid="stSidebar"] *{{color:{THEME['text']};}}
      /* Panah bawaan Streamlit hanya dipakai di HP/layar kecil (drawer); di desktop dipakai tombol kustom. */
      @media(max-width:800px){{
      [data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"]{{
        display:flex!important;visibility:visible!important;opacity:1!important;position:fixed!important;top:.62rem!important;z-index:999998!important;
      }}
      [data-testid="stSidebarCollapseButton"]{{left:calc(21rem - 3rem)!important;}}
      [data-testid="stExpandSidebarButton"]{{left:.65rem!important;}}
      [data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"] button{{
        width:38px!important;height:38px!important;min-height:38px!important;padding:0!important;
        border-radius:10px!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel2']}!important;color:{THEME['text']}!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:grid!important;place-items:center!important;font-size:0!important;line-height:1!important;
      }}
      [data-testid="stSidebarCollapseButton"] button svg, [data-testid="stExpandSidebarButton"] button svg{{display:none!important;}}
      [data-testid="stSidebarCollapseButton"] button::before{{content:"«";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stExpandSidebarButton"] button::before{{content:"»";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stExpandSidebarButton"] button:hover{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.18)!important;}}
      }}
      {CONTROLS_CSS}
      .block-container{{padding-top:.75rem!important;padding-bottom:2.2rem!important;max-width:{MAIN_MAXW};}}
      p,li,label,.stMarkdown{{color:{THEME['text']};}}
      [data-testid="stCaptionContainer"] p{{color:{THEME['muted']}!important;}}
      hr{{border-color:{THEME['border']}!important;}}
      [data-testid="stSidebar"] .stButton button{{
        width:100%;justify-content:flex-start;border-radius:11px;min-height:42px;
        font-weight:700;border:1px solid {THEME['border']};transition:.18s ease;
      }}
      [data-testid="stSidebar"] .stButton button:hover{{transform:translateX(2px);border-color:#2F80ED;}}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:.45rem;}}
      [data-testid="stHorizontalBlock"]{{align-items:stretch!important;min-width:0!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"]{{flex:1 1 0!important;width:0!important;min-width:0!important;max-width:none!important;overflow:hidden!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"] iframe,
      [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stIFrame"]{{width:100%!important;max-width:100%!important;min-width:0!important;display:block!important;}}
      .side-info-card{{background:{THEME['panel2']};border:1px solid {THEME['border']};border-radius:14px;padding:12px 13px;margin-top:10px;box-shadow:0 6px 18px rgba(2,8,23,{'.15' if IS_DARK else '.04'});}}
      .side-info-title{{display:flex;gap:8px;align-items:center;font-size:.94rem;font-weight:820;margin:0 0 8px;color:{THEME['text']};}}
      .side-info-muted{{color:{THEME['muted']};font-size:.77rem;line-height:1.45;margin-bottom:6px;}}
      .side-info-line{{font-size:.82rem;line-height:1.55;color:{THEME['text']};}}
      .side-flow{{font-size:.81rem;line-height:1.55;color:{THEME['text']};letter-spacing:.002em;}}
      .side-profile{{display:flex;align-items:center;gap:11px;background:{THEME['panel2']};border:1px solid {THEME['border']};border-radius:14px;padding:10px 12px;margin-top:12px;min-width:0;}}
      .side-profile img,.side-profile-fallback{{width:42px;height:42px;min-width:42px;border-radius:50%;object-fit:cover;border:1px solid {THEME['border']};background:{THEME['panel']};}}
      .side-profile-fallback{{display:grid;place-items:center;font-weight:850;font-size:1rem;color:#fff!important;background:linear-gradient(135deg,#2563EB,#16A34A);}}
      .side-profile-name{{font-size:.91rem;font-weight:820;line-height:1.25;overflow-wrap:anywhere;color:{THEME['text']};}}
      .side-profile-caption{{font-size:.72rem;color:{THEME['muted']};margin-top:3px;}}
      .side-profile-mini{{display:flex;justify-content:center;margin:10px 0 4px;}}
      .side-profile-mini img,.side-profile-mini .side-profile-fallback{{width:40px;height:40px;border-radius:50%;object-fit:cover;}}
      .login-visual{{min-height:560px;height:100%;border-radius:24px;overflow:hidden;padding:26px 30px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;background-color:#0B1830;background-size:cover;background-position:center;box-shadow:0 18px 50px rgba(2,8,23,.22);}}
      .login-visual-brand{{display:flex;align-items:center;gap:12px;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.3);}}
      .login-visual-brand img{{width:66px;height:66px;object-fit:contain;filter:drop-shadow(0 4px 12px rgba(0,0,0,.25));}}
      .login-visual-brand strong{{display:block;font-size:1.3rem;letter-spacing:.04em;}}
      .login-visual-brand span{{display:block;font-size:.72rem;opacity:.9;max-width:260px;line-height:1.35;}}
      .login-visual-copy{{max-width:570px;color:#fff;text-shadow:0 2px 16px rgba(0,0,0,.35);}}
      .login-visual-copy small{{font-size:.72rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#BFE9FF;}}
      .login-visual-copy h2{{font-size:clamp(1.8rem,3vw,2.8rem);line-height:1.08;font-weight:850;letter-spacing:-.035em;color:#fff;margin:.65rem 0;}}
      .login-visual-copy p{{font-size:.98rem;line-height:1.6;color:rgba(255,255,255,.92);max-width:500px;margin:0;}}
      .login-visual-foot{{font-size:.75rem;color:rgba(255,255,255,.82);letter-spacing:.03em;}}
      .login-panel-brand{{display:flex;align-items:center;gap:12px;margin:2.4rem 0 1.5rem;}}
      .login-panel-brand img{{width:62px;height:62px;object-fit:contain;}}
      .login-panel-brand strong{{font-size:1.2rem;font-weight:900;letter-spacing:.035em;color:{THEME['text']};}}
      .login-panel-brand span{{display:block;font-size:.74rem;color:{THEME['muted']};line-height:1.35;}}
      .st-key-login_form [data-testid="stForm"],.st-key-login_form[data-testid="stForm"]{{background:{THEME['panel']};border:1px solid {THEME['border']};border-radius:18px;padding:1.15rem 1.25rem;box-shadow:0 12px 30px rgba(2,8,23,{'.16' if IS_DARK else '.06'});}}
      .st-key-login_form [data-testid="stFormSubmitButton"] button{{width:100%;min-height:44px;border-radius:11px;font-weight:800;}}
      div[data-testid="stExpander"]{{border-color:{THEME['border']};background:{THEME['panel']};border-radius:12px;}}
      [data-testid="stDataFrame"]{{border:1px solid {THEME['border']};border-radius:12px;overflow:hidden;}}
      [data-testid="stPlotlyChart"]{{border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});}}
      .main .block-container{{animation:somatContentIn .16s ease-out;}}
      @keyframes somatContentIn{{from{{opacity:.94;transform:translateY(2px)}}to{{opacity:1;transform:translateY(0)}}}}
      .somat-header{{display:flex;align-items:center;gap:14px;margin:0 0 10px;padding:4px 0 2px;}}
      @media(min-width:801px){{.somat-header{{padding-right:8.5rem;}}}}
      .somat-header img{{width:78px;height:70px;object-fit:contain;flex:0 0 auto;filter:drop-shadow(0 5px 14px rgba(0,90,160,.12));}}
      .somat-header h1{{font-size:clamp(1.55rem,2.2vw,2.45rem);line-height:1.08;margin:0;color:{THEME['text']};font-weight:850;letter-spacing:-.035em;}}
      .somat-header p{{margin:5px 0 0;color:{THEME['muted']};font-size:.93rem;}}
      .status-panel{{background:{THEME['panel']};border:1px solid {THEME['border']};border-radius:16px;padding:16px 18px;box-shadow:0 7px 20px rgba(2,8,23,{'.16' if IS_DARK else '.05'});}}
      .status-title{{font-weight:800;color:{THEME['text']};margin-bottom:8px;}}
      .status-row{{padding:5px 0;color:{THEME['text']};font-size:.92rem;}}
      .st-ok{{color:#22A55B;font-weight:900;}} .st-warn{{color:#E87924;font-weight:900;}}
      .sim-dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#2F80ED;margin-right:8px;animation:pulse 2s infinite;}}
      @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(47,128,237,.65)}}70%{{box-shadow:0 0 0 8px rgba(47,128,237,0)}}100%{{box-shadow:0 0 0 0 rgba(47,128,237,0)}}}}
      @media(max-width:800px){{
        [data-testid="stSidebar"]{{width:min(86vw,21rem)!important;min-width:min(86vw,21rem)!important;}}
        [data-testid="stSidebarCollapseButton"]{{left:calc(min(86vw,21rem) - 3rem)!important;}}
        .block-container{{padding-left:.75rem!important;padding-right:.75rem!important;padding-top:.45rem!important;}}
        .somat-header{{gap:9px;align-items:center}} .somat-header img{{width:58px;height:53px}}
        .somat-header p{{font-size:.8rem}} h1{{font-size:1.55rem!important}}
        [data-testid="stHorizontalBlock"]{{flex-wrap:wrap!important;gap:.5rem!important;}}
        [data-testid="stHorizontalBlock"] > [data-testid="column"]{{min-width:100%!important;max-width:100%!important;flex:1 1 100%!important;width:100%!important;overflow:visible!important;}}
      }}
      @media(prefers-reduced-motion:reduce){{.sim-dot{{animation:none}}}}
      {EXTRA_CSS}
      {MINI_CSS}
      {TOOLTIP_CSS}
    </style>
    ''',
    unsafe_allow_html=True,
)


# ---------------- Compact theme control ----------------
def _toggle_theme():
    st.session_state["light_mode"] = not bool(st.session_state.get("light_mode", False))


def _toggle_sidebar():
    st.session_state["sb_collapsed"] = not bool(st.session_state.get("sb_collapsed", False))


def _toggle_lang():
    new = "id" if st.session_state.get("lang", "en") == "en" else "en"
    st.session_state["lang"] = new
    st.query_params["lang"] = new


def _set_page(page_id):
    st.session_state["page"] = page_id


# Theme and language controls remain available on the login screen.
st.button(
    "Toggle theme",
    key="theme_icon",
    help=L("Switch to light mode", "Ganti ke light mode") if IS_DARK else L("Switch to dark mode", "Ganti ke dark mode"),
    on_click=_toggle_theme,
)
st.button(
    f"🌐 {LANG.upper()}",
    key="lang_btn",
    help=L("Switch to Bahasa Indonesia", "Ganti ke English"),
    on_click=_toggle_lang,
)




def _sync_url(with_page):
    """Simpan halaman, tema, sidebar & bahasa di URL supaya refresh kembali ke keadaan terakhir."""
    want = {
        "theme": "light" if st.session_state.get("light_mode") else "dark",
        "sb": "1" if COLLAPSED else "0",
        "lang": LANG,
    }
    if with_page:
        want["page"] = st.session_state["page"]
    for _k, _v in want.items():
        if st.query_params.get(_k) != _v:
            st.query_params[_k] = _v


def render_restoring_screen():
    """Tampil sebentar saat memeriksa sesi tersimpan (sebelum layar login)."""
    st.markdown('<div class="login-page-spacer"></div>', unsafe_allow_html=True)
    st.markdown(
        f'''<div style="text-align:center;padding:3rem 0;opacity:.9"><img src="{LOGO_SRC}" alt="SOMAT" style="width:64px">
        <p>{L("Checking your session…", "Memeriksa sesi Anda…")}</p></div>''',
        unsafe_allow_html=True,
    )
    if st.button(L("Go to sign in", "Ke halaman masuk"), key="skip_restore"):
        st.session_state["_restore_tried"] = True
        st.rerun()


def render_login_screen():
    'Login menjadi layar pertama; sidebar dan konten dashboard belum dirender.'
    st.markdown('<div class="login-page-spacer"></div>', unsafe_allow_html=True)
    left, right = st.columns([1.18, 0.82], gap="large", vertical_alignment="center")
    with left:
        if IRRIGATION_SRC:
            _bg = f"linear-gradient(180deg,rgba(5,18,38,.20) 0%,rgba(5,18,38,.84) 100%),url('{IRRIGATION_SRC}')"
        else:
            _bg = "linear-gradient(135deg,#0B3B65,#0F766E)"
        st.markdown(
            f'''<section class="login-visual" style="background-image:{_bg};">
              <div class="login-visual-brand"><img src="{LOGO_SRC}" alt="SOMAT logo"><div>
                <strong>SOMAT</strong><span>Smart Adaptive Irrigation Management System</span>
              </div></div>
              <div class="login-visual-copy"><small>SMART IRRIGATION · DATA · DECISION</small>
                <h2>{L("Smarter water management starts with better decisions.", "Pengelolaan air yang lebih cerdas dimulai dari keputusan yang lebih baik.")}</h2>
                <p>{L("Monitor field conditions, review irrigation recommendations, and keep operational decisions under human control.", "Pantau kondisi lahan, tinjau rekomendasi irigasi, dan pastikan keputusan operasional tetap berada di bawah kendali manusia.")}</p>
              </div>
              <div class="login-visual-foot">SOMAT · Smart Adaptive Irrigation Management System</div>
            </section>''',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f'''<div class="login-panel-brand"><img src="{LOGO_SRC}" alt="Logo SOMAT"><div>
              <strong>SOMAT</strong><span>Smart Adaptive Irrigation Management System</span>
            </div></div>''',
            unsafe_allow_html=True,
        )
        st.header(L("Welcome back", "Selamat datang kembali"))
        st.caption(L("Sign in with your registered account to access the dashboard.", "Masuk menggunakan akun terdaftar untuk mengakses dashboard."))
        if st.session_state.pop("_expired", False):
            st.warning(L("Your session expired after 30 minutes of inactivity. Please sign in again.",
                         "Sesi berakhir setelah 30 menit tidak aktif. Silakan masuk kembali."))
        render_login_form("login_form")
        st.caption(L("Access is managed by the SOMAT administrator.", "Hak akses dikelola oleh administrator SOMAT."))


# Login gate: no dashboard, sidebar, or application data is rendered before authentication.
if not DB_ACTIVE:
    st.session_state["user"] = None
else:
    refresh_user()

if (not current_user()) and DB_ACTIVE and _SESS_COMPONENT is not None and not st.session_state.get("_restore_tried"):
    render_restoring_screen()
    st.stop()

if not current_user():
    st.session_state["page"] = "login"
    _sync_url(False)
    render_login_screen()
    st.stop()

# Once authenticated, enforce tab-level access on every server request.
_u_gate = refresh_user()
if not _u_gate:
    st.session_state["page"] = "login"
    render_login_screen()
    st.stop()

_pg = st.session_state.get("page", "overview")
if _pg == "login":
    st.session_state["page"] = "overview"
elif _pg == "account":
    pass
elif _pg == "admin":
    # Halaman admin bukan bagian APP_PAGE_KEYS, jadi dicek terpisah (sebelumnya jatuh ke cabang
    # berikutnya dan selalu dialihkan ke overview).
    if not is_admin():
        st.session_state["page"] = _first_accessible_page(_u_gate)
elif _pg not in APP_PAGE_KEYS or not can_access_page(_pg, _u_gate):
    st.session_state["page"] = _first_accessible_page(_u_gate)
_sync_url(True)

# One compact custom sidebar toggle is shown only after login.
st.button(
    "Toggle sidebar",
    key="sb_toggle",
    help=L("Expand sidebar", "Perluas sidebar") if COLLAPSED else L("Collapse sidebar", "Perkecil sidebar"),
    on_click=_toggle_sidebar,
)

# ---------------- Role-aware sidebar ----------------
_PAGE_NAV = [
    ("overview", "📊", L("Overview", "Ringkasan")),
    ("monitoring", "📡", L("Sensor Monitoring", "Monitoring Sensor")),
    ("prediction", "💧", L("Prediction & Recommendation", "Prediksi & Rekomendasi")),
    ("alerts", "🚨", L("Alerts", "Peringatan")),
    ("operator", "👷", L("Operator Decision", "Keputusan Operator")),
]
nav_items = [(pid, icon, label) for pid, icon, label in _PAGE_NAV if can_access_page(pid)]
nav_items.append(("account", "👤", L("My Account", "Akun Saya")))
if is_admin():
    nav_items.append(("admin", "🛡️", L("Admin", "Administrasi")))

with st.sidebar:
    if COLLAPSED:
        # Mini-sidebar: hanya logo kecil di tengah + ikon menu.
        st.markdown(
            f"""<div class="side-brand mini"><img src="{LOGO_SRC}" alt="SOMAT"></div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""<div class="side-brand"><img src="{LOGO_SRC}" alt="Logo SOMAT">
            <div><div class="side-brand-name">SOMAT</div>
            <div class="side-brand-sub">Smart Adaptive Irrigation Management System</div></div></div>""",
            unsafe_allow_html=True,
        )
        st.error(L("⚠️ Prototype — Simulated Data", "⚠️ Prototype — Data Simulasi"))
        st.markdown(
            f'<span class="sim-dot"></span>{L("Simulation mode running", "Mode simulasi berjalan")}',
            unsafe_allow_html=True,
        )
        st.markdown("#### Menu")

    for page_id, icon, label in nav_items:
        selected = st.session_state["page"] == page_id
        st.button(
            icon if COLLAPSED else f"{icon}  {label}",
            key=f"nav_{page_id}",
            help=label if COLLAPSED else None,
            type="primary" if selected else "secondary",
            width="stretch",
            on_click=_set_page,
            args=(page_id,),
        )

    _u = current_user()
    if _u:
        _avatar_data = _u.get("avatar_data") or ""
        _safe_avatar = html.escape(_avatar_data, quote=True)
        _initial = html.escape((_u.get("display_name") or _u.get("username", "S"))[:1].upper())
        if _safe_avatar:
            _avatar_markup = f'<img src="{_safe_avatar}" alt="Profile picture">'
        else:
            _avatar_markup = f'<div class="side-profile-fallback">{_initial}</div>'
        if COLLAPSED:
            st.markdown(f'<div class="side-profile-mini">{_avatar_markup}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f"""<div class="side-profile">{_avatar_markup}<div style="min-width:0;">
                  <div class="side-profile-name">{html.escape(_u.get("display_name") or _u.get("username", ""))}</div>
                  <div class="side-profile-caption">{L("Signed in", "Sedang masuk")}</div>
                </div></div>""",
                unsafe_allow_html=True,
            )
        st.button(
            "🚪" if COLLAPSED else "🚪  " + L("Sign out", "Keluar"),
            key="nav_logout",
            help=L("Sign out", "Keluar") if COLLAPSED else None,
            width="stretch",
            on_click=logout,
        )

    if not COLLAPSED:
        st.markdown(
            f"""
            <div class="side-info-card">
              <div class="side-info-title">⚙️ <span>{L("Assumed values", "Nilai asumsi")}</span></div>
              <div class="side-info-muted">{L("Example numbers, not field data.", "Angka contoh, bukan data lapangan.")}</div>
              <div class="side-info-line">{L("Service area", "Luas layanan")}: <b>{ASSUMPTIONS['area_ha']} ha</b></div>
              <div class="side-info-line">{L("Water delivery time", "Waktu pemberian air")}: <b>{ASSUMPTIONS['delivery_hours']} {L("hours", "jam")}</b></div>
              <div class="side-info-line">{L("Minimum water level", "Muka air minimum")}: <b>{ASSUMPTIONS['min_water_level']} m</b></div>
              <div class="side-info-line">{L("Gate capacity", "Kapasitas pintu")}: <b>{ASSUMPTIONS['gate_max_discharge']} m³/s</b></div>
            </div>
            <div class="side-info-card">
              <div class="side-info-title">🔁 <span>{L("SOMAT workflow", "Alur kerja SOMAT")}</span></div>
              <div class="side-flow">{L("Observation → Prediction → Hydraulic Check → Recommendation → Operator Validation → Operation → Feedback", "Observasi → Prediksi → Cek Hidraulik → Rekomendasi → Validasi Operator → Operasi → Umpan Balik")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

page = st.session_state["page"]

# ---------------- Header ----------------
logo_html = f'<img src="{LOGO_SRC}" alt="Logo SOMAT">'
st.markdown(
    f'''
    <div class="somat-header">
      {logo_html}
      <div>
        <h1>SOMAT — Smart Adaptive Irrigation Management System</h1>
        <p>{L("Decision-support prototype for observation, prediction, hydraulic validation and operator decisions.", "Prototipe sistem pendukung keputusan untuk observasi, prediksi, validasi hidraulik, dan keputusan operator.")}</p>
      </div>
    </div>
    ''',
    unsafe_allow_html=True,
)
st.warning(L(
    "PROTOTYPE — SIMULATED DATA. All figures on this dashboard are generated by simulation "
    "to demonstrate the SOMAT concept; they are not actual research data.",
    "PROTOTYPE — DATA SIMULASI. Seluruh angka pada dashboard ini dibangkitkan "
    "secara simulasi untuk demonstrasi konsep SOMAT, bukan data penelitian aktual.",
))

# ---------------- Data + shared calculation ----------------
df = generate_simulated_data()
sensor_df = generate_sensor_readings()
latest = df.iloc[-1].copy()
sensor_summary = summarize_sensors(sensor_df)
latest["soil_moisture"] = sensor_summary["soil_moisture"]
latest["water_level"] = sensor_summary["water_level"]
latest["rainfall"] = sensor_summary["rainfall"]

prediction = predict_irrigation_requirement(
    soil_moisture=latest["soil_moisture"],
    rainfall=latest["rainfall"],
    et0=latest["et0"],
)
hydraulic = check_hydraulic_feasibility(
    irrigation_mm=prediction["irrigation_mm"],
    available_discharge=latest["available_discharge"],
    water_level=latest["water_level"],
)
recommendation = generate_recommendation(
    prediction=prediction,
    hydraulic=hydraulic,
    available_discharge=latest["available_discharge"],
    soil_moisture=latest["soil_moisture"],
)
alerts = detect_alerts(
    soil_moisture=latest["soil_moisture"],
    water_level=latest["water_level"],
    rainfall=latest["rainfall"],
    prediction=prediction,
    recommendation=recommendation,
)
system_status = "ATTENTION" if (alerts or not hydraulic["feasible"]) else "NORMAL"

low_m = 20
heavy_r = 20
sm_ok = latest["soil_moisture"] >= low_m
wl_ok = latest["water_level"] >= ASSUMPTIONS["min_water_level"]
rain_ok = latest["rainfall"] < heavy_r
q_ok = latest["available_discharge"] >= hydraulic["required_discharge"]


def status_row(ok, label, text):
    mark = '<span class="st-ok">✔</span>' if ok else '<span class="st-warn">⚠</span>'
    return f'<div class="status-row">{mark} <b>{html.escape(str(label))}</b>: {html.escape(str(text))}</div>'


# ============================================================
# OVERVIEW (Ringkasan)
# ============================================================
if page == "overview":
    st.header(L("Conditions Overview", "Ringkasan Kondisi (Overview)"))
    st.caption(L("Latest conditions. All figures are prototype simulation data.", "Kondisi terbaru. Seluruh angka adalah data simulasi prototype."))
    sys_normal = system_status == "NORMAL"
    render_card_rows([
        dict(icon="🌱", title=L("Soil Moisture", "Kelembapan Tanah"), target=latest["soil_moisture"], decimals=1, suffix=" %",
             note=L(f"Low limit {low_m}%", f"Batas rendah {low_m}%"), badge_text=L("Normal", "Normal") if sm_ok else L("Low", "Rendah"), badge_kind="ok" if sm_ok else "warn", color="green" if sm_ok else "red"),
        dict(icon="🌊", title=L("Canal Water Level", "Tinggi Muka Air"), target=latest["water_level"], decimals=2, suffix=" m",
             note=L(f"Minimum {ASSUMPTIONS['min_water_level']} m", f"Minimum {ASSUMPTIONS['min_water_level']} m"), badge_text=L("Normal", "Normal") if wl_ok else L("Low", "Rendah"), badge_kind="ok" if wl_ok else "warn", color="blue" if wl_ok else "red"),
        dict(icon="🌧️", title=L("Rainfall", "Curah Hujan"), target=latest["rainfall"], decimals=1, suffix=" mm",
             note=L(f"High limit {heavy_r} mm", f"Batas tinggi {heavy_r} mm"), badge_text=L("Normal", "Normal") if rain_ok else L("High", "Tinggi"), badge_kind="ok" if rain_ok else "warn", color="blue" if rain_ok else "orange"),
        dict(icon="💧", title=L("Available Discharge", "Debit Tersedia"), target=latest["available_discharge"], decimals=3, suffix=" m³/s",
             note=L(f"Required {hydraulic['required_discharge']:.3f} m³/s", f"Dibutuhkan {hydraulic['required_discharge']:.3f} m³/s"), badge_text=L("Sufficient", "Cukup") if q_ok else L("Insufficient", "Kurang"), badge_kind="ok" if q_ok else "warn", color="blue" if q_ok else "red"),
        dict(icon="🌾", title=L("Crop Water Requirement", "Kebutuhan Air Tanaman"), target=latest["crop_water_requirement"], decimals=1, suffix=L(" mm/day", " mm/hari"),
             note=L(f"Predicted irrigation {prediction['irrigation_mm']} mm", f"Irigasi prediksi {prediction['irrigation_mm']} mm"), badge_text=L("Prediction", "Prediksi"), badge_kind="info", color="orange"),
        dict(icon="🛡️", title=L("System Status", "Status Sistem"), value_text="NORMAL" if sys_normal else L("ATTENTION", "PERHATIAN"),
             note=L("No active alerts", "Tidak ada peringatan aktif") if sys_normal else L("Operator validation needed", "Perlu validasi operator"), badge_text=L("Normal", "Normal") if sys_normal else L("Attention", "Perhatian"), badge_kind="ok" if sys_normal else "warn", color="green" if sys_normal else "red"),
    ], columns=3)

    panel_html = (
        f'<div class="status-panel"><div class="status-title">{L("System and Field Status", "Status Sistem dan Lahan")}</div>'
        + status_row(sm_ok, L("Soil moisture", "Kelembapan tanah"), f"{latest['soil_moisture']} %")
        + status_row(wl_ok, L("Canal water level", "Tinggi muka air"), f"{latest['water_level']} m")
        + status_row(rain_ok, L("Rainfall today", "Curah hujan hari ini"), f"{latest['rainfall']} mm")
        + status_row(hydraulic["feasible"], L("Hydraulic status", "Status hidraulik"), hydraulic["status"])
        + status_row(not alerts, L("Active alerts", "Peringatan aktif"), L(f"{len(alerts)} alert(s)", f"{len(alerts)} peringatan"))
        + "</div>"
    )
    st.markdown(panel_html, unsafe_allow_html=True)
    st.write("")
    st.header(L("Latest Conditions Chart (Last 14 Days)", "Grafik Kondisi Terbaru (14 Hari Terakhir)"))
    st.caption(L("Simulated data (prototype). Drag a chart to zoom the timeframe; Pan can be toggled from the toolbar.",
                 "Data simulasi (prototype). Drag grafik untuk zoom timeframe; Pan dapat diaktifkan/nonaktifkan dari toolbar."))
    render_plotly_interactive(make_combo_chart(df.tail(14)), height=360, key_prefix="summary")


# ============================================================
# SENSOR MONITORING (Monitoring Sensor)
# ============================================================
elif page == "monitoring":
    sensor_table = sensor_status_table(sensor_df)
    n_online = int((sensor_table["Status"] == "Online").sum())
    n_total = len(sensor_table)
    n_off = n_total - n_online
    sm_online = int(((sensor_table["Jenis"] == "soil_moisture") & (sensor_table["Status"] == "Online")).sum())

    st.header(L("Sensor Monitoring", "Monitoring Sensor"))
    st.caption(L("SIMULATED sensors (prototype). The rain station is simulated external data.",
                 "Sensor SIMULASI (prototype). Stasiun hujan adalah data eksternal simulasi."))
    all_on = n_online == n_total
    render_card_rows([
        dict(icon="📡", title=L("Sensors Online", "Sensor Online"), target=n_online, decimals=0, suffix=f" / {n_total}",
             note=L("No data > 3 h = offline", "Tanpa data > 3 jam = offline"), badge_text=L("Normal", "Normal") if all_on else L("Attention", "Perhatian"), badge_kind="ok" if all_on else "warn", color="green" if all_on else "orange"),
        dict(icon="🌱", title=L("Soil Moisture Sensors", "Sensor Kelembapan Tanah"), target=sm_online, decimals=0, suffix=" / 6",
             note=L("Plots 1–6", "Petak 1–6"), badge_text="Sensor", badge_kind="info", color="blue"),
        dict(icon="🚨", title=L("Active Alerts", "Peringatan Aktif"), target=len(alerts), decimals=0,
             note=L("From the alert module", "Dari modul peringatan"), badge_text=L("Normal", "Normal") if not alerts else L("Attention", "Perhatian"), badge_kind="ok" if not alerts else "warn", color="green" if not alerts else "red"),
        dict(icon="🗄️", title=L("Data Quality", "Kualitas Data"), target=sensor_summary["data_quality"], decimals=1, suffix=" %",
             note=L("Valid readings, 7 days", "Pembacaan valid 7 hari"), badge_text=L("Good", "Baik") if sensor_summary["data_quality"] >= 95 else L("Low", "Rendah"), badge_kind="ok" if sensor_summary["data_quality"] >= 95 else "warn", color="blue"),
    ], columns=4)

    d1, d2 = st.columns([1, 1], gap="medium")
    with d1:
        show_sensor_donut(n_online, n_off)
    with d2:
        sm = sensor_df[sensor_df["sensor_type"] == "soil_moisture"]
        trend = px.line(
            sm, x="timestamp", y="value", color="sensor_id",
            title=L("Soil Moisture Trend per Sensor (7 days)", "Tren Kelembapan per Sensor (7 hari)"),
            color_discrete_sequence=SERIES_COLORS,
            labels={"sensor_id": "Sensor"},
        )
        trend.update_traces(line=dict(width=2))
        trend.update_layout(
            height=368, yaxis_title=L("Soil moisture (%)", "Kelembapan tanah (%)"), xaxis_title=None,
            margin=dict(l=10, r=10, t=56, b=64),
            legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, title_text="", font=dict(size=10)),
        )
        apply_plot_theme(trend)
        render_plotly_interactive(trend, height=368, key_prefix="sensortrend")

    render_interactive_table(sensor_table, key="sensor_status", hide_index=True)
    st.divider()

    st.header("Monitoring")
    st.caption(L("All charts below come from simulated data.", "Seluruh grafik di bawah berasal dari data simulasi."))
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        show_animated(make_animated_line(df, "soil_moisture", L("🌱 Soil Moisture", "🌱 Kelembapan Tanah"), L("Soil moisture (%)", "Kelembapan tanah (%)")))
        show_animated(make_animated_line(df, "water_level", L("🌊 Canal Water Level", "🌊 Tinggi Muka Air Saluran"), L("Water level (m)", "Tinggi muka air (m)"), color="#2F80ED"))
    with col2:
        render_plotly_interactive(
            make_line_chart(df, "rainfall", L("🌧️ Rainfall", "🌧️ Curah Hujan"), L("Rainfall (mm)", "Curah hujan (mm)"), bar=True),
            height=340, key_prefix="rain",
        )
        show_animated(make_animated_line(df, "crop_water_requirement", L("🌾 Crop Water Requirement", "🌾 Kebutuhan Air Tanaman"), L("CWR (mm/day)", "KAT (mm/hari)"), color="#E87924"))

    with st.expander(L("View simulated data table", "Lihat tabel data simulasi")):
        render_interactive_table(df, key="monitor_data", hide_index=False)

    # Tahap A sengaja HANYA ada di tab Monitoring Sensor.
    with st.expander(L("Stage A: simulated sensor data", "Tahap A: data sensor simulasi")):
        st.caption(L("SIMULATED sensors. Not real sensor data.", "Sensor SIMULASI. Bukan data sensor nyata."))
        render_interactive_table(pd.DataFrame(SENSORS), key="sensor_definition", hide_index=True)
        st.write(L("Latest valid reading per sensor:", "Pembacaan valid terakhir tiap sensor:"))
        last_ok = (
            sensor_df[sensor_df["status"] == "OK"]
            .sort_values("timestamp")
            .groupby("sensor_id")
            .tail(1)
        )
        render_interactive_table(last_ok, key="sensor_last_ok", hide_index=True)


# ============================================================
# PREDICTION & RECOMMENDATION (Prediksi & Rekomendasi)
# ============================================================
elif page == "prediction":
    st.header(L("💧 Water Demand Prediction", "💧 Prediksi Kebutuhan Air"))
    st.caption(L("Prototype prediction logic (rule-based), not the final AI model of the thesis.",
                 "Logika prediksi prototype (berbasis aturan), bukan model AI final tesis."))
    render_card_rows([
        dict(icon="🌱", title=L("Soil Moisture", "Kelembapan Tanah"), target=latest["soil_moisture"], decimals=1, suffix=" %", note=L("Latest sensor condition", "Kondisi sensor terbaru"), badge_text="Input", badge_kind="info", color="green"),
        dict(icon="🌧️", title=L("Rainfall", "Curah Hujan"), target=latest["rainfall"], decimals=1, suffix=" mm", note=L("24-hour accumulation", "Akumulasi 24 jam"), badge_text="Input", badge_kind="info", color="blue"),
        dict(icon="☀️", title="ET0", target=latest["et0"], decimals=2, suffix=L(" mm/day", " mm/hari"), note=L("Reference evapotranspiration", "Evapotranspirasi acuan"), badge_text="Input", badge_kind="info", color="orange"),
        dict(icon="💧", title=L("Irrigation Prediction", "Prediksi Irigasi"), target=prediction["irrigation_mm"], decimals=1, suffix=" mm", note=L("Rule-based result", "Hasil berbasis aturan"), badge_text=L("Prediction", "Prediksi"), badge_kind="info", color="blue"),
    ], columns=4)

    with st.expander(L("🔍 View calculation details", "🔍 Lihat rincian perhitungan")):
        st.write(L("Base demand (ET0 x Kc):", "Kebutuhan dasar (ET0 x Kc):"), prediction["base_demand"], "mm")
        st.write(L("Soil water deficit:", "Kekurangan air tanah:"), prediction["deficit_mm"], "mm")
        st.write(L("Effective rainfall:", "Hujan efektif:"), prediction["useful_rain"], "mm")
        st.write(L("Result = base + deficit - effective rainfall", "Hasil = dasar + kekurangan - hujan efektif"))

    st.divider()
    st.header(L("🚰 Hydraulic Feasibility", "🚰 Kelayakan Hidraulik"))
    st.caption(L("Prototype rule-based check. Hydraulic parameters are assumed numbers.",
                 "Pengecekan prototype berbasis aturan. Parameter hidraulik adalah angka asumsi."))
    render_card_rows([
        dict(icon="💧", title=L("Water Requirement", "Kebutuhan Air"), target=prediction["irrigation_mm"], decimals=1, suffix=" mm", note=L("Predicted demand", "Prediksi kebutuhan"), badge_text=L("Demand", "Kebutuhan"), badge_kind="info", color="blue"),
        dict(icon="🌊", title=L("Available Discharge", "Debit Tersedia"), target=latest["available_discharge"], decimals=3, suffix=" m³/s", note=L("Current canal", "Saluran saat ini"), badge_text=L("Available", "Tersedia"), badge_kind="info", color="green"),
        dict(icon="🚰", title=L("Required Discharge", "Debit Dibutuhkan"), target=hydraulic["required_discharge"], decimals=3, suffix=" m³/s", note=L("For assumed duration", "Untuk durasi asumsi"), badge_text=L("Required", "Dibutuhkan"), badge_kind="info", color="orange"),
    ], columns=3)
    if hydraulic["feasible"]:
        st.success(L("✅ Hydraulic status = FEASIBLE", "✅ Status hidraulik = LAYAK (FEASIBLE)"))
    else:
        st.error(L("⛔ Hydraulic status = NOT FEASIBLE", "⛔ Status hidraulik = TIDAK LAYAK (NOT FEASIBLE)"))
    render_interactive_table(pd.DataFrame(hydraulic["checks"]), key="hydraulic_checks", hide_index=True)

    st.divider()
    st.header(L("🧭 SOMAT Recommendation", "🧭 Rekomendasi SOMAT"))
    st.caption(L("System suggestion only. Awaiting operator validation. Simulated data.",
                 "Hanya saran sistem. Menunggu validasi operator. Data simulasi."))
    feas_ok = recommendation["feasibility"] == "FEASIBLE"
    prio = recommendation["priority"]
    prio_label = {"HIGH": L("HIGH", "TINGGI"), "NORMAL": "NORMAL", "LOW": L("LOW", "RENDAH")}[prio]
    render_card_rows([
        dict(icon="💧", title=L("Recommended Irrigation", "Irigasi Disarankan"), target=recommendation["recommended_mm"], decimals=1, suffix=" mm", note=L(f"Predicted demand {prediction['irrigation_mm']} mm", f"Prediksi kebutuhan {prediction['irrigation_mm']} mm"), badge_text=L("Suggestion", "Saran"), badge_kind="info", color="blue"),
        dict(icon="⏱️", title=L("Recommended Duration", "Durasi Disarankan"), target=recommendation["duration_hours"], decimals=1, suffix=L(" h", " jam"), note=L(f"Area {ASSUMPTIONS['area_ha']} ha", f"Luas {ASSUMPTIONS['area_ha']} ha"), badge_text=L("Suggestion", "Saran"), badge_kind="info", color="blue"),
        dict(icon="🚰", title=L("Hydraulic Feasibility", "Kelayakan Hidraulik"), value_text=L("FEASIBLE", "LAYAK") if feas_ok else L("NOT FEASIBLE", "TIDAK LAYAK"), note=L("All checks passed", "Semua cek lolos") if feas_ok else L("Some checks failed", "Ada cek yang gagal"), badge_text=L("Feasible", "Layak") if feas_ok else L("Not feasible", "Tidak layak"), badge_kind="ok" if feas_ok else "warn", color="green" if feas_ok else "red"),
        dict(icon="⚑", title=L("Priority", "Prioritas"), value_text=prio_label, note=L("Based on demand and soil moisture", "Berdasarkan kebutuhan dan kelembapan tanah"), badge_text=prio_label.capitalize(), badge_kind="warn" if prio == "HIGH" else ("info" if prio == "NORMAL" else "ok"), color="red" if prio == "HIGH" else ("blue" if prio == "NORMAL" else "green")),
    ], columns=4)
    st.info(L("🕒 Status: awaiting operator validation. Open the **Operator Decision** menu to approve, modify, or delay.",
              "🕒 Status: menunggu validasi operator. Buka menu **Keputusan Operator** untuk menyetujui, mengubah, atau menunda."))
    if st.button(L("📨 Send to Operator for Validation", "📨 Kirim ke Operator untuk Validasi"), type="primary"):
        st.session_state["pending_recommendation"] = {
            "mm": recommendation["recommended_mm"],
            "hours": recommendation["duration_hours"],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        st.success(L("Recommendation sent to the operator. Open the **Operator Decision** menu to validate.",
                     "Rekomendasi dikirim ke operator. Buka menu **Keputusan Operator** untuk memvalidasi."))
    st.subheader(L("❓ Why this recommendation?", "❓ Mengapa rekomendasi ini?"))
    for reason in recommendation["reasons"]:
        st.markdown(f"- {reason}")


# ============================================================
# ALERTS (Peringatan)
# ============================================================
elif page == "alerts":
    st.header(L("🚨 Alerts / Anomalies", "🚨 Peringatan / Anomali"))
    st.caption(L("Simulated alerts (rule-based). Alert thresholds are example numbers.",
                 "Peringatan simulasi (berbasis aturan). Batas peringatan adalah angka contoh."))
    if alerts:
        for a in alerts:
            if a["level"] == "error":
                st.error(f"{a['title']}: {a['detail']}")
            else:
                st.warning(f"{a['title']}: {a['detail']}")
        st.warning(L("Abnormal conditions detected. The operator is asked to validate the recommendation carefully before deciding.",
                     "Kondisi abnormal terdeteksi. Operator diminta memvalidasi rekomendasi dengan teliti sebelum mengambil keputusan."))
    else:
        st.success(L("✅ No active alerts. Conditions are within normal limits (simulated data).",
                     "✅ Tidak ada peringatan aktif. Kondisi dalam batas normal (data simulasi)."))

    st.subheader(L("🗂️ Recent Events", "🗂️ Kejadian Terbaru"))
    incidents = []
    sensor_now = sensor_status_table(sensor_df)
    for _, row in sensor_now[sensor_now["Status"] == "Offline"].iterrows():
        incidents.append({
            "Waktu": str(row["Data valid terakhir"]),
            "Sumber": row["Sensor"],
            "Kejadian": L("Sensor offline (no data for more than 3 hours)", "Sensor offline (tanpa data lebih dari 3 jam)"),
            "Tingkat": L("Warning", "Peringatan"),
            "Status": L("Needs checking", "Perlu diperiksa"),
        })
    for a in alerts:
        incidents.append({
            "Waktu": str(sensor_df["timestamp"].max()),
            "Sumber": L("Alert module", "Modul peringatan"),
            "Kejadian": f"{a['title']}: {a['detail']}",
            "Tingkat": L("Critical", "Kritis") if a["level"] == "error" else L("Warning", "Peringatan"),
            "Status": L("Open", "Terbuka"),
        })
    if incidents:
        render_interactive_table(pd.DataFrame(incidents), key="incidents", hide_index=True)
    else:
        st.info(L("No events. All sensors are online and there are no active alerts.",
                  "Tidak ada kejadian. Seluruh sensor online dan tidak ada peringatan aktif."))


# ============================================================
# OPERATOR DECISION (Keputusan Operator)
# ============================================================
elif page == "operator":
    refresh_user()
    st.header(L("👷 Operator Decision (Human in the Loop)", "👷 Keputusan Operator (Human in the Loop)"))
    st.caption(L("SOMAT only gives suggestions. The operator makes the final decision. No irrigation gate is moved automatically. Simulated data.",
                 "SOMAT hanya memberi saran. Operator adalah pengambil keputusan akhir. Tidak ada pintu irigasi yang digerakkan otomatis. Data simulasi."))

    _u = current_user()
    if _u:
        st.caption(L(f"Signed in as **{_u['display_name']}** ({role_label(_u['role'])})",
                     f"Masuk sebagai **{_u['display_name']}** ({role_label(_u['role'])})"))
    if st.session_state.pop("db_error", False):
        st.warning(L("The database could not be reached; the latest data is shown for this session only.",
                     "Database tidak dapat dihubungi; data terbaru hanya tampil untuk sesi ini."))

    def _record(decision, mm, hours, note_text, flash):
        """Cek ulang izin (peran bisa berubah saat sesi) lalu catat keputusan."""
        refresh_user(force=True)
        if not can_decide():
            st.error(auth_msg("forbidden"))
            return
        st.session_state["show_modify"] = False
        log_decision(decision, recommendation, mm, hours, note_text)
        st.success({
            "approve": L("✅ Decision recorded: APPROVE", "✅ Keputusan dicatat: APPROVE"),
            "delay": L("⏸️ Decision recorded: DELAY (irrigation postponed)", "⏸️ Keputusan dicatat: DELAY (irigasi ditunda)"),
            "modify": L("✏️ Decision recorded: MODIFY", "✏️ Keputusan dicatat: MODIFY"),
        }.get(flash, str(flash)))

    if can_decide():
        if "pending_recommendation" in st.session_state:
            p = st.session_state["pending_recommendation"]
            st.warning(L(
                f"📨 Recommendation awaiting validation: {p['mm']} mm for {p['hours']} hours (sent {p['time']}). Choose APPROVE, MODIFY, or DELAY.",
                f"📨 Rekomendasi menunggu validasi: {p['mm']} mm selama {p['hours']} jam (dikirim {p['time']}). Pilih APPROVE, MODIFY, atau DELAY.",
            ))

        note = st.text_input(
            L("📝 Operator note (optional for APPROVE and DELAY)", "📝 Catatan operator (opsional untuk APPROVE dan DELAY)"),
            placeholder=L("Example: discharge is sufficient, proceed as recommended", "Contoh: debit cukup, lanjutkan sesuai rekomendasi"),
        )
        b1, b2, b3 = st.columns(3)
        approve = b1.button("APPROVE", type="primary", width="stretch")
        modify = b2.button("MODIFY", width="stretch")
        delay = b3.button("DELAY", width="stretch")

        if approve:
            _record("APPROVE", recommendation["recommended_mm"], recommendation["duration_hours"], note, "approve")
        if delay:
            _record("DELAY", 0.0, 0.0, note or L("Postponed by operator", "Ditunda oleh operator"), "delay")
        if modify:
            st.session_state["show_modify"] = True

        if st.session_state["show_modify"]:
            with st.form("modify_form"):
                st.subheader(L("✏️ Modify recommendation", "✏️ Ubah rekomendasi"))
                mod_mm = st.number_input(L("Irrigation amount (mm)", "Jumlah air irigasi (mm)"), min_value=0.0, value=float(recommendation["recommended_mm"]), step=0.5)
                mod_hours = st.number_input(L("Duration (hours)", "Durasi (jam)"), min_value=0.0, value=float(recommendation["duration_hours"]), step=0.5)
                mod_reason = st.text_area(L("Reason for change (required)", "Alasan perubahan (wajib diisi)"))
                submitted = st.form_submit_button(L("Save modified decision", "Simpan keputusan yang diubah"))
            if submitted:
                if mod_reason.strip() == "":
                    st.warning(L("A reason is required before saving a MODIFY decision.", "Alasan wajib diisi sebelum menyimpan keputusan MODIFY."))
                else:
                    _record("MODIFY", mod_mm, mod_hours, mod_reason, "modify")
    elif not _u:
        if DB_ACTIVE:
            st.info(L("Please sign in as an operator to record decisions.", "Silakan masuk sebagai operator untuk mencatat keputusan."))
            render_login_form("op_login_form")
    elif DB_ACTIVE:
        st.warning(L("Your role can view this tab but does not have permission to record decisions. Ask an administrator to grant the Operator Decision access.",
                     "Role Anda dapat melihat tab ini, tetapi belum memiliki izin untuk mencatat keputusan. Minta administrator memberikan akses Keputusan Operator."))

    st.header(L("🔄 Feedback Loop", "🔄 Umpan Balik (Feedback Loop)"))
    st.caption(L("Simulated field response (prototype). Not field measurements.", "Respons lapangan simulasi (prototype). Bukan hasil pengukuran lapangan."))
    if "last_feedback" in st.session_state:
        fb = st.session_state["last_feedback"]
        f1, f2, f3 = st.columns(3)
        with f1:
            st.markdown(L("**1. 🧭 SOMAT Recommendation**", "**1. 🧭 Rekomendasi SOMAT**"))
            st.write(f"{fb['recommended_mm']} mm")
        with f2:
            st.markdown(L("**2. 👷 Operator Decision**", "**2. 👷 Keputusan Operator**"))
            st.write(f"{fb['decision']} - {fb['operator_mm']} mm")
        with f3:
            st.markdown(L("**3. 🌾 Field Response (Simulated)**", "**3. 🌾 Respons Lapangan (Simulasi)**"))
            st.write(L(
                f"Soil moisture {latest['soil_moisture']}% → {fb['feedback']['new_moisture']}% ({field_status_text(fb['feedback']['status'])})",
                f"Kelembapan tanah {latest['soil_moisture']}% → {fb['feedback']['new_moisture']}% ({field_status_text(fb['feedback']['status'])})",
            ))
        st.info(L("Feedback to SOMAT: ", "Umpan balik ke SOMAT: ") + feedback_learning_text(fb["feedback"]["learning"]))
    else:
        st.info(L("No decisions yet. Make an operator decision to see the feedback flow.",
                  "Belum ada keputusan. Buat keputusan operator untuk melihat alur feedback."))

    st.subheader(L("📋 Decision History (saved permanently)", "📋 Riwayat Keputusan (tersimpan permanen)")
                 if DB_ACTIVE else L("📋 Decision History (this session only)", "📋 Riwayat Keputusan (sesi ini saja)"))
    if _u:
        if "dec_flash" in st.session_state:
            st.success(st.session_state.pop("dec_flash"))
        _hist = decision_log_df()
        if len(_hist):
            render_interactive_table(_hist, key="decision_history", hide_index=True)
        else:
            st.info(L("No operator decisions recorded yet.", "Belum ada keputusan operator yang tercatat."))

        # Hanya admin: ubah / hapus catatan riwayat (server memeriksa peran lagi sebelum menyimpan).
        if is_admin() and DB_ACTIVE and len(_hist):
            with st.expander(L("🛠️ Edit or delete a record (admin only)", "🛠️ Ubah atau hapus catatan (khusus admin)")):
                st.caption(L("Only the decision, amount, duration and note can be edited. The SOMAT recommendation and the "
                             "simulated field response are not recalculated. Every change is written to the audit log.",
                             "Yang dapat diubah: keputusan, jumlah, durasi, dan catatan. Rekomendasi SOMAT dan respons lapangan "
                             "simulasi tidak dihitung ulang. Setiap perubahan tercatat di log audit."))
                _drows = load_decisions_db()
                _dopts = {r["id"]: f"#{r['id']} · {fmt_ts(r['ts'])} · {r['username']} · {r['decision']}" for r in _drows}
                _dsel = st.selectbox(L("Select record", "Pilih catatan"), list(_dopts), format_func=lambda i: _dopts[i], key="dec_sel")
                _cur = next(r for r in _drows if r["id"] == _dsel)
                with st.form(f"dec_edit_form_{_dsel}"):
                    _edec = st.selectbox(L("Decision", "Keputusan"), DECISION_TYPES,
                                         index=DECISION_TYPES.index(_cur["decision"]) if _cur["decision"] in DECISION_TYPES else 0)
                    _emm = st.number_input(L("Operator irrigation (mm)", "Irigasi operator (mm)"), min_value=0.0, max_value=1000.0,
                                           value=float(_cur["operator_mm"] or 0.0), step=0.5)
                    _eh = st.number_input(L("Operator duration (h)", "Durasi operator (jam)"), min_value=0.0, max_value=240.0,
                                          value=float(_cur["duration_h"] or 0.0), step=0.5)
                    _enote = st.text_area(L("Reason / note", "Alasan / catatan"), value=_cur["note"] or "")
                    _esave = st.form_submit_button(L("Save changes", "Simpan perubahan"), type="primary")
                if _esave:
                    _err = update_decision(_dsel, _edec, _emm, _eh, _enote)
                    if _err:
                        st.error(auth_msg(_err))
                    else:
                        st.session_state["dec_flash"] = L(f"Record #{_dsel} updated.", f"Catatan #{_dsel} diperbarui.")
                        st.rerun()
                st.divider()
                _ok = st.checkbox(L("I understand this permanently deletes the selected record.",
                                    "Saya mengerti catatan terpilih akan dihapus permanen."), key=f"dec_del_ok_{_dsel}")
                if st.button(L("🗑️ Delete record", "🗑️ Hapus catatan"), key="dec_del_btn", disabled=not _ok):
                    _err = delete_decision(_dsel)
                    if _err:
                        st.error(auth_msg(_err))
                    else:
                        st.session_state["dec_flash"] = L(f"Record #{_dsel} deleted.", f"Catatan #{_dsel} dihapus.")
                        st.rerun()


# ============================================================
# MY ACCOUNT (Akun Saya)
# ============================================================
elif page == "account":
    _u = refresh_user()
    st.header(L("👤 My Account", "👤 Akun Saya"))
    if not _u:
        st.info(L("Please sign in.", "Silakan masuk."))
    else:
        st.caption(L("Manage the name and profile photo shown in the sidebar.", "Atur nama dan foto profil yang ditampilkan di sidebar."))
        profile_left, profile_right = st.columns([0.8, 1.7], gap="large")
        with profile_left:
            if _u.get("avatar_data"):
                try:
                    _avatar_bytes = base64.b64decode(_u["avatar_data"].split(",", 1)[1])
                    st.image(_avatar_bytes, width=150)
                except Exception:
                    st.info(L("Profile photo preview is unavailable.", "Pratinjau foto profil tidak tersedia."))
            else:
                _initial = html.escape((_u.get("display_name") or _u["username"])[0].upper())
                st.markdown(
                    f'<div class="side-profile-fallback" style="width:112px;height:112px;font-size:2rem;">{_initial}</div>',
                    unsafe_allow_html=True,
                )
            st.write(f"**{_u['username']}**")
            st.caption(role_label(_u["role"]))
        with profile_right:
            with st.form("profile_form", clear_on_submit=False):
                _display_name = st.text_input(
                    L("Display name", "Nama tampilan"),
                    value=_u.get("display_name") or _u["username"],
                    max_chars=60,
                )
                _photo_upload = st.file_uploader(
                    L("Profile picture", "Foto profil"),
                    type=["png", "jpg", "jpeg", "webp"],
                    help=L("Maximum 5 MB. The image is resized automatically.", "Maksimal 5 MB. Foto akan diperkecil secara otomatis."),
                )
                _remove_photo = st.checkbox(L("Remove current photo", "Hapus foto saat ini"), value=False)
                _save_profile = st.form_submit_button(L("Save profile", "Simpan profil"), type="primary")
            if _save_profile:
                _new_avatar = _u.get("avatar_data")
                _avatar_error = None
                if _remove_photo:
                    _new_avatar = None
                elif _photo_upload is not None:
                    _new_avatar, _avatar_error = avatar_data_from_upload(_photo_upload)
                if _avatar_error:
                    st.error(auth_msg(_avatar_error))
                else:
                    _profile_error = update_own_profile(_display_name, _new_avatar)
                    if _profile_error:
                        st.error(auth_msg(_profile_error))
                    else:
                        st.success(L("Profile updated.", "Profil berhasil diperbarui."))
                        st.rerun()

        st.divider()
        st.subheader(L("Change password", "Ganti kata sandi"))
        with st.form("pw_form", clear_on_submit=True):
            _cur = st.text_input(L("Current password", "Kata sandi saat ini"), type="password")
            _new = st.text_input(L("New password (min. 8 characters)", "Kata sandi baru (min. 8 karakter)"), type="password")
            _cnf = st.text_input(L("Repeat new password", "Ulangi kata sandi baru"), type="password")
            _go = st.form_submit_button(L("Save new password", "Simpan kata sandi baru"))
        if _go:
            _err = change_own_password(_cur, _new, _cnf)
            if _err:
                st.error(auth_msg(_err))
            else:
                st.success(L("Password changed.", "Kata sandi diganti."))


# ============================================================
# ADMIN (Administrasi)
# ============================================================
elif page == "admin":
    refresh_user(force=True)
    st.header(L("🛡️ Administration", "🛡️ Administrasi"))
    if not is_admin():
        st.error(auth_msg("forbidden"))
    else:
        if "adm_flash" in st.session_state:
            st.success(st.session_state.pop("adm_flash"))
        tab_users, tab_roles, tab_audit = st.tabs([
            L("Users", "Pengguna"),
            L("Roles & access", "Role & hak akses"),
            L("Audit log", "Log audit"),
        ])

        with tab_users:
            _users = list_users()
            _role_rows = list_roles()
            _role_keys = [r["role_key"] for r in _role_rows]
            render_interactive_table(pd.DataFrame([{
                L("Username", "Nama pengguna"): r["username"],
                L("Name", "Nama"): r["display_name"],
                L("Role", "Peran"): role_label(r["role"]),
                L("Active", "Aktif"): L("Yes", "Ya") if r["active"] else L("No", "Tidak"),
                L("Created (WIB)", "Dibuat (WIB)"): fmt_ts(r["created_at"]),
            } for r in _users]), key="admin_users", hide_index=True)

            st.subheader(L("➕ Add user", "➕ Tambah pengguna"))
            _default_role = "operator" if "operator" in _role_keys else next((r for r in _role_keys if r != "admin"), _role_keys[0])
            with st.form("add_user_form", clear_on_submit=True):
                a1, a2 = st.columns(2)
                nu = a1.text_input(L("Username", "Nama pengguna"))
                nn = a2.text_input(L("Full name", "Nama lengkap"))
                a3, a4 = st.columns(2)
                nr = a3.selectbox(
                    L("Role", "Peran"), _role_keys,
                    index=_role_keys.index(_default_role), format_func=role_label,
                )
                npw = a4.text_input(L("Initial password (min. 8 characters)", "Kata sandi awal (min. 8 karakter)"), type="password")
                add_go = st.form_submit_button(L("Create user", "Buat pengguna"), type="primary")
            if add_go:
                _err = create_user(nu, nn, nr, npw)
                if _err:
                    st.error(auth_msg(_err))
                else:
                    st.session_state["adm_flash"] = L(f"User '{nu.strip().lower()}' created.", f"Pengguna '{nu.strip().lower()}' dibuat.")
                    st.rerun()

            st.subheader(L("🛠️ Manage user", "🛠️ Kelola pengguna"))
            _names = [r["username"] for r in _users]
            if _names:
                _sel = st.selectbox(L("Select user", "Pilih pengguna"), _names, key="adm_sel")
                _row = next(r for r in _users if r["username"] == _sel)
                m1, m2 = st.columns(2)
                with m1:
                    _row_role = _row["role"] if _row["role"] in _role_keys else _role_keys[0]
                    _role = st.selectbox(
                        L("Role", "Peran"), _role_keys,
                        index=_role_keys.index(_row_role),
                        format_func=role_label,
                        key=f"adm_role_{_sel}",
                    )
                    _act = st.checkbox(L("Active", "Aktif"), value=bool(_row["active"]), key=f"adm_act_{_sel}")
                    if st.button(L("Save changes", "Simpan perubahan"), key="adm_save"):
                        _err = update_user(_sel, _role, _act)
                        if _err:
                            st.error(auth_msg(_err))
                        else:
                            st.session_state["adm_flash"] = L("Changes saved.", "Perubahan disimpan.")
                            st.rerun()
                with m2:
                    with st.form("adm_reset_form", clear_on_submit=True):
                        _rp = st.text_input(L("New password for this user", "Kata sandi baru untuk pengguna ini"), type="password")
                        _rgo = st.form_submit_button(L("Reset password (also unlocks)", "Reset kata sandi (sekaligus membuka kunci)"))
                    if _rgo:
                        _err = reset_password(_sel, _rp)
                        if _err:
                            st.error(auth_msg(_err))
                        else:
                            st.session_state["adm_flash"] = L(f"Password for '{_sel}' reset.", f"Kata sandi '{_sel}' direset.")
                            st.rerun()
            else:
                st.info(L("No users found.", "Belum ada pengguna."))

        with tab_roles:
            st.caption(L(
                "Create custom roles and decide which application tabs each role can open. Account settings remain available to every signed-in user; the Admin tab is reserved for the administrator role.",
                "Buat role khusus dan tentukan tab aplikasi yang dapat dibuka oleh setiap role. Akun Saya tetap tersedia bagi semua pengguna yang sudah masuk; tab Administrasi hanya untuk role administrator."
            ))
            st.subheader(L("➕ Create custom role", "➕ Tambah role khusus"))
            with st.form("create_role_form", clear_on_submit=True):
                _new_role_name = st.text_input(L("Role display name", "Nama role"), max_chars=60)
                _new_role_pages = st.multiselect(
                    L("Tabs this role can access", "Tab yang dapat diakses role ini"),
                    options=list(APP_PAGE_KEYS),
                    default=["overview", "monitoring", "prediction", "alerts"],
                    format_func=page_label,
                )
                _create_role_go = st.form_submit_button(L("Create role", "Buat role"), type="primary")
            if _create_role_go:
                _role_error, _created_key = create_role(_new_role_name, _new_role_pages)
                if _role_error:
                    st.error(auth_msg(_role_error))
                else:
                    st.session_state["adm_flash"] = L(
                        f"Role '{_new_role_name.strip()}' created with key '{_created_key}'.",
                        f"Role '{_new_role_name.strip()}' dibuat dengan kode '{_created_key}'."
                    )
                    st.rerun()

            st.divider()
            st.subheader(L("🔐 Configure role access", "🔐 Atur hak akses role"))
            _role_rows = list_roles()
            _editable_roles = [r for r in _role_rows if r["role_key"] != "admin"]
            if _editable_roles:
                _editable_keys = [r["role_key"] for r in _editable_roles]
                _selected_role = st.selectbox(
                    L("Select role", "Pilih role"), _editable_keys,
                    format_func=role_label, key="role_access_selected",
                )
                _selected_record = next(r for r in _editable_roles if r["role_key"] == _selected_role)
                st.caption(L(f"Role key: `{_selected_role}`", f"Kode role: `{_selected_role}`"))
                _selected_pages = st.multiselect(
                    L("Allowed tabs", "Tab yang diizinkan"),
                    options=list(APP_PAGE_KEYS),
                    default=get_role_pages(_selected_role),
                    format_func=page_label,
                    key=f"role_access_pages_{_selected_role}",
                )
                if st.button(L("Save access settings", "Simpan hak akses"), key="save_role_access", type="primary"):
                    _err = save_role_access(_selected_role, _selected_pages)
                    if _err:
                        st.error(auth_msg(_err))
                    else:
                        st.success(L("Role access updated. The changes apply on the user's next interaction.", "Hak akses role diperbarui. Perubahan berlaku pada interaksi pengguna berikutnya."))
                        st.rerun()

                if not _selected_record["is_system"]:
                    if st.button(L("Delete this custom role", "Hapus role khusus ini"), key="delete_custom_role"):
                        _err = delete_role(_selected_role)
                        if _err:
                            st.error(auth_msg(_err))
                        else:
                            st.success(L("Custom role deleted.", "Role khusus berhasil dihapus."))
                            st.rerun()
            st.divider()
            st.subheader(L("Role overview", "Ringkasan role"))
            _role_summary = []
            for _rr in list_roles():
                _role_summary.append({
                    L("Role", "Role"): _rr["display_name"],
                    L("Role key", "Kode role"): _rr["role_key"],
                    L("Type", "Jenis"): L("Built-in", "Bawaan") if _rr["is_system"] else L("Custom", "Khusus"),
                    L("Accessible tabs", "Tab yang dapat diakses"): ", ".join(page_label(p) for p in get_role_pages(_rr["role_key"])) or "—",
                })
            render_interactive_table(pd.DataFrame(_role_summary), key="admin_roles_summary", hide_index=True)

        with tab_audit:
            st.caption(L("Latest 200 events: sign-ins, decisions, user changes, and role-access changes.",
                         "200 kejadian terbaru: login, keputusan, perubahan pengguna, dan perubahan hak akses role."))
            _aud = fetch_audit()
            if _aud:
                render_interactive_table(pd.DataFrame([{
                    L("Time (WIB)", "Waktu (WIB)"): fmt_ts(r["ts"]),
                    L("User", "Pengguna"): r["username"],
                    L("Action", "Aksi"): r["action"],
                    L("Detail", "Detail"): r["detail"],
                } for r in _aud]), key="admin_audit", hide_index=True)
            else:
                st.info(L("No events yet.", "Belum ada kejadian."))

