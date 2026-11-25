"""Uji explain.py (tanpa database, tanpa Streamlit)."""
from datetime import datetime, timedelta, timezone

import pytest

import explain
import physics_engine as pe
import texts

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("mode", pe.RUN_MODES)
def test_setiap_run_mode_punya_ringkasan_dua_bahasa(mode):
    en, idn = explain.status_summary({"run_mode": mode})
    assert en.strip() and idn.strip() and en != idn


def test_setiap_run_mode_punya_label_di_texts():
    kurang = [m for m in pe.RUN_MODES if m not in texts.RUN_MODE]
    assert not kurang, f"run_mode tanpa label di texts.RUN_MODE: {kurang}"


@pytest.mark.parametrize("mode", pe.RUN_MODES)
def test_kata_validated_hanya_untuk_mode_tervalidasi(mode):
    en, idn = explain.status_summary({"run_mode": mode})
    teks = (en + " " + idn).lower()
    ada = "validat" in teks or "validasi" in teks
    assert ada == (mode in explain.VALIDATED_MODES), f"{mode}: {en} | {idn}"


def test_mode_tak_dikenal_tidak_mengklaim_apa_apa():
    en, idn = explain.status_summary({"run_mode": "ZZ_BARU"})
    assert "ZZ_BARU" in en and "ZZ_BARU" in idn
    assert "validat" not in (en + idn).lower()


def test_run_demo_selalu_berlabel_demo():
    en, idn = explain.status_summary({"run_mode": "DEMO"})
    assert "DEMO" in en and "DEMO" in idn


def test_missing_parameter_menyebut_parameter_yang_menunggu_saja():
    out = {"run_mode": "MANUAL_REQUIRED", "status": "MISSING_PARAMETER",
           "parameter_status": {"zz_param_menunggu": "PENDING", "zz_param_ok": "CALIBRATED"}}
    assert explain.pending_parameters(out) == ["zz_param_menunggu"]
    rs = dict(explain.hold_reasons(out))
    en, idn = rs["missing_parameter"]
    assert "zz_param_menunggu" in en and "zz_param_menunggu" in idn
    assert "zz_param_ok" not in en
    assert "not_decidable_status" in rs and "not_operational" in rs


def test_run_baseline_ok_tanpa_penghalang():
    out = {"run_mode": "BASELINE_PROVISIONAL", "status": "OK"}
    assert explain.hold_reasons(out) == []


def test_run_demo_memakai_aturan_demo_bukan_mode_operasional():
    out = {"run_mode": "DEMO", "status": "OK"}
    assert "not_operational" in dict(explain.hold_reasons(out))
    assert explain.hold_reasons(out, demo=True) == []
    out2 = {"run_mode": "DEMO", "status": "MISSING_PARAMETER"}
    assert "not_decidable_status" in dict(explain.hold_reasons(out2, demo=True))


def test_profil_berubah_menjadi_alasan():
    out = {"run_mode": "BASELINE_PROVISIONAL", "status": "OK"}
    assert "profile_changed" in dict(explain.hold_reasons(out, profile_changed=True))


def test_kode_penghalang_tak_dikenal_tetap_tampil():
    out = {"run_mode": "BASELINE_PROVISIONAL", "status": "OK"}
    rs = dict(explain.hold_reasons(out, inputs_changed=True))
    assert "inputs_changed" in rs and all(rs["inputs_changed"])


def test_isu_dikenal_dan_tak_dikenal_sama_sama_tampil():
    out = {"issues": [{"code": "NO_H_OBSERVATION"}, {"code": "ZZ_ISU_BARU"}]}
    res = explain.visible_issues(out)
    assert len(res) == 2
    assert res[0] == texts.ISSUE["NO_H_OBSERVATION"]
    assert "ZZ_ISU_BARU" in res[1][0] and "ZZ_ISU_BARU" in res[1][1]


def test_input_summary_menghitung_umur_h():
    snap = {"h_observation": {"value": -12.3, "observed_at": NOW - timedelta(hours=3)}}
    rows = explain.input_summary(snap, {}, now=NOW)
    h = [r for r in rows if r["label"][0] == "Last field h"][0]
    assert "-12.3 cm" in h["value"][0] and "age 3.0 h" in h["value"][0] and "umur 3.0 jam" in h["value"][1]


def test_input_summary_tanpa_zona_waktu_tidak_menebak_umur():
    snap = {"h_observation": {"value": -5, "observed_at": datetime(2026, 11, 24, 9, 0)}}
    h = explain.input_summary(snap, {}, now=NOW)[0]
    assert "age" not in h["value"][0] and "umur" not in h["value"][1]


