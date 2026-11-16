"""demo_ml.py - model AI DEMONSTRASI (Random Forest) untuk residual neraca air, dilatih dari data SINTETIS.

Yang didemonstrasikan adalah ALUR-nya (label jendela -> pemisahan temporal -> pelatihan -> evaluasi -> M2), bukan akurasi
lapangan. Kebenaran dasar sintetis (`true_residual`) sengaja berbeda dari SPconstant sehingga perbandingan M1 vs M2 terlihat;
itu BUKAN klaim bahwa model ini lebih baik pada data nyata.

* Label dibentuk oleh `labels.build_window_labels` (aturan jendela yang sama dengan penelitian) dan dipisah oleh
  `labels.split_temporal` (latih < validasi < uji, jendela lintas-batas dibuang). Korpus hanya ada di memori.
* Hiperparameter dipilih pada set VALIDASI; set UJI dipakai sekali untuk laporan.
* M2 = residual RF + bias (SPconstant TIDAK ditambahkan lagi). M1 = SPconstant profil. Tidak ada rumus lain.
* Hanya admin yang dapat melatih; tampilan lain hanya memakai model tersimpan (pindah halaman tidak melatih ulang).
* Bila scikit-learn/model tidak ada: M2 tidak tersedia dan UI menampilkan M1 saja (tanpa error).
"""
from __future__ import annotations

import hashlib
import io
import math
import pickle
from datetime import date, datetime, timedelta, timezone

import demo_mode
import demo_repository as drepo
import demo_weather as dw
import et0 as et0lib
import labels as lb
import ml_features as mf
import physics_engine as pe

try:                                                    # pragma: no cover - ketersediaan tergantung lingkungan
    from sklearn.ensemble import RandomForestRegressor
    HAS_SKLEARN = True
except Exception:                                       # pragma: no cover
    RandomForestRegressor = None
    HAS_SKLEARN = False

TZ = dw.TZ
KIND = "RF_RESIDUAL"
FEATURES = mf.FEATURES
BASE_DATE = date(2025, 1, 1)             # tanggal tetap: korpus & metrik reproduktif, tidak bergantung hari ini
N_PLOTS, N_DAYS = 8, 300
TRAIN_DAYS, VALID_DAYS = 180, 240
SP_CONSTANT = 1.5                        # nilai SPconstant M1 pada korpus (sama dengan profil contoh demo)
MU = 0.30
GRID = [{"max_depth": d, "min_samples_leaf": m} for d in (4, 6, 8) for m in (3, 6)]
RESIDUAL_CLIP = (-2.0, 10.0)             # mm/hari; di luar ini dipotong dan ditandai
NOTICE = "MODEL AI DEMONSTRASI — Dilatih dari data sintetis. Belum tervalidasi menggunakan data lapangan."

_CACHE = {}                              # model_id -> model terlatih (dimuat sekali, bukan dilatih ulang)


# ---------------------------------------------------------------------------------------------- kebenaran dasar sintetis
def true_residual(tmean: float, dtr: float, h_start: float) -> float:
    """Residual (mm/hari) 'sebenarnya' pada korpus sintetis: naik dengan suhu & DTR, lebih besar saat tergenang."""
    return 1.0 + 0.18 * (tmean - 27.0) + 0.06 * (dtr - 9.0) + (0.9 if h_start >= 0 else 0.0)


def _u(*key) -> float:
    return int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _gauss(*key) -> float:
    u1, u2 = max(_u(*key, "a"), 1e-9), _u(*key, "b")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)


