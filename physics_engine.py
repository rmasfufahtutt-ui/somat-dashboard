"""
physics_engine.py - mesin neraca air petak SOMAT (fungsi murni, tanpa Streamlit/DB).

Mengikuti "Grand Framework, Arsitektur, dan AI Predictive SOMAT" v1.0 (13 Nov 2026).
Satuan: h dalam cm (h=0 permukaan tanah, + genangan, - di bawah permukaan);
        air dalam mm; waktu dalam hari/jam; luas ha; debit m3/s.

Prinsip:
  * Tidak ada nilai parameter lokasi yang "diam-diam" terisi. Setiap parameter membawa status
    (CALIBRATED / LITERATURE / EXAMPLE / PENDING) dan hasil perhitungan menyebutkan statusnya.
  * Parameter PENDING (belum diukur) menghasilkan status MISSING_PARAMETER, bukan angka tebakan.
  * h petak berasal dari pengamatan manual (pipa observasi); tidak pernah diturunkan dari kelembapan tanah (%).
  * Tidak ada pembulatan atau pemotongan diam-diam: luapan dicatat terpisah, label negatif ditandai.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

PARAM_STATUSES = ("CALIBRATED", "LITERATURE", "EXAMPLE", "PENDING")


@dataclass(frozen=True)
class Param:
    value: Optional[float] = None
    status: str = "PENDING"
    source: str = ""

    def __post_init__(self):
        if self.status not in PARAM_STATUSES:
            raise ValueError(f"status parameter tidak dikenal: {self.status}")

    @property
    def known(self) -> bool:
        return self.value is not None and self.status != "PENDING"


@dataclass(frozen=True)
class PhaseRule:
    """Ambang AWD per fase tanaman. trigger_h None = aturan fase belum ditetapkan di protokol."""
    trigger_h: Param = field(default_factory=Param)   # cm, irigasi bila h prediktif <= trigger
    target_h: Param = field(default_factory=Param)    # cm, pengisian sampai target


@dataclass(frozen=True)
class PlotProfile:
    plot_id: str
    area_ha: Param = field(default_factory=Param)
    mu_dry: Param = field(default_factory=Param)      # porositas drainase saat pengeringan
    mu_fill: Param = field(default_factory=Param)     # porositas drainase saat pengisian
    lead_time_h: Param = field(default_factory=Param)  # L: waktu tunggu sampai air tiba di petak
    h_cap_cm: Param = field(default_factory=Param)    # tinggi pematang (batas genangan); PENDING = tanpa batas
    phases: dict = field(default_factory=dict)        # {"vegetatif": PhaseRule, ...}
    sp_constant: Param = field(default_factory=Param)  # kehilangan tambahan konstan (mm/hari) untuk M1
    q_plot_m3s: Param = field(default_factory=Param)   # debit ke petak (bukan debit saluran)
    validation_status: str = "UNVALIDATED"            # UNVALIDATED | VALIDATED (keputusan pemeriksa, bukan otomatis)


# ----------------------------------------------------------------------------------------------
# Tampungan dan perambatan h
# ----------------------------------------------------------------------------------------------
def storage_mm(h_cm: float, mu: float) -> float:
    """S(h) relatif terhadap keadaan h=0: 10*h bila h>=0, 10*mu*h bila h<0."""
    return 10.0 * h_cm if h_cm >= 0 else 10.0 * mu * h_cm


def h_from_storage(s_mm: float, mu: float) -> float:
    return s_mm / 10.0 if s_mm >= 0 else s_mm / (10.0 * mu)


def advance_h(h_cm: float, net_loss_mm: float, mu_dry: float, mu_fill: float,
              h_cap_cm: Optional[float] = None):
    """Satu langkah neraca: S_baru = S - net_loss. net_loss>0 pengeringan (mu_dry), <0 pengisian (mu_fill).
    Melintasi h=0 ditangani karena S(0)=0 untuk kedua mu. Mengembalikan (h_baru, luapan_mm)."""
    mu = mu_dry if net_loss_mm >= 0 else mu_fill
    s_new = storage_mm(h_cm, mu) - net_loss_mm
    h_new = h_from_storage(s_new, mu)
    overflow = 0.0
    if h_cap_cm is not None and h_new > h_cap_cm:
        overflow = 10.0 * (h_new - h_cap_cm)
        h_new = h_cap_cm
    return h_new, overflow


def etc_mm(et0_mm_day: float, kc: float) -> float:
    return kc * et0_mm_day


def net_loss_mm_day(etc: float, r_adj: float, pe: float) -> float:
    """F = ETc + R_adj - Pe  (positif = kehilangan tampungan bersih)."""
    return etc + r_adj - pe


def trajectory(h0_cm: float, daily_f_mm: list, hours: float, mu_dry: float, mu_fill: float,
               h_cap_cm: Optional[float] = None):
    """h setelah `hours` jam tanpa irigasi, langkah per jam dengan F harian dari prakiraan.
    Mengembalikan (h_akhir, luapan_total_mm, daftar h per jam). Melebihi horizon -> ValueError."""
    if hours < 0:
        raise ValueError("hours negatif")
    if hours > 24 * len(daily_f_mm):
        raise ValueError("UNSUPPORTED_HORIZON")
    h, overflow, path = h0_cm, 0.0, [h0_cm]
    whole, frac = int(hours), hours - int(hours)
    steps = [1.0] * whole + ([frac] if frac > 1e-12 else [])
    t = 0.0
    for dt in steps:
        f = daily_f_mm[min(int(t // 24), len(daily_f_mm) - 1)]
        h, ov = advance_h(h, f * dt / 24.0, mu_dry, mu_fill, h_cap_cm)
        overflow += ov
        path.append(h)
        t += dt
    return h, overflow, path


# ----------------------------------------------------------------------------------------------
# Kebutuhan pengisian, volume, durasi
# ----------------------------------------------------------------------------------------------
def refill_requirement_mm(h_arrival_cm: float, h_target_cm: float, mu_fill: float) -> float:
    """I_refill = max(0, S(h_target) - S(h_tiba)) dengan koefisien pengisian."""
    return max(0.0, storage_mm(h_target_cm, mu_fill) - storage_mm(h_arrival_cm, mu_fill))


def volume_m3(depth_mm: float, area_ha: float) -> float:
    """V = 10 * A_ha * I_mm  (10 mm pada 0,1 ha = 10 m3)."""
    return 10.0 * area_ha * depth_mm


def duration_hours(v_refill_m3: float, q_plot_m3s: float, area_ha: float, f_application_mm_day: float):
    """D = V_refill / (Q_petak - A_m2*F/1000/86400). None bila penyebut tidak positif (target tak tercapai)."""
    loss_m3s = area_ha * 10000.0 * f_application_mm_day / 1000.0 / 86400.0
    denom = q_plot_m3s - loss_m3s
    if denom <= 0:
        return None
    return v_refill_m3 / denom / 3600.0


# ----------------------------------------------------------------------------------------------
# Label residual dan bias adaptif (bagian 4.2 dan 4.5)
# ----------------------------------------------------------------------------------------------
def window_residual(h_start_cm: float, h_end_cm: float, w_days: float, mean_etc_mm_day: float,
                    mu_dry: float) -> dict:
    """R_W = 10*mu_eff*(h_awal - h_akhir)/W - rata-rata ETc  (mm/hari).
    Jendela yang melintasi h=0 tidak valid. Label negatif tidak dipotong; hanya ditandai untuk ditinjau."""
    if w_days <= 0:
        return {"valid": False, "reason": "w_days_invalid"}
    if h_start_cm * h_end_cm < 0:
        return {"valid": False, "reason": "crosses_zero"}
    mu_eff = 1.0 if (h_start_cm >= 0 and h_end_cm >= 0) else mu_dry
    r = 10.0 * mu_eff * (h_start_cm - h_end_cm) / w_days - mean_etc_mm_day
    return {"valid": True, "r_mm_day": r, "mu_eff": mu_eff, "negative_label_review": r < 0}


def update_bias(b_last: float, elapsed_days: float, r_observed: float, r_base_prior: float,
                alpha: float, lam: float, bmax: float):
    """b_baru = clip((1-alpha)*b_last*exp(-lam*dt) + alpha*e_base, -bmax, +bmax); e_base = R_obs - R_base_prior.
    Hanya untuk label matang dan prediksi apriori yang sama; bukan pelatihan ulang bobot."""
    e_base = r_observed - r_base_prior
    b_decayed = b_last * math.exp(-lam * elapsed_days)
    b_new = max(-bmax, min(bmax, (1.0 - alpha) * b_decayed + alpha * e_base))
    return b_new, e_base


def r_adj_for_model(model: str, sp_constant: Optional[float] = None, bias: float = 0.0,
                    ml_residual: Optional[float] = None) -> float:
    """M0: 0 | M1: SPconstant | M1B: SPconstant + b | M2: residual ML + b (SPconstant TIDAK ditambah lagi)."""
    m = model.upper()
    if m == "M0":
        return 0.0
    if m == "M1":
        if sp_constant is None:
            raise ValueError("SPconstant diperlukan untuk M1")
        return sp_constant
    if m == "M1B":
        if sp_constant is None:
            raise ValueError("SPconstant diperlukan untuk M1B")
        return sp_constant + bias
    if m == "M2":
        if ml_residual is None:
            raise ValueError("residual ML diperlukan untuk M2")
        return ml_residual + bias
    raise ValueError(f"model tidak dikenal: {model}")


# ----------------------------------------------------------------------------------------------
# Rekomendasi
# ----------------------------------------------------------------------------------------------
def recommend(*, h_now_cm: Optional[float], h_observed_at: Optional[datetime], now: datetime,
              forecast: list, kc: Param, profile: PlotProfile, phase: str, model: str = "M0",
              sp_constant: Optional[float] = None, bias: float = 0.0, ml_residual: Optional[float] = None,
              q_plot_m3s: Optional[float] = None, f_application_mm_day: Optional[float] = None,
              max_h_age_hours: float = 30.0) -> dict:
    """forecast = [{"et0": mm/hari, "pe": mm/hari}, ...] (satu elemen per hari, mulai hari ini).
    Tidak mengarang angka: parameter/pengamatan yang kurang menghasilkan status khusus."""
    out = {"status": "OK", "reasons": [], "irrigate": None, "model": model.upper(),
           "h_now_cm": h_now_cm, "h_arrival_cm": None, "trigger_h_cm": None, "target_h_cm": None,
           "refill_mm": None, "total_mm": None, "volume_m3": None, "duration_h": None,
           "overflow_mm": 0.0, "prediction_mode": model.upper(), "provisional": True, "parameter_status": {}}

    def fail(status, reason):
        out.update(status=status, prediction_mode="MANUAL_REQUIRED")
        out["reasons"].append(reason)
        return out

    # 1. Pengamatan h manual harus ada dan segar
    if h_now_cm is None or h_observed_at is None:
        return fail("NEEDS_FIELD_OBSERVATION", "Tidak ada pengamatan h petak yang valid.")
    age_h = (now - h_observed_at).total_seconds() / 3600.0
    if age_h < 0:
        return fail("INVALID_OBSERVATION", "Waktu pengamatan h berada di masa depan.")
    if age_h > max_h_age_hours:
        return fail("STALE_OBSERVATION", f"Pengamatan h terakhir berumur {age_h:.1f} jam (batas {max_h_age_hours:.0f} jam).")

    # 2. Parameter yang diperlukan harus sudah ada
    rule = profile.phases.get(phase)
    needed = {"mu_dry": profile.mu_dry, "mu_fill": profile.mu_fill, "area_ha": profile.area_ha,
              "lead_time_h": profile.lead_time_h, "kc": kc}
    if rule is not None:
        needed["trigger_h"], needed["target_h"] = rule.trigger_h, rule.target_h
    out["parameter_status"] = {k: p.status for k, p in needed.items()}
    if rule is None:
        return fail("PROTOCOL_REQUIRED", f"Aturan fase '{phase}' belum ditetapkan di protokol.")
    missing = [k for k, p in needed.items() if not p.known]
    if missing:
        return fail("MISSING_PARAMETER", "Parameter menunggu pengukuran/kalibrasi: " + ", ".join(missing))

    # 3. Prediksi h saat air tiba (tanpa irigasi selama L)
    r_adj = r_adj_for_model(model, sp_constant, bias, ml_residual)
    daily_f = [net_loss_mm_day(etc_mm(d["et0"], kc.value), r_adj, d["pe"]) for d in forecast]
    cap = profile.h_cap_cm.value if profile.h_cap_cm.known else None
    try:
        h_arr, overflow, _ = trajectory(h_now_cm, daily_f, profile.lead_time_h.value,
                                        profile.mu_dry.value, profile.mu_fill.value, cap)
    except ValueError as exc:
        if str(exc) == "UNSUPPORTED_HORIZON":
            return fail("UNSUPPORTED_HORIZON", "Waktu tunggu L melebihi horizon prakiraan yang tersedia.")
        raise
    out.update(h_arrival_cm=h_arr, overflow_mm=overflow, trigger_h_cm=rule.trigger_h.value, target_h_cm=rule.target_h.value)

    # 4. Aturan AWD
    out["irrigate"] = h_arr <= rule.trigger_h.value
    if out["irrigate"]:
        refill = refill_requirement_mm(h_arr, rule.target_h.value, profile.mu_fill.value)
        out["refill_mm"] = refill
        v_refill = volume_m3(refill, profile.area_ha.value)
        f_app = f_application_mm_day
        if f_app is None:
            f_app = max(0.0, daily_f[min(int(profile.lead_time_h.value // 24), len(daily_f) - 1)])
        if q_plot_m3s is None:
            out["total_mm"], out["volume_m3"] = refill, v_refill
            out["reasons"].append("Durasi belum dapat dihitung: debit ke petak belum diberikan; volume hanya untuk pengisian.")
        else:
            d_h = duration_hours(v_refill, q_plot_m3s, profile.area_ha.value, f_app)
            if d_h is None:
                out["status"] = "TARGET_NOT_REACHABLE"
                out["reasons"].append("Debit ke petak tidak cukup untuk mengimbangi kehilangan; target tidak tercapai.")
            else:
                out["duration_h"] = d_h
                out["total_mm"] = refill + f_app * d_h / 24.0
                out["volume_m3"] = volume_m3(out["total_mm"], profile.area_ha.value)

    # 5. Mutu hasil: tidak ada klaim validasi bila ada parameter belum terkalibrasi
    statuses = set(out["parameter_status"].values())
    out["provisional"] = statuses != {"CALIBRATED"}
    if "EXAMPLE" in statuses:
        out["prediction_mode"] = "DEMO"
    return out


# ==============================================================================================
# Grand Framework v2: alur waktu eksplisit  observed_at -> decision_at -> arrival_at -> end_at
# ==============================================================================================
OPERATIONAL_MODES = ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED")
RUN_MODES = ("DEMO", "BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_SHADOW", "ML_VALIDATED", "MANUAL_REQUIRED")


class MissingDriver(Exception):
    """Pemaksa neraca (ET0/Kc) untuk suatu waktu tidak tersedia -> hasil harus ditandai, bukan ditebak."""

    def __init__(self, when, what="et0"):
        super().__init__(f"{what} tidak tersedia untuk {when}")
        self.when, self.what = when, what


# Domain fisik yang diperiksa sebelum rumus dipakai. (lo, hi, lo_inklusif, hi_inklusif)
DOMAINS = {
    "mu_dry": (0.0, 1.0, False, True), "mu_fill": (0.0, 1.0, False, True),
    "area_ha": (0.0, 5000.0, False, True), "lead_time_h": (0.0, 168.0, True, True),
    "h_cap_cm": (0.0, 100.0, False, True), "kc": (0.0, 2.0, False, True),
    "trigger_h": (-60.0, 10.0, True, True), "target_h": (-10.0, 30.0, True, True),
    "q_plot_m3s": (0.0, 20.0, False, True), "sp_constant": (-5.0, 30.0, True, True),
}


def _in_domain(name: str, v) -> bool:
    lo, hi, lo_inc, hi_inc = DOMAINS[name]
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        return False
    return (v >= lo if lo_inc else v > lo) and (v <= hi if hi_inc else v < hi)


def validate_domain(profile: PlotProfile, kc: Optional[Param], rule: Optional[PhaseRule],
                    q_plot_m3s: Optional[float] = None, sp_constant: Optional[float] = None) -> list:
    """Daftar isu domain (kosong = lolos). Hanya nilai yang `known` diperiksa; yang PENDING ditangani terpisah."""
    items = [("mu_dry", profile.mu_dry), ("mu_fill", profile.mu_fill), ("area_ha", profile.area_ha),
             ("lead_time_h", profile.lead_time_h), ("h_cap_cm", profile.h_cap_cm)]
    if kc is not None:
        items.append(("kc", kc))
    if rule is not None:
        items += [("trigger_h", rule.trigger_h), ("target_h", rule.target_h)]
    issues = []
    for name, p in items:
        if p.known and not _in_domain(name, p.value):
            issues.append({"code": "OUT_OF_DOMAIN", "param": name, "value": p.value})
    for name, v in (("q_plot_m3s", q_plot_m3s), ("sp_constant", sp_constant)):
        if v is not None and not _in_domain(name, v):
            issues.append({"code": "OUT_OF_DOMAIN", "param": name, "value": v})
    if rule is not None and rule.trigger_h.known and rule.target_h.known and rule.target_h.value <= rule.trigger_h.value:
        issues.append({"code": "TARGET_NOT_ABOVE_TRIGGER", "param": "target_h", "value": rule.target_h.value})
    if (rule is not None and rule.target_h.known and profile.h_cap_cm.known
            and rule.target_h.value > profile.h_cap_cm.value):
        issues.append({"code": "TARGET_ABOVE_CAP", "param": "target_h", "value": rule.target_h.value})
    return issues


def _local_midnights(start: datetime, end: datetime):
    d = start.date() + timedelta(days=1)
    while True:
        m = datetime(d.year, d.month, d.day, tzinfo=start.tzinfo)
        if m >= end:
            return
        yield m
        d += timedelta(days=1)


def _breakpoints(start: datetime, end: datetime, extra=(), max_step_h: float = 1.0):
    pts = {start, end}
    pts.update(b for b in extra if start < b < end)
    pts.update(_local_midnights(start, end))
    ordered = sorted(pts)
    out = [ordered[0]]
    step = timedelta(hours=max_step_h)
    for nxt in ordered[1:]:
        cur = out[-1]
        while nxt - cur > step + timedelta(microseconds=1):
            cur = cur + step
            out.append(cur)
        out.append(nxt)
    return out


def trajectory_timed(h0_cm: float, start: datetime, end: datetime, f_at: Callable, mu_dry: float, mu_fill: float,
                     h_cap_cm: Optional[float] = None, breaks=(), max_step_h: float = 1.0):
    """Lintasan h dari `start` ke `end` (datetime berzona) tanpa irigasi. Interval dipotong pada pergantian
    TANGGAL LOKAL dan titik `breaks` (mis. pergantian fase); `f_at(t_tengah)` -> F mm/hari dan boleh
    melempar MissingDriver. Mengembalikan (h_akhir, luapan_total_mm, [(waktu, h), ...])."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("waktu harus berzona")
    if end < start:
        raise ValueError("end sebelum start")
    h, overflow = h0_cm, 0.0
    path = [(start, h)]
    pts = _breakpoints(start, end, breaks, max_step_h)
    for a, b in zip(pts, pts[1:]):
        dt_days = (b - a).total_seconds() / 86400.0
        if dt_days <= 0:
            continue
        f = f_at(a + (b - a) / 2)
        h, ov = advance_h(h, f * dt_days, mu_dry, mu_fill, h_cap_cm)
        overflow += ov
        path.append((b, h))
    return h, overflow, path


