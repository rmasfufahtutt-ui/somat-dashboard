"""Uji end-to-end Streamlit (AppTest) untuk ruang DEMO: login demo tanpa DB produksi, muat data, rekomendasi -> keputusan ->
pelaksanaan, navigasi tidak mereset form maupun melatih ulang model."""
import os
import shutil
import sys

import pytest
from streamlit.testing.v1 import AppTest

import demo_ml

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


@pytest.fixture
def app(demo_template, tmp_path, monkeypatch):
    import demo_mode
    import demo_repository as drepo
    demo_mode.force(None, None)                       # aplikasi memakai mode dari sesi, bukan override tes
    dst = tmp_path / "app_demo.sqlite3"
    shutil.copy(demo_template, dst)
    monkeypatch.setenv("SOMAT_DEMO_DB", str(dst))
    drepo.configure(None)                             # path dari variabel lingkungan
    drepo._READY.clear()
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["lang"] = "id"
    at.run()
    for b in at.button:
        if b.key == "skip_restore":
            b.click()
            at.run()
            break
    yield at
    demo_mode.force(None, None)
    drepo.configure(None)


def _login(at, who="demo_admin"):
    at.button(key=f"demo_login_{who}").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _go(at, page):
    at.button(key=f"nav_{page}").click()
    at.run()
    assert not at.exception, (page, [e.value for e in at.exception])


def test_demo_login_without_production_db_and_banner(app):
    _login(app)
    assert app.session_state["user"]["demo"] is True and app.session_state["app_mode"] == "DEMO"
    html = " ".join(m.value for m in app.markdown)
    assert "DEMO PENELITIAN" in html
    # tidak ada tombol pindah ke OPERASIONAL untuk sesi demo
    assert not [r for r in app.radio if r.key == "mode_radio"]


def test_all_pages_render_for_each_demo_role(app):
    _login(app, "demo_admin")
    for p in ("overview", "monitoring", "prediction", "operator", "observations", "execution", "alerts", "guide", "account", "admin"):
        _go(app, p)


def test_viewer_has_no_decision_pages(app):
    _login(app, "demo_viewer")
    keys = {b.key for b in app.button if b.key and b.key.startswith("nav_")}
    assert "nav_operator" not in keys and "nav_observations" not in keys and "nav_admin" not in keys
    assert "nav_guide" in keys and "nav_overview" in keys


def test_publish_decide_and_execute_flow(app):
    _login(app)
    _go(app, "prediction")
    app.selectbox(key="pred_plot").select("DEMO-P01").run()
    assert not app.exception
    app.button(key="pub_DEMO-P01").click().run()
    assert not app.exception, [e.value for e in app.exception]
    _go(app, "operator")
    ap = [b for b in app.button if b.key and b.key.startswith("ap_")]
    assert ap and not ap[0].disabled
    ap[0].click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("SIMULASI" in s.value for s in app.success)
    _go(app, "execution")
    assert app.selectbox(key="ex_dec").value
    app.button(key="ex_fill_example").click().run()
    assert app.number_input(key="ex_vol").value > 0
    app.button(key="ex_save").click().run()
    assert not app.exception, [e.value for e in app.exception]
    import demo_repository as drepo
    ev = drepo.list_irrigation_events("DEMO-P01", 5)
    assert any(e["is_simulation"] and e["origin"] == "USER" for e in ev)


def test_navigation_keeps_form_state_and_does_not_retrain(app):
    _login(app)
    _go(app, "observations")
    app.button(key="obs_fill_example").click().run()
    val = app.number_input(key="obs_h_val").value
    note = app.text_input(key="obs_h_note").value
    assert "contoh" in note
    for p in ("overview", "prediction", "operator"):
        _go(app, p)
    _go(app, "observations")
    assert app.number_input(key="obs_h_val").value == val and app.text_input(key="obs_h_note").value == note
    if demo_ml.HAS_SKLEARN:
        _go(app, "admin")
        app.button(key="demo_train").click().run()
        import demo_repository as drepo
        mid = drepo.get_model("RF_RESIDUAL")["model_id"]
        n = drepo.q("SELECT COUNT(*) AS n FROM demo_models")[0]["n"]
        for p in ("prediction", "overview", "prediction"):
            _go(app, p)
        assert drepo.get_model("RF_RESIDUAL")["model_id"] == mid and drepo.q("SELECT COUNT(*) AS n FROM demo_models")[0]["n"] == n


def test_admin_reset_requires_confirmation_and_restores(app):
    import demo_repository as drepo
    _login(app)
    drepo.add_h_observation  # noqa
    _go(app, "observations")
    app.button(key="obs_fill_example").click().run()
    app.button(key="obs_h_save").click().run()
    assert not app.exception and drepo.is_dirty()
    _go(app, "admin")
    app.button(key="demo_reset").click().run()
    assert drepo.is_dirty()                                   # belum berubah sebelum konfirmasi
    app.button(key="demo_confirm_yes").click().run()
    assert not app.exception and not drepo.is_dirty()


def test_prediction_selectors_survive_navigation(app):
    _login(app)
    _go(app, "prediction")
    app.selectbox(key="pred_plot").select("DEMO-P03").run()
    app.selectbox(key="demo_rain").select("NONE").run()
    app.selectbox(key="demo_model").select("M2").run()
    for p in ("overview", "operator", "guide"):
        _go(app, p)
    _go(app, "prediction")
    assert app.selectbox(key="pred_plot").value == "DEMO-P03"
    assert app.selectbox(key="demo_rain").value == "NONE" and app.selectbox(key="demo_model").value == "M2"
    assert not app.exception
