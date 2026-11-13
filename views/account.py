"""views/account.py - profil dan ganti kata sandi pengguna."""
from __future__ import annotations

import base64
import html

import streamlit as st

from auth import (auth_msg, avatar_data_from_upload, change_own_password, refresh_user, role_label, update_own_profile)
from i18n import L


def render():
    _u = refresh_user()
    st.header(L("👤 My Account", "👤 Akun Saya"))
    if not _u:
        st.info(L("Please sign in.", "Silakan masuk."))
    else:
        st.caption(L("Manage the name and profile photo shown in the sidebar.", "Atur nama dan foto profil yang ditampilkan di sidebar."))
        profile_left, profile_right = st.columns([0.8, 1.7], gap="large")
        with profile_left:
            if _u.get("avatar_data"):
                try:
                    _avatar_bytes = base64.b64decode(_u["avatar_data"].split(",", 1)[1])
                    st.image(_avatar_bytes, width=150)
                except Exception:
                    st.info(L("Profile photo preview is unavailable.", "Pratinjau foto profil tidak tersedia."))
            else:
                _initial = html.escape((_u.get("display_name") or _u["username"])[0].upper())
                st.markdown(
                    f'<div class="side-profile-fallback" style="width:112px;height:112px;font-size:2rem;">{_initial}</div>',
                    unsafe_allow_html=True,
                )
            st.write(f"**{_u['username']}**")
            st.caption(role_label(_u["role"]))
        with profile_right:
            with st.form("profile_form", clear_on_submit=False):
                _display_name = st.text_input(
                    L("Display name", "Nama tampilan"),
                    value=_u.get("display_name") or _u["username"],
                    max_chars=60,
                )
                _photo_upload = st.file_uploader(
                    L("Profile picture", "Foto profil"),
                    type=["png", "jpg", "jpeg", "webp"],
                    help=L("Maximum 5 MB. The image is resized automatically.", "Maksimal 5 MB. Foto akan diperkecil secara otomatis."),
                )
                _remove_photo = st.checkbox(L("Remove current photo", "Hapus foto saat ini"), value=False)
                _save_profile = st.form_submit_button(L("Save profile", "Simpan profil"), type="primary")
            if _save_profile:
                _new_avatar = _u.get("avatar_data")
                _avatar_error = None
                if _remove_photo:
                    _new_avatar = None
                elif _photo_upload is not None:
                    _new_avatar, _avatar_error = avatar_data_from_upload(_photo_upload)
                if _avatar_error:
                    st.error(auth_msg(_avatar_error))
                else:
                    _profile_error = update_own_profile(_display_name, _new_avatar)
                    if _profile_error:
                        st.error(auth_msg(_profile_error))
                    else:
                        st.success(L("Profile updated.", "Profil berhasil diperbarui."))
                        st.rerun()

        st.divider()
        st.subheader(L("Change password", "Ganti kata sandi"))
        with st.form("pw_form", clear_on_submit=True):
            _cur = st.text_input(L("Current password", "Kata sandi saat ini"), type="password")
            _new = st.text_input(L("New password (min. 8 characters)", "Kata sandi baru (min. 8 karakter)"), type="password")
            _cnf = st.text_input(L("Repeat new password", "Ulangi kata sandi baru"), type="password")
            _go = st.form_submit_button(L("Save new password", "Simpan kata sandi baru"))
        if _go:
            _err = change_own_password(_cur, _new, _cnf)
            if _err:
                st.error(auth_msg(_err))
            else:
                st.success(L("Password changed.", "Kata sandi diganti."))
