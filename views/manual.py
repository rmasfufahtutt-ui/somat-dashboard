"""views/manual.py - halaman Panduan Pengguna (EN/ID), isi dari guide_content, dapat dibuka semua pengguna yang sudah masuk."""
from __future__ import annotations

import streamlit as st

import guide_content
from i18n import L


def render(ctx=None):
    u = (getattr(ctx, "user", None) or st.session_state.get("user") or {})
    role = u.get("role", "viewer")
    st.header(L("📖 User Guide", "📖 Panduan Pengguna"))
    st.caption(L("Short, step-by-step help for your role. SOMAT suggests; the operator decides.",
                 "Panduan singkat langkah demi langkah sesuai peran Anda. SOMAT menyarankan; operator yang memutuskan."))
    secs = guide_content.for_role(role)
    tabs = st.tabs([f"{ic} {L(te, ti)}" for _k, ic, te, ti, _be, _bi in secs])
    for tab, (_k, _ic, _te, _ti, be, bi) in zip(tabs, secs):
        with tab:
            st.markdown(L(be, bi))
