"""demo_data.py - generator data DEMO PENELITIAN yang deterministik dan idempoten.

* Enam petak DEMO-P01..DEMO-P06, masing-masing >= 35 hari riwayat h (gigi gergaji AWD yang disimulasikan memakai
  fungsi mesin yang SAMA: advance_h, refill_requirement_mm, Hargreaves-Samani) + deret sensor sintetis.
* Setiap petak membawa skenario yang DIHASILKAN MESIN (bukan hasil tulisan tangan): keadaan h akhir dicari
  (pencarian h awal pada kisi tetap) sehingga `recommendation_service.compute` menghasilkan status yang dimaksud.
* Semua baris bertanda is_demo, dataset_id, dan origin='SEED'. Tidak ada angka BMKG di sini.
* seed()/reset() idempoten: memuat ulang tidak menggandakan data.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone

import demo_mode
import demo_repository as drepo
import demo_weather as dw
import et0 as et0lib
import physics_engine as pe
import recommendation_service as rs
from repository import inputs_hash

TZ = rs.TZ
VERSION = "demo-data-1"
HIST_DAYS = 35                       # >= 30 hari riwayat
HIST_TRIGGERS = (-14.0, -15.5, -17.0, -12.5)   # variasi ambang irigasi riwayat (operator kadang terlambat); urutan tetap
HIST_TRIGGER = HIST_TRIGGERS[0]                 # ambang irigasi pada riwayat sintetis (cm), sedikit di atas ambang protokol -15
HIST_Q = 0.015                       # debit riwayat (m3/s) agar durasi masuk akal
LEAD_H = 6.0
PHASES = [("vegetatif", 0, 45, False), ("generatif", 46, 85, True), ("pematangan", 86, 115, False)]
PHASE_PARAMS = {"vegetatif": (1.05, -15.0, 5.0), "generatif": (1.20, -10.0, 5.0), "pematangan": (0.90, -20.0, 3.0)}

# kisi pencarian h awal (deterministik, urutan tetap)
H0_GRID = [round(-15.0 + 0.25 * i, 2) for i in range(0, 85)]

SCENARIOS = {
    "IRRIGATE": "Perlu irigasi: h diprediksi mencapai/melewati ambang saat air tiba.",
    "SAFE": "Aman: h diprediksi masih di atas ambang, tidak perlu irigasi.",
    "RAIN_HOLD": "Hujan lebat hari ini menahan irigasi (tanpa hujan, petak ini perlu irigasi).",
    "STALE": "Pengamatan h usang (melewati batas umur): butuh pengamatan baru, mesin menolak menghitung.",
    "MISSING_PARAM": "Parameter belum lengkap (mu_fill belum diukur): butuh keputusan manual.",
    "NOT_REACHABLE": "Debit ke petak terlalu kecil: target h tidak tercapai walau air diberikan.",
}

PLOT_SPECS = [
    dict(plot_id="DEMO-P01", name="Petak Demo 1 — Perlu irigasi", scenario="IRRIGATE", area=0.8, das=36, lat=-7.2501, lon=112.7502,
         age_h=2.0, profile="NORMAL", rain="NONE", ideal_h=-16.0, q=0.015),
    dict(plot_id="DEMO-P02", name="Petak Demo 2 — Aman", scenario="SAFE", area=1.0, das=34, lat=-7.2511, lon=112.7512,
         age_h=2.0, profile="COOL", rain="NONE", ideal_h=-2.0, q=0.015),
    dict(plot_id="DEMO-P03", name="Petak Demo 3 — Hujan menahan irigasi", scenario="RAIN_HOLD", area=0.6, das=38, lat=-7.2521, lon=112.7522,
         age_h=2.0, profile="NORMAL", rain="TODAY_HEAVY", ideal_h=-16.0, q=0.015),
    dict(plot_id="DEMO-P04", name="Petak Demo 4 — Pengamatan usang", scenario="STALE", area=0.9, das=40, lat=-7.2531, lon=112.7532,
         age_h=40.0, profile="NORMAL", rain="NONE", ideal_h=-8.0, q=0.015),
    dict(plot_id="DEMO-P05", name="Petak Demo 5 — Parameter belum lengkap", scenario="MISSING_PARAM", area=0.7, das=35, lat=-7.2541, lon=112.7542,
         age_h=2.0, profile="HOT", rain="NONE", ideal_h=-12.0, q=0.015, pending=("mu_fill",)),
    dict(plot_id="DEMO-P06", name="Petak Demo 6 — Debit tidak cukup", scenario="NOT_REACHABLE", area=0.8, das=42, lat=-7.2551, lon=112.7552,
         age_h=2.0, profile="NORMAL", rain="NONE", ideal_h=-16.0, q=0.0003),
]
SPEC_BY_ID = {s["plot_id"]: s for s in PLOT_SPECS}
SIM_TRUTH = {"mu_dry": 0.30, "mu_fill": 0.30, "sp_constant": 1.5, "h_cap_cm": 15.0}   # "kebenaran" simulasi (bukan klaim lapangan)


def _seed_of(spec) -> str:
    return "demo-" + spec["plot_id"]


def spec_weather(plot_id: str, base=None) -> dict:
    """Pemaksa cuaca bawaan skenario petak (sintetis + hujan skenario). Dapat ditimpa pengguna.
    `base` = tanggal jangkar dataset (ISO); cuaca diindeks relatif terhadapnya."""
    s = SPEC_BY_ID.get(plot_id)
    if s is None:
        return dict(DEFAULT_WEATHER_FALLBACK, base=base)
    return {"driver": dw.DRIVER_SYNTHETIC, "profile": s["profile"], "seed": _seed_of(s), "rain": s["rain"], "base": base}


def default_weather(plot_id: str) -> dict:
    """Cuaca bawaan petak untuk dataset yang sedang dimuat (membaca jangkar dari meta)."""
    a = drepo.get_meta("anchor")
    base = datetime.fromisoformat(a).astimezone(TZ).date().isoformat() if a else None
    return spec_weather(plot_id, base)


DEFAULT_WEATHER_FALLBACK = {"driver": dw.DRIVER_SYNTHETIC, "profile": "NORMAL", "seed": "demo", "rain": "NONE"}


# ---------------------------------------------------------------------------------------------- profil
def profile_params(spec) -> list:
    pend = set(spec.get("pending", ()))
    base = [("area_ha", spec["area"], "ha"), ("mu_dry", SIM_TRUTH["mu_dry"], "–"), ("mu_fill", SIM_TRUTH["mu_fill"], "–"),
            ("lead_time_h", LEAD_H, "jam"), ("h_cap_cm", SIM_TRUTH["h_cap_cm"], "cm"),
            ("sp_constant", SIM_TRUTH["sp_constant"], "mm/hari"), ("q_plot_m3s", spec["q"], "m3/s")]
    for ph, (kc, trig, tgt) in PHASE_PARAMS.items():
        base += [(f"kc_{ph}", kc, "–"), (f"trigger_h_{ph}", trig, "cm"), (f"target_h_{ph}", tgt, "cm")]
    out = []
    for name, val, unit in base:
        if name in pend:
            out.append({"name": name, "value": None, "unit": unit, "status": "PENDING", "source": "belum diukur (skenario demo)"})
        else:
            out.append({"name": name, "value": val, "unit": unit, "status": "EXAMPLE",
                        "source": "Contoh demonstrasi — bukan hasil kalibrasi/pengukuran"})
    return out


def _profile_dict(spec, profile_id=1) -> dict:
    return {"profile_id": profile_id, "version": 1, "validation_status": "UNVALIDATED",
            "params": {p["name"]: p for p in profile_params(spec)},
            "phases": [{"phase": n, "from_das": a, "to_das": b, "protected": pr, "protocol_version": VERSION} for n, a, b, pr in PHASES]}


# ---------------------------------------------------------------------------------------------- simulasi riwayat h
def _et0(spec, d: date) -> float:
    tmin, tmax = dw.day_temps(d, spec["profile"], _seed_of(spec), spec.get("_base"))
    return et0lib.hargreaves_et0(tmin, tmax, spec["lat"], d.timetuple().tm_yday)["et0_mm_day"]


def _f_day(spec, d: date, ph="vegetatif") -> float:
    kc = PHASE_PARAMS[ph][0]
    return kc * _et0(spec, d) + SIM_TRUTH["sp_constant"]


def _phase_for_das(das: int) -> str:
    for n, a, b, _ in PHASES:
        if a <= das <= b:
            return n
    return PHASES[-1][0]


def simulate_history(spec: dict, anchor: datetime, h0: float, n_days: int = HIST_DAYS, hist_trigger: float = HIST_TRIGGER) -> dict:
    """Simulasi harian h (pengamatan tiap 24 jam, berakhir pada waktu pengamatan terakhir) dengan irigasi AWD.
    -> {"times": [...], "h": [...], "events": [{...}]}. Fungsi murni dari (spec, anchor, h0)."""
    last = anchor - timedelta(hours=spec["age_h"])
    times = [last - timedelta(days=n_days - k) for k in range(n_days + 1)]
    planting = (anchor.astimezone(TZ).date()) - timedelta(days=spec["das"])
    mu_d, mu_f, cap = SIM_TRUTH["mu_dry"], SIM_TRUTH["mu_fill"], SIM_TRUTH["h_cap_cm"]
    h, hs, events = float(h0), [], []
    for k, t in enumerate(times):
        hs.append(h)
        if k == n_days:
            break
        d_next = times[k + 1].astimezone(TZ).date()
        ph = _phase_for_das((d_next - planting).days)
        f = _f_day(spec, d_next, ph)
        trig, tgt = PHASE_PARAMS[ph][1], PHASE_PARAMS[ph][2]
        if h <= hist_trigger:
            h_arr, _ = pe.advance_h(h, f * LEAD_H / 24.0, mu_d, mu_f, cap)
            refill = pe.refill_requirement_mm(h_arr, tgt, mu_f)
            vol = pe.volume_m3(refill, spec["area"])
            dur = min(8.0, max(0.5, vol / (HIST_Q * 3600.0)))
            u = int(hashlib.sha256(f"{spec['plot_id']}|{k}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
            applied = refill * (0.95 + 0.10 * u)                       # realisasi sedikit berbeda dari rekomendasi
            h_after, _ = pe.advance_h(h_arr, -applied, mu_d, mu_f, cap)
            remain = max(0.0, 24.0 - LEAD_H - dur)
            h, _ = pe.advance_h(h_after, f * remain / 24.0, mu_d, mu_f, cap)
            events.append({"k": k, "decision_at": t, "arrival_at": t + timedelta(hours=LEAD_H), "dur_h": dur,
                           "refill_mm": refill, "applied_mm": applied, "vol_rec_m3": vol, "vol_actual_m3": pe.volume_m3(applied, spec["area"]),
                           "h_before": h_arr, "h_after": h_after, "trigger": trig, "target": tgt})
        else:
            h, _ = pe.advance_h(h, f, mu_d, mu_f, cap)
    return {"times": times, "h": hs, "events": events, "last_obs_at": last}


def _engine_check(spec, anchor, h_last, last_obs_at, rain=None, profile_override=None) -> dict:
    import demo_service as ds
    plot = {"plot_id": spec["plot_id"], "latitude": spec["lat"], "longitude": spec["lon"]}
    prof = profile_override or _profile_dict(spec)
    cycle = {"cycle_id": 1, "planting_date": anchor.astimezone(TZ).date() - timedelta(days=spec["das"])}
    h_obs = {"obs_id": 1, "value": h_last, "observed_at": last_obs_at, "received_at": last_obs_at}
    w = spec_weather(spec["plot_id"], spec.get("_base"))
    if rain is not None:
        w["rain"] = rain
    out, _ = ds.compute_pure(plot, prof, cycle, h_obs, anchor, w)
    return out


def _predicate(spec, anchor, sim) -> bool:
    hl, lo = sim["h"][-1], sim["last_obs_at"]
    out = _engine_check(spec, anchor, hl, lo)
    sc = spec["scenario"]
    if sc == "IRRIGATE":
        return (out["status"] == "OK" and out["irrigate"] is True and (out["total_mm"] or 0) > 0 and out["duration_h"] is not None
                and (out["trigger_h_cm"] - out["h_arrival_cm"]) >= 0.5)
    if sc == "SAFE":
        return out["status"] == "OK" and out["irrigate"] is False and (out["h_arrival_cm"] - out["trigger_h_cm"]) > 6.0
    if sc == "RAIN_HOLD":
        if not (out["status"] == "OK" and out["irrigate"] is False and (out["h_arrival_cm"] - out["trigger_h_cm"]) > 1.5):
            return False                                  # margin: tetap bertahan beberapa jam setelah jangkar
        dry = _engine_check(spec, anchor, hl, lo, rain="NONE")
        return dry["status"] == "OK" and dry["irrigate"] is True
    if sc == "STALE":
        return out["status"] == "STALE_OBSERVATION"
    if sc == "MISSING_PARAM":
        return out["status"] == "MISSING_PARAMETER"
    if sc == "NOT_REACHABLE":
        return out["status"] == "TARGET_NOT_REACHABLE" and out["irrigate"] is True
    raise ValueError(sc)


def find_history(spec: dict, anchor: datetime) -> dict:
    """Cari h awal pada kisi tetap sehingga keadaan akhir memenuhi skenario menurut MESIN. Deterministik."""
    best = None
    spec = dict(spec, _base=anchor.astimezone(TZ).date().isoformat())
    for trig in HIST_TRIGGERS:
        for h0 in H0_GRID:
            sim = simulate_history(spec, anchor, h0, hist_trigger=trig)
            if not _predicate(spec, anchor, sim):
                continue
            gap = abs(sim["h"][-1] - spec["ideal_h"])
            if best is None or gap < best[0] - 1e-12:
                best = (gap, h0, sim, trig)
    if best is None:
        raise RuntimeError(f"skenario {spec['scenario']} ({spec['plot_id']}) tidak dapat dicapai oleh mesin pada kisi h awal")
    best[2]["h0"], best[2]["hist_trigger"] = best[1], best[3]
    return best[2]


# ---------------------------------------------------------------------------------------------- baris data
def _noise(*key) -> float:
    return int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF - 0.5


def _interp(times, hs, t):
    if t <= times[0]:
        return hs[0]
    for i in range(len(times) - 1):
        if times[i] <= t <= times[i + 1]:
            w = (t - times[i]).total_seconds() / (times[i + 1] - times[i]).total_seconds()
            return hs[i] + w * (hs[i + 1] - hs[i])
    return hs[-1]


def build_rows(anchor: datetime, dataset_id: str) -> dict:
    """Semua baris seed (tanpa menulis). Murni dari (anchor, spesifikasi)."""
    rows = {k: [] for k in ("plots", "plot_profile_versions", "plot_parameters", "phase_rules", "crop_cycles", "observations",
                            "recommendation_runs", "decisions", "irrigation_events")}
    rec_id = dec_id = ev_id = 0
    reports = {}
    for idx, spec in enumerate(PLOT_SPECS, start=1):
        pid = spec["plot_id"]
        sim = find_history(spec, anchor)
        reports[pid] = {"scenario": spec["scenario"], "h0": sim["h0"], "h_last": round(sim["h"][-1], 2), "n_obs": len(sim["h"]),
                        "n_irrigations": len(sim["events"])}
        rows["plots"].append(dict(plot_id=pid, name=spec["name"], latitude=spec["lat"], longitude=spec["lon"], elevation_m=10.0,
                                  datum="SINTETIS", pipe_count=1, pipe_location="sintetis", soil_sensor_id=f"SIM-{pid}-SOIL",
                                  canal_sensor_id="SIM-CANAL-1", rain_source_id="SIM-RAIN-1", temp_source_id="SIM-TEMP-1",
                                  coordinate_source="SINTETIS (demo) — bukan lokasi lapangan", active=1, created_at=anchor,
                                  updated_at=anchor, dataset_id=dataset_id, scenario=spec["scenario"],
                                  note=SCENARIOS[spec["scenario"]]))
        rows["plot_profile_versions"].append(dict(profile_id=idx, plot_id=pid, version=1, effective_from=anchor - timedelta(days=HIST_DAYS + 5),
                                                  effective_to=None, approved_by="demo_seed", note="Profil contoh demonstrasi",
                                                  validation_status="UNVALIDATED", protocol_version=VERSION, created_at=anchor,
                                                  dataset_id=dataset_id, origin="SEED"))
        for p in profile_params(spec):
            rows["plot_parameters"].append(dict(profile_id=idx, name=p["name"], value=p["value"], unit=p["unit"], status=p["status"],
                                                source=p["source"], assessment_method="demo", checked_by="demo_seed", measured_at=None))
        for n, a, b, pr in PHASES:
            rows["phase_rules"].append(dict(profile_id=idx, phase=n, from_das=a, to_das=b, protected=1 if pr else 0, protocol_version=VERSION))
        rows["crop_cycles"].append(dict(cycle_id=idx, plot_id=pid, planting_date=anchor.astimezone(TZ).date() - timedelta(days=spec["das"]),
                                        variety="Contoh (sintetis)", active=1, created_by="demo_seed", created_at=anchor,
                                        dataset_id=dataset_id, origin="SEED"))
        # pengamatan h
        for t, h in zip(sim["times"], sim["h"]):
            rows["observations"].append(dict(plot_id=pid, variable="h_cm", value=round(h, 2), unit="cm", observed_at=t,
                                             received_at=t + timedelta(minutes=10), recorded_by="demo_seed", source_type="MANUAL",
                                             quality_flag="OK", note="data sintetis (demo)", record_status="ACTIVE", method="MANUAL",
                                             dataset_id=dataset_id, origin="SEED"))
        # sensor sintetis: kelembapan tanah (dari h), tinggi muka air saluran, hujan harian (nol: riwayat tanpa hujan)
        t0, t1 = sim["times"][0], anchor
        t = t0
        while t <= t1:
            hh = _interp(sim["times"], sim["h"], min(t, sim["last_obs_at"]))
            sm = max(20.0, min(60.0, 42.0 + 1.1 * hh + 0.8 * _noise(pid, "sm", t.isoformat())))
            canal = 1.30 + 0.12 * math.sin(t.timestamp() / 86400.0 * 2 * math.pi / 7) + 0.03 * _noise(pid, "cn", t.isoformat())
            for var, val, unit, sid in (("soil_moisture", sm, "%", f"SIM-{pid}-SOIL"), ("canal_level", canal, "m", "SIM-CANAL-1")):
                rows["observations"].append(dict(plot_id=pid, sensor_id=sid, variable=var, value=round(val, 3), unit=unit, observed_at=t,
                                                 received_at=t, recorded_by="demo_seed", source_type="SIMULATED", quality_flag="OK",
                                                 note="sensor sintetis (demo)", record_status="ACTIVE", method="SIMULATED",
                                                 dataset_id=dataset_id, origin="SEED"))
            t += timedelta(hours=6)
        d = t0.astimezone(TZ).date()
        while d <= anchor.astimezone(TZ).date():
            rows["observations"].append(dict(plot_id=pid, sensor_id="SIM-RAIN-1", variable="rainfall", value=0.0, unit="mm",
                                             observed_at=datetime(d.year, d.month, d.day, 23, 0, tzinfo=TZ), received_at=anchor,
                                             recorded_by="demo_seed", source_type="SIMULATED", quality_flag="OK",
                                             note="hujan sintetis (demo): tidak hujan", record_status="ACTIVE", method="SIMULATED",
                                             dataset_id=dataset_id, origin="SEED"))
            d += timedelta(days=1)
        # rantai historis: rekomendasi -> keputusan -> pelaksanaan (simulasi)
        for e in sim["events"]:
            rec_id += 1
            dec_id += 1
            ev_id += 1
            snap = {"is_demo": True, "plot_id": pid, "decision_at": e["decision_at"], "model": "M1", "seed_history": True}
            out = {"status": "OK", "irrigate": True, "total_mm": round(e["refill_mm"], 2), "volume_m3": round(e["vol_rec_m3"], 2),
                   "duration_h": round(e["dur_h"], 2),
                   "h_arrival_cm": round(e["h_before"] + 0.8 * _noise(pid, "pred", e["k"]), 2), "trigger_h_cm": e["trigger"],
                   "target_h_cm": e["target"], "run_mode": "DEMO", "model": "M1", "reasons": [], "issues": [], "path": []}
            rows["recommendation_runs"].append(dict(rec_id=rec_id, plot_id=pid, created_at=e["decision_at"], created_by="demo_seed",
                                                    decision_at=e["decision_at"], inputs_snapshot=snap, inputs_hash=inputs_hash(snap),
                                                    profile_id=idx, model_version=rs.MODEL_VERSION + "+DEMO", run_mode="DEMO",
                                                    status_code="OK", output=out, expires_at=e["decision_at"] + timedelta(hours=6),
                                                    status="DECIDED", decided_at=e["decision_at"] + timedelta(minutes=20),
                                                    decided_by="demo_operator", dataset_id=dataset_id, origin="SEED"))
            modify = (e["k"] % 4 == 3)
            op_mm = round(e["applied_mm"], 2)
            rows["decisions"].append(dict(id=dec_id, ts=e["decision_at"] + timedelta(minutes=20), username="demo_operator",
                                          decision="MODIFY" if modify else "APPROVE", recommended_mm=out["total_mm"],
                                          operator_mm=op_mm if modify else out["total_mm"], duration_h=out["duration_h"],
                                          note="keputusan sintetis (riwayat demo)", source="DEMO", rec_id=rec_id, plot_id=pid,
                                          record_status="ACTIVE", run_mode="DEMO", idempotency_key=f"seed-{pid}-{e['k']}",
                                          context={"simulation": True}, dataset_id=dataset_id, origin="SEED"))
            rows["irrigation_events"].append(dict(event_id=ev_id, plot_id=pid, decision_id=dec_id, rec_id=rec_id, arrived_at=e["arrival_at"],
                                                  started_at=e["arrival_at"], ended_at=e["arrival_at"] + timedelta(hours=e["dur_h"]),
                                                  actual_volume_m3=round(e["vol_actual_m3"], 2), actual_discharge_m3s=HIST_Q,
                                                  measurement_method="SIMULASI", h_before_cm=round(e["h_before"], 2),
                                                  h_after_cm=round(e["h_after"], 2), h_after_at=e["arrival_at"] + timedelta(hours=e["dur_h"] + 1),
                                                  note="[SIMULASI] pelaksanaan sintetis", recorded_by="demo_operator",
                                                  recorded_at=e["arrival_at"] + timedelta(hours=e["dur_h"] + 1), record_status="ACTIVE",
                                                  is_simulation=1, dataset_id=dataset_id, origin="SEED"))
    rows["_report"] = reports
    return rows


# ---------------------------------------------------------------------------------------------- operasi (hanya ruang demo)
def _anchor(now=None) -> datetime:
    t = now or datetime.now(timezone.utc)
    return t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _ds_id(anchor) -> str:
    return "demo-" + hashlib.sha256((VERSION + anchor.isoformat()).encode()).hexdigest()[:10]


def load(now=None) -> dict:
    """Muat data awal bila belum ada (idempoten: pemanggilan kedua tidak menggandakan)."""
    demo_mode.require("admin")
    if drepo.is_loaded():
        return {"status": "ALREADY_LOADED", "dataset_id": drepo.dataset_id()}
    return _write(now, "load")


def reset_initial(now=None) -> dict:
    """Kembalikan ke skenario awal: hapus SEMUA isi ruang demo (SQLite demo saja) lalu muat ulang."""
    demo_mode.require("admin")
    return _write(now, "reset")


def _write(now, why) -> dict:
    anchor = _anchor(now)
    ds = _ds_id(anchor)
    rows = build_rows(anchor, ds)                         # dihitung SEBELUM menghapus: gagal tidak merusak data lama
    report = rows.pop("_report")
    drepo.wipe(keep_models=False)
    for table in ("plots", "plot_profile_versions", "plot_parameters", "phase_rules", "crop_cycles", "observations",
                  "recommendation_runs", "decisions", "irrigation_events"):
        drepo.bulk_insert(table, rows[table])
    for k, v in (("dataset_id", ds), ("anchor", anchor.isoformat()), ("version", VERSION), ("seeded_at", datetime.now(timezone.utc).isoformat())):
        drepo.set_meta(k, v)
    drepo.audit(f"demo_{why}", f"dataset {ds}", demo_mode.actor_name())
    return {"status": "LOADED", "dataset_id": ds, "anchor": anchor.isoformat(), "report": report,
            "counts": {t: len(rows[t]) for t in rows}}


def clear(now=None) -> dict:
    """Kosongkan ruang demo (idempoten). Tidak menyentuh database operasional."""
    demo_mode.require("admin")
    drepo.wipe(keep_models=False)
    drepo.audit("demo_clear", "ruang demo dikosongkan", demo_mode.actor_name())
    return {"status": "CLEARED"}


def refresh_time(now=None) -> dict:
    """Geser seluruh waktu data demo agar 'sekarang' kembali selaras (mis. membuka demo di hari berbeda)."""
    demo_mode.require("admin")
    anchor_s = drepo.get_meta("anchor")
    if not anchor_s:
        return {"status": "EMPTY"}
    old = datetime.fromisoformat(anchor_s)
    new = _anchor(now)
    delta = new - old
    if abs(delta.total_seconds()) < 3600:
        return {"status": "UP_TO_DATE"}
    drepo.shift_times(delta)
    drepo.set_meta("anchor", new.isoformat())
    drepo.audit("demo_refresh_time", f"geser {delta}", demo_mode.actor_name())
    return {"status": "SHIFTED", "delta_hours": delta.total_seconds() / 3600.0}
