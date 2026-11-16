"""labels.py - pembentukan label residual (AI offline) dari pengamatan. Fungsi murni, tanpa DB/Streamlit.

Dua kontrak (audit 16 Nov 2026, K01-K03, K05):
  purpose="RESEARCH" (default)  - jalur penelitian. Hanya pengamatan h MANUAL nyata, record_status ACTIVE, quality_flag OK,
      bukan is_demo, provenansi jelas. Data demo/sintetis TIDAK boleh menjadi label penelitian.
  purpose="DEMO_SYNTHETIC"       - hanya untuk melatih model DEMONSTRASI dari korpus sintetis. Data is_demo/sintetis boleh, tetapi
      record VOID/SUPERSEDED dan QC buruk tetap ditolak, dan setiap label diberi purpose agar tidak tercampur (split_temporal
      menolak campuran).

Aturan jendela valid (Grand Framework v2, bagian 7):
  * kedua ujung dan semua pengamatan di antaranya lolos kontrak purpose;
  * tidak ada irigasi aktual yang tumpang tindih dengan jendela;
  * bukti tidak hujan = cakupan data hujan YANG TIDAK BERLUBANG menutup seluruh jendela dan semua nilai hujan valid (angka
    hingga, >= 0) dan <= ambang. Nilai None/NaN/Inf/negatif/hilang => RAIN_UNKNOWN (tidak pernah dianggap nol);
  * pengamatan antara tidak naik dan tidak ada yang melintasi h = 0; panjang jendela W di dalam [w_min, w_max] hari.
`available_at` = waktu terakhir SEMUA bahan label tersedia (h awal/akhir/antara, irigasi, hujan, input lain).
Label negatif tidak dipotong; hanya ditandai peninjauan.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

import physics_engine as pe

NON_REAL_SOURCES = ("DUMMY", "SIMULATED")
REAL_SOURCES = ("MANUAL",)                 # satu-satunya sumber h petak yang sah (pipa AWD dibaca manual)
RAIN_EPS_MM = 0.0
PURPOSES = ("RESEARCH", "DEMO_SYNTHETIC")


def _overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


# --------------------------------------------------------------------------------------------- kontrak sumber/status
def source_problem(o: dict, purpose: str) -> Optional[str]:
    """None bila pengamatan boleh dipakai untuk `purpose`; selain itu alasan singkat."""
    if (o.get("record_status") or None) != "ACTIVE":
        return "record_status bukan ACTIVE"            # VOID/SUPERSEDED, dan status hilang = provenansi tidak jelas
    if (o.get("quality_flag") or None) != "OK":
        return "quality_flag bukan OK"
    st = o.get("source_type")
    if purpose == "RESEARCH":
        if o.get("is_demo") is not False:               # True atau tidak dinyatakan -> tidak dipercaya
            return "is_demo/provenansi tidak jelas"
        if st not in REAL_SOURCES:
            return "source_type bukan sumber nyata"
    else:
        if st is None:                                  # korpus demo boleh sintetis; keterbedaan dijaga lewat purpose
            return "source_type kosong"
    return None


# ------------------------------------------------------------------------------------------------------- hujan
def _rain_value_ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def _norm_cover(cov) -> list:
    """rain_covered: None | (awal, akhir) | [(awal, akhir), ...] -> daftar interval tersortir (tanpa menggabungkan celah)."""
    if not cov:
        return []
    if isinstance(cov, tuple) and len(cov) == 2 and isinstance(cov[0], datetime):
        cov = [cov]
    return sorted((a, b) for a, b in cov if a is not None and b is not None and b >= a)


def _covers(cov_list, t0, t1) -> bool:
    """Satu interval cakupan harus memuat seluruh [t0, t1]; celah di tengah = tidak tercakup."""
    return any(a <= t0 and b >= t1 for a, b in cov_list)


# ------------------------------------------------------------------------------------------- rerata berbobot durasi
def mean_over_interval(daily: dict, t0: datetime, t1: datetime, tz) -> Optional[float]:
    """Rerata nilai harian (kunci: tanggal lokal `tz`) berbobot DURASI pada interval setengah-terbuka [t0, t1).
    Tanggal akhir ikut hanya bila interval benar-benar memasukinya (jendela 00:00-00:00 memakai tepat tanggalnya).
    None bila interval tidak valid atau ada hari tanpa nilai hingga. Dipakai sama oleh label dan fitur (satu dukungan waktu)."""
    if t1 <= t0:
        return None
    a, b = t0.astimezone(tz), t1.astimezone(tz)
    day = datetime(a.year, a.month, a.day, tzinfo=a.tzinfo) if a.tzinfo else datetime(a.year, a.month, a.day)
    num = den = 0.0
    while day < b:
        nxt = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seg0, seg1 = max(a, day), min(b, nxt)
        sec = (seg1 - seg0).total_seconds()
        if sec > 0:
            v = daily.get(day.date())
            if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None
            num += v * sec
            den += sec
        day = nxt
    return num / den if den > 0 else None


def build_window_labels(h_obs: Iterable[dict], irrigation: Iterable[dict], rain: Iterable[dict], rain_covered,
                        mean_etc_fn: Callable, mu_dry: float, w_min_days: float = 2.0, w_max_days: float = 3.0,
                        rain_eps_mm: float = RAIN_EPS_MM, purpose: str = "RESEARCH",
                        inputs_available_at: Optional[datetime] = None) -> list:
    """h_obs: [{obs_id, value, observed_at, received_at, source_type, record_status, quality_flag, is_demo}],
    irrigation: [{started_at|arrived_at, ended_at, received_at?}], rain: [{observed_at, value_mm, received_at?}],
    rain_covered: (awal, akhir) ATAU daftar interval cakupan tanpa celah, mean_etc_fn(t0, t1) -> rata-rata ETc mm/hari atau None,
    inputs_available_at: waktu input lain (ET0/cuaca) tersedia, bila ada. Mengembalikan semua jendela kandidat + validitasnya."""
    if purpose not in PURPOSES:
        raise ValueError(f"purpose harus salah satu dari {PURPOSES}")
    obs = sorted((o for o in h_obs), key=lambda o: o["observed_at"])
    ev = []
    for e in irrigation:
        a = e.get("arrived_at") or e.get("started_at")
        if a is None:
            continue
        b = e.get("ended_at") or a
        ev.append((a, b, e.get("received_at") or b))
    cov = _norm_cover(rain_covered)
    out = []
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            a, b = obs[i], obs[j]
            w = (b["observed_at"] - a["observed_at"]).total_seconds() / 86400.0
            if w < w_min_days:
                continue
            if w > w_max_days:
                break
            mid = obs[i + 1:j]
            t0, t1 = a["observed_at"], b["observed_at"]
            rain_in = [r for r in rain if t0 <= r.get("observed_at", t0 - timedelta(days=9999)) <= t1]
            # waktu semua bahan label tersedia: h awal/akhir/antara + irigasi yang beririsan dengan jendela + hujan di jendela
            avail = [(o.get("received_at") or o["observed_at"]) for o in (a, b, *mid)]
            avail += [rcv for s_, e_, rcv in ev if _overlaps(t0, t1, s_, max(e_, s_ + timedelta(seconds=1)))]
            avail += [(r.get("received_at") or r.get("observed_at") or t1) for r in rain_in]
            if inputs_available_at is not None:
                avail.append(inputs_available_at)
            row = {"start": t0, "end": t1, "w_days": w, "start_obs_id": a.get("obs_id"), "end_obs_id": b.get("obs_id"),
                   "available_at": max(avail), "validity": "VALID", "residual_mm_day": None, "purpose": purpose}
            reason = None
            if any(source_problem(o, purpose) for o in (a, b, *mid)):
                reason = "NON_RESEARCH_SOURCE"
            elif any(_overlaps(t0, t1, s, max(e, s + timedelta(seconds=1))) for s, e, _ in ev):
                reason = "IRRIGATION_IN_WINDOW"
            elif not _covers(cov, t0, t1) or any(not _rain_value_ok(r.get("value_mm")) for r in rain_in):
                reason = "RAIN_UNKNOWN"
            elif any(r["value_mm"] > rain_eps_mm for r in rain_in):
                reason = "RAIN_IN_WINDOW"
            else:
                seq = [a["value"]] + [o["value"] for o in mid] + [b["value"]]
                if any(x2 > x1 + 1e-9 for x1, x2 in zip(seq, seq[1:])):
                    reason = "RISE_IN_WINDOW"
                elif any(x1 * x2 < 0 for x1, x2 in zip(seq, seq[1:])):
                    reason = "CROSSES_ZERO"
            if reason is None:
                etc = mean_etc_fn(t0, t1)
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


def derive_embargo_days(feature_lookback_days: float, target_extension_days: float = 0.0) -> float:
    """Panjang embargo diturunkan dari protokol, bukan angka tetap: dukungan waktu fitur (riwayat ke belakang) ditambah
    seberapa jauh target label menjangkau di luar jendelanya. Kosong (0) bila fitur dan target hanya berada di dalam jendela."""
    return max(0.0, float(feature_lookback_days)) + max(0.0, float(target_extension_days))


def split_temporal(labels: list, train_end: datetime, valid_end: datetime, embargo_days: float = 0.0) -> dict:
    """Pisah VALID menurut waktu dengan cutoff kematangan:
        train : end <= train_end  DAN available_at <= train_end   (label yang belum tersedia saat pelatihan dibekukan = bocor)
        valid : start >= train_end + embargo, end <= valid_end, available_at <= valid_end
        test  : start >= valid_end + embargo
    Yang lain dibuang (`dropped`). Label berbeda `purpose` tidak boleh dicampur dalam satu pemisahan."""
    purposes = {l.get("purpose") for l in labels if l.get("validity") == "VALID"}
    if len(purposes) > 1:
        raise ValueError(f"split_temporal menolak campuran purpose: {sorted(map(str, purposes))}")
    emb = timedelta(days=max(0.0, float(embargo_days)))
    sets = {"train": [], "valid": [], "test": [], "dropped": []}
    for lab in labels:
        if lab["validity"] != "VALID":
            continue
        s, e, av = lab["start"], lab["end"], lab["available_at"]
        if e <= train_end:
            (sets["train"] if av <= train_end else sets["dropped"]).append(lab)
        elif s >= valid_end + emb:
            sets["test"].append(lab)
        elif s >= train_end + emb and e <= valid_end:
            (sets["valid"] if av <= valid_end else sets["dropped"]).append(lab)
        else:
            sets["dropped"].append(lab)
    return sets
