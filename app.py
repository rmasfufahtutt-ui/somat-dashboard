"""SOMAT Dashboard v2 - router tipis.

Arsitektur kecepatan: penarikan data (Google Sheets, BMKG) berjalan di thread latar belakang (`data_hub`) dan
menghasilkan snapshot di memori. Halaman HANYA membaca snapshot + turunan yang di-memo, sehingga pindah tab tidak
menunggu jaringan/DB. Poller kecil (fragment) memicu render ulang hanya bila ada data baru.
"""
from __future__ import annotations

import html
import time
from types import SimpleNamespace

import streamlit as st

st.set_page_config(page_title="SOMAT Dashboard", page_icon="💧", layout="wide", initial_sidebar_state="auto")

import auth  # noqa: E402
import db  # noqa: E402
import derive  # noqa: E402
import repository  # noqa: E402
import styles  # noqa: E402
import ui_kit  # noqa: E402
from data_hub import build_hub  # noqa: E402
from i18n import L  # noqa: E402
from settings import Settings  # noqa: E402

# ---------------- bahasa + preferensi dari URL ----------------
if "lang" not in st.session_state:
    q = st.query_params.get("lang", "en")
    st.session_state["lang"] = q if q in ("en", "id") else "en"
LANG = st.session_state["lang"]
for k, v in (("page", "login"), ("light_mode", False), ("sb_collapsed", False), ("user", None)):
    st.session_state.setdefault(k, v)

PAGES_OK = auth.APP_PAGE_KEYS + ("account", "admin")
if not st.session_state.get("_prefs_loaded"):
    st.session_state["_prefs_loaded"] = True
    qp = st.query_params
    if qp.get("theme") in ("light", "dark"):
        st.session_state["light_mode"] = qp.get("theme") == "light"
    if qp.get("sb") in ("0", "1"):
        st.session_state["sb_collapsed"] = qp.get("sb") == "1"
    if qp.get("page") in PAGES_OK:
        st.session_state["_want_page"] = qp.get("page")


# ---------------- infrastruktur (sekali per proses) ----------------
@st.cache_resource(show_spinner=False)
def get_settings() -> Settings:
    return Settings.from_streamlit()


@st.cache_resource(show_spinner=False)
def get_hub(_settings: Settings):
    db.configure(_settings.db_url)
    ready = db.ensure_ready()
    hub = build_hub(_settings, repo=repository if ready else None)
    return hub.start()


SETTINGS = get_settings()
db.configure(SETTINGS.db_url)
if db.ensure_ready():
    try:
        auth.init_auth()
    except Exception:
        pass
HUB = get_hub(SETTINGS)

auth.sync_browser_session()
if st.session_state.get("user"):
    now_t = time.time()
    if now_t - st.session_state.get("_last_activity", now_t) > auth.IDLE_SECONDS:
        auth.audit("session_timeout")
        auth.logout()
        st.session_state["_expired"] = True
    else:
        st.session_state["_last_activity"] = now_t
        tok = st.session_state.get("_session_token")
        if db.active() and tok and now_t - st.session_state.get("_touched", 0) > 60:
            try:
                auth.touch_session(tok)
            except Exception:
                pass
            st.session_state["_touched"] = now_t

COLLAPSED = bool(st.session_state["sb_collapsed"])
IS_DARK = not bool(st.session_state["light_mode"])
# build_css() sudah membungkus dirinya dengan <style>...</style>; bungkus ganda membuat CSS ui_kit bocor jadi teks.
# Satu blok <style> saja, tanpa baris kosong.
_css = styles.build_css(IS_DARK, COLLAPSED).replace("<style>", "").replace("</style>", "") + "\n" + ui_kit.ui_css(IS_DARK)
_css = "\n".join(ln for ln in _css.splitlines() if ln.strip())
st.markdown(f"<style>\n{_css}\n</style>", unsafe_allow_html=True)


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


def _sync_url(with_page):
    want = {"theme": "light" if st.session_state.get("light_mode") else "dark", "sb": "1" if COLLAPSED else "0", "lang": LANG}
    if with_page:
        want["page"] = st.session_state["page"]
    for k, v in want.items():
        if st.query_params.get(k) != v:
            st.query_params[k] = v


