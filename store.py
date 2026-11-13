"""store.py - pembacaan DB berumur pendek (cache 15 dtk) untuk tampilan. Setelah menulis, panggil `invalidate()`.

Pindah tab dalam jendela 15 dtk tidak menyentuh database. Penulisan selalu langsung ke DB (tanpa cache)."""
from __future__ import annotations

import streamlit as st

import db
import repository as repo

TTL = 15


def _guard(fn, default):
    try:
        return fn() if db.active() else default
    except Exception:
        return default


@st.cache_data(ttl=TTL, show_spinner=False)
def plots(active_only=True):
    return _guard(lambda: repo.list_plots(active_only), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def plot_overview():
    """Per petak: h terakhir (waktu, nilai), rekomendasi PUBLISHED, profil aktif, siklus aktif."""
    def run():
        out = []
        pending = {r["plot_id"]: r for r in repo.list_pending_runs()}
        for p in repo.list_plots():
            pid = p["plot_id"]
            prof = repo.get_active_profile(pid)
            out.append({"plot": p, "h": repo.latest_h(pid), "pending": pending.get(pid),
                        "profile": None if prof is None else {k: prof[k] for k in ("profile_id", "version", "validation_status")},
                        "cycle": repo.get_active_cycle(pid)})
        return out
    return _guard(run, [])


@st.cache_data(ttl=TTL, show_spinner=False)
def pending_runs(plot_id=None):
    return _guard(lambda: repo.list_pending_runs(plot_id), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def h_observations(plot_id, limit=100):
    return _guard(lambda: repo.list_h_observations(plot_id, limit), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def h_series(plot_id, days=30):
    return _guard(lambda: repo.h_series(plot_id, days), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def decisions(limit=200, plot_id=None):
    return _guard(lambda: repo.list_decisions(limit, plot_id), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def awaiting_execution(plot_id=None):
    return _guard(lambda: repo.decisions_awaiting_execution(plot_id), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def events(plot_id=None, limit=100):
    return _guard(lambda: repo.list_irrigation_events(plot_id, limit), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def evaluation(plot_id=None):
    return _guard(lambda: repo.evaluation_rows(plot_id), [])


@st.cache_data(ttl=TTL, show_spinner=False)
def ingest_log(limit=50):
    return _guard(lambda: repo.recent_ingest(limit), [])


def invalidate():
    st.cache_data.clear()
