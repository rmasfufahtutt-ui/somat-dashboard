# 💧 SOMAT — Smart Adaptive Irrigation Management System

> **PROTOTYPE — DATA SIMULASI.** Seluruh angka pada dashboard ini dibangkitkan secara simulasi untuk mendemonstrasikan konsep SOMAT. Bukan data penelitian aktual dan bukan sistem operasional.

**Demo online:** https://somat-prototype.streamlit.app
**Repositori:** https://github.com/rmasfufahtutt-ui/somat-dashboard

---

## 1. Apa itu SOMAT?

SOMAT adalah prototipe **sistem pendukung keputusan** untuk pengelolaan irigasi. Sistem membaca kondisi lahan dan saluran, memperkirakan kebutuhan air, memeriksa kelayakan hidraulik, lalu memberi **rekomendasi** kepada operator.

**Keputusan akhir selalu ada di tangan operator (Human in the Loop).** Prototipe ini tidak menggerakkan pintu air secara otomatis.

### Alur kerja

```
Observasi → Prediksi → Cek Hidraulik → Rekomendasi → Validasi Operator → Operasi → Umpan Balik
```

| Tahap | Yang terjadi di dashboard |
|---|---|
| Observasi | Pembacaan 6 sensor kelembapan tanah, 1 sensor muka air, dan data hujan |
| Prediksi | Kebutuhan air irigasi dihitung dengan aturan sederhana (ET0, kelembapan tanah, hujan efektif) |
| Cek hidraulik | Tiga pemeriksaan: muka air saluran, debit tersedia, dan batas operasi pintu |
| Rekomendasi | Jumlah dan durasi irigasi yang disarankan, lengkap dengan alasannya |
| Validasi operator | Operator memilih **APPROVE**, **MODIFY**, atau **DELAY** |
| Operasi | Keputusan dicatat. Tidak ada pintu yang bergerak otomatis |
| Umpan balik | Respons lapangan **simulasi** ditampilkan untuk membandingkan saran dan hasil |

---

## 2. Fitur dashboard

Dashboard memiliki lima menu:

1. **📊 Ringkasan** — kartu kondisi terbaru, status sistem dan lahan, serta grafik 14 hari terakhir.
2. **📡 Monitoring Sensor** — status sensor online/offline, donat distribusi status, tren kelembapan tanah per sensor, grafik monitoring, dan tabel data.
3. **💧 Prediksi & Rekomendasi** — prediksi kebutuhan air, kelayakan hidraulik, rekomendasi SOMAT, dan tombol kirim ke operator.
4. **🚨 Peringatan** — peringatan berbasis aturan dan tabel kejadian terbaru.
5. **👷 Keputusan Operator** — APPROVE / MODIFY / DELAY, catatan operator, alur umpan balik, dan riwayat keputusan.

Fitur tampilan:
- Mode gelap dan terang (ikon matahari/bulan di pojok kanan atas)
- Antarmuka berbahasa Indonesia
- Animasi kartu dan grafik; donat sensor dapat diklik
- Tabel interaktif: urut, cari, pilih kolom, ubah lebar kolom, layar penuh, dan unduh CSV
- Tampilan responsif untuk laptop dan HP

---

## 3. Sensor (simulasi)

| ID | Jenis | Lokasi |
|---|---|---|
| SM-01 … SM-06 | Kelembapan tanah (%) | Petak 1–6 |
| WL-01 | Muka air (m) | Depan pintu tersier |
| RF-01 | Curah hujan (mm) | Stasiun hujan eksternal (simulasi; rencana: BMKG/BBWS terdekat) |

Sensor yang tidak mengirim data valid lebih dari 3 jam ditandai **Offline**.

---

## 4. Nilai asumsi

Semua angka di bawah adalah **contoh**, bukan data lapangan. Nilai-nilai ini dikumpulkan dalam satu kamus `ASSUMPTIONS` di `app.py`.

