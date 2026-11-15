# SOMAT — Mode DEMO PENELITIAN

Ruang demo untuk presentasi kepada dosen. **Terpisah total** dari data operasional: repositori SQLite sendiri
(`.demo_data/somat_demo.sqlite3`, atau `SOMAT_DEMO_DB`), jalur penerbitan & keputusan khusus (`run_mode='DEMO'`, `source='DEMO'`),
dan setiap baris bertanda `is_demo`, `dataset_id`, `origin` (SEED / USER / SCENARIO).

## Menjalankan
```
pip install -r requirements.txt
streamlit run app.py
```
Layar masuk: tombol **Demo sebagai Admin / Operator / Pengamat** (tanpa database produksi, tanpa kata sandi, hanya ruang demo).
Pengguna nyata (Neon aktif) memakai sakelar **Ruang kerja → Demo penelitian** di sidebar. Akun demo tidak pernah bisa pindah ke operasional.

Pertama kali: **Administrasi → Demo → Muat data demo**.

## Alur presentasi singkat
1. Ringkasan: enam petak DEMO-P01…P06 (irigasi, aman, hujan menahan, pengamatan usang, parameter kurang, debit kurang) + grafik riwayat 35 hari.
2. Pengamatan Lapangan → **Isi contoh** → simpan; coba koreksi dan VOID.
3. Prediksi & Rekomendasi: pilih sumber suhu (sintetis / BMKG asli), skenario hujan, model M1/M2; baca panel **Mengapa rekomendasi ini?**; terbitkan (simulasi).
4. Keputusan Operator: APPROVE (jumlah sama), MODIFY (jumlah harus berubah), DELAY.
5. Pelaksanaan Irigasi: **Isi contoh** → simpan; lihat rantai SOMAT → operator → realisasi simulasi.
6. Admin → Demo → **Latih model demo** (hanya admin); bandingkan M1 vs M2 di Prediksi.
7. **Kembalikan skenario awal** menghapus semua perubahan (dengan konfirmasi) dan memuat ulang; idempoten.
Halaman **Panduan Demo** di aplikasi memuat diagram arsitektur dan tabel hak edit/koreksi/VOID.

## Yang nyata vs sintetis
| Item | Status |
|---|---|
| BMKG | Asli (data hub). Bila dipilih sebagai sumber suhu dan kosong → `INCOMPLETE_FORECAST`, tidak diisi data karangan. Hujan BMKG tidak diprakirakan. |
| Petak, sensor, riwayat h, keputusan, pelaksanaan | Sintetis, seed tetap, berlabel DEMO/SIMULASI |
| Parameter | CONTOH (tidak pernah CALIBRATED) → mode run selalu DEMO |
| Model AI | Random Forest dilatih dari korpus sintetis; M2 = residual RF + bias, **tanpa SPconstant ganda** |

## Batasan jujur
* Metrik model AI hanya menunjukkan alur (label jendela → split temporal → latih → uji); korpus dibuat berbeda dari SPconstant. Bukan akurasi lapangan.
* Skenario dirancang pada waktu muat. Bila demo dibuka berhari-hari kemudian, pakai **Geser waktu** atau **Kembalikan skenario awal**.
* Perilaku jaringan BMKG nyata, Neon nyata, dan Google Sheets tidak dapat diuji di lingkungan pengembangan (tanpa akses keluar).
