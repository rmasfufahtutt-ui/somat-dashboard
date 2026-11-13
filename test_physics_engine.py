"""Tes physics_engine.py. Jalankan: python -m unittest test_physics_engine -v"""
import math
import unittest
from datetime import datetime, timedelta

from physics_engine import (
    Param, PhaseRule, PlotProfile, storage_mm, h_from_storage, advance_h, net_loss_mm_day, trajectory,
    refill_requirement_mm, volume_m3, duration_hours, window_residual, update_bias, r_adj_for_model, recommend,
)

NOW = datetime(2026, 11, 13, 7, 0)


def profile(mu_dry=0.18, mu_fill=0.18, status="EXAMPLE", lead_h=24.0, with_rule=True, area=1.0, cap=None):
    P = lambda v, s=status: Param(v, s, "uji")
    rules = {"vegetatif": PhaseRule(P(-15.0, "LITERATURE"), P(5.0, "LITERATURE"))} if with_rule else {}
    return PlotProfile("P1", area_ha=P(area), mu_dry=P(mu_dry), mu_fill=P(mu_fill), lead_time_h=P(lead_h),
                       h_cap_cm=P(cap, status) if cap is not None else Param(), phases=rules)


class SpecExamples(unittest.TestCase):
    def test_contoh_46(self):                       # bagian 4.6 dokumen
        F = net_loss_mm_day(4.95, 2.00, 1.00)
        self.assertAlmostEqual(F, 5.95)
        h1, ov = advance_h(-12.0, F, 0.18, 0.18)
        self.assertAlmostEqual(h1, -15.31, places=2)
        self.assertAlmostEqual(refill_requirement_mm(h1, 4.0, 0.18), 67.55, places=2)
        self.assertEqual(ov, 0.0)

    def test_kriteria_4_melintasi_nol(self):        # h=+1 cm, kehilangan 15 mm, mu=0,2 -> -2,5 cm (bukan -0,5)
        h, _ = advance_h(1.0, 15.0, 0.2, 0.2)
        self.assertAlmostEqual(h, -2.5)

    def test_kriteria_5_refill(self):               # h=-10 ke +4, mu_fill=0,2 -> 60 mm (bukan 140)
        self.assertAlmostEqual(refill_requirement_mm(-10.0, 4.0, 0.2), 60.0)

    def test_kriteria_6_volume(self):               # 10 mm pada 0,1 ha = 10 m3
        self.assertAlmostEqual(volume_m3(10.0, 0.1), 10.0)

    def test_durasi_laju_konstan(self):
        d = duration_hours(675.5, 0.02, 1.0, 5.0)
        self.assertAlmostEqual(d, 9.66, places=2)
        # Q*D = V_refill + kehilangan selama D (konsisten, tidak dihitung dua kali)
        q_d = 0.02 * d * 3600
        loss = 1.0 * 10000 * 5.0 / 1000 / 86400 * d * 3600
        self.assertAlmostEqual(q_d, 675.5 + loss, places=3)

    def test_durasi_tak_tercapai(self):
        self.assertIsNone(duration_hours(100.0, 0.0001, 1.0, 5.0))


class Fisika(unittest.TestCase):
    def test_storage_roundtrip(self):
        for h in (-20, -3.3, 0, 2.5, 7):
            self.assertAlmostEqual(h_from_storage(storage_mm(h, 0.2), 0.2), h)

    def test_pengisian_memakai_mu_fill(self):
        h, _ = advance_h(-10.0, -20.0, 0.18, 0.25)      # tambah 20 mm
        self.assertAlmostEqual(h, -20.0 / 20 * 0 + (10 * 0.25 * -10 + 20) / (10 * 0.25))
        self.assertAlmostEqual(h, -2.0)

    def test_pengisian_melintasi_nol(self):
        h, _ = advance_h(-2.0, -25.0, 0.2, 0.2)         # S=-4 -> +21 -> h=2,1
        self.assertAlmostEqual(h, 2.1)

    def test_luapan_dicatat_bukan_dihilangkan(self):
        h, ov = advance_h(4.0, -30.0, 0.2, 0.2, h_cap_cm=5.0)   # seharusnya +7 cm
        self.assertAlmostEqual(h, 5.0)
        self.assertAlmostEqual(ov, 20.0)

    def test_trajektori_satu_hari_sama_dengan_satu_langkah(self):
        h, ov, path = trajectory(-12.0, [5.95], 24, 0.18, 0.18)
        self.assertAlmostEqual(h, -15.31, places=2)
        self.assertEqual(len(path), 25)

    def test_horizon_terlampaui(self):
        with self.assertRaises(ValueError):
            trajectory(-5.0, [4.0, 4.0], 49, 0.18, 0.18)


