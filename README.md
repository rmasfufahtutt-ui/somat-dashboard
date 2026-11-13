# SOMAT Dashboard v2

Dashboard pendukung keputusan irigasi (Streamlit + Neon PostgreSQL) yang disesuaikan dengan **Grand Framework SOMAT v2**
(`docs/Grand_Framework_SOMAT_v2.md`) dan roadmap (`docs/Roadmap_Pengembangan.csv`). Fungsi inti dashboard lama tetap ada
(login & peran, ringkasan, monitoring sensor, BMKG, prediksi/rekomendasi, peringatan, keputusan operator, admin).

## Yang berubah

**Kecepatan (penarikan data di latar belakang + tampilan ter-cache)**
- `data_hub.py`: satu thread daemon per proses menarik Google Sheets, prakiraan BMKG, dan peringatan BMKG sesuai interval masing-masing
  (90 dtk / 30 mnt / 5 mnt), lalu menukar *snapshot* di memori secara atomik. Halaman **hanya membaca snapshot** — pindah tab tidak menunggu sensor/spreadsheet/BMKG.
- Awal dingin cepat: snapshot diisi dulu dari arsip DB (`origin = db_cache`), lalu diganti data live begitu penarikan pertama selesai.
- Turunan pandas dihitung **sekali per versi snapshot** (`derive.py`), figur Plotly di-memo, CSS dibangun sekali per tema, pembacaan DB di-cache 15 dtk (`store.py`).
- Kartu/grafik/tabel memakai elemen native Streamlit (satu blok markdown, `st.plotly_chart`, `st.dataframe`) — bukan satu iframe per kartu/grafik seperti sebelumnya. Animasi penghitung pada kartu **dihapus** demi ringan.
- Poller kecil (`st.fragment`, 10 dtk) memicu render ulang hanya bila ada data baru, dan hanya di halaman baca-saja (agar isian form tidak terganggu).
- `worker.py` + `.github/workflows/ingest.yml`: ingest terjadwal (15 menit) saat dashboard tertutup, memakai kode & arsip yang sama (idempoten).

**Integritas data**
- Penarikan gagal **tidak menimpa** data baik terakhir; sumber ditandai `ok=False` + galat ringkas + umur data. Respons kosong yang mencurigakan juga tidak menimpa data lama.
- Pembacaan sensor diarsipkan idempoten (`ext_key`); prakiraan BMKG diarsipkan per penerbitan (hash payload) — dasar evaluasi sistem dengan prakiraan historis.
- Data simulasi hanya muncul sebagai **DEMO** berlabel jelas, tidak pernah menjadi pengamatan/label/keputusan operasional.

**Sesuai Grand Framework v2**
- Neraca air per petak (`physics_engine.py`): S(h), F = ETc + R_adj − Pe, model M0/M1/M1B/M2, pemicu & target AWD per fase, rantai waktu `observed_at → decision_at → arrival_at → end_at`, lintasan dipotong pada tengah malam lokal dan pergantian fase.
- ET0 Hargreaves-Samani `HS_v1` dengan `config_hash`, Tmin/Tmax prakiraan berlabel `ESTIMATED_FORECAST_EXTREMA`, hari tak lengkap (`INCOMPLETE_FORECAST`) tetap ada di kalender dan menahan run (tidak dilewati). Hujan tidak diprakirakan: `NO_RAIN_SCENARIO`.
- Pemisahan **jenis sumber** (MANUAL, SENSOR, BMKG_FORECAST, DUMMY, SIMULATED …), **status parameter** (CALIBRATED, LITERATURE, EXAMPLE, PENDING), dan **mode run** (DEMO, BASELINE_PROVISIONAL, BASELINE_VALIDATED, ML_SHADOW, ML_VALIDATED, MANUAL_REQUIRED). Parameter `PENDING` → run `MISSING_PARAMETER`; `EXAMPLE` → `DEMO` (tidak dapat diputuskan operasional).
- Profil parameter **berversi** (simpan = versi baru, yang lama ditutup), siklus tanam, jendela fase dari protokol.
- Rekomendasi **immutable** + snapshot input & hash; keputusan **atomik & idempoten** (klaim baris dengan `FOR UPDATE`, kunci idempotensi, kedaluwarsa, tolak bila ada pengamatan h baru sejak rekomendasi). Koreksi = record baru (`SUPERSEDED`), pembatalan = `VOID` beralasan; tidak ada edit/hapus di tempat.
- Halaman baru: **Pengamatan Lapangan** (input h manual; waktu kejadian ≠ waktu input), **Pelaksanaan Irigasi** (volume/waktu aktual terpisah dari persetujuan + galat prediksi vs pengamatan), Admin → **Petak & parameter** dan **Sistem** (status hub, log ingest).
- `labels.py`: pembentukan label residual untuk AI offline (tanpa kebocoran, jendela tanpa hujan/irigasi/kenaikan/lintas nol, pemisahan temporal).

