# SOMAT Release Log

## Rilis 2026-11-24 08:09 (+07:00)

- **Commit:** `0b8ef27` (sebelumnya `b4856a7`)
- **Isi perubahan:** panel "Catat h simulasi sekarang" di tab Prediksi (`demo_service.py`, `views/demo_panels.py`, `views/prediction.py`, `test_demo_fresh_h.py`)

### Bukti tes

| Tes | Hasil | Lingkungan | Catatan |
|---|---|---|---|
| Tes DB | 21 passed | Neon **branch uji** (db `somat_test`) | Ini BUKAN uji migrasi produksi |
| Tes unit/aplikasi | 392 passed, 0 skipped | Komputer lokal (venv) | Dilaporkan oleh pemilik proyek |

Catatan: angka di atas dilaporkan dari proses sebelumnya dan tidak dijalankan ulang saat log ini dibuat.

### Belum diuji / belum terbukti

- Migrasi di database produksi (branch production, db `neondb`)
- Alur lewat browser dan ponsel
- Konflik dua operator (keputusan bersamaan)
- Tampilan demo di web: Prediksi -> DEMO-P01 -> "Catat h simulasi sekarang" (belum ada screenshot)
- GitHub Actions "SOMAT ingest": status merah (exit code 2) sampai Secrets/Variable diisi dan dijalankan ulang lewat Run workflow. Belum ada konfirmasi hijau.

### Catatan keamanan yang masih terbuka

- Konfirmasi reset password Neon dan pembaruan di GitHub Secret, Streamlit Secrets, serta env lokal: **belum dikonfirmasi**
- Rotasi kunci sensor: ditunda, **wajib** sebelum sensor fisik dipasang

### Catatan data

- Data DEMO/DUMMY berlabel dan terpisah dari data riset/operasional; dummy lama sudah di-VOID (append-only)
- Spesifikasi pipa AWD masih PENDING