def inflow_mm_day(q_plot_m3s: float, area_ha: float) -> float:
    """Debit ke petak -> kedalaman ekuivalen per hari: Q*86400 m3/hari / (A*10000 m2) * 1000 mm."""
    return q_plot_m3s * 86400.0 * 1000.0 / (area_ha * 10000.0)


def application_duration(start: datetime, need_mm: float, q_plot_m3s: float, area_ha: float, f_at: Callable,
                         max_hours: float = 96.0, breaks=()):
    """Waktu D agar tampungan bertambah need_mm saat air masuk dengan debit tetap Q dan F(t) berubah.
    Integrasi per interval (pergantian tanggal/fase) dengan interpolasi di interval penentu.
    Mengembalikan (D_jam | None, alasan | None) dengan alasan in {"TARGET_NOT_REACHABLE", "UNSUPPORTED_HORIZON"}."""
    inflow = inflow_mm_day(q_plot_m3s, area_ha)
    end = start + timedelta(hours=max_hours)
    acc, any_progress = 0.0, False
    pts = _breakpoints(start, end, breaks, max_step_h=6.0)
    for a, b in zip(pts, pts[1:]):
        dt_days = (b - a).total_seconds() / 86400.0
        try:
            f = f_at(a + (b - a) / 2)
        except MissingDriver:
            return None, "UNSUPPORTED_HORIZON"
        net = inflow - f
        if net > 0:
            any_progress = True
            if acc + net * dt_days >= need_mm - 1e-12:
                t_hit = (need_mm - acc) / net          # hari dalam interval ini
                return ((a - start).total_seconds() / 3600.0 + t_hit * 24.0), None
            acc += net * dt_days
    return None, ("UNSUPPORTED_HORIZON" if any_progress else "TARGET_NOT_REACHABLE")


