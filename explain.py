"""Penjelasan rekomendasi (explainability). Fungsi murni tanpa Streamlit.

Teks dikembalikan sebagai pasangan (Inggris, Indonesia); tampilan memakainya lewat L(*pasangan).
Modul ini TIDAK mengubah perhitungan: hanya menyusun ulang apa yang sudah dihasilkan engine agar mudah
dibaca operator dan ditelusuri penguji. Kata "validated/tervalidasi" hanya dipakai untuk run_mode yang memang tervalidasi.
"""
from datetime import datetime, timezone

import physics_engine as pe
import texts

VALIDATED_MODES = ("BASELINE_VALIDATED", "ML_VALIDATED")

_SUMMARY = {
    "DEMO": ("DEMO run: example inputs only. It cannot be decided operationally.",
             "Run DEMO: hanya masukan contoh. Tidak dapat diputuskan secara operasional."),
    "BASELINE_PROVISIONAL": ("Provisional baseline: some parameters are not yet calibrated or approved. "
                             "Treat it as decision support and check in the field.",
                             "Baseline sementara: sebagian parameter belum dikalibrasi atau disetujui. "
                             "Anggap sebagai pendukung keputusan dan cek di lapangan."),
    "BASELINE_VALIDATED": ("Validated baseline: the parameter profile is approved by the reviewer and no parameter is pending.",
                           "Baseline tervalidasi: profil parameter sudah disetujui pemeriksa dan tidak ada parameter yang menunggu."),
    "ML_SHADOW": ("ML shadow run: shown for comparison only, not used for decisions.",
                  "Run ML bayangan: hanya pembanding, tidak dipakai untuk keputusan."),
    "ML_VALIDATED": ("ML run marked as validated in the system configuration.",
                     "Run ML yang ditandai tervalidasi pada konfigurasi sistem."),
    "MANUAL_REQUIRED": ("Manual handling required: this run cannot be published for decision. See the reasons below.",
                        "Perlu penanganan manual: run ini tidak dapat diterbitkan untuk keputusan. Lihat alasan di bawah."),
}


def status_summary(out: dict) -> tuple:
    """Satu kalimat (en, id) tentang status run. Tidak pernah menyebut 'validated' untuk mode yang belum tervalidasi."""
    mode = (out or {}).get("run_mode", "MANUAL_REQUIRED")
    if mode in _SUMMARY:
        return _SUMMARY[mode]
    return (f"Unrecognised run mode: {mode}.", f"Mode run tidak dikenal: {mode}.")


def pending_parameters(out: dict, profile: dict = None) -> list:
    """Nama parameter yang masih PENDING (menunggu pengukuran/kalibrasi), terurut.
    Sumber utama: out['parameter_status']; jika kosong (engine berhenti sebelum mengisinya), pakai profil petak."""
    ps = (out or {}).get("parameter_status") or {}
    names = [str(k) for k, v in ps.items() if v == "PENDING"]
    if not ps and profile:
        names = [str(k) for k, p in (profile.get("params") or {}).items()
                 if isinstance(p, dict) and p.get("status") == "PENDING"]
    return sorted(names)


def hold_reasons(out: dict, *, demo: bool = False, expired: bool = False, inputs_changed: bool = False,
                 profile_changed: bool = False, profile: dict = None) -> list:
    """Alasan run tidak dapat diterbitkan untuk keputusan: daftar (kode, (en, id)). Kosong = tidak ada penghalang.
    demo=True: run simulasi diterbitkan lewat aturan demo, jadi pemeriksaan mode operasional dilewati."""
    out = out or {}
    mode = "BASELINE_PROVISIONAL" if demo else out.get("run_mode", "MANUAL_REQUIRED")
    codes = pe.decision_blockers(run_mode=mode, status_code=out.get("status"), expired=expired,
                                 inputs_changed=inputs_changed, profile_changed=profile_changed)
    rows = []
    for c in codes:
        rows.append((c, texts.DECISION_ERR.get(c, (c, c))))
    if out.get("status") == "MISSING_PARAMETER":
        pend = pending_parameters(out, profile)
        if pend:
            names = ", ".join(pend)
            rows.append(("missing_parameter",
                         (f"Parameters awaiting measurement/calibration: {names}.",
                          f"Parameter menunggu pengukuran/kalibrasi: {names}.")))
    return rows


