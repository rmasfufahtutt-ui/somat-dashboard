"""demo_mode.py - pemilihan ruang DEMO PENELITIAN vs OPERASIONAL (state sesi) dan aturan akses demo.

Prinsip isolasi:
* Mode disimpan di sesi pengguna. `repo_router` memilih backend (SQLite demo atau Postgres operasional) per pemanggilan.
* Sesi masuk lewat akun DEMO (tanpa database produksi) TIDAK PERNAH dapat berpindah ke OPERASIONAL.
* Pemeriksaan hak akses dilakukan lagi di backend demo (`require`), bukan hanya di UI.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Optional

MODE_DEMO = "DEMO"
MODE_OPS = "OPS"

# Akun demo (hanya untuk ruang DEMO; tidak ada di database operasional dan tidak punya kata sandi).
DEMO_USERS = {
    "demo_admin": {"display_name": "Admin Demo", "role": "admin"},
    "demo_operator": {"display_name": "Operator Demo", "role": "operator"},
    "demo_viewer": {"display_name": "Pengamat Demo", "role": "viewer"},
}

BANNER_ID = ("DEMO PENELITIAN — Data petak, sensor, parameter, dan pelaksanaan bersifat sintetis. "
             "Informasi BMKG menggunakan sumber eksternal asli dengan status keterkinian.")
BANNER_EN = ("RESEARCH DEMO — Plot, sensor, parameter and execution data are synthetic. "
             "BMKG information comes from the real external source, with its freshness shown.")
AI_NOTICE_ID = "MODEL AI DEMONSTRASI — Dilatih dari data sintetis. Belum tervalidasi menggunakan data lapangan."
AI_NOTICE_EN = "DEMONSTRATION AI MODEL — Trained on synthetic data. Not yet validated with field data."
EXAMPLE_NOTE_ID = "contoh demonstrasi, bukan hasil pengukuran penelitian"
EXAMPLE_NOTE_EN = "demonstration example, not a research measurement"

# Untuk pengujian di luar Streamlit.
_TEST = {"mode": None, "actor": None}


def force(mode: Optional[str] = None, actor: Optional[tuple] = None):
    """Hanya untuk tes: paksa mode dan/atau aktor (username, role). None = kembali ke perilaku sesi."""
    _TEST["mode"], _TEST["actor"] = mode, actor


def _session():
    try:
        import streamlit as st
        return st.session_state
    except Exception:                                                   # pragma: no cover
        return {}


def user():
    if _TEST["actor"] is not None:
        name, role = _TEST["actor"]
        return {"username": name, "role": role, "demo": True}
    try:
        return _session().get("user")
    except Exception:                                                   # di luar konteks Streamlit
        return None


def is_demo_user(u=None) -> bool:
    u = u if u is not None else user()
    return bool(u) and bool(u.get("demo"))


def mode() -> str:
    if _TEST["mode"] is not None:
        return _TEST["mode"]
    try:
        s = _session()
        if is_demo_user(s.get("user")):
            return MODE_DEMO
        return s.get("app_mode") or MODE_OPS
    except Exception:
        return MODE_OPS


def is_demo() -> bool:
    return mode() == MODE_DEMO


def mode_key() -> str:
    """Kunci cache: dipakai agar cache tampilan tidak tercampur antar mode."""
    return mode()


def can_use_ops() -> bool:
    """OPERASIONAL hanya untuk pengguna sungguhan dan bila database produksi aktif."""
    import db
    return db.active() and not is_demo_user()


def set_mode(m: str) -> bool:
    if m == MODE_OPS and not can_use_ops():
        return False
    try:
        _session()["app_mode"] = m
    except Exception:
        return False
    return True


def default_mode_for_login(u: dict) -> str:
    return MODE_DEMO if is_demo_user(u) else MODE_OPS


# ---------------------------------------------------------------- hak akses (dipakai ulang oleh backend demo)
_ROLE_PAGES = {"admin": ("operator", "observations", "execution", "admin"),
               "operator": ("operator", "observations", "execution"), "viewer": ()}


_SYS = threading.local()


@contextmanager
def system():
    """Konteks internal untuk pengisian otomatis ruang DEMO (bukan tindakan pengguna). Hanya berlaku di thread ini dan
    hanya untuk repositori DEMO; tidak pernah memberi akses ke database operasional."""
    prev = getattr(_SYS, "on", False)
    _SYS.on = True
    try:
        yield
    finally:
        _SYS.on = prev


def can(action: str) -> bool:
    """action: operator | observations | execution | admin. Dihitung dari peran pada sesi (atau aktor tes)."""
    if getattr(_SYS, "on", False):
        return True
    if _TEST["actor"] is not None:
        return action in _ROLE_PAGES.get(_TEST["actor"][1], ())
    u = user()
    if not u:
        return False
    if is_demo_user(u):
        return action in _ROLE_PAGES.get(u.get("role"), ())
    import auth
    if action == "admin":
        return auth.is_admin()
    return auth.can_access_page(action, u) and auth.can_decide() if action == "operator" else auth.can_access_page(action, u)


def require(action: str):
    if not can(action):
        raise PermissionError("forbidden")


def actor_name() -> str:
    u = user()
    return (u or {}).get("username", "-")