def test_input_summary_tanpa_pengamatan():
    rows = explain.input_summary({}, {}, now=NOW)
    assert rows[0]["value"] == ("no observation", "belum ada pengamatan")


def test_input_summary_status_parameter_dan_profil():
    out = {"parameter_status": {"a": "CALIBRATED", "b": "PENDING", "c": "PENDING"}, "rain_scenario": "NO_RAIN_SCENARIO"}
    rows = {r["label"][0]: r["value"] for r in explain.input_summary({}, out, {"version": 3, "validation_status": "UNVALIDATED"}, now=NOW)}
    assert rows["Parameter status"][0] == "Calibrated: 1; Pending: 2"
    assert rows["Parameter status"][1] == "Terkalibrasi: 1; Menunggu: 2"
    assert rows["Parameter profile"][0] == "v3, UNVALIDATED"
    assert rows["Rain assumption"][0] == "NO_RAIN_SCENARIO"


def test_input_summary_tidak_memuat_nilai_parameter():
    out = {"parameter_status": {"diameter_pipa": "PENDING"}}
    teks = str(explain.input_summary({}, out, now=NOW))
    assert "diameter_pipa" not in teks


# ---- tahap lanjutan: isu tanpa deskripsi, duplikat status, parameter dari profil ----
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _kode_isu_dari_sumber():
    """Kode isu yang ditulis engine/service di kode sumber (pola fail(status, KODE, ...), {"code": KODE}, _manual(KODE, ...))."""
    pe_src = (_ROOT / "physics_engine.py").read_text(encoding="utf-8")
    v2 = pe_src[pe_src.index("def recommend_timed"):]
    svc = (_ROOT / "recommendation_service.py").read_text(encoding="utf-8")
    kode = set(re.findall(r'fail\(\s*"[A-Z_]+"\s*,\s*"([A-Z_]+)"', v2))
    kode |= set(re.findall(r'"code":\s*"([A-Z_]+)"', v2))
    kode |= set(re.findall(r'"code":\s*"([A-Z_]+)"', svc))
    kode |= set(re.findall(r'_manual\(\s*"([A-Z_]+)"', svc))
    return kode


def test_semua_kode_isu_engine_punya_teks():
    kode = _kode_isu_dari_sumber()
    assert len(kode) >= 10, f"pemindai kode isu tidak menemukan cukup kode: {sorted(kode)}"
    kurang = sorted(c for c in kode if c not in texts.ISSUE and c not in texts.STATUS)
    assert not kurang, f"kode isu tanpa teks di texts.ISSUE/STATUS: {kurang}"


def test_isu_sama_dengan_status_tidak_diulang_tetapi_isu_lain_tetap_tampil():
    out = {"status": "MISSING_PARAMETER",
           "issues": [{"code": "MISSING_PARAMETER"}, {"code": "NO_H_OBSERVATION"}, {"code": "ZZ_ISU_BARU"}]}
    res = explain.visible_issues(out)
    assert len(res) == 2
    assert res[0] == texts.ISSUE["NO_H_OBSERVATION"]
    assert "ZZ_ISU_BARU" in res[1][0]


def test_isu_tanpa_teks_isu_memakai_label_status():
    out = {"status": "OK", "issues": [{"code": "STALE_OBSERVATION"}]}
    assert explain.visible_issues(out) == [texts.STATUS["STALE_OBSERVATION"]]


def test_isu_menampilkan_nama_parameter():
    out = {"status": "INVALID_PARAMETER", "issues": [{"code": "OUT_OF_DOMAIN", "param": "mu_fill", "value": 9}]}
    en, idn = explain.visible_issues(out)[0]
    assert "[mu_fill]" in en and "[mu_fill]" in idn
    assert "9" not in en                       # nilai tidak ditampilkan, hanya nama parameter


def test_parameter_menunggu_diambil_dari_profil_bila_engine_belum_mengisi():
    out = {"run_mode": "MANUAL_REQUIRED", "status": "MISSING_PARAMETER", "parameter_status": {}}
    profile = {"params": {"mu_fill": {"status": "PENDING", "value": None}, "area_ha": {"status": "LITERATURE", "value": 1.0}}}
    assert explain.pending_parameters(out, profile) == ["mu_fill"]
    rs = dict(explain.hold_reasons(out, demo=True, profile=profile))
    en, idn = rs["missing_parameter"]
    assert "mu_fill" in en and "mu_fill" in idn and "area_ha" not in en


def test_status_run_di_engine_diutamakan_daripada_profil():
    out = {"status": "MISSING_PARAMETER", "parameter_status": {"a": "PENDING"}}
    profile = {"params": {"b": {"status": "PENDING"}}}
    assert explain.pending_parameters(out, profile) == ["a"]
