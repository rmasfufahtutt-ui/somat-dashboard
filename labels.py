"""labels.py - pembentukan label residual (AI offline) dari pengamatan nyata. Fungsi murni, tanpa DB/Streamlit.

Aturan (Grand Framework v2, bagian 7): jendela valid hanya bila
  * kedua ujung adalah pengamatan h manual AKTIF dari sumber nyata (bukan DUMMY/SIMULATED);
  * tidak ada irigasi aktual yang tumpang tindih dengan jendela;
  * ada bukti tidak hujan: cakupan data hujan menutup jendela dan semua nilai <= ambang (hujan tak tersedia != nol);
  * pengamatan antara tidak naik (kenaikan = aliran masuk/hujan lokal) dan tidak ada yang melintasi h = 0;
  * panjang jendela W di dalam [w_min, w_max] hari.
Label negatif tidak dipotong; hanya ditandai peninjauan. Pemisahan temporal membuang jendela yang melintasi batas.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

import physics_engine as pe

NON_REAL_SOURCES = ("DUMMY", "SIMULATED")
RAIN_EPS_MM = 0.0


def _overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def build_window_labels(h_obs: Iterable[dict], irrigation: Iterable[dict], rain: Iterable[dict], rain_covered: tuple,
                        mean_etc_fn: Callable, mu_dry: float, w_min_days: float = 2.0, w_max_days: float = 3.0,
                        rain_eps_mm: float = RAIN_EPS_MM) -> list:
    """h_obs: [{obs_id, value, observed_at, received_at, source_type}] (waktu berzona), irrigation: [{started_at|arrived_at,
    ended_at}], rain: [{observed_at, value_mm}], rain_covered: (awal, akhir) rentang data hujan yang tersedia,
    mean_etc_fn(t0, t1) -> rata-rata ETc mm/hari atau None. Mengembalikan semua jendela kandidat berikut validitasnya."""
    obs = sorted((o for o in h_obs), key=lambda o: o["observed_at"])
    ev = [(e.get("arrived_at") or e.get("started_at"), e.get("ended_at") or e.get("arrived_at") or e.get("started_at"))
          for e in irrigation]
    ev = [(a, b) for a, b in ev if a is not None]
    out = []
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            a, b = obs[i], obs[j]
            w = (b["observed_at"] - a["observed_at"]).total_seconds() / 86400.0
            if w < w_min_days:
                continue
            if w > w_max_days:
                break
            row = {"start": a["observed_at"], "end": b["observed_at"], "w_days": w, "start_obs_id": a.get("obs_id"),
                   "end_obs_id": b.get("obs_id"), "available_at": b.get("received_at") or b["observed_at"],
                   "validity": "VALID", "residual_mm_day": None}
            mid = obs[i + 1:j]
            reason = None
            if any((o.get("source_type") or "MANUAL") in NON_REAL_SOURCES for o in (a, b, *mid)):
                reason = "NON_REAL_SOURCE"
            elif any(_overlaps(a["observed_at"], b["observed_at"], s, max(e, s + timedelta(seconds=1))) for s, e in ev):
                reason = "IRRIGATION_IN_WINDOW"
            elif not rain_covered or rain_covered[0] > a["observed_at"] or rain_covered[1] < b["observed_at"]:
                reason = "RAIN_UNKNOWN"
            elif any(r["observed_at"] >= a["observed_at"] and r["observed_at"] <= b["observed_at"]
                     and (r.get("value_mm") or 0) > rain_eps_mm for r in rain):
                reason = "RAIN_IN_WINDOW"
            else:
                seq = [a["value"]] + [o["value"] for o in mid] + [b["value"]]
                if any(x2 > x1 + 1e-9 for x1, x2 in zip(seq, seq[1:])):
                    reason = "RISE_IN_WINDOW"
                elif any(x1 * x2 < 0 for x1, x2 in zip(seq, seq[1:])):
                    reason = "CROSSES_ZERO"
            if reason is None:
                etc = mean_etc_fn(a["observed_at"], b["observed_at"])
                if etc is None:
                    reason = "ETC_UNAVAILABLE"
                else:
                    r = pe.window_residual(a["value"], b["value"], w, etc, mu_dry)
                    if not r["valid"]:
                        reason = r["reason"].upper()
                    else:
                        row.update(residual_mm_day=r["r_mm_day"], mu_eff=r["mu_eff"],
                                   negative_label_review=r["negative_label_review"])
            if reason:
                row["validity"] = reason
            out.append(row)
    return out


def split_temporal(labels: list, train_end: datetime, valid_end: datetime) -> dict:
    """Pisah VALID menurut waktu: train < train_end <= valid < valid_end <= test. Jendela yang melintasi batas dibuang
    (dilaporkan di `dropped`). Memakai available_at agar label belum matang tidak bocor ke periode lebih awal."""
    sets = {"train": [], "valid": [], "test": [], "dropped": []}
    for lab in labels:
        if lab["validity"] != "VALID":
            continue
        s, e = lab["start"], lab["end"]
        if lab["available_at"] > valid_end and e <= valid_end:
            sets["dropped"].append(lab)
        elif e <= train_end:
            sets["train"].append(lab)
        elif s >= train_end and e <= valid_end:
            sets["valid"].append(lab)
        elif s >= valid_end:
            sets["test"].append(lab)
        else:
            sets["dropped"].append(lab)
    return sets