st.button("Toggle theme", key="theme_icon", on_click=_toggle_theme,
          help=L("Switch to light mode", "Ganti ke light mode") if IS_DARK else L("Switch to dark mode", "Ganti ke dark mode"))
st.button(f"🌐 {LANG.upper()}", key="lang_btn", on_click=_toggle_lang, help=L("Switch to Bahasa Indonesia", "Ganti ke English"))

# ---------------- gerbang login ----------------
from views import login  # noqa: E402

if not db.active():
    st.session_state["user"] = None
else:
    auth.refresh_user()

if (not auth.current_user()) and db.active() and auth._SESS_COMPONENT is not None and not st.session_state.get("_restore_tried"):
    login.render_restoring_screen()
    st.stop()
if not auth.current_user():
    st.session_state["page"] = "login"
    _sync_url(False)
    login.render_login_screen()
    st.stop()
user = auth.refresh_user()
if not user:
    st.session_state["page"] = "login"
    login.render_login_screen()
    st.stop()

pg = st.session_state.get("page", "overview")
if pg == "login":
    st.session_state["page"] = st.session_state.pop("_want_page", None) or "overview"
    pg = st.session_state["page"]
if pg == "account":
    pass
elif pg == "admin":
    if not auth.is_admin():
        st.session_state["page"] = auth._first_accessible_page(user)
elif pg not in auth.APP_PAGE_KEYS or not auth.can_access_page(pg, user):
    st.session_state["page"] = auth._first_accessible_page(user)
_sync_url(True)

st.button("Toggle sidebar", key="sb_toggle", on_click=_toggle_sidebar,
          help=L("Expand sidebar", "Perluas sidebar") if COLLAPSED else L("Collapse sidebar", "Perkecil sidebar"))

# ---------------- data: HANYA membaca snapshot ----------------
SNAP = HUB.snapshot()
D = derive.get(SNAP)
CTX = SimpleNamespace(hub=HUB, settings=SETTINGS, snap=SNAP, d=D, user=user)


def _age(state):
    a = state.age_s()
    if a is None:
        return "—"
    return f"{a:.0f}s" if a < 90 else (f"{a / 60:.0f}m" if a < 5400 else f"{a / 3600:.1f}h")


# ---------------- sidebar ----------------
NAV = [("overview", "📊", L("Overview", "Ringkasan")),
       ("monitoring", "📡", L("Sensor Monitoring", "Monitoring Sensor")),
       ("prediction", "💧", L("Prediction & Recommendation", "Prediksi & Rekomendasi")),
       ("operator", "👷", L("Operator Decision", "Keputusan Operator")),
       ("observations", "🪣", L("Field Observations", "Pengamatan Lapangan")),
       ("execution", "🚿", L("Irrigation Execution", "Pelaksanaan Irigasi")),
       ("alerts", "🚨", L("Alerts", "Peringatan"))]
nav_items = [(p, i, t) for p, i, t in NAV if auth.can_access_page(p)]
nav_items.append(("account", "👤", L("My Account", "Akun Saya")))
if auth.is_admin():
    nav_items.append(("admin", "🛡️", L("Admin", "Administrasi")))

