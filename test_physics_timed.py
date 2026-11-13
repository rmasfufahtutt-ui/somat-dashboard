"""Tes alur waktu eksplisit physics_engine (Grand Framework v2, bagian 6 dan 12)."""
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from physics_engine import (
    Param, PhaseRule, PlotProfile, Drivers, MissingDriver, recommend_timed, trajectory_timed, advance_h,
    application_duration, duration_hours, inflow_mm_day, evaluate_modification, classify_run_mode, validate_domain,
    OPERATIONAL_MODES, refill_requirement_mm, volume_m3,
)

TZ = ZoneInfo("Asia/Jakarta")
D1, D2, D3 = date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)


def at(d, hh=7, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


def P(v, s="LITERATURE"):
    return Param(v, s, "uji")


def make_profile(status="LITERATURE", lead=24.0, cap=None, q=None, valid="UNVALIDATED", sp=2.0, area=1.0):
    return PlotProfile("P1", area_ha=P(area, status), mu_dry=P(0.18, status), mu_fill=P(0.18, status),
                       lead_time_h=P(lead, status), h_cap_cm=P(cap, status) if cap else Param(),
                       sp_constant=P(sp, status) if sp is not None else Param(),
                       q_plot_m3s=P(q, status) if q else Param(), validation_status=valid)


RULE = PhaseRule(P(-15.0), P(5.0))
RULE_AT = lambda t: ("vegetatif", RULE)
KC_AT = lambda t: P(1.1)


def drivers(et0=None, kc=1.1):
    et0 = et0 or {D1: 4.5, D2: 4.5, D3: 4.5}
    return Drivers(et0_by_date=et0, kc_at=lambda t: kc, tz=TZ)


def run(**kw):
    base = dict(h_obs_cm=-12.0, observed_at=at(D1, 7), decision_at=at(D1, 7), drivers=drivers(),
                profile=make_profile(), rule_at=RULE_AT, kc_param_at=KC_AT, model="M1")
    base.update(kw)
    return recommend_timed(**base)


class Lintasan(unittest.TestCase):
    def test_satu_hari_sama_dengan_langkah_tunggal(self):
        f = 4.5 * 1.1 + 2.0
        r = run()
        expected, _ = advance_h(-12.0, f, 0.18, 0.18)
        self.assertEqual(r["status"], "OK")
        self.assertAlmostEqual(r["h_arrival_cm"], expected, places=6)

    def test_pergantian_tanggal_lokal_memakai_et0_masing_masing(self):
        # 07:00 -> 07:00 hari berikutnya: 17 jam tanggal D1 (ET0=3) + 7 jam tanggal D2 (ET0=6)
        et0 = {D1: 3.0, D2: 6.0, D3: 6.0}
        r = run(drivers=drivers(et0))
        f1, f2 = 3.0 * 1.1 + 2.0, 6.0 * 1.1 + 2.0
        h = -12.0
        h, _ = advance_h(h, f1 * 17 / 24, 0.18, 0.18)
        h, _ = advance_h(h, f2 * 7 / 24, 0.18, 0.18)
        self.assertAlmostEqual(r["h_arrival_cm"], h, places=6)

    def test_sore_melewati_tengah_malam_masuk_tanggal_benar(self):
        # keputusan 22:00, L=6 jam -> 2 jam di D1, 4 jam di D2
        et0 = {D1: 3.0, D2: 6.0}
        r = run(observed_at=at(D1, 22), decision_at=at(D1, 22), profile=make_profile(lead=6.0), drivers=drivers(et0))
        f1, f2 = 3.0 * 1.1 + 2.0, 6.0 * 1.1 + 2.0
        h, _ = advance_h(-12.0, f1 * 2 / 24, 0.18, 0.18)
        h, _ = advance_h(h, f2 * 4 / 24, 0.18, 0.18)
        self.assertAlmostEqual(r["h_arrival_cm"], h, places=6)

    def test_selang_pengamatan_ke_keputusan_diperhitungkan(self):
        r0 = run(observed_at=at(D1, 7), decision_at=at(D1, 7))
        r12 = run(observed_at=at(D1, 7), decision_at=at(D1, 19))
        self.assertAlmostEqual(r12["propagated_hours"], 12.0)
        self.assertLess(r12["h_decision_cm"], -12.0)
        self.assertLess(r12["h_arrival_cm"], r0["h_arrival_cm"])        # 12 jam tambahan kehilangan

    def test_hari_et0_hilang_tidak_dilewati(self):
        r = run(drivers=drivers({D1: 4.5, D2: None}))
        self.assertEqual(r["status"], "INCOMPLETE_FORECAST")
        self.assertEqual(r["run_mode"], "MANUAL_REQUIRED")
        self.assertIsNone(r["h_arrival_cm"])
        r2 = run(drivers=drivers({D1: 4.5}))              # kunci tanggal hilang sama dengan None
        self.assertEqual(r2["status"], "INCOMPLETE_FORECAST")

    def test_pergantian_fase_memotong_interval(self):
        # Kc 1.0 sebelum 19:00 D1, 1.4 sesudahnya; breaks harus memotong tepat pada 19:00
        boundary = at(D1, 19)
        kc_at = lambda t: 1.0 if t < boundary else 1.4
        d = Drivers(et0_by_date={D1: 5.0, D2: 5.0}, kc_at=kc_at, tz=TZ)
        d.r_adj = 0.0
        h, _, path = trajectory_timed(-12.0, at(D1, 7), at(D1, 23), d.f_at, 0.18, 0.18, breaks=[boundary])
        manual = -12.0
        manual, _ = advance_h(manual, 5.0 * 1.0 * 12 / 24, 0.18, 0.18)
        manual, _ = advance_h(manual, 5.0 * 1.4 * 4 / 24, 0.18, 0.18)
        self.assertAlmostEqual(h, manual, places=6)

    def test_waktu_tanpa_zona_ditolak(self):
        with self.assertRaises(ValueError):
            run(observed_at=datetime(2026, 11, 13, 7), decision_at=datetime(2026, 11, 13, 7))


class Pengisian(unittest.TestCase):
    def test_durasi_piecewise_sama_dengan_rumus_laju_konstan(self):
        q = 0.02
        f = 5.0
        need = 67.55
        d, why = application_duration(at(D1, 7), need, q, 1.0, lambda t: f)
        self.assertIsNone(why)
        v = volume_m3(need, 1.0)
        self.assertAlmostEqual(d, duration_hours(v, q, 1.0, f), places=6)

    def test_durasi_melintasi_hari_dengan_f_berubah(self):
        # F=2 mm/hari sampai tengah malam, 10 mm/hari sesudahnya
        def f_at(t):
            return 2.0 if t.astimezone(TZ).date() == D1 else 10.0
        inflow = inflow_mm_day(0.02, 1.0)
        need = 50.0
        d, _ = application_duration(at(D1, 20), need, 0.02, 1.0, f_at)
        # integral manual: 4 jam pertama (20:00-24:00) net=inflow-2, sisanya net=inflow-10
        first = (inflow - 2.0) * 4 / 24
        self.assertGreater(need, first)
        rest = (need - first) / (inflow - 10.0) * 24
        self.assertAlmostEqual(d, 4 + rest, places=4)

    def test_debit_tidak_cukup(self):
        d, why = application_duration(at(D1, 7), 50.0, 0.0001, 1.0, lambda t: 5.0)
        self.assertIsNone(d)
        self.assertEqual(why, "TARGET_NOT_REACHABLE")

    def test_horizon_et0_tidak_cukup(self):
        def f_at(t):
            if t.astimezone(TZ).date() > D1:
                raise MissingDriver(t)
            return 1.0
        d, why = application_duration(at(D1, 20), 500.0, 0.02, 1.0, f_at)
        self.assertEqual(why, "UNSUPPORTED_HORIZON")

    def test_rekomendasi_dengan_debit_konsisten_volume(self):
        r = run(profile=make_profile(q=0.02))
        self.assertEqual(r["status"], "OK")
        self.assertTrue(r["irrigate"])
        self.assertAlmostEqual(r["volume_m3"], 0.02 * r["duration_h"] * 3600, places=6)
        self.assertAlmostEqual(r["total_mm"], r["volume_m3"] / 10.0, places=6)
        self.assertGreater(r["total_mm"], r["refill_mm"])
        self.assertEqual(r["end_at"], r["arrival_at"] + timedelta(hours=r["duration_h"]))

    def test_tanpa_debit_petak_tidak_ada_durasi(self):
        r = run()
        self.assertIsNone(r["duration_h"])
        self.assertAlmostEqual(r["volume_m3"], 10.0 * r["refill_mm"])
        self.assertTrue(any(i["code"] == "DURATION_NEEDS_PLOT_DISCHARGE" for i in r["issues"]))

    def test_debit_kecil_target_tidak_tercapai(self):
        long_et0 = {D1 + timedelta(days=i): 4.5 for i in range(10)}
        r = run(profile=make_profile(q=0.0001), drivers=drivers(long_et0))
        self.assertEqual(r["status"], "TARGET_NOT_REACHABLE")
        self.assertIsNone(r["duration_h"])

    def test_debit_kecil_horizon_pendek_tidak_diklaim_mustahil(self):
        r = run(profile=make_profile(q=0.0001))           # ET0 hanya sampai D3: belum bisa menyimpulkan
        self.assertEqual(r["status"], "OK")
        self.assertIsNone(r["duration_h"])
        self.assertTrue(any(i["code"] == "UNSUPPORTED_HORIZON" for i in r["issues"]))

    def test_tidak_perlu_irigasi(self):
        r = run(h_obs_cm=3.0, drivers=drivers({D1: 2.0, D2: 2.0}))
        self.assertFalse(r["irrigate"])
        self.assertIsNone(r["volume_m3"])


class Gerbang(unittest.TestCase):
    def test_tanpa_pengamatan(self):
        r = run(h_obs_cm=None, observed_at=None)
        self.assertEqual((r["status"], r["run_mode"]), ("NEEDS_FIELD_OBSERVATION", "MANUAL_REQUIRED"))

    def test_pengamatan_masa_depan_dan_basi(self):
        self.assertEqual(run(observed_at=at(D1, 9))["status"], "INVALID_OBSERVATION")
        self.assertEqual(run(observed_at=at(D1, 7) - timedelta(hours=31), decision_at=at(D1, 7))["status"], "STALE_OBSERVATION")

    def test_parameter_pending_tidak_ditebak(self):
        prof = make_profile()
        prof = PlotProfile(prof.plot_id, area_ha=prof.area_ha, lead_time_h=prof.lead_time_h, sp_constant=prof.sp_constant)
        r = run(profile=prof)
        self.assertEqual(r["status"], "MISSING_PARAMETER")
        self.assertIn("mu_dry", r["issues"][-1]["params"])

    def test_sp_constant_pending_menghambat_m1_tetapi_tidak_m0(self):
        self.assertEqual(run(profile=make_profile(sp=None))["status"], "MISSING_PARAMETER")
        r0 = run(profile=make_profile(sp=None), model="M0")
        self.assertEqual(r0["status"], "OK")

    def test_fase_belum_di_protokol(self):
        self.assertEqual(run(rule_at=lambda t: (None, None))["status"], "PROTOCOL_REQUIRED")

    def test_domain_tidak_sah(self):
        bad = make_profile()
        bad = PlotProfile("P1", area_ha=bad.area_ha, mu_dry=P(1.5), mu_fill=bad.mu_fill, lead_time_h=bad.lead_time_h,
                          sp_constant=bad.sp_constant)
        self.assertEqual(run(profile=bad)["status"], "INVALID_PARAMETER")
        bad_rule = PhaseRule(P(5.0), P(-5.0))                # target di bawah pemicu
        self.assertEqual(run(rule_at=lambda t: ("v", bad_rule))["status"], "INVALID_PARAMETER")
        nan_area = PlotProfile("P1", area_ha=P(float("nan")), mu_dry=P(0.2), mu_fill=P(0.2), lead_time_h=P(24.0),
                               sp_constant=P(2.0))
        self.assertEqual(run(profile=nan_area)["status"], "INVALID_PARAMETER")

    def test_target_di_atas_pematang_ditandai(self):
        issues = validate_domain(make_profile(cap=3.0), P(1.1), RULE)
        self.assertTrue(any(i["code"] == "TARGET_ABOVE_CAP" for i in issues))


class ModeRun(unittest.TestCase):
    def test_example_adalah_demo(self):
        self.assertEqual(run(profile=make_profile(status="EXAMPLE"))["run_mode"], "DEMO")

    def test_sumber_dummy_adalah_demo(self):
        self.assertEqual(run(inputs_dummy=True)["run_mode"], "DEMO")

    def test_literatur_tanpa_validasi_provisional(self):
        r = run()
        self.assertEqual(r["run_mode"], "BASELINE_PROVISIONAL")
        self.assertTrue(r["provisional"])
        self.assertIn(r["run_mode"], OPERATIONAL_MODES)

    def test_terkalibrasi_dan_divalidasi(self):
        r = run(profile=make_profile(status="CALIBRATED", valid="VALIDATED"))
        self.assertEqual(r["run_mode"], "BASELINE_VALIDATED")
        self.assertFalse(r["provisional"])

    def test_terkalibrasi_tanpa_status_validasi_tetap_provisional(self):
        r = run(profile=make_profile(status="CALIBRATED"))
        self.assertEqual(r["run_mode"], "BASELINE_PROVISIONAL")

    def test_klasifikasi_langsung(self):
        self.assertEqual(classify_run_mode("MISSING_PARAMETER", {}), "MANUAL_REQUIRED")
        self.assertEqual(classify_run_mode("OK", {"a": "EXAMPLE"}), "DEMO")


class Modifikasi(unittest.TestCase):
    def setUp(self):
        self.prof = make_profile(cap=8.0, q=0.02)
        self.rec = run(profile=self.prof)

    def test_jumlah_sama_ditolak(self):
        r = evaluate_modification(self.rec, self.prof, self.rec["total_mm"] + 0.04, 0.02)
        self.assertFalse(r["valid"])
        self.assertEqual(r["issues"][0]["code"], "AMOUNT_UNCHANGED")

    def test_jumlah_berubah_dihitung_ulang(self):
        new = self.rec["total_mm"] - 10.0
        r = evaluate_modification(self.rec, self.prof, new, 0.02)
        self.assertTrue(r["valid"])
        self.assertAlmostEqual(r["volume_m3"], 10.0 * new)
        self.assertAlmostEqual(r["duration_h"], 10.0 * new / (0.02 * 3600))
        self.assertTrue(r["duration_verified"])

    def test_melebihi_pematang_diblokir(self):
        r = evaluate_modification(self.rec, self.prof, self.rec["total_mm"] + 500.0, 0.02)
        self.assertIn("EXCEEDS_CAP", [i["code"] for i in r["issues"]])

    def test_durasi_tidak_konsisten_dengan_debit(self):
        new = self.rec["total_mm"] - 10.0
        good = 10.0 * new / (0.02 * 3600)
        r = evaluate_modification(self.rec, self.prof, new, 0.02, duration_h=good * 2)
        self.assertIn("DURATION_INCONSISTENT", [i["code"] for i in r["issues"]])

    def test_tanpa_debit_durasi_tidak_terverifikasi(self):
        new = self.rec["total_mm"] - 10.0
        r = evaluate_modification(self.rec, self.prof, new, None, duration_h=3.0)
        self.assertTrue(r["valid"])
        self.assertFalse(r["duration_verified"])

    def test_nilai_negatif_dan_nan(self):
        for bad in (-1.0, float("nan")):
            self.assertFalse(evaluate_modification(self.rec, self.prof, bad, 0.02)["valid"])


if __name__ == "__main__":
    unittest.main()
