"""data_hub.py - penarik data latar belakang + snapshot dalam memori (tanpa Streamlit).

UI hanya MEMBACA snapshot (operasi O(1), tanpa jaringan/DB). Satu thread daemon per proses menarik sensor
(Google Sheets), prakiraan BMKG, dan peringatan dini sesuai interval masing-masing, lalu menukar snapshot
secara atomik. Prinsip integritas:
  * data baik terakhir TIDAK diganti oleh hasil gagal; sumber ditandai `ok=False`, `stale=True` + galat ringkas;
  * respons kosong yang mencurigakan (sebelumnya ada data) tidak menimpa data lama;
  * arsip DB bersifat idempoten dan kegagalan DB tidak menjatuhkan penarikan;
  * setiap snapshot membawa `fetched_at` per sumber agar UI/rekomendasi dapat memeriksa umur data.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd

import sensor_sheet

log = logging.getLogger("somat.hub")

SOURCES = ("sensor", "forecast", "warnings")


@dataclass(frozen=True)
class SourceState:
    name: str
    ok: bool = False                    # percobaan terakhir sukses
    configured: bool = True
    fetched_at: Optional[datetime] = None      # waktu data baik TERAKHIR diperoleh (UTC)
    attempted_at: Optional[datetime] = None    # percobaan terakhir (UTC)
    error: str = ""
    message: str = ""
    rows: int = 0
    origin: str = "none"                # none | live | db_cache
    suspicious_empty: bool = False

    @property
    def has_data(self) -> bool:
        return self.fetched_at is not None

    def age_s(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.fetched_at is None:
            return None
        return ((now or datetime.now(timezone.utc)) - self.fetched_at).total_seconds()


@dataclass(frozen=True)
class Snapshot:
    version: int = 0
    sensor_df: pd.DataFrame = field(default_factory=sensor_sheet.empty_df)
    sensor_meta: dict = field(default_factory=dict)
    forecast: Optional[dict] = None
    warnings: tuple = ()
    sources: dict = field(default_factory=lambda: {n: SourceState(n) for n in SOURCES})
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def source(self, name: str) -> SourceState:
        return self.sources[name]


def _utc() -> datetime:
    return datetime.now(timezone.utc)


class DataHub:
    """Pengelola snapshot. Semua penarik diinjeksi sehingga mudah diuji tanpa jaringan."""

    def __init__(self, settings, fetch_sensor: Callable, fetch_forecast: Callable, fetch_warnings: Callable,
                 archive_sensor: Optional[Callable] = None, archive_forecast: Optional[Callable] = None,
                 log_ingest: Optional[Callable] = None, warm_loader: Optional[Callable] = None,
                 on_update: Optional[Callable] = None):
        self.s = settings
        self._fetch = {"sensor": fetch_sensor, "forecast": fetch_forecast, "warnings": fetch_warnings}
        self._archive_sensor, self._archive_forecast = archive_sensor, archive_forecast
        self._log_ingest = log_ingest
        self._warm_loader = warm_loader
        self._on_update = on_update
        self._interval = {"sensor": float(settings.refresh_sensor_s),
                          "forecast": float(settings.refresh_forecast_s),
                          "warnings": float(settings.refresh_warning_s)}
        self._snap = Snapshot()
        self._swap = threading.Lock()                 # hanya melindungi penukaran referensi
        self._due = {n: 0.0 for n in SOURCES}
        self._fail_streak = {n: 0 for n in SOURCES}
        self._busy = {n: False for n in SOURCES}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._started = False
        self._last_archived: dict = {}

    # ------------------------------------------------------------------ baca (dipakai UI)
    def snapshot(self) -> Snapshot:
        return self._snap                              # penugasan referensi atomik di CPython

    def intervals(self) -> dict:
        return dict(self._interval)

    # ------------------------------------------------------------------ kontrol siklus hidup
    def start(self) -> "DataHub":
        """Mulai thread latar belakang (idempoten). Awal dingin: muat cache DB dulu agar UI langsung terisi."""
        if self._started:
            return self
        self._started = True
        if self._warm_loader:
            try:
                self._apply_warm(self._warm_loader())
            except Exception as exc:                   # cache awal bersifat opsional
                log.warning("warm start gagal: %s", type(exc).__name__)
        if self.s.background_fetch:
            self._thread = threading.Thread(target=self._run, name="somat-data-hub", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh_now(self, *names: str):
        """Minta penarikan segera (tidak memblokir pemanggil)."""
        for n in (names or SOURCES):
            if n in self._due:
                self._due[n] = 0.0
        self._wake.set()

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------ thread
    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._wake.wait(timeout=2.0)
            self._wake.clear()

    def tick(self, now: Optional[float] = None) -> list:
        """Satu putaran: tarik sumber yang jatuh tempo. Mengembalikan daftar sumber yang ditarik."""
        now = time.monotonic() if now is None else now
        ran = []
        for n in SOURCES:
            if now >= self._due[n] and not self._busy[n]:
                self._busy[n] = True
                try:
                    self._pull(n)
                except Exception as exc:               # pengaman terakhir: thread tidak boleh mati
                    log.exception("pull %s tak terduga", n)
                    self._record_failure(n, type(exc).__name__)
                finally:
                    self._busy[n] = False
                    streak = self._fail_streak[n]
                    backoff = min(2 ** min(streak, 5), 16) if streak else 1
                    self._due[n] = time.monotonic() + self._interval[n] * backoff
                ran.append(n)
        return ran

    # ------------------------------------------------------------------ penarikan per sumber
    def _pull(self, name: str):
        attempted = _utc()
        if name == "sensor":
            df, info = self._fetch["sensor"](self.s)
            self._apply_sensor(df, info, attempted)
        elif name == "forecast":
            res = self._fetch["forecast"](self.s.bmkg_adm4)
            self._apply_forecast(res, attempted)
        else:
            res = self._fetch["warnings"]()
            self._apply_warnings(res, attempted)

    def _apply_sensor(self, df, info, attempted):
        prev = self._snap
        st = prev.sources["sensor"]
        if not info.get("configured", True):
            self._publish(sources={"sensor": replace(st, ok=False, configured=False, attempted_at=attempted,
                                                     message=info.get("message", ""), error="not_configured")})
            return
        if not info.get("ok"):
            self._record_failure("sensor", info.get("error") or "error", message=info.get("message", ""))
            return
        suspicious = bool(df is None or df.empty) and prev.sensor_df is not None and not prev.sensor_df.empty
        if suspicious:
            # Jangan timpa data baik dengan respons kosong; tandai agar UI/operator tahu.
            self._fail_streak["sensor"] += 1
            self._publish(sources={"sensor": replace(st, ok=False, attempted_at=attempted, suspicious_empty=True,
                                                     error="empty_response", message="Respons kosong; data lama dipertahankan.")})
            self._ingest("sensor", False, 0, "empty_response")
            return
        self._fail_streak["sensor"] = 0
        new_state = SourceState("sensor", ok=True, configured=True, fetched_at=attempted, attempted_at=attempted,
                                message=info.get("message", ""), rows=int(len(df)), origin="live")
        self._publish(sensor_df=df, sensor_meta={"sensors": info.get("sensors") or []}, sources={"sensor": new_state})
        n = self._archive("sensor", df)
        self._ingest("sensor", True, n if n is not None else len(df), info.get("message", ""))

    def _apply_forecast(self, res, attempted):
        if not res or not res.get("ok"):
            self._record_failure("forecast", (res or {}).get("error", "error"))
            return
        self._fail_streak["forecast"] = 0
        state = SourceState("forecast", ok=True, fetched_at=res.get("fetched_at") or attempted, attempted_at=attempted,
                            rows=len(res.get("rows", [])), origin="live")
        self._publish(forecast=res, sources={"forecast": state})
        n = self._archive("forecast", res)
        self._ingest("forecast", True, len(res.get("rows", [])), "baru" if n else "payload sama")

    def _apply_warnings(self, res, attempted):
        if not res or not res.get("ok"):
            self._record_failure("warnings", (res or {}).get("error", "error"))
            return
        self._fail_streak["warnings"] = 0
        items = tuple(res.get("warnings") or ())
        state = SourceState("warnings", ok=True, fetched_at=attempted, attempted_at=attempted, rows=len(items),
                            origin="live")
        self._publish(warnings=items, sources={"warnings": state})

    def _apply_warm(self, warm: dict):
        """warm: {"sensor_df": df, "forecast": result} dari DB; ditandai origin=db_cache."""
        kw, sources = {}, {}
        df = warm.get("sensor_df")
        if df is not None and not df.empty:
            kw["sensor_df"] = df
            last = pd.to_datetime(df["timestamp"]).max()
            fa = last.tz_localize("Asia/Jakarta").tz_convert("UTC").to_pydatetime()
            sources["sensor"] = SourceState("sensor", ok=False, fetched_at=fa, rows=len(df), origin="db_cache",
                                            message="Dimuat dari arsip DB; menunggu penarikan terbaru.")
            self._last_archived = {sid: g["timestamp"].max() for sid, g in df.groupby("sensor_id")}
        fc = warm.get("forecast")
        if fc and fc.get("ok"):
            kw["forecast"] = fc
            sources["forecast"] = SourceState("forecast", ok=False, fetched_at=fc.get("fetched_at"),
                                              rows=len(fc.get("rows", [])), origin="db_cache",
                                              message="Dimuat dari arsip DB; menunggu penarikan terbaru.")
        if sources:
            self._publish(sources=sources, **kw)

    # ------------------------------------------------------------------ pembantu
    def _record_failure(self, name, error, message=""):
        self._fail_streak[name] += 1
        st = self._snap.sources[name]
        self._publish(sources={name: replace(st, ok=False, attempted_at=_utc(), error=str(error)[:80],
                                             message=message or st.message)})
        self._ingest(name, False, 0, str(error))

    def _publish(self, sources: dict, **data):
        """Tukar snapshot secara atomik (salinan baru; pembaca lama tetap konsisten)."""
        with self._swap:
            cur = self._snap
            merged = dict(cur.sources)
            merged.update(sources)
            self._snap = Snapshot(
                version=cur.version + 1,
                sensor_df=data.get("sensor_df", cur.sensor_df),
                sensor_meta=data.get("sensor_meta", cur.sensor_meta),
                forecast=data.get("forecast", cur.forecast),
                warnings=data.get("warnings", cur.warnings),
                sources=merged, created_at=_utc())
        if self._on_update:
            try:
                self._on_update(self._snap)
            except Exception:
                pass

    def _archive(self, name, payload):
        """Arsip DB best-effort. Kegagalan hanya dicatat; snapshot memori tetap benar."""
        try:
            if name == "sensor" and self._archive_sensor:
                n = self._archive_sensor(payload, self._last_archived)
                if payload is not None and not payload.empty:
                    self._last_archived = {sid: g["timestamp"].max() for sid, g in payload.groupby("sensor_id")}
                return n
            if name == "forecast" and self._archive_forecast:
                _, is_new = self._archive_forecast(payload)
                return 1 if is_new else 0
        except Exception as exc:
            log.warning("arsip %s gagal: %s", name, type(exc).__name__)
            self._ingest(name, False, 0, f"archive_{type(exc).__name__}")
        return None

    def _ingest(self, source, ok, rows, message):
        if self._log_ingest:
            try:
                self._log_ingest(source, ok, rows, message)
            except Exception:
                pass

    # ------------------------------------------------------------------ status untuk tab Sistem
    def status_rows(self) -> list:
        snap, now = self._snap, _utc()
        out = []
        for n in SOURCES:
            st = snap.sources[n]
            age = st.age_s(now)
            out.append({"source": n, "ok": st.ok, "configured": st.configured, "origin": st.origin,
                        "age_s": None if age is None else round(age), "rows": st.rows, "error": st.error,
                        "message": st.message, "interval_s": self._interval[n], "fail_streak": self._fail_streak[n],
                        "stale": age is None or age > 3 * self._interval[n]})
        return out


def build_hub(settings, repo=None) -> DataHub:
    """Rangkai DataHub produksi. `repo` (modul repository) opsional; tanpa DB hanya memori."""
    import bmkg_integration as bmkg

    archive_sensor = archive_forecast = log_ingest = warm = None
    if repo is not None:
        def archive_sensor(df, last):
            since = {sid: repo.as_utc(ts) for sid, ts in last.items()} if last else repo.last_sensor_times()
            return repo.archive_sensor_rows(df, since)

        archive_forecast = repo.archive_forecast_run
        log_ingest = repo.log_ingest

        def warm():
            import db
            if not db.active():
                return {}
            out = {"sensor_df": repo.load_recent_sensor_frame(14)}
            rows = db.db_query("SELECT run_id, location_id, issued_at, fetched_at, payload_hash, raw_payload FROM "
                               "weather_forecast_runs WHERE location_id=%s ORDER BY fetched_at DESC LIMIT 1",
                               (settings.bmkg_adm4,))
            if rows and rows[0]["raw_payload"]:
                r = rows[0]
                parsed = bmkg.parse_forecast_payload(r["raw_payload"])
                out["forecast"] = {"ok": True, **parsed, "adm4": r["location_id"], "issued_at": r["issued_at"],
                                   "fetched_at": r["fetched_at"], "payload_hash": r["payload_hash"],
                                   "raw": r["raw_payload"]}
            return out

    return DataHub(settings, fetch_sensor=sensor_sheet.fetch_sensor_data,
                   fetch_forecast=lambda adm4: bmkg.fetch_bmkg_forecast(adm4),
                   fetch_warnings=bmkg.fetch_bmkg_early_warnings,
                   archive_sensor=archive_sensor, archive_forecast=archive_forecast,
                   log_ingest=log_ingest, warm_loader=warm)