| Parameter | Nilai contoh |
|---|---|
| Luas layanan | 50 ha |
| Waktu pemberian air | 8 jam |
| Muka air minimum | 0,90 m |
| Kapasitas pintu | 0,45 m³/s |

Batas peringatan (kelembapan rendah 20 %, hujan lebat 20 mm) juga angka contoh.

---

## 5. Teknologi

Python · Streamlit · Pandas · NumPy · Plotly

Tidak memakai layanan berbayar, kunci API, maupun basis data.

---

## 6. Struktur proyek

```
somat-dashboard/
├── app.py                 # seluruh aplikasi (data simulasi, logika, tampilan)
├── requirements.txt       # daftar library
├── README.md              # dokumen ini
├── assets/
│   └── somat_logo.png     # logo SOMAT
└── .streamlit/
    └── config.toml        # tema bawaan
```

---

## 7. Menjalankan di komputer sendiri

Prasyarat: Anaconda (atau Python 3.10+).

```bash
# 1. Buat dan aktifkan environment (sekali saja untuk pembuatan)
conda create -n somat python=3.11
conda activate somat

# 2. Masuk ke folder proyek
cd somat-dashboard

# 3. Pasang library
pip install -r requirements.txt

# 4. Jalankan
streamlit run app.py
```

Browser akan terbuka di `http://localhost:8501`. Hentikan dengan **Ctrl+C** di terminal.

Catatan: terminal akan "terkunci" selama server berjalan. Buka jendela terminal baru untuk perintah lain.

---

## 8. Deploy ke Streamlit Community Cloud

1. Dorong kode ke GitHub (`git add`, `git commit`, `git push`).
2. Di https://share.streamlit.io, pilih repositori, cabang `main`, dan file utama `app.py`.
3. Setiap `git push` ke cabang `main` akan membuat aplikasi diperbarui otomatis.

---

## 9. Keterbatasan

- **Seluruh data adalah simulasi.** Tidak ada sensor fisik yang terhubung.
- Logika prediksi, hidraulik, rekomendasi, dan peringatan berbasis **aturan sederhana**, bukan model final penelitian.
- Riwayat keputusan hanya tersimpan selama sesi browser dan hilang saat halaman dimuat ulang.
- Tidak ada login atau pembagian peran pengguna.
- Fungsi `st.components.v1.html` yang dipakai untuk kartu dan grafik sudah dinyatakan akan dihapus oleh Streamlit. Aplikasi masih berjalan, tetapi perlu dimigrasikan ke `st.iframe` pada pengembangan berikutnya.

---

## 10. Rencana pengembangan

Prototipe ini dirancang agar tiap bagian logika (prediksi, hidraulik, rekomendasi, peringatan, umpan balik) berupa fungsi terpisah yang bisa diganti tanpa mengubah tampilan.

| Tahap | Rencana |
|---|---|
| 1 | Hubungkan data hujan ke BMKG/BBWS |
| 2 | Hubungkan sensor lapangan nyata (kelembapan tanah dan muka air) |
| 3 | Simpan data dan riwayat keputusan di basis data |
| 4 | Tambahkan login dan peran pengguna (operator, pengawas, admin) |
| 5 | Ganti logika aturan dengan model hasil penelitian, lalu validasi dengan data lapangan |
| 6 | Uji bertahap bila kelak diinginkan kendali pintu: lapisan keamanan, gateway/PLC, dan uji lapangan terbatas |

> Menggerakkan pintu secara otomatis memerlukan basis data, login dan peran, lapisan keamanan, umpan balik lapangan, gateway/PLC, dan pengujian bertahap. Hal-hal tersebut **belum** ada pada prototipe ini.

---

## 11. Lisensi dan penafian

Prototipe untuk keperluan akademik dan demonstrasi. Tidak untuk dipakai sebagai dasar keputusan operasional irigasi.
