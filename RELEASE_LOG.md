# SOMAT Release Log

## Rilis 2026-11-24 08:09 (+07:00)

- **Commit:** `0b8ef27` (sebelumnya `b4856a7`)
- **Isi perubahan:** panel "Catat h simulasi sekarang" di tab Prediksi (`demo_service.py`, `views/demo_panels.py`, `views/prediction.py`, `test_demo_fresh_h.py`)

### Bukti tes

| Tes | Hasil | Lingkungan | Catatan |
|---|---|---|---|
| Tes DB | 21 passed | Neon **branch uji** (db `somat_test`) | Ini BUKAN uji migrasi produksi |
| Tes unit/aplikasi | 392 passed, 0 skipped | Komputer lokal (venv) | Dilaporkan oleh pemilik proyek |

Catatan: angka tes dilaporkan dari proses sebelumnya dan tidak dijalankan ulang saat log ini dibuat.

### Dikonfirmasi pemilik proyek pada 2026-11-24

- GitHub Actions "SOMAT ingest": run lewat Run workflow berstatus **hijau** (Secrets dan Variable sudah diisi)
- Password Neon sudah direset dan diperbarui di GitHub Secret, Streamlit Secrets, dan env lokal
- Demo di web (Prediksi -> DEMO-P01 -> "Catat h simulasi sekarang"): kartu prediksi h, irigasi, dan durasi **terisi tepat**

Catatan: konfirmasi di atas berasal dari laporan pemilik proyek, bukan dari bukti terlampir (log/screenshot belum disimpan di repo).

### Belum diuji / belum terbukti

- Migrasi di database produksi (branch production, db `neondb`)
- Alur lewat browser dan ponsel
- Konflik dua operator (keputusan bersamaan)

### Catatan keamanan yang masih terbuka

- Rotasi kunci sensor: ditunda, **wajib** sebelum sensor fisik dipasang

### Catatan data

- Data DEMO/DUMMY berlabel dan terpisah dari data riset/operasional; dummy lama sudah di-VOID (append-only)
- Spesifikasi pipa AWD masih PENDING