def classify_run_mode(status: str, parameter_status: dict, validation_status: str = "UNVALIDATED",
                      inputs_dummy: bool = False, ml_mode: Optional[str] = None) -> str:
    """Run mode terpisah dari status parameter dan jenis sumber data (bagian 7)."""
    if status not in ("OK", "TARGET_NOT_REACHABLE"):
        return "MANUAL_REQUIRED"
    st = set(parameter_status.values())
    if "EXAMPLE" in st or inputs_dummy:
        return "DEMO"
    if ml_mode in ("ML_SHADOW", "ML_VALIDATED"):
        return ml_mode
    if "PENDING" not in st and validation_status == "VALIDATED":
        return "BASELINE_VALIDATED"
    return "BASELINE_PROVISIONAL"


@dataclass
class Drivers:
    """Pemaksa neraca per tanggal lokal. None = tidak tersedia (INCOMPLETE_FORECAST)."""
    et0_by_date: dict                      # {date: mm/hari | None}
    kc_at: Callable                        # datetime -> Kc | None (bergantung fase)
    pe_by_date: dict = field(default_factory=dict)   # {date: mm/hari}; kosong = skenario tanpa hujan eksplisit
    r_adj: float = 0.0
    tz: object = None

    def f_at(self, t: datetime) -> float:
        local = t.astimezone(self.tz) if self.tz is not None else t
        d = local.date()
        et0 = self.et0_by_date.get(d)
        if et0 is None:
            raise MissingDriver(d, "et0")
        kc = self.kc_at(t)
        if kc is None:
            raise MissingDriver(t, "kc")
        return net_loss_mm_day(etc_mm(et0, kc), self.r_adj, float(self.pe_by_date.get(d, 0.0)))


