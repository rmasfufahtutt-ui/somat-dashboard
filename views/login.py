"""views/login.py - layar masuk, layar pemulihan sesi, dan form login."""
from __future__ import annotations

import streamlit as st

import auth
from auth import authenticate, auth_msg, start_session, current_user
import db
from i18n import L
from styles import LOGO_SRC, _irrigation_image_b64
import sekar_theme

_irr = _irrigation_image_b64()
IRRIGATION_SRC = f"data:image/jpeg;base64,{_irr}" if _irr else ""

def render_demo_login(key="demo_login"):
    """Masuk ke ruang DEMO PENELITIAN tanpa database produksi (akun demo bawaan, tanpa kata sandi)."""
    import demo_mode
    st.markdown("---")
    st.markdown("**" + L("Research demo (synthetic data)", "Demo penelitian (data sintetis)") + "**")
    st.caption(L("For presentation and trials. Isolated from operational data; BMKG stays real.",
                 "Untuk presentasi dan uji coba. Terpisah dari data operasional; BMKG tetap asli."))
    if st.button("📘 " + L("Demo Guide", "Panduan Demo"), key=f"{key}_guide", width="stretch",
                 help=L("Architecture, walkthrough, who can edit what", "Arsitektur, alur pelaksanaan, siapa boleh mengedit apa")):
        from views import guide
        guide.open_guide()
    roles = [("demo_admin", L("Demo as Admin", "Demo sebagai Admin")),
             ("demo_operator", L("Demo as Operator", "Demo sebagai Operator")),
             ("demo_viewer", L("Demo as Viewer", "Demo sebagai Pengamat"))]
    cols = st.columns(len(roles))
    for col, (uname, label) in zip(cols, roles):
        if col.button(label, key=f"{key}_{uname}", use_container_width=True):
            auth.demo_login(uname)
            st.rerun()


def render_login_form(key="login_form", show_title=True):
    if show_title:
        st.subheader(L("🔐 Sign in", "🔐 Masuk"))
    if not db.active():
        st.error(auth_msg("db"))
        render_demo_login()
        return
    with st.form(key):
        uname = st.text_input(L("Username", "Nama pengguna"), placeholder=L("Username", "Nama pengguna"))
        pwd = st.text_input(L("Password", "Kata sandi"), type="password", placeholder=L("Password", "Kata sandi"))
        go = st.form_submit_button(L("Sign in", "Masuk"), type="primary")
    if go:
        user, err = authenticate(uname, pwd)
        if user:
            start_session(user)
            st.rerun()
        else:
            st.error(auth_msg(err))
    render_demo_login()


def render_restoring_screen():
    """Tampil sebentar saat memeriksa sesi tersimpan (sebelum layar login)."""
    st.markdown('<div class="login-page-spacer"></div>', unsafe_allow_html=True)
    st.markdown(
        f'''<div style="text-align:center;padding:3rem 0;opacity:.9"><img src="{LOGO_SRC}" alt="SEKAR" style="width:64px">
        <p>{L("Checking your session…", "Memeriksa sesi Anda…")}</p></div>''',
        unsafe_allow_html=True,
    )
    if st.button(L("Go to sign in", "Ke halaman masuk"), key="skip_restore"):
        st.session_state["_restore_tried"] = True
        st.rerun()



