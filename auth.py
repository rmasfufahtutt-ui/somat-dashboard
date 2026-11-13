"""auth.py - login, sesi, peran, dan manajemen pengguna (diekstrak dari prototipe, memakai modul db).

Kata sandi hanya disimpan sebagai hash PBKDF2-SHA256 + salt. Token sesi acak disimpan di localStorage browser
(komponen somat_session); database hanya menyimpan hash-nya.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import re
import secrets as pysecrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

import db
from db import db_query
from i18n import L
from repository import audit as _audit

SYSTEM_ROLES = ("admin", "operator", "viewer")
APP_PAGE_KEYS = ("overview", "monitoring", "prediction", "alerts", "operator", "observations", "execution")
# Halaman baru mengikuti hak 'operator' bila baris izin belum ada (peran kustom lama tidak ikut terkunci/terbuka sendiri).
INHERIT_FROM_OPERATOR = ("observations", "execution")
DEFAULT_ROLE_PERMISSIONS = {
    "admin": APP_PAGE_KEYS,
    "operator": APP_PAGE_KEYS,
    "viewer": ("overview", "monitoring", "prediction", "alerts"),
}
MAX_FAILS, LOCK_SECONDS = 5, 300
PBKDF2_ITERS = 310_000
USER_CHECK_TTL = 30
SESSION_DAYS = 14
IDLE_SECONDS = 14 * 24 * 60 * 60


def _secret(section, key, default=""):
    try:
        return st.secrets[section][key]
    except Exception:
        return default


def _now():
    return datetime.now(timezone.utc)


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


_DUMMY = None


def _dummy_hash():
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("dummy-password-for-timing")
    return _DUMMY


def valid_username(u):
    return bool(re.fullmatch(r"[a-z0-9._-]{3,32}", u or ""))


def valid_password(p):
    return isinstance(p, str) and len(p) >= 8



# ---------- inisialisasi peran bawaan + admin awal (sekali per proses) ----------
_INIT_DONE = False


def init_auth():
    """Seed peran bawaan dan admin awal dari secrets bila belum ada pengguna. Idempoten; aman dipanggil tiap rerun."""
    global _INIT_DONE
    if _INIT_DONE or not db.active():
        return _INIT_DONE
    for key, name in (("admin", "Administrator"), ("operator", "Operator"), ("viewer", "Viewer")):
        db_query("INSERT INTO roles (role_key, display_name, is_system) VALUES (%s,%s,TRUE) ON CONFLICT (role_key) DO NOTHING",
                 (key, name))
    for role, pages in DEFAULT_ROLE_PERMISSIONS.items():
        for page in APP_PAGE_KEYS:
            db_query("INSERT INTO role_permissions (role_key, page_key, can_access) VALUES (%s,%s,%s) "
                     "ON CONFLICT (role_key, page_key) DO NOTHING", (role, page, page in pages))
    if not db_query("SELECT 1 FROM users LIMIT 1"):
        bu = str(_secret("bootstrap_admin", "username", "")).strip().lower()
        bp = str(_secret("bootstrap_admin", "password", ""))
        if valid_username(bu) and valid_password(bp):
            db_query("INSERT INTO users (username, display_name, role, password_hash, created_at) "
                     "VALUES (%s,%s,'admin',%s,%s)", (bu, bu, hash_password(bp), _now()))
            _audit("bootstrap_admin", f"admin '{bu}' dibuat dari secrets", "system")
    _INIT_DONE = True
    return True


def current_user():
    return st.session_state.get("user")


def audit(action, detail="", username=None):
    _audit(action, detail, username or (current_user() or {}).get("username", "-"))


_ROLE_ACCESS_CACHE = {}
_ROLE_LABEL_CACHE = {}


def list_roles():
    return db_query(
        "SELECT role_key, display_name, is_system, created_at FROM roles "
        "ORDER BY CASE role_key WHEN 'admin' THEN 0 WHEN 'operator' THEN 1 WHEN 'viewer' THEN 2 ELSE 3 END, display_name"
    )


def role_exists(role_key):
    if not db.active():
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
    if db.active():
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
        "operator": L("Operator Decision", "Keputusan Operator"),
        "alerts": L("Alerts", "Peringatan"),
        "observations": L("Field Observations", "Pengamatan Lapangan"),
        "execution": L("Irrigation Execution", "Pelaksanaan Irigasi"),
    }.get(page_key, page_key)


def get_role_pages(role_key):
    """Tab yang diizinkan untuk role (cache 30 dtk; admin selalu penuh). Halaman baru tanpa baris izin
    mengikuti hak 'operator' agar peran kustom lama tidak terbuka/terkunci tanpa keputusan admin."""
    if role_key == "admin":
        return list(APP_PAGE_KEYS)
    hit = _ROLE_ACCESS_CACHE.get(role_key)
    if hit and time.time() - hit[0] < 30:
        return list(hit[1])
    if not db.active():
        return []
    rows = db_query("SELECT page_key, can_access FROM role_permissions WHERE role_key=%s", (role_key,))
    perm = {r["page_key"]: bool(r["can_access"]) for r in rows}
    pages = []
    for k in APP_PAGE_KEYS:
        if k in perm:
            ok = perm[k]
        elif k in INHERIT_FROM_OPERATOR:
            ok = perm.get("operator", False)
        else:
            ok = False
        if ok:
            pages.append(k)
    _ROLE_ACCESS_CACHE[role_key] = (time.time(), pages)
    return list(pages)


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
        _ROLE_ACCESS_CACHE.pop(role_key, None)
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
        _ROLE_ACCESS_CACHE.pop(role_key, None)
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
    if not u or not db.active():
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
    return bool(u) and db.active() and u.get("role") == "admin"


def can_decide():
    u = current_user()
    return bool(u) and db.active() and can_access_page("operator", u)


SESSION_DAYS = 14
IDLE_SECONDS = 14 * 24 * 60 * 60


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
    if _SESS_COMPONENT is None or not db.active():
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
    if token and db.active():
        try:
            db_query("DELETE FROM sessions WHERE token_hash=%s", (_token_hash(token),))
        except Exception:
            pass
    st.session_state["_sess_args"] = {"action": "clear", "token": "", "nonce": "clear-" + pysecrets.token_hex(4)}
    st.session_state["user"] = None
    st.session_state["page"] = "login"
    for _k in ("pending_recommendation", "show_modify", "show_delay", "op_flash", "_last_activity", "_touched"):
        st.session_state.pop(_k, None)


def update_own_profile(display_name, avatar_data):
    u = current_user()
    if not u or not db.active():
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
    if not u or not db.active():
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

