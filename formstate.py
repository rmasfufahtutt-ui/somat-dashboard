"""formstate.py - pertahankan isian widget saat pindah halaman.

Streamlit membuang state widget yang tidak dirender pada sebuah run (mis. saat pengguna membuka halaman lain), sehingga
isian/pilihan kembali ke bawaan. Solusi: salin nilai ke kunci biasa (bukan widget) dan pulihkan sebelum widget dibuat.

Pemakaian:  fs.keep("kunci", bawaan[, options])  ->  widget(..., key="kunci")  ->  fs.sync("kunci", ...)
"""
from __future__ import annotations

import streamlit as st

_P = "_keep_"


def keep(key, default, options=None):
    """Pastikan st.session_state[key] terisi: nilai tersimpan (bila masih sah) atau `default`."""
    ss = st.session_state
    if key in ss:
        return
    val = ss.get(_P + key, default)
    if options is not None and val not in options:
        val = default
    ss[key] = val


def sync(*keys):
    """Salin nilai widget saat ini ke penyimpanan tetap (panggil setelah widget dibuat)."""
    ss = st.session_state
    for k in keys:
        if k in ss:
            ss[_P + k] = ss[k]


def reset(*keys):
    """Hapus nilai (widget dan salinan tetap) agar kembali ke bawaan."""
    ss = st.session_state
    for k in keys:
        ss.pop(k, None)
        ss.pop(_P + k, None)
