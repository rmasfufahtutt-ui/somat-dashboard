"""conftest.py - fixture bersama untuk tes ruang DEMO. Tes demo memakai berkas SQLite SEMENTARA; tidak ada yang menyentuh
database operasional (tidak ada DROP SCHEMA di sini)."""
import os
import shutil
import sqlite3
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="session")
def demo_template(tmp_path_factory):
    """Muat data demo SEKALI (butuh beberapa detik) lalu salin per tes."""
    import demo_data
    import demo_mode
    import demo_repository as drepo
    p = tmp_path_factory.mktemp("demo_tpl") / "tpl.sqlite3"
    drepo.configure(p)
    demo_mode.force("DEMO", ("demo_admin", "admin"))
    try:
        r = demo_data.load(datetime.now(timezone.utc))
        assert r["status"] == "LOADED"
        con = sqlite3.connect(p)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
    finally:
        demo_mode.force(None, None)
    return p


@pytest.fixture
def demo(demo_template, tmp_path):
    """Ruang demo segar (salinan template) dengan aktor admin. Gunakan demo.as_("operator") untuk mengganti peran."""
    import demo_mode
    import demo_repository as drepo
    dst = tmp_path / "demo.sqlite3"
    shutil.copy(demo_template, dst)
    drepo.configure(dst)

    class Env:
        path = dst
        repo = drepo

        @staticmethod
        def as_(role, name=None):
            demo_mode.force("DEMO", (name or f"demo_{role}", role))

    env = Env()
    env.as_("admin")
    try:
        yield env
    finally:
        demo_mode.force(None, None)


@pytest.fixture
def pgdb(monkeypatch):
    """Database PostgreSQL untuk tes SQL sungguhan. Prioritas: (1) TEST_DATABASE_URL (nama DB mengandung 'test'; skema public
    DIHAPUS lalu dibuat ulang) dengan driver psycopg2; (2) SOMAT_PSQL_SHIM="-h /tmp -p 5544 -U pgtest -d somat_test" memakai
    proses psql (untuk lingkungan tanpa psycopg2); selain itu tes dilewati."""
    import os
    import repository as repo
    import db
    url = os.environ.get("TEST_DATABASE_URL", "")
    if "test" in url.rsplit("/", 1)[-1] and db.psycopg2 is not None:
        c = db.psycopg2.connect(url)
        c.autocommit = True
        c.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        c.close()
        db.configure(url)
        assert db.ensure_ready(), db.last_error()
        yield repo
        return
    args = os.environ.get("SOMAT_PSQL_SHIM", "")
    if not args:
        pytest.skip("butuh TEST_DATABASE_URL (DB uji) atau SOMAT_PSQL_SHIM")
    import pgshim
    shim = pgshim.Shim(args.split())
    shim.reset_schema()
    monkeypatch.setattr(repo, "db_query", shim.db_query)
    monkeypatch.setattr(repo, "transaction", shim.transaction)
    monkeypatch.setattr(repo.db, "execute_values", shim.execute_values)
    monkeypatch.setattr(repo, "J", lambda o: pgshim.JsonLit(repo.clean_json(o)))
    yield repo
    shim.close()
