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
