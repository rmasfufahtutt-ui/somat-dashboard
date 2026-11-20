"""demo_service.py - alur rekomendasi/keputusan/pelaksanaan ruang DEMO di atas mesin SOMAT yang sama.

Tidak ada rumus baru: `recommendation_service.compute` (mesin Grand Framework v2) dipakai apa adanya; yang berbeda hanya
PEMAKSA input (cuaca sintetis ATAU BMKG asli, hujan skenario) dan JALUR penyimpanan (demo_repository, run_mode 'DEMO').
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import demo_mode
import demo_repository as drepo
import demo_weather as dw
import physics_engine as pe
import recommendation_service as rs

TZ = rs.TZ
DEFAULT_WEATHER = {"driver": dw.DRIVER_SYNTHETIC, "profile": "NORMAL", "seed": "demo", "rain": "NONE", "base": None}


def _utc(t):
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def weather_points(weather: dict, decision_at: datetime, observed_at: Optional[datetime], forecast: Optional[dict] = None):
    """-> (points, meta). Satu sumber per panggilan (BMKG asli ATAU sintetis), tidak dicampur."""
    w = {**DEFAULT_WEATHER, **(weather or {})}
    start = ((observed_at or decision_at).astimezone(TZ).date()) - timedelta(days=1)
    days = (decision_at.astimezone(TZ).date() - start).days + rs.HORIZON_DAYS + 3
    return dw.driver_points(w["driver"], today=start, days=days, profile=w["profile"], seed=w["seed"],
                            base=w.get("base"), composite_points_fn=rs.composite_points, forecast=forecast)


def compute_pure(plot: dict, profile: Optional[dict], cycle: Optional[dict], h_obs: Optional[dict], decision_at: datetime,
                 weather: Optional[dict] = None, *, forecast: Optional[dict] = None, max_h_age_hours: float = 30.0,
                 model: str = "M1", ml_residual: Optional[float] = None, bias: float = 0.0,
                 since_obs: Optional[dict] = None) -> tuple:
    """Perhitungan murni (tanpa DB). -> (output, snapshot) dengan snapshot bertanda is_demo=True."""
    w = {**DEFAULT_WEATHER, **(weather or {})}
    decision_at = _utc(decision_at)
    obs_at = _utc(h_obs["observed_at"]) if h_obs else None
    points, meta = weather_points(w, decision_at, obs_at, forecast)
    pe_by_date = dw.rain_by_date(w["rain"], decision_at.astimezone(TZ).date())
    out, snap = rs.compute(plot=plot, profile=profile, cycle=cycle, h_obs=h_obs, points=points, decision_at=decision_at,
                           max_h_age_hours=max_h_age_hours, inputs_dummy=True, forecast_meta=meta,
                           pe_by_date=pe_by_date, model=model, ml_residual=ml_residual, bias=bias,
                           rain_label=f"SYNTHETIC_RAIN:{w['rain']}", since_obs=since_obs)
    out["run_mode"] = "DEMO" if out.get("run_mode") != "MANUAL_REQUIRED" else "MANUAL_REQUIRED"
    snap.update(is_demo=True, run_label="DEMO", weather=meta, rain_kind=w["rain"], weather_driver=w["driver"])
    out["weather"] = meta
    out["rain_kind"] = w["rain"]
    return out, snap


def _expires(decision_at, hours=6.0):
    return decision_at + timedelta(hours=hours)


def gather(plot_id: str, decision_at: datetime) -> dict:
    h_obs = drepo.latest_h(plot_id, decision_at)
    since = rs.events_since_observation(drepo, plot_id, h_obs["observed_at"], decision_at) if h_obs else None
    return {"plot": drepo.get_plot(plot_id), "profile": drepo.get_active_profile(plot_id, decision_at),
            "cycle": drepo.get_active_cycle(plot_id), "h_obs": h_obs, "since_obs": since}


def compute_for_plot(plot_id: str, decision_at: Optional[datetime] = None, weather: Optional[dict] = None, *,
                     forecast: Optional[dict] = None, max_h_age_hours: float = 30.0, model: str = "M1",
                     ml_residual: Optional[float] = None, bias: float = 0.0) -> tuple:
    decision_at = _utc(decision_at or drepo.now_utc())
    g = gather(plot_id, decision_at)
    if g["plot"] is None:
        raise ValueError(f"petak demo tidak ditemukan: {plot_id}")
    return compute_pure(g["plot"], g["profile"], g["cycle"], g["h_obs"], decision_at, weather, forecast=forecast,
                        max_h_age_hours=max_h_age_hours, model=model, ml_residual=ml_residual, bias=bias,
                        since_obs=g["since_obs"])


def publish(plot_id: str, actor: str, decision_at: Optional[datetime] = None, weather: Optional[dict] = None, *,
            forecast: Optional[dict] = None, max_h_age_hours: float = 30.0, expiry_hours: float = 24.0,
            model: str = "M1", ml_residual: Optional[float] = None, bias: float = 0.0, origin: str = "USER") -> dict:
    """Hitung dan terbitkan rekomendasi DEMO (immutable). -> {"rec_id", "output"}."""
    decision_at = _utc(decision_at or drepo.now_utc())
    out, snap = compute_for_plot(plot_id, decision_at, weather, forecast=forecast, max_h_age_hours=max_h_age_hours,
                                 model=model, ml_residual=ml_residual, bias=bias)
    # Hasil MANUAL_REQUIRED tetap diterbitkan sebagai catatan (status & alasan terlihat) tetapi tidak dapat disetujui
    # (lihat decide/record_decision). Jalur demo hanya menerima run_mode 'DEMO'; status mesin dipertahankan terpisah.
    out["engine_run_mode"] = out["run_mode"]
    out["run_mode"] = "DEMO"
    rec_id = drepo.publish_recommendation(plot_id, actor, decision_at, snap, snap.get("profile_id"), rs.MODEL_VERSION + "+DEMO",
                                          "DEMO", out["status"], out, _expires(decision_at, expiry_hours), origin=origin)
    return {"rec_id": rec_id, "output": out}


# ---------------------------------------------------------------------------------------------- keputusan & pelaksanaan
def _idem(prefix, *parts) -> str:
    import hashlib
    return prefix + "-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def decide(rec_id: int, user: str, decision: str, operator_mm: float, duration_h: Optional[float], note: str,
           idempotency_key: str) -> tuple:
    """Keputusan simulasi lengkap: validasi di backend (APPROVE jumlah sama, MODIFY harus berubah, DELAY tanpa pelaksanaan).
    -> (decision_id, duplikat?)."""
    run = drepo.get_run(rec_id)
    if run is None:
        raise drepo.DecisionError("not_found")
    out = run["output"] or {}
    if out.get("status") not in ("OK", "TARGET_NOT_REACHABLE") and decision in ("APPROVE", "MODIFY"):
        raise drepo.DecisionError("approve_invalid")
    return drepo.record_decision(rec_id, user, decision, operator_mm, duration_h, note, idempotency_key)


def record_execution(decision_id: int, actor: str, *, arrived_at: datetime, started_at: datetime, ended_at: datetime,
                     actual_volume_m3: float, h_after_cm: Optional[float], h_after_at: Optional[datetime],
                     note: str = "", method: str = "SIMULASI", supersedes_id: Optional[int] = None) -> int:
    """Pelaksanaan SIMULASI: mencatat realisasi dari keputusan demo (bukan pengukuran lapangan)."""
    dec = drepo.q("SELECT id, plot_id, rec_id, record_status, decision FROM decisions WHERE id=?", (int(decision_id),))
    if not dec or dec[0]["record_status"] != "ACTIVE" or dec[0]["decision"] not in ("APPROVE", "MODIFY"):
        raise drepo.DecisionError("not_active")
    if not (arrived_at <= started_at <= ended_at):
        raise ValueError("urutan waktu pelaksanaan tidak sah (tiba <= mulai <= selesai)")
    if actual_volume_m3 is None or actual_volume_m3 < 0:
        raise ValueError("volume aktual tidak sah")
    dur_h = (ended_at - started_at).total_seconds() / 3600.0
    q = (actual_volume_m3 / (dur_h * 3600.0)) if dur_h > 0 else None
    return drepo.add_irrigation_event(dec[0]["plot_id"], int(decision_id), dec[0]["rec_id"], arrived_at, started_at, ended_at,
                                      actual_volume_m3, q, method, h_after_cm, h_after_at, ("[SIMULASI] " + note)[:500], actor,
                                      supersedes_id=supersedes_id)


def simulated_h_after(plot_id: str, h_arrival_cm: float, applied_mm: float) -> float:
    """h setelah pengisian simulasi: S(h)+I lewat koefisien pengisian profil aktif, dibatasi pematang."""
    prof = drepo.get_active_profile(plot_id)
    params = (prof or {}).get("params", {})
    mu_fill = (params.get("mu_fill") or {}).get("value")
    cap = (params.get("h_cap_cm") or {}).get("value")
    if mu_fill is None:
        raise ValueError("mu_fill belum tersedia")
    h, _ = pe.advance_h(h_arrival_cm, -float(applied_mm), mu_fill, mu_fill, cap)
    return h
