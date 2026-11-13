"""db.py - akses Neon PostgreSQL yang aman untuk thread (UI Streamlit, thread latar, dan worker terjadwal).

* Satu pool per proses (bukan st.cache_resource) agar dapat dipakai thread latar tanpa konteks Streamlit.
* Koneksi basi (Neon menidurkan komputasi ketika idle) dideteksi dan diganti sebelum dipakai.
* Migrasi idempoten dijalankan sekali per proses di bawah advisory lock; kegagalan TIDAK di-cache dan
  dicoba ulang paling cepat tiap RETRY_SECONDS.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
except Exception:                                  # paket belum terpasang
    psycopg2 = None

from schema import ALL_STATEMENTS, SCHEMA_VERSION

RETRY_SECONDS = 10.0
IDLE_PING_SECONDS = 90.0
_LOCK = threading.RLock()
_URL = ""
_POOL = None
_POOL_URL = None
_LAST: dict = {}                  # id(koneksi) -> waktu pakai terakhir
_READY = False
_LAST_FAIL = 0.0
_LAST_ERROR = ""


def configure(url: str) -> None:
    """Tetapkan URL database (dipanggil sekali saat aplikasi/worker dimulai)."""
    global _URL, _READY, _POOL, _POOL_URL
    url = (url or "").strip()
    with _LOCK:
        if url != _URL:
            _URL, _READY = url, False
            if _POOL is not None:
                try:
                    _POOL.closeall()
                except Exception:
                    pass
            _POOL, _POOL_URL = None, None


def configured() -> bool:
    return bool(_URL) and psycopg2 is not None


def last_error() -> str:
    return _LAST_ERROR


def _pool():
    global _POOL, _POOL_URL
    with _LOCK:
        if _POOL is None or _POOL_URL != _URL:
            _POOL = psycopg2.pool.ThreadedConnectionPool(
                1, 8, dsn=_URL, connect_timeout=10, client_encoding="UTF8",
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
            )
            _POOL_URL = _URL
        return _POOL


def _checkout():
    """Ambil koneksi sehat. Koneksi idle lama di-ping; bila mati diganti."""
    pool = _pool()
    for _ in range(3):
        con = pool.getconn()
        if con.closed:
            pool.putconn(con, close=True)
            continue
        last = _LAST.get(id(con), 0.0)
        if last and time.time() - last > IDLE_PING_SECONDS:
            try:
                with con.cursor() as cur:
                    cur.execute("SELECT 1")
                con.commit()
            except Exception:
                pool.putconn(con, close=True)
                continue
        return con
    return pool.getconn()


def _release(con, close=False):
    try:
        if close or con.closed:
            _LAST.pop(id(con), None)
        else:
            _LAST[id(con)] = time.time()          # objek koneksi psycopg2 tidak menerima atribut baru
        _pool().putconn(con, close=close or con.closed)
    except Exception:
        pass


def db_query(sql, params=()):
    """Jalankan satu query berparameter. SELECT -> list of dict. Diulang sekali pada kegagalan koneksi."""
    if not configured():
        raise RuntimeError("database belum dikonfigurasi")
    for attempt in (1, 2):
        con = _checkout()
        try:
            with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            con.commit()
            _release(con)
            return rows
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _release(con, close=True)
            if attempt == 2:
                raise
        except Exception:
            try:
                con.rollback()
            finally:
                _release(con)
            raise


@contextmanager
def transaction():
    """Satu transaksi atomik: `with transaction() as cur: cur.execute(...)`. Commit saat keluar normal."""
    if not configured():
        raise RuntimeError("database belum dikonfigurasi")
    con = _checkout()
    try:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        con.commit()
        _release(con)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        _release(con, close=True)
        raise
    except Exception:
        try:
            con.rollback()
        finally:
            _release(con)
        raise


def execute_values(sql: str, rows: list, page_size: int = 500) -> int:
    """INSERT massal: sql memakai satu '%s' untuk VALUES. Mengembalikan jumlah baris yang dikirim."""
    if not rows:
        return 0
    with transaction() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=page_size)
    return len(rows)


def run_migrations() -> None:
    with transaction() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(727401)")
        cur.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cur.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cur.fetchone()
        if row and int(row["value"]) >= SCHEMA_VERSION:
            return
        for stmt in ALL_STATEMENTS:
            cur.execute(stmt)
        cur.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (str(SCHEMA_VERSION),))


def ensure_ready() -> bool:
    """True bila database terkonfigurasi dan migrasi selesai. Tidak memblokir lama saat gagal berulang."""
    global _READY, _LAST_FAIL, _LAST_ERROR
    if _READY:
        return True
    if not configured():
        return False
    with _LOCK:
        if _READY:
            return True
        if time.time() - _LAST_FAIL < RETRY_SECONDS:
            return False
        try:
            run_migrations()
            _READY, _LAST_ERROR = True, ""
        except Exception as exc:                        # pesan ringkas tanpa DSN/kredensial
            _LAST_FAIL, _LAST_ERROR = time.time(), type(exc).__name__
            return False
    return True


def active() -> bool:
    return ensure_ready()
