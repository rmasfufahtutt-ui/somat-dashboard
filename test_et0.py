"""Tes et0.py. Jalankan: python -m unittest test_et0 -v"""
import math
import unittest
from datetime import datetime, date, timedelta, timezone

from et0 import (
    extraterrestrial_radiation, hargreaves_et0, daily_tminmax_from_forecast, forecast_et0_series, daily_forecast_summary,
    normalize_forecast_rows, HSConfig, METHOD_ID, TEMP_SOURCE_FORECAST,
)


class Ra(unittest.TestCase):
    def test_fao56_contoh_8(self):                 # FAO-56 Contoh 8: 3 September, 20°S -> Ra = 32,2 MJ/m2/hari
        self.assertAlmostEqual(extraterrestrial_radiation(-20.0, 246), 32.2, delta=0.15)

    def test_lintang_di_luar_jangkauan(self):
        with self.assertRaises(ValueError):
            extraterrestrial_radiation(80.0, 100)

    def test_input_tidak_sah(self):
        for lat, doy in ((float("nan"), 100), (float("inf"), 100), (-6.8, 0), (-6.8, 400), (-6.8, 1.5)):
            with self.assertRaises(ValueError):
                extraterrestrial_radiation(lat, doy)


class Hargreaves(unittest.TestCase):
    def test_regresi_majalengka_nov(self):         # nilai regresi (bukan kebenaran eksternal): lintang -6,8; 12 Nov
        r = hargreaves_et0(23.0, 33.0, -6.8, 316)
        self.assertAlmostEqual(r["et0_mm_day"], 5.23, delta=0.05)
        self.assertEqual(r["method"], METHOD_ID)
        self.assertFalse(r["clamped"])

    def test_rentang_suhu_lebih_sempit_et0_lebih_rendah(self):
        self.assertLess(hargreaves_et0(25.0, 31.0, -6.8, 316)["et0_mm_day"], hargreaves_et0(23.0, 33.0, -6.8, 316)["et0_mm_day"])

    def test_tmax_tidak_valid(self):
        with self.assertRaises(ValueError):
            hargreaves_et0(30.0, 30.0, -6.8, 316)
        with self.assertRaises(ValueError):
            hargreaves_et0(31.0, 30.0, -6.8, 316)

    def test_nan_inf_dan_rentang_fisik_ditolak(self):
        for tmin, tmax in ((float("nan"), 30.0), (20.0, float("inf")), (-40.0, 30.0), (20.0, 80.0)):
            with self.assertRaises(ValueError):
                hargreaves_et0(tmin, tmax, -6.8, 316)

    def test_koefisien_berbeda_config_hash_berbeda(self):
        a = hargreaves_et0(23.0, 33.0, -6.8, 316)
        b = hargreaves_et0(23.0, 33.0, -6.8, 316, coefficient=0.0025)
        self.assertEqual(a["method"], b["method"])                 # METHOD_ID tetap sama ...
        self.assertNotEqual(a["config_hash"], b["config_hash"])    # ... tetapi konfigurasi dapat dibedakan
        self.assertNotEqual(a["method_version"], b["method_version"])
        self.assertGreater(b["et0_mm_day"], a["et0_mm_day"])

    def test_pembatasan_nol_ditandai(self):
        # suhu rata-rata sangat rendah membuat (Tmean+17.8) negatif -> ET0 mentah negatif
        r = hargreaves_et0(-30.0, -28.0, 10.0, 15, config=HSConfig(temp_min_c=-40.0))
        self.assertEqual(r["et0_mm_day"], 0.0)
        self.assertTrue(r["clamped"])
        self.assertLess(r["et0_raw"], 0.0)


def pts(day, temps, start_hour=1):
    return [(datetime(day.year, day.month, day.day, start_hour + 3 * i), t) for i, t in enumerate(temps)]


D = date(2026, 11, 14)
FULL = [24, 23, 26, 31, 33, 32, 28, 25]