## Setup

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # isi DATABASE (Neon), admin awal, Google Sheets
streamlit run app.py
```

Migrasi database berjalan otomatis (advisory lock, idempoten). Data pengguna, peran, dan riwayat keputusan lama dipertahankan; tabel
`pending_recommendations` lama tidak lagi dipakai (rekomendasi sekarang di `recommendation_runs`).

Langkah pertama setelah login sebagai admin: **Admin → Petak & parameter** → tambah petak (lintang wajib untuk ET0), mulai siklus tanam,
isi jendela fase dari protokol, lalu isi parameter. **Jangan isi angka tanpa dasar** — biarkan `PENDING`; sistem akan menolak
menghitung dan meminta keputusan manual, itu perilaku yang benar.

`source_type = "DUMMY"` (bawaan) menandai umpan sensor sebagai uji; dashboard menampilkan peringatan DEMO. Ubah ke `SENSOR` hanya setelah perangkat nyata terpasang.

### Ingest terjadwal (opsional, disarankan)
GitHub → Settings → Secrets: `DATABASE_URL`, `SENSOR_SHEET_URL`, `SENSOR_SHEET_READ_KEY` (Variables opsional: `SENSOR_SOURCE_TYPE`, `BMKG_ADM4`).
Workflow `SOMAT ingest` berjalan tiap 15 menit (jadwal GitHub dapat tertunda) dan bisa dijalankan manual.

## Alur kerja
`h lapangan → prakiraan BMKG → neraca air → rekomendasi (terbit) → keputusan operator → irigasi aktual → evaluasi`.
SOMAT tidak menggerakkan pintu; persetujuan ≠ air sudah mengalir.

## Uji

```bash
pip install -r requirements-dev.txt
pytest -q                                  # 121 uji unit (fisika, ET0, hub, rekomendasi, label, turunan)
TEST_DATABASE_URL=postgresql://.../somat_test pytest test_db_integration.py   # integrasi DB (MENGHAPUS skema public DB itu)
```

## Batasan yang jujur
- **Tidak ada model ML terlatih.** `labels.py` menyiapkan label; pelatihan RF/ANN menunggu data pilot yang cukup. Mode `ML_*` belum dipakai.
- Parameter fisik (μ, Kc, ambang AWD, lead time L, debit ke petak) **belum ditetapkan**; templat sengaja kosong/`PENDING`. `max_h_age_hours` (30 jam) dan masa berlaku rekomendasi (6 jam) adalah nilai sementara.
- Hujan tidak diprakirakan (skenario tanpa hujan); `tp` BMKG hanya ditampilkan (satuan tidak terdokumentasi). Pengamatan hujan BBWS/stasiun belum terhubung.
- Data sensor sekarang umpan uji (`DUMMY`), bukan perangkat terpasang. Respons lapangan simulasi dari prototipe lama **dihapus** (simulasi tidak boleh tampak sebagai hasil).
- Thread latar belakang hidup selama proses Streamlit hidup; di Streamlit Community Cloud proses dapat tidur saat tidak ada pengunjung — di situlah `worker.py` terjadwal dibutuhkan.
- Pemulihan sesi memakai komponen `somat_session/` (localStorage); tidak berubah dari versi lama.
