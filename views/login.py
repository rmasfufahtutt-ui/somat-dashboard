"""views/login.py - layar masuk, layar pemulihan sesi, dan form login."""
from __future__ import annotations

import streamlit as st

import auth
from auth import authenticate, auth_msg, start_session, current_user
import db
from i18n import L
from styles import LOGO_SRC, _irrigation_image_b64

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


def render_login_form(key="login_form"):
    st.subheader(L("🔐 Sign in", "🔐 Masuk"))
    if not db.active():
        st.error(auth_msg("db"))
        render_demo_login()
        return
    with st.form(key):
        uname = st.text_input(L("Username", "Nama pengguna"))
        pwd = st.text_input(L("Password", "Kata sandi"), type="password")
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
        f'''<div style="text-align:center;padding:3rem 0;opacity:.9"><img src="{LOGO_SRC}" alt="SOMAT" style="width:64px">
        <p>{L("Checking your session…", "Memeriksa sesi Anda…")}</p></div>''',
        unsafe_allow_html=True,
    )
    if st.button(L("Go to sign in", "Ke halaman masuk"), key="skip_restore"):
        st.session_state["_restore_tried"] = True
        st.rerun()



def render_login_screen():
    'Login menjadi layar pertama; sidebar dan konten dashboard belum dirender.'
    st.markdown('<div class="login-page-spacer"></div>', unsafe_allow_html=True)
    left, right = st.columns([1.18, 0.82], gap="large", vertical_alignment="center")
    with left:
        if IRRIGATION_SRC:
            _bg = f"linear-gradient(180deg,rgba(5,18,38,.20) 0%,rgba(5,18,38,.84) 100%),url('{IRRIGATION_SRC}')"
        else:
            _bg = "linear-gradient(135deg,#0B3B65,#0F766E)"
        st.markdown(
            f'''<section class="login-visual" style="background-image:{_bg};">
              <div class="login-visual-brand"><img src="{LOGO_SRC}" alt="SOMAT logo"><div>
                <strong>SOMAT</strong><span>Smart Adaptive Irrigation Management System</span>
              </div></div>
              <div class="login-visual-copy"><small>SMART IRRIGATION · DATA · DECISION</small>
                <h2>{L("Smarter water management starts with better decisions.", "Pengelolaan air yang lebih cerdas dimulai dari keputusan yang lebih baik.")}</h2>
                <p>{L("Monitor field conditions, review irrigation recommendations, and keep operational decisions under human control.", "Pantau kondisi lahan, tinjau rekomendasi irigasi, dan pastikan keputusan operasional tetap berada di bawah kendali manusia.")}</p>
              </div>
              <div class="login-visual-foot">SOMAT · Smart Adaptive Irrigation Management System</div>
            </section>''',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f'''<div class="login-panel-brand"><img src="{LOGO_SRC}" alt="Logo SOMAT"><div>
              <strong>SOMAT</strong><span>Smart Adaptive Irrigation Management System</span>
            </div></div>''',
            unsafe_allow_html=True,
        )
        st.header(L("Welcome back", "Selamat datang kembali"))
        st.caption(L("Sign in with your registered account to access the dashboard.", "Masuk menggunakan akun terdaftar untuk mengakses dashboard."))
        if st.session_state.pop("_expired", False):
            st.warning(L("Your session expired after 30 minutes of inactivity. Please sign in again.",
                         "Sesi berakhir setelah 30 menit tidak aktif. Silakan masuk kembali."))
        render_login_form("login_form")
        st.caption(L("Access is managed by the SOMAT administrator.", "Hak akses dikelola oleh administrator SOMAT."))

