"""evaluation.py - metrik evaluasi yang sesuai keputusan irigasi SOMAT (audit 16 Nov 2026, bagian 5). Fungsi murni, tanpa DB/Streamlit.

Yang dipakai (satuan fisik, bukan kategori DAS): MAE, RMSE, bias h dalam cm dan residual dalam mm/hari menurut horizon; galat waktu mencapai
ambang AWD (dengan selang pengamatan); kejadian terlambat/terlewat; galat volume terhadap acuan yang direkonstruksi SECARA INDEPENDEN;
pelanggaran batas. Skill score membandingkan model dengan pembanding pada sampel yang IDENTIK.

Yang sengaja TIDAK dilakukan: kategori Moriasi 2007 (skala DAS/bulanan), PBIAS/KGE pada h atau residual yang berpusat dekat nol
(penyebut tidak stabil), dan interval keyakinan tanpa uji coverage. Satu petak yang diukur berulang bukan sampel independen:
laporan selalu memuat n pasangan DAN n petak.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Iterable, Optional

MIN_N = 8                          # di bawah ini hasil ditandai `insufficient_n` (bukan dihilangkan)


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ------------------------------------------------------------------------------------------------ galat pasangan
def error_metrics(pairs: Iterable[tuple], min_n: int = MIN_N) -> dict:
    """pairs: [(prediksi, pengamatan)] dalam satuan yang sama. bias = rerata(prediksi - pengamatan) (positif = melebih-lebihkan).
    Pasangan tak hingga/None dibuang dan dihitung di `n_dropped`."""
    pairs = list(pairs)
    p = [(a, b) for a, b in pairs if _fin(a) and _fin(b)]
    total = len(pairs)
    n = len(p)
    out = {"n": n, "n_dropped": total - n, "insufficient_n": n < min_n, "mae": None, "rmse": None, "bias": None}
    if n:
        e = [a - b for a, b in p]
        out.update(mae=sum(abs(x) for x in e) / n, rmse=math.sqrt(sum(x * x for x in e) / n), bias=sum(e) / n)
    return out


def by_horizon(records: list, pred_key: str = "pred", obs_key: str = "obs", min_n: int = MIN_N) -> dict:
    """records: [{horizon_h, pred, obs, plot_id?}] -> {horizon: error_metrics + n_plots}."""
    groups: dict = {}
    for r in records:
        groups.setdefault(r.get("horizon_h"), []).append(r)
    out = {}
    for h, rs in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0])):
        m = error_metrics([(r.get(pred_key), r.get(obs_key)) for r in rs], min_n)
        m["n_plots"] = len({r.get("plot_id") for r in rs if r.get("plot_id") is not None})
        out[h] = m
    return out


def skill_score(rmse_model: Optional[float], rmse_ref: Optional[float]) -> Optional[float]:
    """1 - RMSE_model / RMSE_pembanding. Positif = lebih baik dari pembanding. None bila penyebut nol/tidak ada."""
    if not _fin(rmse_model) or not _fin(rmse_ref) or rmse_ref <= 0:
        return None
    return 1.0 - rmse_model / rmse_ref


def paired_comparison(model: dict, reference: dict, min_n: int = MIN_N) -> dict:
    """Bandingkan model vs pembanding pada kunci (petak, waktu, horizon) YANG SAMA. model/reference: {kunci: (prediksi, pengamatan)}.
    Pengamatan pada kunci bersama harus identik; bila beda, ValueError (bukan target yang sama)."""
    common = sorted(set(model) & set(reference), key=str)
    for k in common:
        if not (_fin(model[k][1]) and _fin(reference[k][1])) or abs(model[k][1] - reference[k][1]) > 1e-9:
            raise ValueError(f"pengamatan berbeda untuk kunci {k}: bukan sampel/target yang identik")
    a = error_metrics([model[k] for k in common], min_n)
    b = error_metrics([reference[k] for k in common], min_n)
    return {"n_common": len(common), "n_model_only": len(set(model) - set(reference)),
            "n_reference_only": len(set(reference) - set(model)), "model": a, "reference": b,
            "skill_rmse": skill_score(a["rmse"], b["rmse"]), "insufficient_n": a["insufficient_n"]}


# ------------------------------------------------------------------------------------------------ pemicu AWD
def trigger_timing(events: list) -> list:
    """Galat waktu mencapai ambang. Tiap event: {event_id, plot_id, observed_bracket: (t_terakhir_di_atas, t_pertama_di_bawah),
    predicted_at: waktu prediksi mencapai ambang | None}. Waktu sebenarnya HANYA diketahui di dalam selang pengamatan (pembacaan
    manual 1-2 kali sehari), jadi galat = 0 bila prediksi jatuh di dalam selang; selainnya jarak ke tepi terdekat (jam; negatif = terlalu
    dini, positif = terlambat). Prediksi None = ambang TERLEWAT."""
    out = []
    for ev in events:
        lo, hi = ev["observed_bracket"]
        if lo is None or hi is None or hi < lo:
            out.append({**_id(ev), "status": "BRACKET_INVALID", "error_h": None, "bracket_h": None})
            continue
        width = (hi - lo).total_seconds() / 3600.0
        t = ev.get("predicted_at")
        if t is None:
            out.append({**_id(ev), "status": "MISSED", "error_h": None, "bracket_h": width})
        elif t < lo:
            out.append({**_id(ev), "status": "EARLY", "error_h": -(lo - t).total_seconds() / 3600.0, "bracket_h": width})
        elif t > hi:
            out.append({**_id(ev), "status": "LATE", "error_h": (t - hi).total_seconds() / 3600.0, "bracket_h": width})
        else:
            out.append({**_id(ev), "status": "WITHIN_BRACKET", "error_h": 0.0, "bracket_h": width})
    return out


def _id(ev: dict) -> dict:
    return {"event_id": ev.get("event_id"), "plot_id": ev.get("plot_id")}


def late_irrigation(events: list, tolerance_h: float = 0.0) -> list:
    """Kejadian terlambat mengairi: air aktual baru tiba setelah ambang teramati dilampaui lebih dari `tolerance_h` sejak tepi atas selang.
    Tiap event: {event_id, observed_bracket, irrigation_arrived_at | None}. Tanpa irigasi sama sekali = TIDAK ADA IRIGASI (bukan 'terlambat')."""
    out = []
    for ev in events:
        lo, hi = ev["observed_bracket"]
        arr = ev.get("irrigation_arrived_at")
        if arr is None:
            out.append({**_id(ev), "status": "NO_IRRIGATION", "delay_h": None})
            continue
        delay = (arr - hi).total_seconds() / 3600.0
        out.append({**_id(ev), "status": "LATE" if delay > tolerance_h else "ON_TIME", "delay_h": delay})
    return out


def trigger_summary(timing: list) -> dict:
    n = len(timing)
    err = [t["error_h"] for t in timing if t["error_h"] is not None]
    cnt = {s: sum(1 for t in timing if t["status"] == s) for s in ("WITHIN_BRACKET", "EARLY", "LATE", "MISSED", "BRACKET_INVALID")}
    return {"n_events": n, **cnt, "mae_h": (sum(abs(x) for x in err) / len(err)) if err else None,
            "bias_h": (sum(err) / len(err)) if err else None, "n_plots": len({t["plot_id"] for t in timing if t["plot_id"] is not None}),
            "note": "Waktu sebenarnya hanya diketahui dalam selang pengamatan; 0 jam berarti prediksi berada di dalam selang."}


# ------------------------------------------------------------------------------------------------ volume
def volume_errors(records: list, min_n: int = MIN_N) -> dict:
    """records: [{recommended_mm, reference_mm, reference_source, independent: bool, plot_id?}]. Acuan HARUS direkonstruksi secara
    independen (mis. dari pengamatan h dan ETc terukur), bukan dari model yang dinilai; `independent` harus True dan `reference_source`
    terisi, jika tidak ValueError. Bias dalam mm (positif = rekomendasi melebihi kebutuhan acuan)."""
    for r in records:
        if r.get("independent") is not True or not str(r.get("reference_source") or "").strip():
            raise ValueError("acuan volume wajib independen dan menyebut sumbernya")
    m = error_metrics([(r.get("recommended_mm"), r.get("reference_mm")) for r in records], min_n)
    m["n_plots"] = len({r.get("plot_id") for r in records if r.get("plot_id") is not None})
    m["unit"] = "mm"
    return m


# ------------------------------------------------------------------------------------------------ batas
def limit_violations(records: list, h_max_cm: Optional[float] = None, h_floor_cm: Optional[float] = None,
                     sensitive_floor_cm: Optional[float] = None) -> dict:
    """Hitung pelanggaran batas. records: [{h_pred_max, h_pred_min, h_obs_min?, sensitive_phase: bool}].
    Batas diberikan pemanggil dari protokol (tidak ada nilai bawaan); batas None -> tidak diperiksa."""
    res = {"n": len(records), "overflow": 0, "below_floor": 0, "below_sensitive_floor": 0, "checked": []}
    if h_max_cm is not None:
        res["checked"].append("overflow")
        res["overflow"] = sum(1 for r in records if _fin(r.get("h_pred_max")) and r["h_pred_max"] > h_max_cm)
    if h_floor_cm is not None:
        res["checked"].append("below_floor")
        res["below_floor"] = sum(1 for r in records if _fin(r.get("h_pred_min")) and r["h_pred_min"] < h_floor_cm)
    if sensitive_floor_cm is not None:
        res["checked"].append("below_sensitive_floor")
        res["below_sensitive_floor"] = sum(1 for r in records if r.get("sensitive_phase") and _fin(r.get("h_pred_min"))
                                           and r["h_pred_min"] < sensitive_floor_cm)
    return res


# ------------------------------------------------------------------------------------------------ ringkasan model
def model_table(records_by_model: dict, reference: str, min_n: int = MIN_N) -> list:
    """Tabel M2 vs M1B vs M1 vs persistence pada sampel identik. records_by_model: {model: {kunci: (pred, obs)}}.
    Tiap baris dibandingkan dengan `reference` hanya pada kunci yang dimiliki KEDUANYA."""
    ref = records_by_model[reference]
    rows = []
    for name, rec in records_by_model.items():
        if name == reference:
            m = error_metrics(list(ref.values()), min_n)
            rows.append({"model": name, "n": m["n"], "mae": m["mae"], "rmse": m["rmse"], "bias": m["bias"], "skill_vs_reference": None,
                         "n_common": m["n"], "insufficient_n": m["insufficient_n"]})
            continue
        c = paired_comparison(rec, ref, min_n)
        rows.append({"model": name, "n": c["model"]["n"], "mae": c["model"]["mae"], "rmse": c["model"]["rmse"], "bias": c["model"]["bias"],
                     "skill_vs_reference": c["skill_rmse"], "n_common": c["n_common"], "insufficient_n": c["insufficient_n"]})
    return rows
