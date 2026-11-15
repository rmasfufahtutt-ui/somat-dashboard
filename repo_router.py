"""repo_router.py - satu pintu `repo.*` untuk tampilan. Backend dipilih per sesi:
DEMO -> demo_repository (SQLite terpisah), OPERASIONAL -> repository (Neon/Postgres).

Tampilan tidak perlu tahu mode; pemisahan data dijamin di sini dan di lapisan backend masing-masing."""
from __future__ import annotations

import demo_mode
import demo_repository
import repository
from repository import DecisionError, PARAM_STATUSES, WIB, as_utc, clean_json, inputs_hash, now_utc  # noqa: F401


def backend():
    return demo_repository if demo_mode.is_demo() else repository


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(backend(), name)