def generate_corpus(seed: int = 42, n_plots: int = N_PLOTS, n_days: int = N_DAYS) -> dict:
    """Simulasikan petak virtual -> pengamatan h harian + irigasi -> label jendela (aturan labels.py).
    -> {"labels": [...], "rows": [...fitur...], "meta": {...}}."""
    all_labels, rows = [], []
    for v in range(n_plots):
        prof = ("NORMAL", "HOT", "COOL")[v % 3]
        lat = -7.0 - 0.1 * v
        kc = (1.05, 1.20, 0.90)[v % 3]
        start = datetime(BASE_DATE.year, BASE_DATE.month, BASE_DATE.day, 8, tzinfo=TZ)
        h = -2.0 + 6.0 * _u(seed, v, "h0")
        obs, events, day_info = [], [], {}
        for k in range(n_days + 1):
            t = start + timedelta(days=k)
            d = t.date()
            tmin, tmax = dw.day_temps(d, prof, f"ml-{seed}-{v}", BASE_DATE)
            et0 = et0lib.hargreaves_et0(tmin, tmax, lat, d.timetuple().tm_yday)["et0_mm_day"]
            tmean, dtr = (tmin + tmax) / 2.0, tmax - tmin
            day_info[d] = {"tmean": tmean, "dtr": dtr, "et0": et0, "etc": kc * et0, "kc": kc, "tmin": tmin, "tmax": tmax}
            obs.append({"obs_id": v * 10000 + k, "value": round(h, 2), "observed_at": t, "received_at": t + timedelta(minutes=10),
                        "source_type": "MANUAL", "record_status": "ACTIVE", "quality_flag": "OK", "is_demo": True})
            if k == n_days:
                break
            if h <= -14.0:                                                   # irigasi AWD: isi sampai +4 cm
                events.append({"arrived_at": t + timedelta(hours=6), "ended_at": t + timedelta(hours=10)})
                h = 4.0
                continue
            r = true_residual(tmean, dtr, h) + 0.35 * _gauss(seed, v, k)
            h, _ = pe.advance_h(h, kc * et0 + r, MU, MU, 15.0)

        def _series(key, _info=day_info):
            return {d: v[key] for d, v in _info.items()}

        def mean_etc(t0, t1, _s=_series("etc")):                  # rerata berbobot durasi pada [t0, t1) — dukungan waktu = label
            return lb.mean_over_interval(_s, t0, t1, TZ)

        labs = lb.build_window_labels(obs, events, [], [(obs[0]["observed_at"], obs[-1]["observed_at"])], mean_etc, MU,
                                      w_min_days=2.0, w_max_days=3.0, purpose="DEMO_SYNTHETIC")
        by_id = {o["obs_id"]: o for o in obs}
        for lab in labs:
            lab["plot"] = v
            if lab["validity"] != "VALID":
                continue
            a = by_id[lab["start_obs_id"]]
            x, why = mf.build_features({k: _series(k) for k in mf.DAILY_KEYS}, lab["start"], lab["end"], a["value"], kc, TZ)
            if x is None:
                lab["validity"], lab["feature_problem"] = "FEATURE_UNAVAILABLE", why
                continue
            lab["x"] = [x[f] for f in FEATURES]
            lab["snapshot_days"] = [{"date": d, "status": "OK", "tmin": day_info[d]["tmin"], "tmax": day_info[d]["tmax"],
                                     "et0_mm_day": day_info[d]["et0"]}
                                    for d in sorted(day_info) if lab["start"].astimezone(TZ).date() <= d <= lab["end"].astimezone(TZ).date()]
            lab["h_start"], lab["h_end_obs"] = a["value"], by_id[lab["end_obs_id"]]["value"]
        all_labels.extend(labs)
    valid = [l for l in all_labels if l["validity"] == "VALID"]
    meta = {"seed": seed, "n_plots": n_plots, "n_days": n_days, "n_windows": len(all_labels), "n_valid": len(valid),
            "rejected": _count_reasons(all_labels), "base_date": str(BASE_DATE),
            "source": "SINTETIS — korpus simulasi di memori (tidak disimpan sebagai pengamatan)", "features": list(FEATURES)}
    return {"labels": all_labels, "meta": meta}


def _count_reasons(labels):
    out = {}
    for l in labels:
        if l["validity"] != "VALID":
            out[l["validity"]] = out.get(l["validity"], 0) + 1
    return out


def _xy(subset):
    return [l["x"] for l in subset], [l["residual_mm_day"] for l in subset]


