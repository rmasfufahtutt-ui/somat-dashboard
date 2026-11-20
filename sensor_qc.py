"""sensor_qc.py - QC pembacaan sensor dengan TINDAKAN eksplisit per flag (audit P2). Fungsi murni (pandas), tanpa Streamlit/DB.

Prinsip:
  * Flag TIDAK mengubah atau membuang nilai mentah. Nilai asli tetap tersimpan; flag menyatakan bagaimana nilai itu boleh dipakai.
  * Setiap kode punya (flag, tindakan). Tindakan menentukan pemakaian turunan:
        USE                         dipakai normal
        USE_WITH_WARNING            dipakai, tetapi ditandai di tampilan
        EXCLUDE_FROM_AUTOMATIC_USE  tidak dipakai dalam agregat/keputusan otomatis; tetap tampil dan dapat ditinjau
  * Ambang bawaan adalah batas FISIK GENERIK (bukan hasil kalibrasi perangkat); konfirmasi per perangkat sebelum dipakai di
    penelitian. Jenis tanpa batas yang pasti (mis. muka air saluran, datum/satuan belum ditetapkan) TIDAK diberi batas rentang.
  * QC berversi (H07): assess() = penilaian RETROSPEKTIF (memakai seluruh jendela, termasuk tetangga masa depan); assess_asof() =
    penilaian ONLINE (hanya informasi yang ada saat titik tiba). Hasil disimpan terpisah dari nilai mentah (tabel observation_qc).
  * Spike hanya dinilai untuk titik yang punya tetangga sebelum dan sesudah dalam celah waktu wajar; titik paling akhir tidak
    dapat diklasifikasi sebagai spike (belum ada pembanding) dan dibiarkan OK.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

FLAG_ORDER = {"OK": 0, "SUSPECT": 1, "BAD": 2}

# kode -> (flag, tindakan, teks EN, teks ID)
CODES = {
    "NO_VALUE": ("BAD", "EXCLUDE_FROM_AUTOMATIC_USE", "No numeric value", "Tidak ada nilai numerik"),
    "OUT_OF_RANGE": ("BAD", "EXCLUDE_FROM_AUTOMATIC_USE", "Outside the physical range", "Di luar rentang fisik"),
    "SPIKE": ("SUSPECT", "EXCLUDE_FROM_AUTOMATIC_USE", "Isolated jump (differs from both neighbours)",
              "Lonjakan terisolasi (berbeda dari kedua tetangga)"),
    "FLATLINE": ("SUSPECT", "USE_WITH_WARNING", "Identical value for too long (stuck sensor?)",
                 "Nilai sama terlalu lama (sensor macet?)"),
}
# tingkat sensor (bukan per titik)
SENSOR_CODES = {
    "STALE": ("EXCLUDE_FROM_AUTOMATIC_USE", "Latest valid reading is too old", "Pembacaan valid terakhir terlalu lama"),
    "LOW_COVERAGE": ("USE_WITH_WARNING", "Too few readings in the window", "Pembacaan di jendela terlalu sedikit"),
    "NO_DATA": ("EXCLUDE_FROM_AUTOMATIC_USE", "No valid reading", "Tidak ada pembacaan valid"),
}


@dataclass(frozen=True)
class Rule:
    lo: Optional[float] = None           # batas fisik bawah (None = tidak diperiksa)
    hi: Optional[float] = None
    max_jump: Optional[float] = None     # selisih antar bacaan berurutan yang dianggap lonjakan (satuan sensor)
    max_gap_h: float = 3.0               # celah waktu maksimum agar dua titik dianggap bertetangga
    flat_n: Optional[int] = None         # jumlah bacaan identik berurutan
    flat_hours: float = 6.0              # ... yang juga berlangsung minimal selama ini
    basis: str = "batas fisik generik — konfirmasi per perangkat"


DEFAULT_RULES = {
    "soil_moisture": Rule(lo=0.0, hi=100.0, max_jump=25.0, flat_n=12, flat_hours=6.0),
    "temperature": Rule(lo=-10.0, hi=60.0, max_jump=12.0, flat_n=12, flat_hours=6.0),
    "rainfall": Rule(lo=0.0, flat_n=None, basis="curah hujan tidak negatif; pembacaan nol berulang itu wajar"),
    "water_level": Rule(max_jump=None, flat_n=12, flat_hours=6.0,
                        basis="rentang belum ditetapkan: datum dan satuan muka air saluran belum final"),
}


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def assess(df: pd.DataFrame, rules: Optional[dict] = None) -> pd.DataFrame:
    """Tambahkan kolom qc_flag (OK/SUSPECT/BAD), qc_codes ('A,B'), qc_action (tindakan paling ketat). Nilai TIDAK diubah."""
    rules = rules or DEFAULT_RULES
    out = df.copy()
    n = len(out)
    codes = [[] for _ in range(n)]
    if n:
        out = out.reset_index(drop=True)
        ts = pd.to_datetime(out["timestamp"], errors="coerce")
        for (sid, stype), idx in out.groupby(["sensor_id", "sensor_type"], sort=False).groups.items():
            rule = rules.get(stype)
            order = sorted(idx, key=lambda i: (ts.iloc[i] if pd.notna(ts.iloc[i]) else pd.Timestamp.max))
            vals = [out["value"].iloc[i] for i in order]
            tms = [ts.iloc[i] for i in order]
            for k, i in enumerate(order):
                if not _is_num(vals[k]):
                    codes[i].append("NO_VALUE")
                elif rule and ((rule.lo is not None and vals[k] < rule.lo) or (rule.hi is not None and vals[k] > rule.hi)):
                    codes[i].append("OUT_OF_RANGE")
            if not rule:
                continue
            # SPIKE: terisolasi — berbeda > max_jump dari sebelum DAN sesudah, sedangkan sebelum~sesudah
            if rule.max_jump is not None:
                for k in range(1, len(order) - 1):
                    a, b, c = vals[k - 1], vals[k], vals[k + 1]
                    if not (_is_num(a) and _is_num(b) and _is_num(c)) or pd.isna(tms[k - 1]) or pd.isna(tms[k + 1]):
                        continue
                    if (tms[k] - tms[k - 1]).total_seconds() / 3600 > rule.max_gap_h or (tms[k + 1] - tms[k]).total_seconds() / 3600 > rule.max_gap_h:
                        continue
                    if abs(b - a) > rule.max_jump and abs(b - c) > rule.max_jump and abs(a - c) <= rule.max_jump / 2:
                        codes[order[k]].append("SPIKE")
            # FLATLINE: >= flat_n bacaan identik berurutan yang berlangsung >= flat_hours
            if rule.flat_n:
                k = 0
                while k < len(order):
                    j = k
                    while j + 1 < len(order) and _is_num(vals[k]) and _is_num(vals[j + 1]) and vals[j + 1] == vals[k]:
                        j += 1
                    run = j - k + 1
                    if run >= rule.flat_n and pd.notna(tms[k]) and pd.notna(tms[j]) \
                            and (tms[j] - tms[k]).total_seconds() / 3600 >= rule.flat_hours:
                        for m in range(k, j + 1):
                            codes[order[m]].append("FLATLINE")
                    k = j + 1
    flags, acts, joined = _summarize(codes)
    out["qc_flag"], out["qc_action"], out["qc_codes"] = flags, acts, joined
    return out


def rule_version(rules: Optional[dict] = None) -> str:
    """Versi aturan QC yang turun otomatis dari isi aturan: mengubah ambang mengubah versi (jejak audit H07)."""
    import hashlib
    rules = rules or DEFAULT_RULES
    canon = repr(sorted((k, (v.lo, v.hi, v.max_jump, v.max_gap_h, v.flat_n, v.flat_hours)) for k, v in rules.items()))
    return "qc-" + hashlib.sha256(canon.encode()).hexdigest()[:10]


def assess_asof(df: pd.DataFrame, rules: Optional[dict] = None) -> pd.DataFrame:
    """QC ONLINE: tiap titik dinilai HANYA dengan informasi yang sudah ada saat titik itu tiba (titik itu dan sebelumnya).
    Pemeriksaan yang butuh tetangga masa depan (SPIKE) tidak dapat dinilai: titik tetap OK sampai QC retrospektif.
    FLATLINE dinilai atas urutan identik yang BERAKHIR di titik itu. Kolom keluaran sama dengan assess()."""
    rules = rules or DEFAULT_RULES
    out = df.copy().reset_index(drop=True)
    codes = [[] for _ in range(len(out))]
    if len(out):
        ts = pd.to_datetime(out["timestamp"], errors="coerce")
        for (sid, stype), idx in out.groupby(["sensor_id", "sensor_type"], sort=False).groups.items():
            rule = rules.get(stype)
            order = sorted(idx, key=lambda i: (ts.iloc[i] if pd.notna(ts.iloc[i]) else pd.Timestamp.max))
            vals = [out["value"].iloc[i] for i in order]
            tms = [ts.iloc[i] for i in order]
            run_start = 0
            for k, i in enumerate(order):
                if not _is_num(vals[k]):
                    codes[i].append("NO_VALUE")
                elif rule and ((rule.lo is not None and vals[k] < rule.lo) or (rule.hi is not None and vals[k] > rule.hi)):
                    codes[i].append("OUT_OF_RANGE")
                if k == 0 or not (_is_num(vals[k]) and _is_num(vals[k - 1]) and vals[k] == vals[k - 1]):
                    run_start = k
                if rule and rule.flat_n and _is_num(vals[k]) and (k - run_start + 1) >= rule.flat_n \
                        and pd.notna(tms[k]) and pd.notna(tms[run_start]) \
                        and (tms[k] - tms[run_start]).total_seconds() / 3600 >= rule.flat_hours:
                    codes[i].append("FLATLINE")
    flags, acts, joined = _summarize(codes)
    out["qc_flag"], out["qc_action"], out["qc_codes"] = flags, acts, joined
    return out


def _summarize(codes: list) -> tuple:
    flags, acts, joined = [], [], []
    for c in codes:
        flags.append(max((CODES[x][0] for x in c), key=lambda f: FLAG_ORDER[f], default="OK"))
        acts.append("EXCLUDE_FROM_AUTOMATIC_USE" if any(CODES[x][1] == "EXCLUDE_FROM_AUTOMATIC_USE" for x in c) else
                    ("USE_WITH_WARNING" if c else "USE"))
        joined.append(",".join(dict.fromkeys(c)))
    return flags, acts, joined


def combine_flag(device_status, qc_flag: str) -> str:
    """Status perangkat dan flag QC digabung tanpa saling menimpa: status perangkat selain OK dipertahankan apa adanya
    (tidak diturunkan menjadi OK); bila perangkat OK, flag QC menjadi flag simpanan."""
    st = str(device_status or "OK").upper()
    if st != "OK":
        return st
    return qc_flag


def gate_for_decisions(df: pd.DataFrame, rules: Optional[dict] = None) -> tuple:
    """Salinan df untuk PERHITUNGAN OTOMATIS: baris berstatus OK yang tindakan QC-nya EXCLUDE_FROM_AUTOMATIC_USE diberi status
    "QC_EXCLUDED" sehingga tidak dihitung sebagai pembacaan valid (ringkasan, kualitas data, tren harian, status sensor). Nilai mentah
    tetap utuh dan df asli tidak diubah (tampilan mentah memakai df asli). -> (df_terseleksi, jumlah_baris_dikecualikan)."""
    if df is None or df.empty:
        return df, 0
    a = assess(df, rules)
    ex = (a["qc_action"] == "EXCLUDE_FROM_AUTOMATIC_USE") & (a["status"].fillna("").astype(str).str.upper() == "OK")
    out = df.copy().reset_index(drop=True)
    out.loc[ex.values, "status"] = "QC_EXCLUDED"
    return out, int(ex.sum())


def coverage_report(df: pd.DataFrame, sensors: list, now: pd.Timestamp, window_hours: float = 24.0,
                    min_coverage: float = 0.5) -> pd.DataFrame:
    """Per sensor: n_valid, n_expected, coverage, umur bacaan valid terakhir, kode tingkat-sensor dan tindakannya.
    sensors: [{sensor_id, sensor_type, expected_interval_min, offline_after_min}]. df harus hasil assess() (kolom qc_flag)."""
    rows = []
    d = df.copy() if df is not None else pd.DataFrame()
    if not d.empty:
        d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce")
    for s in sensors:
        sid = s["sensor_id"]
        interval = float(s.get("expected_interval_min", 30))
        offline_h = float(s.get("offline_after_min", 180)) / 60.0
        sub = d[d["sensor_id"] == sid] if not d.empty else d
        ok = sub[(sub["qc_flag"] == "OK") & (sub["status"].fillna("").astype(str).str.upper() == "OK")] if len(sub) else sub
        win = ok[ok["timestamp"] >= now - pd.Timedelta(hours=window_hours)] if len(ok) else ok
        expected = max(1.0, window_hours * 60.0 / interval)
        cov = min(1.0, len(win) / expected)
        last = ok["timestamp"].max() if len(ok) else pd.NaT
        age_h = None if pd.isna(last) else (now - last).total_seconds() / 3600.0
        codes = []
        if len(ok) == 0:
            codes.append("NO_DATA")
        else:
            if age_h > offline_h:
                codes.append("STALE")
            if cov < min_coverage:
                codes.append("LOW_COVERAGE")
        action = "USE"
        if any(SENSOR_CODES[c][0] == "EXCLUDE_FROM_AUTOMATIC_USE" for c in codes):
            action = "EXCLUDE_FROM_AUTOMATIC_USE"
        elif codes:
            action = "USE_WITH_WARNING"
        rows.append({"sensor_id": sid, "sensor_type": s.get("sensor_type", ""), "n_valid": int(len(win)),
                     "n_expected": round(expected, 1), "coverage": round(cov, 3), "last_valid": last,
                     "age_hours": None if age_h is None else round(age_h, 2), "codes": ",".join(codes), "action": action,
                     "n_suspect": int((sub["qc_flag"] == "SUSPECT").sum()) if len(sub) else 0,
                     "n_bad": int((sub["qc_flag"] == "BAD").sum()) if len(sub) else 0})
    return pd.DataFrame(rows)


def describe(code: str, lang: str = "en") -> str:
    if code in CODES:
        return CODES[code][2 if lang == "en" else 3]
    if code in SENSOR_CODES:
        return SENSOR_CODES[code][1 if lang == "en" else 2]
    return code