def recommend_timed(*, h_obs_cm: Optional[float], observed_at: Optional[datetime], decision_at: datetime,
                    drivers: Optional[Drivers], profile: PlotProfile, rule_at: Callable,
                    phase_breaks=(), kc_param_at: Optional[Callable] = None, model: str = "M1",
                    max_h_age_hours: float = 30.0, inputs_dummy: bool = False, q_plot_m3s: Optional[float] = None) -> dict:
    """Rekomendasi per petak dengan selang waktu eksplisit.

    * Kondisi h diperambat dari observed_at ke decision_at (selang pengamatan), lalu ke arrival_at = decision_at + L.
    * Interval dipotong pada pergantian tanggal lokal dan fase; F per interval berasal dari ET0 tanggal tsb.
    * rule_at(t) -> (nama_fase | None, PhaseRule | None); kc_param_at(t) -> Param | None (untuk status/domain).
    * Tidak ada angka dikarang: parameter PENDING/EXAMPLE, h usang, ET0 hari tak lengkap -> status & alasan khusus.
    """
    out = {"status": "OK", "reasons": [], "issues": [], "irrigate": None, "model": model.upper(),
           "observed_at": observed_at, "decision_at": decision_at, "arrival_at": None, "end_at": None,
           "h_obs_cm": h_obs_cm, "h_decision_cm": None, "h_arrival_cm": None, "phase_decision": None,
           "phase_arrival": None, "trigger_h_cm": None, "target_h_cm": None, "refill_mm": None, "total_mm": None,
           "volume_m3": None, "duration_h": None, "overflow_mm": 0.0, "propagated_hours": None,
           "lead_time_h": None, "path": [], "parameter_status": {}, "run_mode": "MANUAL_REQUIRED",
           "provisional": True, "validated": False, "rain_scenario": "NO_RAIN_SCENARIO", "rain_note": None,
           "f_mm_day_arrival": None, "inflow_mm_day": None}

    def fail(status, code, reason, **extra):
        out["status"] = status
        out["run_mode"] = "MANUAL_REQUIRED"
        out["issues"].append({"code": code, **extra})
        out["reasons"].append(reason)
        return out

    # 1. Pengamatan h harus ada, sah, dan tidak terlalu tua
    if h_obs_cm is None or observed_at is None or not isinstance(h_obs_cm, (int, float)) or not math.isfinite(h_obs_cm):
        return fail("NEEDS_FIELD_OBSERVATION", "NO_H_OBSERVATION", "Tidak ada pengamatan h petak yang valid.")
    if observed_at.tzinfo is None or decision_at.tzinfo is None:
        raise ValueError("observed_at dan decision_at harus berzona waktu")
    age_h = (decision_at - observed_at).total_seconds() / 3600.0
    if age_h < 0:
        return fail("INVALID_OBSERVATION", "OBSERVATION_IN_FUTURE", "Waktu pengamatan h berada di masa depan.")
    if age_h > max_h_age_hours:
        return fail("STALE_OBSERVATION", "STALE_OBSERVATION",
                    f"Pengamatan h terakhir berumur {age_h:.1f} jam (batas {max_h_age_hours:.0f} jam).",
                    age_h=age_h, limit_h=max_h_age_hours)

    # 2. Parameter wajib, aturan fase, domain
    ph_dec, rule_dec = rule_at(decision_at)
    L_param = profile.lead_time_h
    arrival_at = decision_at + timedelta(hours=L_param.value) if L_param.known else None
    ph_arr, rule_arr = rule_at(arrival_at) if arrival_at is not None else (None, None)
    out.update(phase_decision=ph_dec, phase_arrival=ph_arr)
    kc_dec = kc_param_at(decision_at) if kc_param_at else None
    kc_arr = kc_param_at(arrival_at) if (kc_param_at and arrival_at is not None) else None
    needed = {"mu_dry": profile.mu_dry, "mu_fill": profile.mu_fill, "area_ha": profile.area_ha,
              "lead_time_h": profile.lead_time_h}
    if kc_arr is not None or kc_dec is not None:
        needed["kc"] = kc_arr or kc_dec
    else:
        needed["kc"] = Param()
    if rule_arr is not None:
        needed["trigger_h"], needed["target_h"] = rule_arr.trigger_h, rule_arr.target_h
    if model.upper() in ("M1", "M1B"):
        needed["sp_constant"] = profile.sp_constant
    out["parameter_status"] = {k: p.status for k, p in needed.items()}
    if rule_dec is None or (arrival_at is not None and rule_arr is None):
        return fail("PROTOCOL_REQUIRED", "PROTOCOL_REQUIRED",
                    "Aturan fase belum ditetapkan di protokol untuk waktu keputusan/air tiba.",
                    phase=ph_arr or ph_dec)
    missing = [k for k, p in needed.items() if not p.known]
    if missing:
        return fail("MISSING_PARAMETER", "MISSING_PARAMETER",
                    "Parameter menunggu pengukuran/kalibrasi: " + ", ".join(missing), params=missing)
    sp = profile.sp_constant.value if profile.sp_constant.known else None
    q = q_plot_m3s if q_plot_m3s is not None else (profile.q_plot_m3s.value if profile.q_plot_m3s.known else None)
    bad = validate_domain(profile, needed["kc"], rule_arr, q, sp)
    hard = [i for i in bad if i["code"] in ("OUT_OF_DOMAIN", "TARGET_NOT_ABOVE_TRIGGER")]
    if hard:
        out["issues"].extend(hard)
        return fail("INVALID_PARAMETER", "INVALID_PARAMETER",
                    "Parameter di luar domain yang sah: " + ", ".join(f"{i['param']}={i['value']}" for i in hard))
    out["issues"].extend(i for i in bad if i not in hard)
    if drivers is None:
        return fail("INCOMPLETE_FORECAST", "NO_DRIVERS", "ET0/prakiraan belum tersedia.")
    drivers.r_adj = r_adj_for_model(model, sp, 0.0, None) if model.upper() != "M2" else drivers.r_adj

    cap = profile.h_cap_cm.value if profile.h_cap_cm.known else None
    mu_d, mu_f = profile.mu_dry.value, profile.mu_fill.value
    out.update(lead_time_h=L_param.value, arrival_at=arrival_at, trigger_h_cm=rule_arr.trigger_h.value,
               target_h_cm=rule_arr.target_h.value, propagated_hours=age_h)

    # 3. observed_at -> decision_at -> arrival_at (satu lintasan kontinu; titik tengah dicatat)
    try:
        h_dec, ov1, path1 = trajectory_timed(h_obs_cm, observed_at, decision_at, drivers.f_at, mu_d, mu_f, cap, phase_breaks)
        h_arr, ov2, path2 = trajectory_timed(h_dec, decision_at, arrival_at, drivers.f_at, mu_d, mu_f, cap, phase_breaks)
    except MissingDriver as exc:
        return fail("INCOMPLETE_FORECAST", "INCOMPLETE_FORECAST",
                    f"Data {exc.what.upper()} untuk {exc.when} belum lengkap; lintasan h tidak dihitung (hari tidak dilewati).",
                    when=str(exc.when), what=exc.what)
    out.update(h_decision_cm=h_dec, h_arrival_cm=h_arr, overflow_mm=ov1 + ov2, path=path1 + path2[1:])
    try:
        out["f_mm_day_arrival"] = drivers.f_at(arrival_at)
    except MissingDriver:
        out["f_mm_day_arrival"] = None

    # 4. Aturan AWD
    out["irrigate"] = h_arr <= rule_arr.trigger_h.value
    if out["irrigate"]:
        refill = refill_requirement_mm(h_arr, rule_arr.target_h.value, mu_f)
        v_refill = volume_m3(refill, profile.area_ha.value)
        out["refill_mm"] = refill
        if q is None:
            out["total_mm"], out["volume_m3"] = refill, v_refill
            out["reasons"].append("Durasi belum dapat dihitung: debit ke petak belum ditetapkan; volume hanya untuk pengisian.")
            out["issues"].append({"code": "DURATION_NEEDS_PLOT_DISCHARGE"})
        else:
            out["inflow_mm_day"] = inflow_mm_day(q, profile.area_ha.value)
            d_h, why = application_duration(arrival_at, refill, q, profile.area_ha.value, drivers.f_at,
                                            breaks=phase_breaks)
            if d_h is None:
                if why == "TARGET_NOT_REACHABLE":
                    out["status"] = "TARGET_NOT_REACHABLE"
                    out["reasons"].append("Debit ke petak tidak cukup untuk mengimbangi kehilangan; target tidak tercapai.")
                else:
                    out["reasons"].append("Durasi belum dapat dihitung: horizon ET0 tidak mencukupi sampai target tercapai.")
                out["total_mm"], out["volume_m3"] = refill, v_refill
                out["issues"].append({"code": why})
            else:
                v_total = q * d_h * 3600.0
                out.update(duration_h=d_h, end_at=arrival_at + timedelta(hours=d_h), volume_m3=v_total,
                           total_mm=v_total / (10.0 * profile.area_ha.value))

    # 5. Mode run: dipisahkan dari kualitas parameter dan jenis sumber
    out["validated"] = profile.validation_status == "VALIDATED"
    out["run_mode"] = classify_run_mode(out["status"], out["parameter_status"], profile.validation_status, inputs_dummy)
    out["provisional"] = out["run_mode"] != "BASELINE_VALIDATED"
    return out


