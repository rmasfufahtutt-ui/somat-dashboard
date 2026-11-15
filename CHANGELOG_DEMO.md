# Perubahan — Mode DEMO PENELITIAN

**Baru:** demo_mode.py, demo_repository.py (SQLite), repo_router.py, demo_data.py, demo_weather.py, demo_service.py, demo_ml.py,
formstate.py, views/demo_panels.py, views/guide.py, docs/DEMO_PENELITIAN.md, conftest.py, test_demo_*.py (7 berkas).

**Diubah (kompatibel mundur):**
* `recommendation_service.compute`: parameter opsional `pe_by_date`, `model`, `ml_residual`, `bias`, `rain_label` (default = perilaku lama).
* `store.py`: cache per-mode (kunci cache memuat mode; argumen tanpa awalan `_`).
* `auth.py`: akun demo tanpa DB, audit demo, izin halaman demo sama dengan peran bawaan, `guide` halaman umum.
* `app.py`: banner DEMO, sakelar ruang kerja, halaman Panduan Demo; `views/login.py`: tombol masuk demo.
* `views/observations|execution|prediction|operator|overview|admin|admin_plots`: sambungan ke router, "Isi contoh", panel penjelasan, label SIMULASI,
  tab Admin → Demo, isian form bertahan saat pindah halaman (widget biasa + tombol Simpan, menggantikan `st.form`).
* `texts.py`: kode galat keputusan baru. `requirements.txt`: `scikit-learn>=1.5`.

**Tidak diubah:** rumus mesin, aturan keputusan operasional, integrasi BMKG/Sheets, otentikasi nyata, skema Neon.
