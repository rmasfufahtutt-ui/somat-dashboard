"""i18n.py - pilihan teks dua bahasa (EN/ID). Bahasa dibaca dari sesi Streamlit SAAT DIPANGGIL (bukan saat impor).
Di luar sesi Streamlit (thread latar, worker, tes) bahasa default adalah Indonesia."""


def current_lang() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return "id"
        import streamlit as st
        return st.session_state.get("lang", "en")
    except Exception:
        return "id"


def L(en, id_):
    """Pilih teks sesuai bahasa aktif: L("English", "Indonesia")."""
    return en if current_lang() == "en" else id_