with st.sidebar:
    if COLLAPSED:
        st.markdown(f'<div class="side-brand mini"><img src="{styles.LOGO_SRC}" alt="SOMAT"></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="side-brand"><img src="{styles.LOGO_SRC}" alt="Logo SOMAT"><div><div class="side-brand-name">SOMAT</div>'
                    f'<div class="side-brand-sub">Smart Adaptive Irrigation Management System</div></div></div>', unsafe_allow_html=True)
        if D.is_real:
            st.success(L("Live sensor data", "Data sensor live"))
        else:
            st.error(L("⚠️ DEMO / non-field data in use", "⚠️ Data DEMO / non-lapangan dipakai"))
        st.markdown("#### Menu")
    for pid, icon, label in nav_items:
        st.button(icon if COLLAPSED else f"{icon}  {label}", key=f"nav_{pid}", help=label if COLLAPSED else None,
                  type="primary" if st.session_state["page"] == pid else "secondary", width="stretch",
                  on_click=_set_page, args=(pid,))
    u = auth.current_user()
    if u:
        av = html.escape(u.get("avatar_data") or "", quote=True)
        initial = html.escape((u.get("display_name") or u.get("username", "S"))[:1].upper())
        avm = f'<img src="{av}" alt="Profile picture">' if av else f'<div class="side-profile-fallback">{initial}</div>'
        if COLLAPSED:
            st.markdown(f'<div class="side-profile-mini">{avm}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="side-profile">{avm}<div style="min-width:0;"><div class="side-profile-name">'
                        f'{html.escape(u.get("display_name") or u.get("username", ""))}</div>'
                        f'<div class="side-profile-caption">{L("Signed in", "Sedang masuk")}</div></div></div>', unsafe_allow_html=True)
        st.button("🚪" if COLLAPSED else "🚪  " + L("Sign out", "Keluar"), key="nav_logout", width="stretch", on_click=auth.logout,
                  help=L("Sign out", "Keluar") if COLLAPSED else None)
    if not COLLAPSED:
        rows = "".join(f'<div class="side-info-line">{n}: <b>{_age(SNAP.source(k))}</b> {"✔" if SNAP.source(k).ok else "⚠"}</div>'
                       for k, n in (("sensor", L("Sensors", "Sensor")), ("forecast", L("BMKG forecast", "Prakiraan BMKG")),
                                    ("warnings", L("BMKG warnings", "Peringatan BMKG"))))
        st.markdown(f'<div class="side-info-card"><div class="side-info-title">🔄 <span>{L("Data freshness (background)", "Kesegaran data (latar belakang)")}</span></div>'
                    f'{rows}</div><div class="side-info-card"><div class="side-info-title">🔁 <span>{L("SOMAT workflow", "Alur kerja SOMAT")}</span></div>'
                    f'<div class="side-flow">{L("Field h → Forecast → Water balance → Recommendation → Operator decision → Actual irrigation → Evaluation", "h lapangan → Prakiraan → Neraca air → Rekomendasi → Keputusan operator → Irigasi aktual → Evaluasi")}</div></div>',
                    unsafe_allow_html=True)

page = st.session_state["page"]
st.markdown(f'<div class="somat-header"><img src="{styles.LOGO_SRC}" alt="Logo SOMAT"><div>'
            f'<h1>SOMAT — Smart Adaptive Irrigation Management System</h1>'
            f'<p>{L("Decision-support for observation, water-balance prediction, operator decisions and evaluation.", "Pendukung keputusan untuk observasi, prediksi neraca air, keputusan operator, dan evaluasi.")}</p></div></div>',
            unsafe_allow_html=True)

# ---------------- halaman ----------------
if page == "overview":
    from views import overview
    overview.render(CTX)
elif page == "monitoring":
    from views import monitoring
    monitoring.render(CTX)
elif page == "prediction":
    from views import prediction
    prediction.render(CTX)
elif page == "alerts":
    from views import alerts
    alerts.render(CTX)
elif page == "operator":
    from views import operator
    operator.render(CTX)
elif page == "observations":
    from views import observations
    observations.render(CTX)
elif page == "execution":
    from views import execution
    execution.render(CTX)
elif page == "account":
    from views import account
    account.render()
elif page == "admin":
    from views import admin
    admin.render(HUB, SETTINGS)

# ---------------- poller: render ulang hanya bila ada data baru (halaman baca-saja) ----------------
AUTO_PAGES = ("overview", "monitoring", "prediction", "alerts")


def content_key(snap):
    return tuple((s.fetched_at, s.ok, s.error) for s in (snap.source(n) for n in ("sensor", "forecast", "warnings")))


if page in AUTO_PAGES:
    st.session_state["_seen_key"] = content_key(SNAP)

    @st.fragment(run_every=10)
    def _poller():
        if content_key(HUB.snapshot()) != st.session_state.get("_seen_key"):
            st.rerun()

    _poller()
