"""bias_state.py - state bias adaptif per petak dan per model (audit K06; Bab III 3.4.5). Fungsi murni, tanpa DB/Streamlit.

    b_baru = clip[(1 - a) * b_last * exp(-lam * dt) + a * (R_obs - R_prior), -bmax, +bmax]     (physics_engine.update_bias)

Aturan yang dijaga:
  * ATURAN dan PARAMETER (a, lam, bmax, umur maksimum) SAMA untuk M1B dan M2; STATE-nya terpisah per (petak, model), karena galat
    apriori keduanya berbeda: R_prior M1B = SPconstant; R_prior M2 = residual ML sebelum bias.
  * Update hanya setelah label MATANG (available_at <= waktu update) dan hanya dengan prediksi apriori yang SUDAH diterbitkan
    sebelum jendela mulai (prior.issued_at <= awal jendela).
  * Satu label memperbarui state paling banyak sekali; jendela yang tumpang tindih dengan jendela yang sudah dipakai TIDAK
    dihitung sebagai bukti baru (dicatat sebagai dilewati).
  * Bias kedaluwarsa (umur > max_age_days) tidak dipakai (0) dan ditandai. Bobot RF/ANN tidak dilatih ulang selama eksperimen.
  * Parameter harus DIBEKUKAN dari kalibrasi/validasi; tidak ada nilai bawaan untuk jalur penelitian. DEMO_CONFIG hanya ilustrasi.
  * Seluruh perubahan dicatat di `history` (dapat diaudit dan diserialisasi lewat `snapshot()`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import physics_engine as pe

MODELS = ("M1B", "M2")


@dataclass(frozen=True)
class BiasConfig:
    alpha: float
    lam: float
    bmax: float
    max_age_days: float
    frozen_from: str = ""          # sumber/versi kalibrasi (wajib diisi untuk penelitian)

    def __post_init__(self):
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError("alpha harus di (0, 1]")
        if self.lam < 0 or self.bmax <= 0 or self.max_age_days <= 0:
            raise ValueError("lam >= 0, bmax > 0, max_age_days > 0")
        for v in (self.alpha, self.lam, self.bmax, self.max_age_days):
            if not math.isfinite(v):
                raise ValueError("parameter harus hingga")


DEMO_CONFIG = BiasConfig(alpha=0.3, lam=0.10, bmax=1.5, max_age_days=7.0, frozen_from="ILUSTRASI DEMO — bukan hasil kalibrasi")


@dataclass
class BiasState:
    plot_id: str
    model: str
    b: float = 0.0
    last_update_at: Optional[datetime] = None
    last_window_end: Optional[datetime] = None
    consumed: set = field(default_factory=set)
    history: list = field(default_factory=list)

    def __post_init__(self):
        if self.model.upper() not in MODELS:
            raise ValueError(f"model bias harus salah satu dari {MODELS}")
        self.model = self.model.upper()


def bias_for_issue(state: BiasState, cfg: BiasConfig, issue_at: datetime) -> tuple:
    """-> (bias yang dipakai untuk prediksi pada issue_at, status). Tanpa update apa pun: 0 + NO_BIAS_YET; kedaluwarsa: 0 + EXPIRED."""
    if state.last_update_at is None:
        return 0.0, "NO_BIAS_YET"
    age = (issue_at - state.last_update_at).total_seconds() / 86400.0
    if age < 0:
        raise ValueError("waktu penerbitan lebih awal daripada update bias terakhir (urutan waktu rusak)")
    if age > cfg.max_age_days:
        return 0.0, "EXPIRED"
    return state.b, "ACTIVE"


def apply_label(state: BiasState, cfg: BiasConfig, label: dict, prior: dict, now: datetime) -> dict:
    """Perbarui state dari SATU label matang. label: {label_id, start, end, available_at, residual_mm_day, validity};
    prior: {issued_at, r_base_mm_day} = prediksi apriori TANPA bias untuk jendela label itu.
    -> {"applied": bool, "reason": str, ...}. State hanya berubah bila applied."""
    lid = label.get("label_id")

    def skip(reason):
        rec = {"applied": False, "reason": reason, "label_id": lid}
        state.history.append({**rec, "at": now})
        return rec

    if lid is None:
        return skip("LABEL_ID_MISSING")
    if lid in state.consumed:
        return skip("ALREADY_USED")
    if label.get("validity") != "VALID" or label.get("residual_mm_day") is None:
        return skip("LABEL_NOT_VALID")
    if label["available_at"] > now:
        return skip("LABEL_NOT_MATURE")
    if prior is None or prior.get("r_base_mm_day") is None or not math.isfinite(prior["r_base_mm_day"]):
        return skip("NO_PRIOR")
    if prior["issued_at"] > label["start"]:
        return skip("PRIOR_NOT_A_PRIORI")               # prediksi diterbitkan setelah jendela mulai -> bukan apriori
    if state.last_window_end is not None and label["start"] < state.last_window_end:
        return skip("OVERLAPS_USED_WINDOW")             # bukan bukti independen
    elapsed = 0.0 if state.last_update_at is None else max(0.0, (label["end"] - state.last_update_at).total_seconds() / 86400.0)
    b_new, e_base = pe.update_bias(state.b, elapsed, float(label["residual_mm_day"]), float(prior["r_base_mm_day"]),
                                   cfg.alpha, cfg.lam, cfg.bmax)
    rec = {"applied": True, "reason": "OK", "label_id": lid, "e_base_mm_day": e_base, "b_before": state.b, "b_after": b_new,
           "elapsed_days": elapsed, "clipped": abs(b_new) >= cfg.bmax - 1e-12, "at": now}
    state.b, state.last_update_at, state.last_window_end = b_new, label["end"], label["end"]
    state.consumed.add(lid)
    state.history.append(rec)
    return rec


def replay(state: BiasState, cfg: BiasConfig, labels: list, priors: dict, now: datetime) -> list:
    """Terapkan label secara KRONOLOGIS (menurut akhir jendela). priors: {label_id: prior}. -> daftar hasil per label."""
    return [apply_label(state, cfg, lab, priors.get(lab.get("label_id")), now)
            for lab in sorted(labels, key=lambda l: (l["end"], str(l.get("label_id"))))]


def snapshot(state: BiasState, cfg: BiasConfig, issue_at: datetime) -> dict:
    """Ringkasan yang dapat diaudit untuk disimpan di snapshot rekomendasi."""
    b, status = bias_for_issue(state, cfg, issue_at)
    return {"plot_id": state.plot_id, "model": state.model, "bias_used_mm_day": b, "status": status, "b_state": state.b,
            "last_update_at": state.last_update_at, "n_updates": sum(1 for h in state.history if h.get("applied")),
            "config": {"alpha": cfg.alpha, "lam": cfg.lam, "bmax": cfg.bmax, "max_age_days": cfg.max_age_days,
                       "frozen_from": cfg.frozen_from}}