def _mae(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _rmse(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / max(1, len(a)))


def _r2(y, p):
    m = sum(y) / len(y)
    ss_t = sum((v - m) ** 2 for v in y)
    return 1.0 - sum((a - b) ** 2 for a, b in zip(y, p)) / ss_t if ss_t > 0 else float("nan")


def _h_end_pred(lab, r_adj):
    """Prediksi h akhir jendela memakai r_adj (mm/hari) - fungsi mesin yang sama (advance_h, harian)."""
    h = lab["h_start"]
    etc = lab["x"][FEATURES.index("etc")]
    for _ in range(int(round(lab["w_days"]))):
        h, _ = pe.advance_h(h, etc + r_adj, MU, MU, 15.0)
    return h


def train(actor: str | None = None, seed: int = 42, _internal: bool = False) -> dict:
    """Latih dan simpan model demo (hanya admin). -> ringkasan lengkap (termasuk metrik uji M1 vs M2)."""
    if not _internal:
        demo_mode.require("admin")
    if not HAS_SKLEARN:
        return {"status": "NO_SKLEARN", "message": "scikit-learn tidak tersedia; M2 tidak dapat dilatih."}
    corpus = generate_corpus(seed)
    labs = corpus["labels"]
    t0 = datetime(BASE_DATE.year, BASE_DATE.month, BASE_DATE.day, 8, tzinfo=TZ)
    sp = lb.split_temporal(labs, t0 + timedelta(days=TRAIN_DAYS), t0 + timedelta(days=VALID_DAYS))
    if min(len(sp["train"]), len(sp["valid"]), len(sp["test"])) < 20:
        return {"status": "TOO_FEW_LABELS", "message": "Label terlalu sedikit untuk pelatihan.",
                "counts": {k: len(v) for k, v in sp.items()}}
    Xtr, ytr = _xy(sp["train"])
    Xva, yva = _xy(sp["valid"])
    Xte, yte = _xy(sp["test"])
    best = None
    tuning = []
    for g in GRID:
        m = RandomForestRegressor(n_estimators=120, random_state=seed, n_jobs=1, **g).fit(Xtr, ytr)
        e = _mae(yva, m.predict(Xva))
        tuning.append({**g, "valid_mae": e})
        if best is None or e < best[0] - 1e-12:
            best = (e, g, m)
    model, cfg = best[2], best[1]
    p_te = [float(v) for v in model.predict(Xte)]
    m1 = [SP_CONSTANT] * len(yte)
    metrics = {
        "test": {"n": len(yte), "M1": {"mae_residual": _mae(yte, m1), "rmse_residual": _rmse(yte, m1)},
                 "M2": {"mae_residual": _mae(yte, p_te), "rmse_residual": _rmse(yte, p_te), "r2": _r2(yte, p_te)}},
        "split": {k: len(v) for k, v in sp.items()}, "tuning": tuning, "chosen": cfg,
        "feature_importance": dict(zip(FEATURES, [float(v) for v in model.feature_importances_])),
    }
    obs_end = [l["h_end_obs"] for l in sp["test"]]
    metrics["h_end_mae_cm"] = {
        "M1": _mae(obs_end, [_h_end_pred(l, SP_CONSTANT) for l in sp["test"]]),
        "M2": _mae(obs_end, [_h_end_pred(l, p) for l, p in zip(sp["test"], p_te)])}
    metrics["h_end_mae_cm"]["n"] = len(obs_end)
    metrics["better_on_test"] = "M2" if metrics["test"]["M2"]["mae_residual"] < metrics["test"]["M1"]["mae_residual"] else "M1"
    metrics["notice"] = NOTICE
    blob = pickle.dumps(model)
    sha = hashlib.sha256(blob).hexdigest()
    ds_hash = hashlib.sha256(("|".join(f"{l['start']}{l['end']}{l['residual_mm_day']:.4f}" for l in sp["train"] + sp["valid"] + sp["test"])).encode()).hexdigest()[:16]
    model_id = f"rf-demo-{ds_hash[:8]}"
    config = {**cfg, "n_estimators": 120, "random_state": seed, "sp_constant_m1": SP_CONSTANT, "blob_sha256": sha,
              "corpus": corpus["meta"], "residual_clip": list(RESIDUAL_CLIP), "label_source": "SINTETIS"}
    drepo.save_model(model_id, KIND, actor or demo_mode.actor_name(), ds_hash, config, metrics, list(FEATURES), blob)
    _CACHE[model_id] = model
    return {"status": "TRAINED", "model_id": model_id, "metrics": metrics, "config": config}


# ---------------------------------------------------------------------------------------------- pemakaian model
def status() -> dict:
    m = drepo.get_model(KIND)
    return {"sklearn": HAS_SKLEARN, "trained": m is not None,
            "model_id": m["model_id"] if m else None, "created_at": m["created_at"] if m else None,
            "metrics": m["metrics"] if m else None, "config": m["config"] if m else None, "notice": NOTICE}


def load_model():
    """-> (model | None, meta | None). Dimuat sekali per model_id; verifikasi sha256 sebelum unpickle."""
    if not HAS_SKLEARN:
        return None, None
    rec = drepo.get_model(KIND)
    if rec is None or not rec.get("blob"):
        return None, None
    mid = rec["model_id"]
    if mid in _CACHE:
        return _CACHE[mid], rec
    blob = bytes(rec["blob"])
    if hashlib.sha256(blob).hexdigest() != (rec.get("config") or {}).get("blob_sha256"):
        return None, rec                                   # berkas model rusak -> M2 tidak tersedia (bukan crash)
    _CACHE[mid] = pickle.loads(blob)                       # nosec - blob ditulis sendiri ke SQLite demo lokal dan diverifikasi hash
    return _CACHE[mid], rec


def features_from_output(out: dict, snapshot: dict, kc, decision_at=None) -> tuple:
    """Fitur operasi dari hasil M1 + snapshot: PEMBENTUK YANG SAMA dengan pelatihan (ml_features), jendela [keputusan, keputusan + W).
    -> (fitur | None, alasan | None). Tidak ada tebakan bila ada hari tanpa nilai OK."""
    h_dec = out.get("h_decision_cm")
    t0 = decision_at or snapshot.get("decision_at")
    if t0 is None:
        return None, "waktu keputusan tidak tersedia"
    return mf.features_for_decision(snapshot.get("et0_daily") or [], t0, h_dec, kc, TZ)


def predict_residual(x: dict) -> dict:
    """-> {"available", "residual", "clipped", "model_id"}. Tanpa model -> available False (alasan jelas)."""
    model, rec = load_model()
    if model is None:
        return {"available": False, "reason": "Model demo belum dilatih" if rec is None else "Model demo tidak dapat dimuat",
                "residual": None, "clipped": False, "model_id": None}
    r = float(model.predict([[x[f] for f in FEATURES]])[0])
    lo, hi = RESIDUAL_CLIP
    c = min(hi, max(lo, r))
    return {"available": True, "residual": c, "raw": r, "clipped": c != r, "model_id": rec["model_id"]}


def compare_models(plot_id: str, decision_at=None, weather=None, bias: float = 0.0, forecast=None) -> dict:
    """M1 (SPconstant) vs M2 (residual RF + bias) untuk satu petak, di atas input yang SAMA. Tanpa SPconstant ganda."""
    import demo_service as ds
    out1, snap1 = ds.compute_for_plot(plot_id, decision_at, weather, model="M1", forecast=forecast)
    res = {"M1": {"output": out1, "snapshot": snap1}, "M2": None, "notice": NOTICE, "residual": None}
    prof = drepo.get_active_profile(plot_id, ds._utc(decision_at or drepo.now_utc()))
    kc = None
    if prof and out1.get("phase_decision"):
        kc = ((prof["params"].get(f"kc_{out1['phase_decision']}") or {}).get("value"))
    x, why = features_from_output(out1, snap1, kc, ds._utc(decision_at or drepo.now_utc()))
    if x is None:
        res["residual"] = {"available": False, "reason": f"Fitur tidak lengkap: {why}"}
        return res
    pr = predict_residual(x)
    res["residual"] = {**pr, "features": x}
    if pr["available"]:
        out2, snap2 = ds.compute_for_plot(plot_id, decision_at, weather, model="M2", ml_residual=pr["residual"], bias=bias,
                                          forecast=forecast)
        res["M2"] = {"output": out2, "snapshot": snap2}
    return res