class LabelDanBias(unittest.TestCase):
    def test_label_jendela_kering(self):
        r = window_residual(-4.0, -9.0, 2.0, 4.0, 0.2)   # 10*0,2*5/2 - 4 = 1,0
        self.assertTrue(r["valid"]); self.assertAlmostEqual(r["r_mm_day"], 1.0); self.assertAlmostEqual(r["mu_eff"], 0.2)

    def test_label_tergenang_mu_1(self):
        r = window_residual(5.0, 2.0, 3.0, 4.0, 0.2)     # 10*1*3/3 - 4 = 6
        self.assertAlmostEqual(r["r_mm_day"], 6.0); self.assertEqual(r["mu_eff"], 1.0)

    def test_jendela_melintasi_nol_tidak_valid(self):
        self.assertFalse(window_residual(2.0, -3.0, 2.0, 4.0, 0.2)["valid"])

    def test_label_negatif_tidak_dipotong(self):
        r = window_residual(-4.0, -5.0, 2.0, 4.95, 0.18)  # 10*0,18*1/2 - 4,95 < 0
        self.assertLess(r["r_mm_day"], 0); self.assertTrue(r["negative_label_review"])

    def test_bias(self):
        b, e = update_bias(1.0, 2.0, r_observed=3.0, r_base_prior=2.0, alpha=0.3, lam=0.1, bmax=2.0)
        self.assertAlmostEqual(e, 1.0)
        self.assertAlmostEqual(b, 0.7 * math.exp(-0.2) + 0.3 * 1.0)

    def test_bias_dibatasi(self):
        b, _ = update_bias(0.0, 0.0, 100.0, 0.0, 1.0, 0.0, 1.5)
        self.assertEqual(b, 1.5)

    def test_m2_tidak_menambah_spconstant(self):
        self.assertEqual(r_adj_for_model("M2", sp_constant=2.0, bias=0.5, ml_residual=1.0), 1.5)
        self.assertEqual(r_adj_for_model("M1B", sp_constant=2.0, bias=0.5), 2.5)
        self.assertEqual(r_adj_for_model("M0", sp_constant=2.0), 0.0)
        with self.assertRaises(ValueError):
            r_adj_for_model("M2", sp_constant=2.0)


class Rekomendasi(unittest.TestCase):
    fc = [{"et0": 4.5, "pe": 1.0}, {"et0": 4.5, "pe": 1.0}]
    kc = Param(1.1, "LITERATURE", "FAO-56")

    def run_rec(self, **kw):
        base = dict(h_now_cm=-12.0, h_observed_at=NOW - timedelta(hours=2), now=NOW, forecast=self.fc, kc=self.kc,
                    profile=profile(), phase="vegetatif", model="M1", sp_constant=2.0)
        base.update(kw); return recommend(**base)

    def test_irigasi_dan_hasil_lengkap(self):
        r = self.run_rec(q_plot_m3s=0.02, f_application_mm_day=5.0)
        self.assertEqual(r["status"], "OK"); self.assertTrue(r["irrigate"])
        self.assertLess(r["h_arrival_cm"], -12.0)
        self.assertGreater(r["total_mm"], r["refill_mm"])
        self.assertAlmostEqual(r["volume_m3"], 10 * 1.0 * r["total_mm"])
        self.assertTrue(r["provisional"]); self.assertEqual(r["prediction_mode"], "DEMO")  # ada parameter EXAMPLE

    def test_tidak_perlu_irigasi(self):
        r = self.run_rec(h_now_cm=2.0, forecast=[{"et0": 3.0, "pe": 0.0}])
        self.assertFalse(r["irrigate"]); self.assertIsNone(r["refill_mm"])

    def test_tanpa_pengamatan_h(self):
        r = self.run_rec(h_now_cm=None, h_observed_at=None)
        self.assertEqual(r["status"], "NEEDS_FIELD_OBSERVATION"); self.assertEqual(r["prediction_mode"], "MANUAL_REQUIRED")

    def test_pengamatan_basi(self):
        self.assertEqual(self.run_rec(h_observed_at=NOW - timedelta(hours=40))["status"], "STALE_OBSERVATION")

    def test_pengamatan_masa_depan(self):
        self.assertEqual(self.run_rec(h_observed_at=NOW + timedelta(hours=1))["status"], "INVALID_OBSERVATION")

    def test_parameter_pending_tidak_ditebak(self):
        p = PlotProfile("P1", area_ha=Param(1.0, "EXAMPLE"), lead_time_h=Param(24.0, "EXAMPLE"),
                        phases={"vegetatif": PhaseRule(Param(-15.0, "LITERATURE"), Param(5.0, "LITERATURE"))})
        r = self.run_rec(profile=p)
        self.assertEqual(r["status"], "MISSING_PARAMETER"); self.assertIn("mu_dry", r["reasons"][0])
        self.assertIsNone(r["irrigate"])

    def test_fase_belum_di_protokol(self):
        self.assertEqual(self.run_rec(phase="pembungaan")["status"], "PROTOCOL_REQUIRED")

    def test_horizon_prakiraan_terlampaui(self):
        self.assertEqual(self.run_rec(profile=profile(lead_h=72.0))["status"], "UNSUPPORTED_HORIZON")

    def test_debit_tidak_cukup(self):
        r = self.run_rec(q_plot_m3s=0.0001, f_application_mm_day=5.0)
        self.assertEqual(r["status"], "TARGET_NOT_REACHABLE")

    def test_tanpa_debit_tidak_ada_durasi(self):
        r = self.run_rec()
        self.assertIsNone(r["duration_h"]); self.assertEqual(r["volume_m3"], 10 * 1.0 * r["refill_mm"])

    def test_terkalibrasi_bukan_provisional(self):
        p = profile(status="CALIBRATED")
        rules = {"vegetatif": PhaseRule(Param(-15.0, "CALIBRATED"), Param(5.0, "CALIBRATED"))}
        p = PlotProfile("P1", p.area_ha, p.mu_dry, p.mu_fill, p.lead_time_h, p.h_cap_cm, rules)
        r = self.run_rec(profile=p, kc=Param(1.1, "CALIBRATED"))
        self.assertFalse(r["provisional"]); self.assertEqual(r["prediction_mode"], "M1")


if __name__ == "__main__":
    unittest.main()
