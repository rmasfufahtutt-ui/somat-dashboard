"""rights.py - pemeriksaan hak aksi di BACKEND (repositori operasional), bukan hanya di antarmuka.

Tombol yang disembunyikan atau dinonaktifkan di UI tidak cukup: setiap penulisan yang mengubah keputusan, koreksi,
VOID, pelaksanaan irigasi, pengamatan, atau parameter harus lolos pemeriksaan ini sebelum menyentuh database.

Aturan (sama dengan yang sudah berlaku di UI dan di demo_mode.require):
* Pengguna diambil dari SESI yang terautentikasi, bukan dari argumen `actor`; argumen `actor` harus sama dengan pengguna sesi.
* admin: boleh semua aksi.
* Aksi khusus admin: simpan versi profil/parameter, ubah petak, tambah siklus tanam, VOID keputusan.
* Aksi berbasis halaman: operator (keputusan), observations (pengamatan h), execution (irigasi aktual).
* Koreksi/VOID pengamatan dan pelaksanaan, serta koreksi keputusan: hanya pemilik rekaman atau admin.
* Tanpa sesi (mis. skrip) = ditolak. Pekerjaan sistem yang sah memakai `system()` secara eksplisit dan tercatat.

Kode kegagalan (PermissionError.args[0]): no_session, actor_mismatch, admin_only, page_forbidden, not_owner.
"""
from __future__ import annotations

from contextlib import contextmanager

ALL_PAGES = ("overview", "monitoring", "prediction", "alerts", "operator", "observations", "execution")
DEFAULT_PAGES = {
    "admin": ALL_PAGES,
    "operator": ALL_PAGES,
    "viewer": ("overview", "monitoring", "prediction", "alerts"),
}

ADMIN_ONLY = frozenset({"profile.save", "plot.upsert", "cycle.add", "decision.void"})
PAGE_FOR = {
    "decision.record": "operator",
    "decision.correct": "operator",
    "observation.add": "observations",
    "observation.correct": "observations",
    "observation.void": "observations",
    "execution.add": "execution",
    "execution.correct": "execution",
    "execution.void": "execution",
}
OWNER_OR_ADMIN = frozenset({"decision.correct", "observation.correct", "observation.void",
                            "execution.correct", "execution.void"})
KNOWN_ACTIONS = ADMIN_ONLY | frozenset(PAGE_FOR)

_STATE = {"user": None, "system": False}


def force(user):
    """Hanya untuk tes: paksa pengguna sesi ((username, role) atau dict). None = kembali ke sesi sungguhan."""
    if user is None:
        _STATE["user"] = None
    elif isinstance(user, dict):
        _STATE["user"] = dict(user)
    else:
        _STATE["user"] = {"username": user[0], "role": user[1]}


@contextmanager
def system():
    """Pekerjaan sistem yang sah (mis. migrasi/seed terjadwal). Tidak dipakai oleh jalur tampilan."""
    prev = _STATE["system"]
    _STATE["system"] = True
    try:
        yield
    finally:
        _STATE["system"] = prev


def _session_user():
    if _STATE["user"] is not None:
        return _STATE["user"]
    try:
        import auth
        return auth.current_user()
    except Exception:
        return None


def _page_ok(page, user):
    if _STATE["user"] is not None:
        return page in DEFAULT_PAGES.get(user.get("role"), ())
    import auth
    return bool(auth.can_access_page(page, user))


def evaluate(action, user, actor, owner=None, page_ok=None):
    """Murni (mudah dites). Mengembalikan None bila diizinkan, selain itu kode kegagalan."""
    if action not in KNOWN_ACTIONS:
        return "admin_only"                       # aksi tak dikenal = paling ketat
    if not user or not user.get("username"):
        return "no_session"
    if actor != user["username"]:
        return "actor_mismatch"
    role = user.get("role")
    if role == "admin":
        return None
    if action in ADMIN_ONLY:
        return "admin_only"
    page = PAGE_FOR.get(action)
    ok = page_ok if page_ok is not None else (page in DEFAULT_PAGES.get(role, ()))
    if not ok:
        return "page_forbidden"
    if action in OWNER_OR_ADMIN and owner != user["username"]:
        return "not_owner"
    return None


def authorize(action, actor, owner=None):
    """Lempar PermissionError(kode) bila aksi tidak diizinkan untuk pengguna sesi."""
    if _STATE["system"]:
        return
    user = _session_user()
    page = PAGE_FOR.get(action)
    page_ok = None
    if user and user.get("role") != "admin" and page:
        page_ok = _page_ok(page, user)
    code = evaluate(action, user, actor, owner, page_ok)
    if code:
        raise PermissionError(code)