class Prakiraan(unittest.TestCase):
    def test_tmin_tmax_harian(self):
        out = daily_tminmax_from_forecast(pts(D, FULL))
        self.assertEqual((out[D]["tmin"], out[D]["tmax"], out[D]["n"]), (23.0, 33.0, 8))

    def test_hari_tidak_lengkap_dilewati_pada_api_lama(self):
        self.assertEqual(daily_tminmax_from_forecast(pts(D, [24, 23, 26, 31])), {})

    def test_nilai_kosong_diabaikan(self):
        out = daily_tminmax_from_forecast(pts(D, [24, None, 26, 31, 33, 32, 28, 25]))
        self.assertEqual(out[D]["n"], 7)

    def test_duplikasi_enam_slot_tidak_dianggap_lengkap(self):
        # enam titik identik pada slot yang sama: hanya 1 slot unik
        p = [(datetime(2026, 11, 14, 13), 30.0)] * 6
        s = daily_forecast_summary(p)
        self.assertEqual(s[0]["status"], "INCOMPLETE_FORECAST")
        self.assertEqual(s[0]["n"], 1)

    def test_enam_slot_menumpuk_siang_belum_cukup_cakupan(self):
        p = [(datetime(2026, 11, 14, h), 30.0 + h / 10) for h in (12, 13, 14, 15, 16, 17)]
        s = daily_forecast_summary(p)
        self.assertEqual(s[0]["n"], 6)
        self.assertEqual(s[0]["status"], "INCOMPLETE_FORECAST")
        self.assertIn("night", s[0]["reason"])

    def test_hari_hilang_tetap_ada_di_kalender(self):
        p = pts(D, FULL) + pts(D + timedelta(days=2), FULL)
        s = daily_forecast_summary(p)
        self.assertEqual([e["date"] for e in s], [D, D + timedelta(days=1), D + timedelta(days=2)])
        self.assertEqual([e["status"] for e in s], ["OK", "INCOMPLETE_FORECAST", "OK"])

    def test_seri_et0_label_dan_status(self):
        series = forecast_et0_series(pts(D, FULL) + pts(D + timedelta(days=1), [27] * 8), -6.8)
        self.assertEqual([s["status"] for s in series], ["OK", "INVALID_RANGE"])
        self.assertGreater(series[0]["et0_mm_day"], 3.0)
        self.assertEqual(series[0]["temperature_source"], TEMP_SOURCE_FORECAST)
        self.assertTrue(series[0]["config_hash"])

    def test_seri_et0_hari_kurang_tidak_hilang(self):
        series = forecast_et0_series(pts(D, [24, 23, 26, 31]) + pts(D + timedelta(days=1), FULL), -6.8)
        self.assertEqual([s["status"] for s in series], ["INCOMPLETE_FORECAST", "OK"])
        self.assertIsNone(series[0]["et0_mm_day"])

    def test_lintang_tidak_sah_ditandai_bukan_crash(self):
        series = forecast_et0_series(pts(D, FULL), 80.0)
        self.assertEqual(series[0]["status"], "INVALID_INPUT")

    def test_suhu_di_luar_rentang_ditolak(self):
        series = forecast_et0_series(pts(D, [24, 23, 26, 31, 33, 32, 28, 99]), -6.8)
        self.assertEqual(series[0]["status"], "INVALID_INPUT")


class WaktuLokalUtc(unittest.TestCase):
    def test_local_datetime_dipakai_apa_adanya(self):
        rows = [{"local_datetime": "2026-11-14 01:00:00", "temperature": 24}]
        n = normalize_forecast_rows(rows)
        self.assertEqual(n[0]["valid_at"].hour, 1)
        self.assertEqual(n[0]["utc"].hour, 18)            # 01:00 WIB = 18:00 UTC hari sebelumnya
        self.assertEqual(n[0]["utc"].day, 13)

    def test_fallback_utc_dikonversi_sebelum_agregasi(self):
        # 18:00 UTC tanggal 13 = 01:00 WIB tanggal 14 -> harus jatuh pada TANGGAL LOKAL 14
        rows = [{"utc_datetime": "2026-11-13 18:00:00", "temperature": 24}]
        n = normalize_forecast_rows(rows)
        self.assertEqual(n[0]["valid_at"].date(), date(2026, 11, 14))
        self.assertEqual(n[0]["time_basis"], "utc_converted")

    def test_baris_tanpa_waktu_dibuang_dan_suhu_rusak_none(self):
        rows = [{"temperature": 25}, {"local_datetime": "2026-11-14 04:00:00", "temperature": "abc"},
                {"local_datetime": "2026-11-14 07:00:00", "temperature": float("nan")}]
        n = normalize_forecast_rows(rows)
        self.assertEqual(len(n), 2)
        self.assertTrue(all(x["temp"] is None for x in n))

    def test_agregasi_memakai_tanggal_lokal(self):
        rows = [{"utc_datetime": f"2026-11-{13 if h >= 17 else 14} {h:02d}:00:00", "temperature": 20 + i}
                for i, h in enumerate((18, 21, 0, 3, 6, 9, 12, 15))]
        n = normalize_forecast_rows(rows)
        s = daily_forecast_summary([(x["valid_at"], x["temp"]) for x in n])
        self.assertEqual(s[0]["date"], date(2026, 11, 14))
        self.assertEqual(s[0]["n"], 8)
        self.assertEqual(s[0]["status"], "OK")


class Config(unittest.TestCase):
    def test_hash_stabil_dan_sensitif(self):
        self.assertEqual(HSConfig().config_hash, HSConfig().config_hash)
        self.assertNotEqual(HSConfig().config_hash, HSConfig(min_slots_per_day=7).config_hash)
        self.assertNotEqual(HSConfig().config_hash, HSConfig(required_periods=("morning",)).config_hash)


if __name__ == "__main__":
    unittest.main()
