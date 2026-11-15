"""store.py - pembacaan DB berumur pendek (cache 15 dtk) untuk tampilan. Setelah menulis, panggil `invalidate()`.

Pindah tab dalam jendela 15 dtk tidak menyentuh database. Penulisan selalu langsung ke DB (tanpa cache).
Kunci cache memuat MODE (DEMO/OPS) sehingga data demo dan operasional tidak pernah saling menyajikan."""
from __future__ import annotations

import streamlit as st

import db
import demo_mode
import repo_router as repo

TTL = 15


def _guard(fn, default):
    try:
        return fn() if (demo_mode.is_demo() or db.active()) else default
    except Exception:
        return default


def _cached(fn):
    """Bungkus fn(*args) menjadi cache per-mode: argumen pertama internal = mode_key().
    Setiap fungsi mendapat identitas cache sendiri (nama/qualname) agar kunci cache tidak bertabrakan."""
    def inner(mode_key, *a, **k):      # TANPA awalan "_": argumen berawalan "_" tidak ikut kunci cache
        return fn(*a, **k)
    inner.__name__ = inner.__qualname__ = "store_" + fn.__name__
    inner.__module__ = fn.__module__
    cached = st.cache_data(ttl=TTL, show_spinner=False)(inner)

    def wrapper(*a, **k):
        return cached(demo_mode.mode_key(), *a, **k)
    wrapper.__name__ = fn.__name__
    return wrapper


@_cached
def plots(active_only=True):
    return _guard(lambda: repo.list_plots(active_only), [])


@_cached
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


@_cached
def pending_runs(plot_id=None):
    return _guard(lambda: repo.list_pending_runs(plot_id), [])


@_cached
def h_observations(plot_id, limit=100):
    return _guard(lambda: repo.list_h_observations(plot_id, limit), [])


@_cached
def h_series(plot_id, days=30):
    return _guard(lambda: repo.h_series(plot_id, days), [])


@_cached
def decisions(limit=200, plot_id=None):
    return _guard(lambda: repo.list_decisions(limit, plot_id), [])


@_cached
def awaiting_execution(plot_id=None):
    return _guard(lambda: repo.decisions_awaiting_execution(plot_id), [])


@_cached
def events(plot_id=None, limit=100):
    return _guard(lambda: repo.list_irrigation_events(plot_id, limit), [])


@_cached
def evaluation(plot_id=None):
    return _guard(lambda: repo.evaluation_rows(plot_id), [])


@_cached
def ingest_log(limit=50):
    return _guard(lambda: repo.recent_ingest(limit), [])


def invalidate():
    st.cache_data.clear()