def visible_issues(out: dict) -> list:
    """Isu run sebagai (en, id). Isu berkode tak dikenal TIDAK disembunyikan: ditampilkan apa adanya.
    Dilewati hanya isu yang kodenya sama dengan status run (sudah tampil di banner status).
    Teks: texts.ISSUE, lalu texts.STATUS, lalu kode mentah. Nama parameter (bila ada) ditambahkan."""
    out = out or {}
    res = []
    for i in out.get("issues") or []:
        code = i.get("code") if isinstance(i, dict) else str(i)
        if code == out.get("status"):
            continue
        txt = texts.ISSUE.get(code) or texts.STATUS.get(code)
        if not txt:
            txt = (f"{code} (no description available)", f"{code} (belum ada deskripsi)")
        param = i.get("param") if isinstance(i, dict) else None
        if param:
            txt = (f"{txt[0]} [{param}]", f"{txt[1]} [{param}]")
        res.append(txt)
    return res


def _to_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _age_hours(observed_at, now=None):
    dt = _to_dt(observed_at)
    if dt is None or dt.tzinfo is None:        # tanpa zona waktu: umur tidak dihitung, tidak ditebak
        return None
    now = now or datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def _fmt_dt(v):
    dt = _to_dt(v)
    if dt is None:
        return str(v)
    return dt.strftime("%Y-%m-%d %H:%M %z").strip() if dt.tzinfo else dt.strftime("%Y-%m-%d %H:%M")


def _num(v):
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return str(v)


def _same(s):
    return (s, s)


def input_summary(snapshot: dict, out: dict, profile: dict = None, now=None) -> list:
    """Input yang dipakai run ini: daftar {'label': (en, id), 'value': (en, id)}. Hanya yang tersedia yang ditampilkan."""
    snapshot, out = snapshot or {}, out or {}
    rows = []

    h = snapshot.get("h_observation")
    if h:
        age = _age_hours(h.get("observed_at"), now)
        age_en = f", age {age:.1f} h" if age is not None else ""
        age_id = f", umur {age:.1f} jam" if age is not None else ""
        v = _num(h.get("value"))
        when = _fmt_dt(h.get("observed_at"))
        rows.append({"label": ("Last field h", "h lapangan terakhir"),
                     "value": (f"{v} cm, observed {when}{age_en}",
                               f"{v} cm, diamati {when}{age_id}")})
    else:
        rows.append({"label": ("Last field h", "h lapangan terakhir"), "value": ("no observation", "belum ada pengamatan")})

    fc = snapshot.get("forecast")
    if isinstance(fc, dict) and fc.get("issued_at"):
        rows.append({"label": ("Forecast issued", "Prakiraan diterbitkan"), "value": _same(str(fc["issued_at"]))})
    w = snapshot.get("weather")
    if isinstance(w, dict) and w.get("label"):
        rows.append({"label": ("Temperature source (DEMO)", "Sumber suhu (DEMO)"), "value": _same(str(w["label"]))})

    if snapshot.get("et0_daily"):
        rows.append({"label": ("ET0 method", "Metode ET0"),
                     "value": ("HS_v1 (Hargreaves-Samani) from forecast temperature",
                               "HS_v1 (Hargreaves-Samani) dari suhu prakiraan")})

    if out.get("rain_scenario"):
        note = f" - {out['rain_note']}" if out.get("rain_note") else ""
        rows.append({"label": ("Rain assumption", "Asumsi hujan"), "value": _same(f"{out['rain_scenario']}{note}")})

    if profile:
        rows.append({"label": ("Parameter profile", "Profil parameter"),
                     "value": _same(f"v{profile.get('version')}, {profile.get('validation_status')}")})

    ps = out.get("parameter_status") or {}
    if ps:
        counts = {}
        for s in ps.values():
            counts[s] = counts.get(s, 0) + 1
        en, idn = [], []
        for s in sorted(counts):
            lab = texts.PARAM_STATUS.get(s, (s, s))
            en.append(f"{lab[0]}: {counts[s]}")
            idn.append(f"{lab[1]}: {counts[s]}")
        rows.append({"label": ("Parameter status", "Status parameter"), "value": ("; ".join(en), "; ".join(idn))})
    return rows
