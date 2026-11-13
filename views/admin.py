"""views/admin.py - administrasi: pengguna, peran/hak akses, log audit (diekstrak) + Petak & Parameter + Sistem."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import db
from auth import (APP_PAGE_KEYS, SYSTEM_ROLES, auth_msg, create_role, create_user, current_user, delete_role,
                  get_role_pages, is_admin, list_roles, list_users, page_label, refresh_user, reset_password, role_label,
                  save_role_access, update_user)
from db import db_query
from i18n import L
from ui_kit import fmt_ts, table


def fetch_audit(limit=200):
    return db_query("SELECT ts, username, action, detail FROM audit_log ORDER BY ts DESC LIMIT %s", (int(limit),))


def render(hub=None, settings=None):
    refresh_user(force=True)
    st.header(L("🛡️ Administration", "🛡️ Administrasi"))
    if not is_admin():
        st.error(auth_msg("forbidden"))
        return
    if "adm_flash" in st.session_state:
        st.success(st.session_state.pop("adm_flash"))
    from views import admin_plots, admin_system
    tab_users, tab_roles, tab_audit, tab_plots, tab_system = st.tabs([
        L("Users", "Pengguna"),
        L("Roles & access", "Role & hak akses"),
        L("Audit log", "Log audit"),
        L("Plots & parameters", "Petak & parameter"),
        L("System", "Sistem"),
    ])

    with tab_users:
        _users = list_users()
        _role_rows = list_roles()
        _role_keys = [r["role_key"] for r in _role_rows]
        table(pd.DataFrame([{
            L("Username", "Nama pengguna"): r["username"],
            L("Name", "Nama"): r["display_name"],
            L("Role", "Peran"): role_label(r["role"]),
            L("Active", "Aktif"): L("Yes", "Ya") if r["active"] else L("No", "Tidak"),
            L("Created (WIB)", "Dibuat (WIB)"): fmt_ts(r["created_at"]),
        } for r in _users]), key="admin_users", hide_index=True)

        st.subheader(L("➕ Add user", "➕ Tambah pengguna"))
        _default_role = "operator" if "operator" in _role_keys else next((r for r in _role_keys if r != "admin"), _role_keys[0])
        with st.form("add_user_form", clear_on_submit=True):
            a1, a2 = st.columns(2)
            nu = a1.text_input(L("Username", "Nama pengguna"))
            nn = a2.text_input(L("Full name", "Nama lengkap"))
            a3, a4 = st.columns(2)
            nr = a3.selectbox(
                L("Role", "Peran"), _role_keys,
                index=_role_keys.index(_default_role), format_func=role_label,
            )
            npw = a4.text_input(L("Initial password (min. 8 characters)", "Kata sandi awal (min. 8 karakter)"), type="password")
            add_go = st.form_submit_button(L("Create user", "Buat pengguna"), type="primary")
        if add_go:
            _err = create_user(nu, nn, nr, npw)
            if _err:
                st.error(auth_msg(_err))
            else:
                st.session_state["adm_flash"] = L(f"User '{nu.strip().lower()}' created.", f"Pengguna '{nu.strip().lower()}' dibuat.")
                st.rerun()

        st.subheader(L("🛠️ Manage user", "🛠️ Kelola pengguna"))
        _names = [r["username"] for r in _users]
        if _names:
            _sel = st.selectbox(L("Select user", "Pilih pengguna"), _names, key="adm_sel")
            _row = next(r for r in _users if r["username"] == _sel)
            m1, m2 = st.columns(2)
            with m1:
                _row_role = _row["role"] if _row["role"] in _role_keys else _role_keys[0]
                _role = st.selectbox(
                    L("Role", "Peran"), _role_keys,
                    index=_role_keys.index(_row_role),
                    format_func=role_label,
                    key=f"adm_role_{_sel}",
                )
                _act = st.checkbox(L("Active", "Aktif"), value=bool(_row["active"]), key=f"adm_act_{_sel}")
                if st.button(L("Save changes", "Simpan perubahan"), key="adm_save"):
                    _err = update_user(_sel, _role, _act)
                    if _err:
                        st.error(auth_msg(_err))
                    else:
                        st.session_state["adm_flash"] = L("Changes saved.", "Perubahan disimpan.")
                        st.rerun()
            with m2:
                with st.form("adm_reset_form", clear_on_submit=True):
                    _rp = st.text_input(L("New password for this user", "Kata sandi baru untuk pengguna ini"), type="password")
                    _rgo = st.form_submit_button(L("Reset password (also unlocks)", "Reset kata sandi (sekaligus membuka kunci)"))
                if _rgo:
                    _err = reset_password(_sel, _rp)
                    if _err:
                        st.error(auth_msg(_err))
                    else:
                        st.session_state["adm_flash"] = L(f"Password for '{_sel}' reset.", f"Kata sandi '{_sel}' direset.")
                        st.rerun()
        else:
            st.info(L("No users found.", "Belum ada pengguna."))

    with tab_roles:
        st.caption(L(
            "Create custom roles and decide which application tabs each role can open. Account settings remain available to every signed-in user; the Admin tab is reserved for the administrator role.",
            "Buat role khusus dan tentukan tab aplikasi yang dapat dibuka oleh setiap role. Akun Saya tetap tersedia bagi semua pengguna yang sudah masuk; tab Administrasi hanya untuk role administrator."
        ))
        st.subheader(L("➕ Create custom role", "➕ Tambah role khusus"))
        with st.form("create_role_form", clear_on_submit=True):
            _new_role_name = st.text_input(L("Role display name", "Nama role"), max_chars=60)
            _new_role_pages = st.multiselect(
                L("Tabs this role can access", "Tab yang dapat diakses role ini"),
                options=list(APP_PAGE_KEYS),
                default=["overview", "monitoring", "prediction", "alerts"],
                format_func=page_label,
            )
            _create_role_go = st.form_submit_button(L("Create role", "Buat role"), type="primary")
        if _create_role_go:
            _role_error, _created_key = create_role(_new_role_name, _new_role_pages)
            if _role_error:
                st.error(auth_msg(_role_error))
            else:
                st.session_state["adm_flash"] = L(
                    f"Role '{_new_role_name.strip()}' created with key '{_created_key}'.",
                    f"Role '{_new_role_name.strip()}' dibuat dengan kode '{_created_key}'."
                )
                st.rerun()

        # DELETE CUSTOM ROLE
        st.divider()
        st.subheader(L("🗑️ Delete custom role", "🗑️ Hapus role khusus"))

        _custom_role_rows = [
            r for r in list_roles()
            if not r["is_system"]
        ]

        if _custom_role_rows:
            _custom_role_map = {
                r["role_key"]: r["display_name"]
                for r in _custom_role_rows
            }

            _delete_role_key = st.selectbox(
                L("Select role to delete", "Pilih role yang akan dihapus"),
                options=list(_custom_role_map.keys()),
                format_func=lambda k: (
                    f"{_custom_role_map[k]} ({k})"
                ),
                key="delete_role_selected",
            )

            _delete_confirm = st.checkbox(
                L(
                    "I confirm that I want to permanently delete this role.",
                    "Saya yakin ingin menghapus role ini secara permanen."
                ),
                key="confirm_delete_custom_role",
            )

            if st.button(
                L("🗑️ Delete selected role", "🗑️ Hapus role terpilih"),
                key="delete_role_action",
                disabled=not _delete_confirm,
                type="secondary",
            ):
                _err = delete_role(_delete_role_key)

                if _err == "role_in_use":
                    st.error(L(
                        "This role is assigned to users. Reassign those users first in Manage User.",
                        "Role ini masih digunakan pengguna. Ubah role pengguna terlebih dahulu melalui Kelola Pengguna."
                    ))
                elif _err:
                    st.error(auth_msg(_err))
                else:
                    st.session_state["adm_flash"] = L(
                        "Custom role successfully deleted.",
                        "Custom role berhasil dihapus."
                    )

                    for _key in (
                        "role_access_selected",
                        "delete_role_selected",
                        "confirm_delete_custom_role",
                        f"role_access_pages_{_delete_role_key}",
                    ):
                        st.session_state.pop(_key, None)

                    st.rerun()

        else:
            st.info(L(
                "No custom roles available to delete.",
                "Belum ada custom role yang dapat dihapus."
            ))

        # CONFIGURE ROLE ACCESS
        st.divider()
        st.subheader(L("🔐 Configure role access", "🔐 Atur hak akses role"))
        _role_rows = list_roles()

        _editable_roles = [r for r in _role_rows if r["role_key"] != "admin"]
        if _editable_roles:
            _editable_keys = [r["role_key"] for r in _editable_roles]
            _selected_role = st.selectbox(
                L("Select role", "Pilih role"), _editable_keys,
                format_func=role_label, key="role_access_selected",
            )
            _selected_record = next(r for r in _editable_roles if r["role_key"] == _selected_role)
            st.caption(L(f"Role key: `{_selected_role}`", f"Kode role: `{_selected_role}`"))
            _selected_pages = st.multiselect(
                L("Allowed tabs", "Tab yang diizinkan"),
                options=list(APP_PAGE_KEYS),
                default=get_role_pages(_selected_role),
                format_func=page_label,
                key=f"role_access_pages_{_selected_role}",
            )
            if st.button(L("Save access settings", "Simpan hak akses"), key="save_role_access", type="primary"):
                _err = save_role_access(_selected_role, _selected_pages)
                if _err:
                    st.error(auth_msg(_err))
                else:
                    st.success(L("Role access updated. The changes apply on the user's next interaction.", "Hak akses role diperbarui. Perubahan berlaku pada interaksi pengguna berikutnya."))
                    st.rerun()


        st.divider()
        st.subheader(L("Role overview", "Ringkasan role"))
        _role_summary = []
        for _rr in list_roles():
            _role_summary.append({
                L("Role", "Role"): _rr["display_name"],
                L("Role key", "Kode role"): _rr["role_key"],
                L("Type", "Jenis"): L("Built-in", "Bawaan") if _rr["is_system"] else L("Custom", "Khusus"),
                L("Accessible tabs", "Tab yang dapat diakses"): ", ".join(page_label(p) for p in get_role_pages(_rr["role_key"])) or "—",
            })
        table(pd.DataFrame(_role_summary), key="admin_roles_summary", hide_index=True)

    with tab_audit:
        st.caption(L("Latest 200 events: sign-ins, decisions, user changes, and role-access changes.",
                     "200 kejadian terbaru: login, keputusan, perubahan pengguna, dan perubahan hak akses role."))
        _aud = fetch_audit()
        if _aud:
            table(pd.DataFrame([{
                L("Time (WIB)", "Waktu (WIB)"): fmt_ts(r["ts"]),
                L("User", "Pengguna"): r["username"],
                L("Action", "Aksi"): r["action"],
                L("Detail", "Detail"): r["detail"],
            } for r in _aud]), key="admin_audit", hide_index=True)
        else:
            st.info(L("No events yet.", "Belum ada kejadian."))

    with tab_plots:
        admin_plots.render()
    with tab_system:
        admin_system.render(hub, settings)