def evaluate_modification(rec: dict, profile: PlotProfile, new_mm: float, q_plot_m3s: Optional[float],
                          precision_mm: float = 0.1, duration_h: Optional[float] = None,
                          duration_tolerance: float = 0.05) -> dict:
    """Validasi MODIFY: jumlah irigasi harus berubah (presisi beku), tidak melebihi pematang, dan durasi
    dihitung ulang dari debit. Mengembalikan {valid, issues, volume_m3, duration_h, duration_verified}."""
    issues = []
    area = profile.area_ha.value if profile.area_ha.known else None
    rec_mm = rec.get("total_mm")
    amount_ok = isinstance(new_mm, (int, float)) and not isinstance(new_mm, bool) and math.isfinite(new_mm) and new_mm >= 0
    if not amount_ok:
        issues.append({"code": "BAD_AMOUNT"})
    elif rec_mm is not None and abs(new_mm - rec_mm) < precision_mm - 1e-12:
        issues.append({"code": "AMOUNT_UNCHANGED", "precision_mm": precision_mm})
    vol, dur, verified = None, None, False
    if area is not None and amount_ok:
        vol = volume_m3(new_mm, area)
        if profile.h_cap_cm.known and rec.get("h_arrival_cm") is not None and profile.mu_fill.known:
            max_refill = refill_requirement_mm(rec["h_arrival_cm"], profile.h_cap_cm.value, profile.mu_fill.value)
            f_app = max(0.0, rec.get("f_mm_day_arrival") or 0.0)
            # air yang masuk dapat melebihi pengisian sampai pematang hanya sebesar kehilangan selama pengairan
            limit = max_refill + (f_app * (rec.get("duration_h") or 0.0) / 24.0)
            if new_mm > limit + 1e-9:
                issues.append({"code": "EXCEEDS_CAP", "limit_mm": limit})
        if q_plot_m3s is not None and q_plot_m3s > 0:
            dur = vol / (q_plot_m3s * 3600.0)
            verified = True
            if duration_h is not None and dur > 0 and abs(duration_h - dur) / dur > duration_tolerance:
                issues.append({"code": "DURATION_INCONSISTENT", "expected_h": dur})
        elif duration_h is not None:
            dur = duration_h
    return {"valid": not issues, "issues": issues, "volume_m3": vol, "duration_h": dur, "duration_verified": verified}
