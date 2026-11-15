"""Isolasi end-to-end dengan DB operasional NYATA (Postgres uji): pengguna asli berpindah OPERASIONAL <-> DEMO, dan data
demo tidak pernah menyentuh Postgres. Hanya jalan bila TEST_DATABASE_URL (nama DB mengandung 'test') diisi.
Tes ini TIDAK menghapus skema; hanya memakai tabel baru/kosong dan membersihkan data yang ia buat."""
import os
import shutil

import pytest

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif("test" not in URL.rsplit("/", 1)[-1], reason="TEST_DATABASE_URL (nama DB mengandung 'test') tidak diisi")
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


def _pg(sql, args=()):
    import psycopg2
    c = psycopg2.connect(URL)
    c.autocommit = True
    cur = c.cursor()
    cur.execute(sql, args)
    out = cur.fetchall() if cur.description else None
    c.close()
    return out


def test_real_user_switches_modes_without_leaking(demo_template, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import auth
    import db
    import demo_mode
    import demo_repository as drepo
    import repository
    demo_mode.force(None, None)
    dst = tmp_path / "sw.sqlite3"
    shutil.copy(demo_template, dst)
    monkeypatch.setenv("SOMAT_DEMO_DB", str(dst))
    monkeypatch.setenv("DATABASE_URL", URL)
    drepo.configure(None)
    drepo._READY.clear()
    db.configure(URL)
    assert db.ensure_ready(), db.last_error()
    db.run_migrations()
    import streamlit as st
    st.cache_resource.clear()                      # Settings di-cache lintas tes: paksa baca DATABASE_URL uji
    auth._INIT_DONE = False
    auth.init_auth()
    _pg("DELETE FROM sessions") if _pg("SELECT to_regclass('public.sessions')")[0][0] else None
    _pg("DELETE FROM users WHERE username='swadmin'")
    _pg("INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (%s,%s,'admin',%s,now())",
        ("swadmin", "SW Admin", auth.hash_password("Passw0rd!x")))
    ops_plots_before = _pg("SELECT COUNT(*) FROM plots")[0][0]
    ops_runs_before = _pg("SELECT COUNT(*) FROM recommendation_runs")[0][0]
    try:
        at = AppTest.from_file(APP, default_timeout=90)
        at.session_state["lang"] = "id"
        at.run()
        for b in at.button:
            if b.key == "skip_restore":
                b.click()
                at.run()
                break
        ti = at.text_input
        ti[0].set_value("swadmin")
        ti[1].set_value("Passw0rd!x")
        btns = [b for b in at.button if b.label in ("Masuk", "Sign in")]
        assert btns, ([b.label for b in at.button], [e.value for e in at.exception], [e.value for e in at.error])
        btns[0].click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["user"]["username"] == "swadmin" and at.session_state["app_mode"] == "OPS"
        assert not [m for m in at.markdown if "demo-banner" in m.value]
        at.radio(key="mode_radio").set_value("DEMO").run()
        assert at.session_state["app_mode"] == "DEMO" and any("demo-banner" in m.value for m in at.markdown)
        at.button(key="nav_prediction").click().run()
        at.button(key="pub_DEMO-P01").click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert drepo.q("SELECT COUNT(*) AS n FROM recommendation_runs WHERE origin='USER'")[0]["n"] == 1
        assert _pg("SELECT COUNT(*) FROM plots")[0][0] == ops_plots_before          # Postgres tidak tersentuh
        assert _pg("SELECT COUNT(*) FROM recommendation_runs")[0][0] == ops_runs_before
        at.radio(key="mode_radio").set_value("OPS").run()
        assert at.session_state["app_mode"] == "OPS" and not at.exception
        assert not any("DEMO-P01" in str(getattr(e, "value", "")) for e in at.markdown)
    finally:
        _pg("DELETE FROM users WHERE username='swadmin'")
        demo_mode.force(None, None)
        drepo.configure(None)
        st.cache_resource.clear()
        db.configure("")
        auth._INIT_DONE = False
