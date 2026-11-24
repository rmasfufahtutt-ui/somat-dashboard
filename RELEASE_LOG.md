# SOMAT Release Log

## Pembaruan 2026-11-24 08:59 (+07:00): uji konflik dua operator

- **Commit:** 4b58100 (menambah test_two_operator_conflict.py)
- **Lingkungan:** Neon branch uji, database somat_test, koneksi direct. BUKAN produksi.

### Bukti tes

| Tes | Hasil | Catatan |
|---|---|---|
| test_two_operator_conflict.py | 2 passed (20 detik) | 5 putaran per tes |
| Seluruh tes dengan TEST_DATABASE_URL terpasang | 394 passed, 0 skipped (152 detik) | Dijalankan langsung, keluaran pytest dilihat |

Yang terbukti pada SQL sungguhan: dua permintaan serentak dengan kunci idempotensi berbeda menghasilkan tepat satu keputusan (yang kalah mendapat already_handled), status akhir DECIDED; klik ganda serentak dengan kunci sama tidak menggandakan keputusan.

Batas tes: kedua permintaan memakai user admin, jadi bukan uji dua peran berbeda (peran dicakup test_rights.py). Lima putaran bukan bukti mutlak tanpa balapan. Kesesuaian dengan Handbook v1.3 (aturan konflik) BELUM diverifikasi.

### Keamanan

- Password Neon direset ulang pada 2026-11-24 di branch production dan branch uji. GitHub Secret, Streamlit Secrets, dan env lokal diperbarui, dan SOMAT ingest hijau setelahnya (dilaporkan pemilik proyek).

### Belum diuji / belum terbukti

- Migrasi di database produksi (branch production, db neondb)
- Alur lewat browser dan ponsel
- Dua operator dengan peran berbeda; kesesuaian aturan konflik dengan Handbook v1.3

### Catatan data

- Data DEMO/DUMMY berlabel dan terpisah dari data riset/operasional; dummy lama sudah di-VOID (append-only)
- Spesifikasi pipa AWD masih PENDING
- Rotasi kunci sensor: ditunda, WAJIB sebelum sensor fisik dipasang

---

## Rilis 2026-11-24 08:09 (+07:00)

- **Commit:** 0b8ef27 (sebelumnya b4856a7)
- **Isi perubahan:** panel "Catat h simulasi sekarang" di tab Prediksi (demo_service.py, views/demo_panels.py, views/prediction.py, test_demo_fresh_h.py)
- **Bukti tes:** 392 passed, 0 skipped (lokal, dengan DB uji); 21 tes DB lulus di branch uji yang lama (sudah kedaluwarsa dan dihapus)
- **Dikonfirmasi pemilik proyek:** ingest GitHub Actions hijau; demo DEMO-P01 kartu prediksi terisi tepat (laporan pemilik, tanpa bukti terlampir di repo)

---

## Catatan keputusan desain 2026-11-24: konflik dua operator

- **Aturan:** jika dua operator memutuskan rekomendasi yang sama, yang pertama tercatat menang dan yang kedua ditolak (already_handled). Kekeliruan dikoreksi lewat jalur koreksi (supersede) atau VOID, bukan lewat keputusan kedua.
- **Sumber aturan:** keputusan pemilik proyek. Kesesuaian dengan bunyi Handbook v1.3 belum diverifikasi; jika belum tercantum, tambahkan pada revisi Handbook berikutnya.
- **Bukti:** perilaku kode sesuai aturan ini pada SQL sungguhan di branch uji (test_two_operator_conflict.py, 2 passed).
- **Belum diuji:** jalur koreksi setelah konflik (operator yang kalah memperbaiki lewat supersede), dan dua peran berbeda.
