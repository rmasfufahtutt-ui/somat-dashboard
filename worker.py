"""worker.py - ingest sekali jalan untuk penjadwal eksternal (GitHub Actions) saat dashboard tertutup.

Memakai modul yang sama dengan dashboard (sensor_sheet, bmkg_integration, repository) sehingga arsip identik
dan idempoten. Kode keluar 0 bila ada sumber yang berhasil, 1 bila semua gagal, 2 bila DB tidak siap.

Variabel lingkungan: DATABASE_URL, SENSOR_SHEET_URL, SENSOR_SHEET_READ_KEY, SENSOR_SOURCE_TYPE, BMKG_ADM4.
Opsi: --recommend  juga menerbitkan rekomendasi tiap petak aktif (hanya bila h manual masih segar).
"""
from __future__ import annotations

import argparse
import sys

import bmkg_integration as bmkg
import db
import repository as repo
import sensor_sheet
from settings import Settings


def ingest(settings: Settings) -> dict:
    res = {"sensor": None, "forecast": None}
    df, info = sensor_sheet.fetch_sensor_data(settings)
    if info.get("ok"):
        n = repo.archive_sensor_rows(df, repo.last_sensor_times())
        repo.log_ingest("sensor", True, n, "worker")
        res["sensor"] = ("ok", n)
    elif info.get("configured"):
        repo.log_ingest("sensor", False, 0, "worker:" + str(info.get("error")))
        res["sensor"] = ("fail", info.get("error"))
    else:
        res["sensor"] = ("skip", "not_configured")
    fc = bmkg.fetch_bmkg_forecast(settings.bmkg_adm4)
    if fc.get("ok"):
        _, new = repo.archive_forecast_run(fc)
        repo.log_ingest("forecast", True, len(fc["rows"]), "worker:" + ("baru" if new else "sama"))
        res["forecast"] = ("ok", new)
    else:
        repo.log_ingest("forecast", False, 0, "worker:" + str(fc.get("error")))
        res["forecast"] = ("fail", fc.get("error"))
    return res


def recommend_all(settings: Settings, forecast_result=None) -> list:
    import recommendation_service as rsvc
    from types import SimpleNamespace
    snap = SimpleNamespace(forecast=forecast_result)
    out = []
    for plot in repo.list_plots():
        h = repo.latest_h(plot["plot_id"])
        if h is None:
            out.append((plot["plot_id"], "skip:no_h"))
            continue
        r = rsvc.run_and_publish(repo, plot["plot_id"], snap, "worker", settings)
        out.append((plot["plot_id"], r["output"]["status"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recommend", action="store_true")
    args = ap.parse_args(argv)
    settings = Settings.from_env()
    db.configure(settings.db_url)
    if not db.ensure_ready():
        print("DB tidak siap:", db.last_error() or "belum dikonfigurasi", file=sys.stderr)
        return 2
    res = ingest(settings)
    print({k: v for k, v in res.items()})
    if args.recommend:
        fc = bmkg.fetch_bmkg_forecast(settings.bmkg_adm4)
        print(recommend_all(settings, fc if fc.get("ok") else None))
    ok = any(v and v[0] == "ok" for v in res.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
