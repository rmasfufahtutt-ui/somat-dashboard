"""recommendation_service.py - menyusun rekomendasi per petak dari profil, pengamatan h, dan prakiraan.

Bagian murni (`compute`) tidak menyentuh jaringan/DB sehingga dapat diuji. `run_and_publish` merangkai data
repository + snapshot hub lalu menerbitkan rekomendasi yang tidak berubah (immutable) beserta snapshot input.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import et0 as et0lib
import physics_engine as pe

TZ = ZoneInfo("Asia/Jakarta")
MODEL_VERSION = "SOMAT-baseline-2.0"
HORIZON_DAYS = 10
PLOT_PARAMS = ("area_ha", "mu_dry", "mu_fill", "lead_time_h", "h_cap_cm", "sp_constant", "q_plot_m3s")


# ----------------------------------------------------------------------------------------------
# profil -> struktur mesin
# ----------------------------------------------------------------------------------------------
def _param(params: dict, name: str) -> pe.Param:
    r = params.get(name)
    if not r or r.get("value") is None:
        return pe.Param()
    return pe.Param(float(r["value"]), r.get("status") or "PENDING", r.get("source") or "")


def build_profile(plot_id: str, profile: dict) -> tuple:
    """profil DB (dict dengan params, phases) -> (PlotProfile, {fase: Param kc}, [aturan fase DAS])."""
    params = profile.get("params") or {}
    phases, kc = {}, {}
    for ph in profile.get("phases") or []:
        name = ph["phase"]
        phases[name] = pe.PhaseRule(_param(params, f"trigger_h_{name}"), _param(params, f"target_h_{name}"))
        kc[name] = _param(params, f"kc_{name}")
    plot_profile = pe.PlotProfile(
        plot_id=plot_id, phases=phases, validation_status=profile.get("validation_status") or "UNVALIDATED",
        **{n: _param(params, n) for n in PLOT_PARAMS})
    return plot_profile, kc, list(profile.get("phases") or [])


def phase_at(t: datetime, planting: Optional[date], phase_rows: list) -> Optional[str]:
    """Fase pada waktu t menurut hari setelah tanam (DAS, hari tanam = 0); None bila tidak terdefinisi."""
    if planting is None:
        return None
    das = (t.astimezone(TZ).date() - planting).days
    for ph in phase_rows:
        if int(ph["from_das"]) <= das <= int(ph["to_das"]):
            return ph["phase"]
    return None


def phase_breaks(start: datetime, end: datetime, planting: Optional[date], phase_rows: list) -> list:
    """Waktu pergantian fase (tengah malam lokal pada from_das setiap fase) di dalam (start, end)."""
    if planting is None:
        return []
    out = []
    for ph in phase_rows:
        for day in (int(ph["from_das"]), int(ph["to_das"]) + 1):
            d = planting + timedelta(days=day)
            t = datetime(d.year, d.month, d.day, tzinfo=TZ)
            if start < t < end:
                out.append(t)
    return sorted(set(out))


# ----------------------------------------------------------------------------------------------
# prakiraan -> ET0 harian
# ----------------------------------------------------------------------------------------------
def composite_points(latest_rows: list, archived_slots: list) -> list:
    """Titik suhu komposit [(waktu lokal berzona, suhu)]. Prakiraan TERBARU menang atas arsip untuk waktu sama;
    arsip hanya mengisi slot yang sudah lewat (penerbitan baru hanya memuat slot ke depan)."""
    by_utc = {}
    for a in archived_slots or []:
        v = a.get("temp")
        if v is None:
            continue
        t = a["valid_at"]
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        by_utc[t.astimezone(timezone.utc)] = float(v)
    for n in et0lib.normalize_forecast_rows(latest_rows or []):
        if n["temp"] is not None:
            by_utc[n["utc"]] = float(n["temp"])
    return sorted(((u.astimezone(TZ), v) for u, v in by_utc.items()), key=lambda x: x[0])


def build_drivers(points: list, latitude: Optional[float], kc_by_phase: dict, planting: Optional[date],
                  phase_rows: list, start_date: date, end_date: date, config=et0lib.DEFAULT_CONFIG):
    """-> (Drivers, ringkasan ET0 harian). Tanpa lintang atau titik: Drivers tanpa ET0 (INCOMPLETE_FORECAST)."""
    series = []
    if latitude is not None and points:
        series = et0lib.forecast_et0_series(points, latitude, config, start_date=start_date, end_date=end_date)
    et0_by_date = {s["date"]: s["et0_mm_day"] for s in series if s["status"] == "OK"}

    def kc_at(t):
        ph = phase_at(t, planting, phase_rows)
        p = kc_by_phase.get(ph) if ph else None
        return p.value if (p is not None and p.known) else None

    return pe.Drivers(et0_by_date=et0_by_date, kc_at=kc_at, tz=TZ), series


# ----------------------------------------------------------------------------------------------
# komputasi murni
# ----------------------------------------------------------------------------------------------
def compute(*, plot: dict, profile: Optional[dict], cycle: Optional[dict], h_obs: Optional[dict],
            points: list, decision_at: datetime, max_h_age_hours: float, inputs_dummy: bool = False,
            forecast_meta: Optional[dict] = None) -> tuple:
    """-> (output, snapshot). `output` hasil recommend_timed + penjelasan; `snapshot` seluruh input yang dipakai."""
    planting = cycle["planting_date"] if cycle else None
    snap = {
        "plot_id": plot["plot_id"], "decision_at": decision_at, "model_version": MODEL_VERSION,
        "max_h_age_hours": max_h_age_hours, "forecast": forecast_meta or {},
        "profile_id": profile.get("profile_id") if profile else None,
        "profile_version": profile.get("version") if profile else None,
        "cycle": {"cycle_id": cycle["cycle_id"], "planting_date": cycle["planting_date"]} if cycle else None,
        "h_observation": ({"obs_id": h_obs["obs_id"], "value": h_obs["value"], "observed_at": h_obs["observed_at"],
                           "received_at": h_obs.get("received_at")} if h_obs else None),
        "et0_config_hash": et0lib.DEFAULT_CONFIG.config_hash,
    }
    if profile is None:
        return _manual("PROFILE_REQUIRED", "Profil petak belum dibuat/disetujui (Admin > Petak & Parameter).", decision_at), snap
    if cycle is None:
        return _manual("PROTOCOL_REQUIRED", "Siklus tanam aktif belum diisi; fase dan Kc tidak dapat ditentukan.", decision_at), snap

    plot_profile, kc_by_phase, phase_rows = build_profile(plot["plot_id"], profile)
    snap["parameters"] = {k: {"value": v.get("value"), "status": v.get("status")}
                          for k, v in (profile.get("params") or {}).items()}
    observed_at = h_obs["observed_at"] if h_obs else None
    if observed_at is not None and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    start_d = (observed_at or decision_at).astimezone(TZ).date()
    end_d = (decision_at + timedelta(days=HORIZON_DAYS)).astimezone(TZ).date()
    drivers, series = build_drivers(points, plot.get("latitude"), kc_by_phase, planting, phase_rows, start_d, end_d)
    snap["et0_daily"] = [{"date": s["date"], "status": s["status"], "et0_mm_day": s["et0_mm_day"],
                          "tmin": s["tmin"], "tmax": s["tmax"], "n": s["n"], "source": s["temperature_source"]}
                         for s in series]
    end = decision_at + timedelta(days=HORIZON_DAYS)
    breaks = phase_breaks(observed_at or decision_at, end, planting, phase_rows)

    def rule_at(t):
        ph = phase_at(t, planting, phase_rows)
        return ph, (plot_profile.phases.get(ph) if ph else None)

    def kc_param_at(t):
        ph = phase_at(t, planting, phase_rows)
        return kc_by_phase.get(ph) if ph else None

    model = "M1" if plot_profile.sp_constant.known else "M0"
    out = pe.recommend_timed(
        h_obs_cm=h_obs["value"] if h_obs else None, observed_at=observed_at, decision_at=decision_at,
        drivers=drivers, profile=plot_profile, rule_at=rule_at, phase_breaks=breaks, kc_param_at=kc_param_at,
        model=model, max_h_age_hours=max_h_age_hours, inputs_dummy=inputs_dummy)
    out["et0_by_date"] = {str(k): v for k, v in drivers.et0_by_date.items()}
    out["phase_note"] = f"fase {out.get('phase_decision') or '-'} → {out.get('phase_arrival') or '-'}"
    snap["model"] = model
    return out, snap


def _manual(code, reason, decision_at):
    return {"status": code, "run_mode": "MANUAL_REQUIRED", "reasons": [reason], "issues": [{"code": code}],
            "irrigate": None, "decision_at": decision_at, "provisional": True, "validated": False,
            "total_mm": None, "volume_m3": None, "duration_h": None, "path": [], "parameter_status": {}}


# ----------------------------------------------------------------------------------------------
# perangkaian dengan repository + hub
# ----------------------------------------------------------------------------------------------
def gather_inputs(repo, plot_id: str, snapshot, decision_at: datetime) -> dict:
    plot = repo.get_plot(plot_id)
    profile = repo.get_active_profile(plot_id, decision_at)
    cycle = repo.get_active_cycle(plot_id)
    h_obs = repo.latest_h(plot_id, decision_at)
    fc = snapshot.forecast if snapshot is not None else None
    loc = (fc or {}).get("adm4")
    archived = repo.load_forecast_slots(loc) if loc else []
    points = composite_points((fc or {}).get("rows") or [], archived)
    meta = {"adm4": loc, "payload_hash": (fc or {}).get("payload_hash"),
            "issued_at": (fc or {}).get("issued_at"), "fetched_at": (fc or {}).get("fetched_at"),
            "n_points": len(points), "archived_slots": len(archived)}
    return {"plot": plot, "profile": profile, "cycle": cycle, "h_obs": h_obs, "points": points,
            "forecast_meta": meta}


def run_and_publish(repo, plot_id: str, snapshot, actor: str, settings, decision_at: Optional[datetime] = None) -> dict:
    """Hitung dan terbitkan rekomendasi untuk satu petak. Mengembalikan {"rec_id", "output"}."""
    decision_at = decision_at or datetime.now(timezone.utc)
    inp = gather_inputs(repo, plot_id, snapshot, decision_at)
    if inp["plot"] is None:
        raise ValueError(f"petak tidak ditemukan: {plot_id}")
    out, snap = compute(max_h_age_hours=settings.max_h_age_hours, decision_at=decision_at, **inp)
    expires = decision_at + timedelta(hours=settings.rec_expiry_hours)
    rec_id = repo.publish_recommendation(
        plot_id, actor, decision_at, snap, snap.get("profile_id"), MODEL_VERSION, out["run_mode"],
        out["status"], out, expires)
    return {"rec_id": rec_id, "output": out}