# Perbaikan tampilan login: berdiri sendiri di sini agar tidak bergantung pada sekar_theme.py yang bisa ter-cache.
LOGIN_FIX_CSS = r"""
/* Layar login: SATU tema (terang) untuk mode gelap maupun terang. Selektor dibuat sangat spesifik agar menang atas CSS tema dashboard. */
/* latar login dikunci ke foto sawah, menang atas latar dalam dashboard (sekar_bg) */
html body .stApp.stApp{background:#7fb0d8 url('app/static/sekar_login_bg.jpg') center/cover no-repeat fixed!important}
html body .stApp.stApp::before{display:none!important}
@media(min-width:901px){ html body .stApp .sk-hero, html body .stApp [data-testid="stMarkdownContainer"]:has(> .sk-hero){display:none!important} }
html body .stApp .st-key-sekar_login_card{color-scheme:light!important;background:linear-gradient(160deg,rgba(255,255,255,.90),rgba(232,242,250,.84))!important}
html body .stApp .st-key-sekar_login_card :is(p,span,label,small,li,div){color:#243b52!important}
html body .stApp .st-key-sekar_login_card :is(h1,h2,h3){color:#0b2a46!important}
html body .stApp .st-key-sekar_login_card [data-testid="stCaptionContainer"] *{color:#47607a!important}
html body .stApp .st-key-sekar_login_card [data-baseweb="input"],html body .stApp .st-key-sekar_login_card [data-baseweb="base-input"]{background:#ffffff!important;border:1px solid rgba(11,42,70,.28)!important;border-radius:14px!important}
html body .stApp .st-key-sekar_login_card input{color:#0b2a46!important;-webkit-text-fill-color:#0b2a46!important;background:transparent!important}
html body .stApp .st-key-sekar_login_card input::placeholder{color:#7a8ea3!important;-webkit-text-fill-color:#7a8ea3!important;opacity:1!important}
html body .stApp .st-key-sekar_login_card [data-baseweb="input"] svg{fill:#516a80!important;color:#516a80!important}
html body .stApp .st-key-sekar_login_card [data-testid^="stBaseButton"]{background:#ffffff!important;border:1px solid rgba(11,42,70,.30)!important;border-radius:12px!important;min-height:44px;box-shadow:none!important}
html body .stApp .st-key-sekar_login_card [data-testid^="stBaseButton"] *{color:#0b2a46!important;-webkit-text-fill-color:#0b2a46!important;font-weight:700;font-size:.85rem;line-height:1.15;white-space:normal!important;overflow:visible!important;text-overflow:clip!important}
html body .stApp .st-key-sekar_login_card [data-testid^="stBaseButton"]:hover{background:#eef5fb!important;border-color:#0b2a46!important}
html body .stApp .st-key-sekar_login_card [data-testid^="stBaseButton"][data-testid*="primary"]{background:#0b2a46!important;border:0!important;min-height:54px;border-radius:999px!important}
html body .stApp .st-key-sekar_login_card [data-testid^="stBaseButton"][data-testid*="primary"] *{color:#ffffff!important;-webkit-text-fill-color:#ffffff!important;font-size:1.05rem;font-weight:800}
html body .stApp .st-key-sekar_login_card [data-testid="stAlertContainer"]{background:#fdeceb!important;border:1px solid #f1b5b0!important;border-radius:12px!important}
html body .stApp .st-key-sekar_login_card [data-testid="stAlertContainer"] *{color:#7a1d1d!important;-webkit-text-fill-color:#7a1d1d!important}
html body .stApp .st-key-sekar_login_card hr{border-color:rgba(11,42,70,.18)!important}
html body .stApp .st-key-lang_btn [data-testid^="stBaseButton"]{background:rgba(255,255,255,.85)!important;border:1px solid rgba(11,42,70,.25)!important}
html body .stApp .st-key-lang_btn [data-testid^="stBaseButton"] *{color:#0b2a46!important;-webkit-text-fill-color:#0b2a46!important}

/* kolom input: Streamlit baru mengecat wadahnya (stTextInputRootElement) dengan warna tema gelap */
html body .stApp .st-key-sekar_login_card [data-testid="stTextInputRootElement"],html body .stApp .st-key-sekar_login_card [data-testid="stTextInput"] [data-baseweb="input"]{background:#ffffff!important;border:1px solid rgba(11,42,70,.28)!important;border-radius:14px!important}
html body .stApp .st-key-sekar_login_card [data-testid="stTextInputRootElement"] button{background:transparent!important;border:0!important;box-shadow:none!important}
html body .stApp .st-key-sekar_login_card [data-testid="stTextInputRootElement"] svg{fill:#516a80!important;color:#516a80!important}
html body .stApp .st-key-sekar_login_card [data-testid="stFormSubmitButton"],html body .stApp .st-key-sekar_login_card [data-testid="stFormSubmitButton"] button{width:100%!important}
/* HP / layar sempit: hero diberi panel gelap agar tulisan putih terbaca, jarak ke kartu, dan latar digeser ke sisi kanan (tanpa sisa tulisan di tepi kiri) */
@media(max-width:900px){
  html body .stApp.stApp{background-position:86% center!important}
  html body .stApp .sk-hero{background:rgba(6,34,58,.62)!important;border-radius:26px;padding:1.2rem 1rem 1.4rem!important;margin-bottom:1.2rem!important;
    -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
  html body .stApp .st-key-sekar_login_card{margin-top:.6rem!important}
}
"""

def render_login_screen():
    'Layar login SEKAR: latar sawah penuh, logo + judul di kiri, kartu kaca di kanan. Sidebar/dashboard belum dirender.'
    st.markdown("<style>\n" + sekar_theme.FONT_IMPORT + "\n" + sekar_theme.login_css() + "\n</style>", unsafe_allow_html=True)
    st.markdown("<style>\n" + LOGIN_FIX_CSS + "\n</style>", unsafe_allow_html=True)
    st.markdown('<div class="login-page-spacer"></div>', unsafe_allow_html=True)
    left, right = st.columns([1.15, 0.85], gap="large", vertical_alignment="center")
    with left:
        st.markdown(
            f'''<section class="sk-hero">
              <img src="{sekar_theme.STATIC}/sekar_logo.png" onerror="this.onerror=null;this.src=\'{LOGO_SRC}\'" alt="SEKAR logo">
              <div class="sk-title">SEKAR</div>
              <div class="sk-tag">{sekar_theme.TAGLINE}</div>
              <div class="sk-sub">{sekar_theme.FULL_ID}<i>{sekar_theme.FULL_EN}</i></div>
            </section>''',
            unsafe_allow_html=True,
        )
    with right:
        with st.container(key="sekar_login_card"):
            st.header(L("Sign in to SEKAR", "Masuk ke SEKAR"))
            st.caption(L("System access for monitoring, evaluation, and irrigation recommendations.",
                         "Akses sistem untuk monitoring, evaluasi, dan rekomendasi irigasi."))
            if st.session_state.pop("_expired", False):
                st.warning(L("Your session expired after a long period of inactivity. Please sign in again.",
                             "Sesi berakhir karena lama tidak aktif. Silakan masuk kembali."))
            render_login_form("login_form", show_title=False)
            st.caption(L("Access is managed by the SEKAR administrator.", "Hak akses dikelola oleh administrator SEKAR."))
