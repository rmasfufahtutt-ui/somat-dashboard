# Grand framework dan arsitektur pengembangan SOMAT

Versi rancangan 2.0 • 13 November 2026

SOMAT dikembangkan sebagai sistem pendukung keputusan irigasi per petak. Neraca air membentuk dasar perhitungan; machine learning mengestimasi residual kehilangan air setelah data lapangan mencukupi; operator menentukan tindakan akhir. Pengukuran h petak dilakukan manual melalui pipa observasi AWD sebanyak 1–2 kali sehari. Sensor kelembapan tanah dan sensor muka air saluran tetap menjadi dua aliran data yang berbeda.

Dokumen ini merupakan spesifikasi pengembangan. Fitur yang direncanakan tidak dianggap sudah berjalan. Pemeriksaan kode dilakukan pada arsip somat-dashboard.rar yang dikirim pada 13 November 2026. Tidak ada perubahan atau deployment aplikasi pada pekerjaan ini.

## 1 Tujuan dan batas sistem

SOMAT menjawab empat pertanyaan: bagaimana kondisi petak dan pasokan air; kapan petak diperkirakan mencapai ambang; berapa kebutuhan pengisian dan durasinya; serta apa keputusan dan pelaksanaan operator. Hasil yang diperlukan adalah prediksi h saat air tiba, kedalaman irigasi, volume, durasi apabila debit diketahui, kelayakan hidraulik, dan alasan rekomendasi.

SOMAT tidak menggerakkan pintu secara otomatis. Persetujuan operator tidak berarti air sudah dialirkan. Respons simulasi tidak menjadi hasil pengamatan atau label pelatihan. Tampilan online dari data dummy tidak membuktikan perangkat fisik sudah terpasang.

Tahap awal mempertahankan Streamlit, Neon PostgreSQL, dan adapter Google Sheets yang sudah ada. Pemisahan modul cukup untuk kebutuhan awal; migrasi ke frontend atau microservice baru belum menjadi prioritas. Pengambilan data berkala yang harus berlangsung saat dashboard ditutup dilakukan oleh pekerjaan terjadwal di luar siklus tampilan Streamlit.

## 2 Kondisi aktual berdasarkan pemeriksaan kode

| Komponen | Bukti pada arsip | Implikasi |
|---|---|---|
| Dashboard | app.py masih menghitung rekomendasi dengan predict_irrigation_requirement dan generate_recommendation | Jalur baru belum menjadi sumber rekomendasi dashboard |
| Neraca air | physics_engine.py berisi storage, trajectory, residual, bias, dan recommend | Modul tersedia, belum terintegrasi dengan app.py |
| ET0 | et0.py berisi Ra, Hargreaves–Samani, dan agregasi prakiraan | Modul tersedia, belum menjadi ET0 aktif dashboard |
| Tes modul | 30 tes fisika dan 9 tes ET0 dijalankan ulang; seluruhnya lolos | Memastikan perilaku yang diuji, belum memvalidasi lapangan atau integrasi |
| BMKG | bmkg_integration.py menyediakan prakiraan dan peringatan dini; kode ADM4 Panongan 32.10.15.2003 | Lokasi administratif tersedia; koordinat petak belum ditetapkan |
| Sensor | sensor_sheet.py menyediakan adapter data Google Sheets | Konektor tersedia; belum menjadi bukti sensor sudah terpasang |
| Neon | Kode tabel pengguna, keputusan, audit, sesi, role, dan pending recommendation tersedia | Koneksi produksi dan isi database tidak diperiksa pada audit ini |
| Input h dan profil | Belum ditemukan tabel khusus pengamatan h atau profil parameter petak | Keduanya menjadi pekerjaan pertama |
| MODIFY | Alasan diwajibkan; jumlah masih dapat disimpan sama dengan saran | Tambahkan validasi jumlah berubah dan perhitungan ulang hidraulik |
| Feedback | simulate_field_response masih digunakan saat pencatatan keputusan | Pisahkan demonstrasi dari pelaksanaan dan evaluasi aktual |

Python yang tidak ditemukan di laptop hanya menghambat tes lokal. Itu tidak membuktikan kegagalan runtime Streamlit Cloud. Siapkan Python atau runner pengujian pada repositori sebelum rilis; jumlah tes yang lolos tidak menggantikan uji integrasi.

## 3 Grand framework penelitian dan operasi

Gambar Grand_Framework_SOMAT.png menunjukkan hubungan pengumpulan data, mesin fisika, pengembangan AI, keputusan operator, dan evaluasi.

### 3.1 Pengamatan kondisi aktual

Petugas membaca h pada pipa observasi. Nilai nol ditetapkan pada permukaan tanah; nilai positif menunjukkan genangan, nilai negatif menunjukkan muka air di bawah permukaan. Data dikirim melalui formulir dashboard dengan ID petak, waktu pengamatan, nilai h dalam cm, dan pencatat.

Frekuensi yang disepakati adalah 1–2 kali sehari: satu kali pada jam tetap ketika kondisi relatif stabil; dua kali, pagi dan sore, ketika mendekati ambang atau kondisi berubah cepat. Pembacaan tambahan sebelum dan sesudah pengairan dapat dilakukan untuk kalibrasi dan verifikasi pelaksanaan. Ini adalah rancangan protokol SOMAT, bukan klaim frekuensi universal dari literatur. Batas umur data operasional ditetapkan melalui pilot; default 30 jam dalam kode belum menjadi keputusan penelitian.

Sensor kelembapan tanah mengirim persen kelembapan dengan waktu dan ID petak. Sensor saluran mengirim muka air saluran beserta datum dan lokasi. Keduanya diperiksa keterkinian, rentang, dan status sumber. Nilai h manual tidak dihitung dari persen kelembapan tanah; muka air saluran tidak menggantikan h petak.

### 3.2 Cuaca dan hujan

Prakiraan BMKG disimpan sebagai arsip tiap waktu penerbitan, bersama waktu berlaku dan waktu diterima. Pengamatan suhu historis berasal dari logger berpelindung yang dipasang sesuai protokol atau stasiun yang keterwakilan dan akses datanya sudah diperiksa. Belum ada sumber suhu pengamatan yang dikunci.

Hujan pengamatan direncanakan menggunakan pos BBWS Cimanuk Cisanggarung yang representatif terhadap lokasi. Pos belum ditetapkan hanya berdasarkan jarak: periksa koordinat, kondisi wilayah, kelengkapan, satuan, interval akumulasi, akses, dan keterlambatan. Data hujan aktual untuk evaluasi dipisahkan dari prakiraan hujan untuk operasi.

Field tp pada BMKG belum menjadi hujan efektif otomatis dalam kode. Adapter saat ini menyebut satuan dan periode akumulasinya belum terkonfirmasi. Jangan mengubah ikon cuaca, tutupan awan, atau data hujan yang hilang menjadi nilai hujan numerik. Jika prakiraan hujan numerik belum terverifikasi, skenario Pe=0 dapat ditampilkan sebagai skenario tanpa hujan yang eksplisit; jangan menyebutnya prakiraan BMKG atau memasukkannya ke pelatihan sebagai pengamatan nol.

### 3.3 Baseline fisika

Hitung ET0, ETc, kehilangan bersih, lintasan h, kebutuhan pengisian, volume, dan durasi. Terapkan ambang AWD sesuai fase serta batas hidraulik. Sebelum ML tersedia, gunakan baseline yang sudah dikalibrasi dan dievaluasi; M0 dapat digunakan untuk pembandingan dan pemeriksaan perhitungan, bukan otomatis baseline operasional terbaik.

### 3.4 AI residual

Latih model hanya setelah pengamatan dan parameter mendukung label yang dapat dipertanggungjawabkan. Model memprediksi residual kehilangan air, kemudian residual masuk kembali ke neraca air. Kandidat awal adalah Random Forest Regressor. ANN menjadi pembanding bila ukuran dan cakupan data mendukung. Pemilihan ini merupakan usulan rekayasa untuk data tabular terbatas, bukan kesimpulan bahwa RF pasti paling akurat.

### 3.5 Keputusan dan pelaksanaan

Rekomendasi tersimpan sebagai snapshot yang dapat ditinjau. Operator memilih APPROVE, MODIFY, atau DELAY. Pelaksanaan dicatat terpisah, termasuk waktu air tiba, awal dan akhir pengairan, debit atau volume terukur, dan kondisi petak setelah pelaksanaan.

### 3.6 Evaluasi dan pembekuan versi

Evaluasi ketepatan prediksi h, residual, rekomendasi, dan pelaksanaan. Bekukan metode ET0, parameter, transformasi input, model, dan aturan sebelum pengujian penelitian final. Versi baru dibangun dan diuji terpisah. Tidak ada pembaruan bobot otomatis berdasarkan tombol operator.

## 4 Arsitektur teknis yang dituju

Gambar Arsitektur_SOMAT.png membedakan sumber, layanan aplikasi, penyimpanan, mesin rekomendasi, dan jalur pelatihan offline. Seluruh kotak adalah arsitektur tujuan; status implementasi mengikuti tabel bagian 2.

Aliran sensor yang direncanakan: perangkat → pengirim atau gateway yang dipilih saat pemasangan → endpoint/Google Sheets → sensor_sheet.py → validasi → observations di Neon → grafik dan ringkasan dashboard. Protokol koneksi, interval kirim, jenis perangkat, dan gateway belum dikunci. Kontrak data harus tetap sama bila media pengiriman kemudian berubah.

Aliran h manual: formulir operator → validasi dan hak akses → observations → layanan rekomendasi. Simpan waktu kejadian dan waktu input secara terpisah agar pengisian terlambat terlihat.

Aliran BMKG: adapter → penyimpanan payload dan waktu penerbitan → pemeriksaan cakupan → agregasi tanggal lokal → et0.py → layanan rekomendasi. Hindari mengambil ulang prakiraan terbaru lalu menggunakannya sebagai pengganti arsip yang tersedia pada keputusan masa lalu.

Layanan rekomendasi membaca snapshot input, profil petak versi aktif, protokol fase, dan model yang diizinkan. Semua hasil dan alasan kegagalan disimpan bersama ID snapshot. UI membaca hasil layanan tersebut, sehingga Overview, Prediction, dan Operator Decision menampilkan angka yang sama.

## 5 Penguncian ET0

Keputusan awal: Hargreaves–Samani sebagai metode sementara yang layak untuk keterbatasan input, dengan evaluasi lokal sebelum pembekuan penelitian. FAO-56 menetapkan Penman–Monteith sebagai acuan dan menganjurkan estimasi variabel yang hilang untuk mempertahankan penggunaan metode acuan bila dapat dilakukan secara layak. HS adalah alternatif data terbatas yang memerlukan pemeriksaan regional (Allen et al., 1998, Bab 3).

Rumus HS bila Ra dalam MJ/m²/hari:

`ET0 = 0.0023 × (Tmean + 17.8) × sqrt(Tmax − Tmin) × 0.408 × Ra`

`Tmean = (Tmax + Tmin) / 2`

HS tidak memerlukan pengukuran radiasi matahari, tetapi tetap memakai Ra yang dihitung dari lintang dan tanggal. Elevasi tidak masuk langsung ke rumus HS ini; tetap simpan untuk metadata lokasi dan evaluasi PM. Koordinat desa dalam respons cuaca bukan otomatis koordinat petak.

Contoh Ra pada tes telah diperiksa ke FAO-56 Contoh 8: 3 September, 20°LS, Ra 32,2 MJ/m²/hari. Ini pemeriksaan rumus astronomi, bukan validasi ET0 lokasi penelitian.

BMKG menyediakan prakiraan tiga-jaman. Tmin/Tmax dari titik tersebut harus diberi label ESTIMATED_FORECAST_EXTREMA. Pada kurva suhu yang sama, sampling jarang dapat melewatkan ekstrem; tetapi bias prakiraan dapat bekerja ke kedua arah. Karena itu, pernyataan ET0 pasti atau hampir pasti lebih rendah tidak dapat dikunci tanpa pembandingan lokal. FAO juga mencatat kecenderungan HS mengestimasi berlebih pada kondisi kelembapan tinggi. Ukur arah dan besar bias aktual; jangan memasang koreksi sepihak dari dugaan.

Label residual historis memakai ET0 berbasis suhu pengamatan dan Kc yang dibekukan. Operasi memakai suhu prakiraan yang sudah tersedia saat keputusan. Rumus sama tidak membuat kedua sumber setara. Simpan kedua jalur, ukur kesalahan menurut horizon, dan evaluasi keseluruhan sistem dengan prakiraan historis yang diarsipkan. Koreksi prakiraan, jika diperlukan, dilatih hanya pada periode pelatihan dan ikut dibekukan.

Perbaikan et0.py sebelum integrasi:

- Validasi angka finite, satuan, timezone, dan rentang fisik yang disetujui; tolak NaN/Inf dan tanggal tidak sah.
- Hitung slot waktu unik; duplikasi tidak menambah jumlah titik. Enam titik dapat berkumpul di sebagian hari, sehingga jumlah titik saja belum cukup. Periksa cakupan pagi/siang/malam sesuai aturan pilot yang dibekukan.
- Hari kurang data tetap muncul dengan status INCOMPLETE_FORECAST; jangan hilang dari kalender lalu menyebabkan pergeseran horizon.
- Bedakan waktu lokal dari UTC pada adapter. Fallback utc_datetime saat local_datetime tidak tersedia harus dikonversi sebelum agregasi harian.
- Simpan forecast_issued_at, valid_date, fetched_at, jumlah slot, cakupan jam, Tmin/Tmax, koordinat, koefisien, dan method_version.
- Koefisien dapat diubah melalui argumen fungsi saat ini tetapi METHOD_ID tetap HS_v1. Setiap konfigurasi koefisien harus memiliki versi atau hash konfigurasi berbeda; ID string tunggal belum menjamin pembekuan metode.
- Hasil max(0, ET0) dalam kode harus disertai penanda bila pembatasan terjadi; input tidak masuk akal tidak boleh berubah diam-diam menjadi data nol yang tampak valid.

## 6 Mesin neraca air dan batas hidraulik

Satuan wajib: h cm, ET0/ETc/Pe/residual mm/hari, luas ha, debit m³/detik, volume m³, lead time dan durasi jam. h petak, muka air saluran, dan elevasi permukaan tanah memiliki datum terpisah.

Tampungan ekuivalen terhadap permukaan tanah:

`S(h) = 10h`, untuk h ≥ 0; `S(h) = 10μh`, untuk h < 0.

Koefisien μ_dry digunakan pada pengeringan dan μ_fill pada pengisian sesuai hasil kalibrasi. Hubungan linier ini adalah penyederhanaan model yang harus diuji di petak. Nilai contoh tidak menjadi hasil pengukuran.

`ETc = Kc × ET0`

`F = ETc + R_adj − Pe`

| Mode | R_adj | Peran |
|---|---|---|
| M0 | 0 | Pembanding fisika sederhana |
| M1 | SPconstant | Baseline kehilangan tambahan konstan |
| M1B | SPconstant + b | Baseline dengan koreksi bias terbatas |
| M2 | residual_ML + b | Model hybrid; SPconstant tidak ditambah lagi |

Urutan waktu harus eksplisit: observed_at → decision_at → arrival_at → end_at. Pengamatan manual umumnya mendahului waktu keputusan. Kondisi perlu diperambat dari waktu pengamatan ke waktu keputusan menggunakan informasi yang benar-benar tersedia, kemudian ke saat air tiba menggunakan prakiraan yang sesuai. Fungsi recommend saat ini memeriksa umur h, tetapi memperlakukan nilainya sebagai h saat ini. Integrasi tidak boleh melewatkan selang tersebut.

Lintasan harus memotong interval pada pergantian tanggal lokal dan pergantian fase, bukan menganggap satu hari prakiraan selalu berarti 24 jam sejak tombol ditekan. daily_f_mm dalam fungsi trajectory saat ini hanya diindeks berdasarkan waktu relatif; buat adapter waktu atau perbarui antarmukanya sebelum operasi.

`I_refill = max(0, S(h_target) − S(h_arrival))`

`V_refill = 10 × A_ha × I_refill_mm`

Untuk Q petak dan F selama pengairan yang konstan:

`D_h = V_refill / (Q_petak − A_m² × F_application / 1000 / 86400) / 3600`

Penyebut harus positif. Tambahkan kehilangan selama D satu kali, karena kehilangan selama L sudah masuk h_arrival. Bila durasi melintasi hari atau fase dengan F berubah, lakukan integrasi per interval dan pencarian waktu target, bukan meneruskan pendekatan laju konstan tanpa penanda.

Muka air saluran tidak langsung berarti debit tersedia. Dibutuhkan kurva hubungan tinggi–debit atau metode hidraulik yang dikalibrasi, kondisi pintu, serta pembagian dan kehilangan air menuju petak. Q saluran dan Q_petak harus disimpan terpisah. Tanpa Q petak, tampilkan kebutuhan pengisian dengan status durasi belum dapat dihitung, bukan durasi asumsi yang terlihat operasional.

## 7 Profil petak dan kualitas data

Profil minimal mencakup ID, nama, geometri atau koordinat, elevasi, luas, datum pipa, μ_dry, μ_fill, lead time, tinggi pematang, fase tanaman, kalender tanam, Kc, ambang pemicu dan target per fase, sumber hujan, serta sumber suhu.

Setiap parameter memiliki nilai, satuan, status, sumber atau sitasi, metode penetapan, tanggal berlaku, versi, dan pemeriksa. Status sesuai modul: CALIBRATED, LITERATURE, EXAMPLE, PENDING. Tambahkan metadata penetapan lapangan agar luas atau koordinat terukur tidak keliru disebut hasil kalibrasi model. Secara implementasi awal status CALIBRATED dapat menandai nilai lapangan terverifikasi dengan assessment_method yang jelas; rencana skema berikutnya dapat menambahkan MEASURED melalui migrasi eksplisit.

Kualitas parameter berbeda dari kualitas data dan status validasi model. Kc dari literatur dapat diterima dalam protokol tanpa menjadi hasil kalibrasi lokal. Sebaliknya, semua parameter berstatus CALIBRATED tidak otomatis membuktikan model sudah tervalidasi. Field provisional yang ada di modul harus dilengkapi validation_status dan daftar alasan kelayakan.

Pisahkan tiga dimensi:

- Source type: MANUAL, SENSOR, BMKG_FORECAST, BBWS_OBSERVED, STATION_OBSERVED, DUMMY, SIMULATED.
- Parameter status: CALIBRATED, LITERATURE, EXAMPLE, PENDING.
- Run mode: DEMO, BASELINE_PROVISIONAL, BASELINE_VALIDATED, ML_SHADOW, ML_VALIDATED, MANUAL_REQUIRED.

Data dummy tetap dapat melewati Google Sheets. Karena itu, keberhasilan konektor tidak boleh mengubah source_type DUMMY menjadi SENSOR. Kualitas data 99,6% pada dummy harus diberi cakupan eksplisit, bukan dilaporkan sebagai keberhasilan alat lapangan.

## 8 Desain AI predictive

Target awal yang diusulkan adalah rata-rata residual kehilangan air pada jendela W selama 2–3 hari. Pilih dan bekukan W setelah pilot menunjukkan jumlah label valid dan keterukuran h. Model tidak memprediksi keputusan operator sebagai target.

Pada jendela kering yang memenuhi syarat:

`R_obs = 10 × μ_eff × (h_start − h_end) / W_days − mean(ETc_observed)`

μ_eff = 1 untuk jendela seluruhnya tergenang; μ_dry untuk jendela seluruhnya di bawah permukaan. Jendela melintasi nol dikeluarkan dari label awal. Harus ada bukti tidak terjadi hujan, irigasi, aliran masuk lain, limpasan, atau gangguan. Kedua titik ujung saja tidak membuktikan tidak ada kejadian di tengah jendela. Fungsi window_residual saat ini hanya mengecek durasi dan lintasan nol dari ujung; layanan pembentukan label harus mengecek seluruh catatan kejadian dan pengamatan antara.

Nilai negatif tidak langsung dipotong; tandai untuk pemeriksaan datum, pengukuran, ETc, dan kejadian yang terlewat. Jangan menganggap semua residual identik dengan perkolasi murni: ia juga dapat memuat rembesan dan galat model atau pengamatan.

Fitur kandidat: h dan tren masa lalu, kelembapan tanah dan trennya, fase dan umur tanaman, profil petak, riwayat hujan, serta cuaca yang tersedia pada waktu penerbitan prediksi. Hujan aktual masa depan dan suhu pengamatan masa depan tidak menjadi fitur keputusan. Ketersediaan tiap fitur dicatat dengan available_at; imputasi tidak boleh memakai data masa depan. ID petak perlu dievaluasi terhadap sasaran generalisasi, karena pengenal dapat membuat model menghafal petak.

Alur pelatihan: snapshot data → seleksi label valid → pemisahan kronologis → fit transformasi pada train → pemilihan model pada validasi → evaluasi satu kali pada test → penyimpanan model dan versi data. Pisahkan berdasarkan interval waktu aktual dan dukungan fitur/label, bukan jumlah baris. Singkirkan jendela yang melintasi batas train/valid/test dan jendela tumpang tindih yang menimbulkan kebocoran. Pakai cutoff waktu konsisten antarpetak. Jika ingin mengklaim berlaku di petak baru, tambahkan evaluasi petak yang ditahan dari pelatihan.

Bandingkan M0, M1, M1B, dan M2 pada waktu serta input yang setara. Laporkan galat residual, MAE/RMSE/bias h per horizon, kesalahan waktu mencapai ambang, kejadian terlambat mengairi, dan pelanggaran batas hidraulik. Uji dampak salah prakiraan suhu dan hujan. Ambang penerimaan ditetapkan sebelum test final berdasarkan risiko lapangan; belum ada angka akurasi yang diklaim.

Jalankan model dalam ML_SHADOW lebih dahulu: prediksi dicatat, keputusan masih memakai baseline yang disetujui. Jika model tidak memperbaiki hasil atau input di luar cakupan pelatihan, gunakan baseline tervalidasi bila inputnya lengkap; bila h atau parameter kritis tidak tersedia, gunakan MANUAL_REQUIRED. Baseline juga tidak boleh menghitung angka operasional dari input dummy.

Koreksi bias b, jika dipakai, hanya diperbarui setelah label aktual matang dan dibandingkan dengan prediksi apriori pada jendela yang sama. Parameter pembaruan dan batas bias dibekukan. Ini berbeda dari pelatihan ulang RF/ANN. Catatan APPROVE/MODIFY/DELAY adalah informasi keputusan, bukan bukti kebutuhan air atau label fisika.

## 9 Penyimpanan Neon yang direncanakan

| Entitas | Kolom atau hubungan utama | Tujuan |
|---|---|---|
| plots | plot_id, koordinat, elevasi, datum, active | Identitas petak |
| plot_profile_versions | profile_id, plot_id, effective_from/to, approved_by | Profil yang dapat direproduksi |
| plot_parameters | profile_id, name, value, unit, status, source, assessment_method | Provenansi parameter |
| crop_cycles dan phase_rules | cycle_id, plot_id, planting_date, phase, Kc, trigger, target, protocol_version | Kalender dan aturan fase |
| observations | obs_id, plot_id/station_id, variable, value, unit, observed_at, received_at, recorded_by, source_type, quality_flag | h manual dan data sensor/pengamatan |
| station_registry | station_id, sumber, lokasi, datum, interval, akses, batas keterwakilan | Metadata stasiun |
| weather_forecast_runs | run_id, issued_at, fetched_at, location_id, payload_hash, raw_payload | Arsip prakiraan per penerbitan |
| weather_forecast_values | run_id, valid_at, variable, value, unit, quality | Prakiraan bertanggal dan bersatuan |
| et0_daily | date, forecast_run_id atau observation_snapshot_id, temperature_source, method_version, config_hash, et0, quality | ET0 pengamatan dan prakiraan terpisah |
| irrigation_events | event_id, plot_id, arrived_at, started_at, ended_at, actual_volume, measurement_method | Pelaksanaan aktual |
| model_registry | model_version, target, W, feature_schema, et0_config, dataset_hash, cutoffs, metrics, approved_at | Versi AI dan kelayakan |
| recommendation_runs | rec_id, plot_id, decision_at, inputs_snapshot, profile_id, model_version, output, expiry, status | Hasil yang tidak berubah setelah diterbitkan |
| operator_decisions | decision_id, rec_id, action, mm, duration, note, actor, decided_at, supersedes_id | Keputusan dan koreksi berjejak |
| residual_labels dan prediction_log | support_start/end, available_at, validity, prediction_id, residual | Pelatihan dan evaluasi apriori |
| audit_log | actor, action, entity_id, timestamp, old/new version | Jejak perubahan |

Ini rancangan entitas, bukan SQL migrasi siap produksi. Hindari membuat dua sumber kebenaran untuk keputusan: perluas atau migrasikan tabel decisions dan pending_recommendations yang ada. Pertahankan akun, role, sesi, dan keputusan lama; tandai hasil lama sebagai LEGACY_SIMULATION bila sumbernya simulasi. Koreksi riwayat penelitian memakai revisi atau superseding record; edit dan delete UI lama perlu diatur ulang agar rekonstruksi keputusan tetap mungkin.

Gunakan timestamp berzona waktu dan tampilkan Asia/Jakarta. Tulis keputusan secara atomik dengan penguncian rekomendasi dan kunci idempotensi untuk mencegah dua operator mengonsumsi rekomendasi yang sama. Periksa kembali expiry dan versi input saat tombol diklik. Kegagalan DB tidak boleh menghasilkan pesan keputusan berhasil tersimpan permanen.

## 10 Perubahan dashboard per bagian

| Bagian | Isi yang dituju | Perilaku ketika input belum layak |
|---|---|---|
| Overview | h manual terbaru dan umurnya, kelembapan tanah, muka air saluran, hujan, status mode dan tindakan | Badge DEMO atau NEEDS_FIELD_OBSERVATION, bukan NORMAL menyeluruh |
| Sensor Monitoring | Grafik per perangkat/petak, sumber, waktu terakhir, mutu dan status perangkat | Pisahkan offline, data dummy, data terlambat, dan nilai model |
| Pengamatan Petak | Form h, petak, tanggal/jam, pencatat, catatan, riwayat dan koreksi | Tolak unit salah, waktu masa depan, duplikasi; nilai tidak wajar perlu verifikasi |
| Prediction and Recommendation | ET0, ETc, F, lintasan h, lead time, pemicu, target, volume, durasi, sumber dan versi | Tampilkan bagian yang dapat dihitung dan alasan bagian yang belum tersedia |
| Operator Decision | Snapshot rekomendasi, APPROVE/MODIFY/DELAY, alasan dan audit | Disable keputusan atas rekomendasi kedaluwarsa atau mode tidak operasional |
| Pelaksanaan dan Evaluasi | Catatan air tiba, pengairan aktual, volume dan h sesudahnya | Jangan mengisi pengukuran aktual dari simulasi |
| Alerts | Mutu/keterkinian data, ambang petak, keterbatasan hidraulik, serta peringatan BMKG terpisah | Tidak ada peringatan cuaca tidak berarti data atau petak aman |
| Admin | Profil petak, parameter, sumber stasiun, protokol, model aktif dan hak akses | Parameter PENDING tidak otomatis mendapat nilai contoh |

Pengamatan Petak dan Pelaksanaan dapat dibuat sebagai subhalaman agar menu utama tetap ringkas. Pertahankan gaya visual dashboard yang ada. Tambahkan informasi sumber pada kartu dan rincian metode pada panel penjelasan.

Aturan operator:

- APPROVE: jumlah dan durasi mengikuti snapshot; catatan opsional. Simpan sebagai keputusan, belum sebagai pelaksanaan.
- MODIFY: alasan wajib dan jumlah irigasi harus berubah dari rekomendasi menurut presisi satuan yang dibekukan. Perubahan durasi saja tidak memenuhi aturan yang disepakati. Hitung ulang volume, durasi yang konsisten dengan debit, dan kelayakan; blokir nilai tidak sah. Jika durasi juga bisa diedit, wajib periksa konsistensi jumlah–durasi–debit.
- DELAY: catatan opsional; tidak ada volume yang diotorisasi pada keputusan saat itu. Jadwalkan peninjauan ulang atau terbitkan rekomendasi baru setelah input diperbarui. Nilai nol pada keputusan tidak membuktikan pelaksanaan aktual nol.

## 11 Tahap pengembangan dan syarat kelulusan

Urutan berikut mengikuti dependensi. Durasi kalender belum ditetapkan karena kesiapan data dan lapangan lebih menentukan daripada jumlah menu.

| Tahap | Pekerjaan | Syarat sebelum berlanjut |
|---|---|---|
| 0 Audit dan baseline kode | Simpan versi arsip, runner tes, daftar gap, pisahkan DEMO | 39 tes dapat direproduksi; jalur rekomendasi aktif diketahui; tidak ada klaim field dari dummy |
| 1 Identitas petak dan h manual | Migrasi profil dan observations, form h, hak akses, sumber/status parameter | Input dan koreksi berjejak; pembacaan 1–2 kali/hari dapat disimpan; PENDING menghambat hasil yang memerlukannya |
| 2 Arsip cuaca dan ET0 | Simpan forecast vintages, adapter waktu, cakupan slot, ET0 terpisah pengamatan/prakiraan, sumber suhu | Unit dan tanggal konsisten; hari hilang tidak menggeser horizon; versi konfigurasi dapat ditelusuri |
| 3 Kalibrasi petak dan hidraulik | Survei luas/datum, μ, SPconstant, Kc/protokol, L, kurva debit dan distribusi | Parameter punya bukti; rekomendasi parsial ditandai; debit saluran tidak disamakan dengan debit petak |
| 4 Integrasi neraca air | Service per petak, observed_at→decision_at→arrival_at, lintas tanggal/fase, volume dan durasi | Uji integrasi pengamatan/DB/UI lulus; seluruh halaman memakai snapshot yang sama; rumus lama hanya DEMO |
| 5 Keputusan dan pelaksanaan | Aturan MODIFY lengkap, expiry/idempotensi, log pelaksanaan, pemisahan feedback | Dua operator tidak menduplikasi keputusan; perubahan jumlah dicek ulang; persetujuan tidak mengisi volume aktual |
| 6 Pilot baseline | Operasikan manual+sensor setelah terpasang, evaluasi ET0 dan h, mutu dan jadwal baca | Data memadai dan baseline memenuhi batas penerimaan lapangan yang ditetapkan |
| 7 Dataset dan AI offline | Label jendela valid, split temporal, RF vs baseline, ANN bila layak | Tidak ada kebocoran; W/fitur/protokol jelas; perbaikan pada data tahan uji dapat dijelaskan |
| 8 Shadow dan pembekuan | M2 tanpa kendali keputusan, uji fallback/drift, persetujuan versi penelitian | Target akurasi, keamanan agronomis dan hidraulik terpenuhi; model/ET0/parameter dibekukan |
| 9 Pengujian penelitian | Jalankan protokol petak/perlakuan, simpan actual inlet volume dan hasil panen | Hasil dapat diaudit; tidak ada retraining selama periode yang mensyaratkan pembekuan |
| 10 Peningkatan berikutnya | Otomasi h jika kebutuhan terbukti; pertimbangkan PM ketika input memadai | Evaluasi manfaat dan biaya; perubahan menghasilkan versi baru yang diuji ulang |

Prioritas sprint pertama: tabel profil dan input h manual, lalu arsip BMKG serta perbaikan validasi ET0. Hubungkan recommend setelah kontrak waktu, sumber data, dan parameter terpenuhi. ML ditempatkan sesudah pilot baseline menghasilkan label yang layak.

## 12 Pemeriksaan sebelum integrasi operasional

1. Waktu pengamatan tertinggal dari keputusan: prediksi memperhitungkan selang tersebut dan batas pergantian hari lokal.
2. Prediksi dari sore melewati tengah malam: prakiraan masuk ke tanggal yang benar.
3. Duplikasi enam slot BMKG tidak dianggap hari lengkap; NaN/Inf dan koordinat tidak valid ditolak.
4. Metode dengan koefisien berbeda tidak memiliki identitas konfigurasi sama.
5. Hujan tidak tersedia dibedakan dari hujan nol; skenario tanpa hujan diberi label.
6. h melintasi nol ditangani pada neraca; label pelatihan awal yang melintasi nol ditolak.
7. Jendela label dengan pengairan/hujan di tengah tetap ditolak walau dua ujung terlihat kering.
8. Data PENDING atau h usang menghasilkan alasan tindakan manual; data EXAMPLE tidak menjadi rekomendasi operasional.
9. μ, luas, lead time, Kc, debit, ambang dan target diperiksa domainnya; tes sukses sebelumnya belum mencakup semua input tidak sah.
10. Durasi pengairan melebihi horizon atau melintasi fase tidak dihitung menggunakan F konstan tanpa validasi cakupan.
11. MODIFY dengan jumlah sama ditolak; MODIFY yang melanggar debit atau target ditangani sebelum disimpan.
12. Klik ganda, dua operator, dan DB gagal tidak menghasilkan keputusan permanen ganda atau pesan sukses palsu.
13. Versi profil yang berubah tidak mengubah snapshot rekomendasi masa lalu.
14. Keputusan tidak masuk otomatis sebagai volume aktual, dan simulasi tidak membentuk label atau metrik penelitian.
15. Sistem tetap berguna dalam mode baseline saat model belum ada; jika baseline juga kehilangan input kritis, status menjadi MANUAL_REQUIRED.

## 13 Data yang masih perlu dilengkapi

Koordinat, elevasi, luas, datum, lokasi dan jumlah pipa; sumber suhu pengamatan; pos hujan BBWS dan mekanisme akses; μ_dry/μ_fill; SPconstant; fase dan Kc; ambang AWD dan target termasuk fase yang dilindungi; L; pengukuran debit dan distribusi ke petak; serta batas keterkinian, cakupan prakiraan, akurasi dan keselamatan yang akan dipakai pada pilot.

Nama lokasi administratif Panongan sudah ditemukan dalam konfigurasi BMKG. Lintang −6,8° pada tes adalah angka regresi contoh dan tidak menjadi koordinat penelitian. Nilai 50 ha pada tampilan lama tidak boleh dipakai sebagai luas penelitian tanpa bukti.

## 14 Dasar metode dan status evidence

Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998). Crop evapotranspiration: Guidelines for computing crop water requirements (FAO Irrigation and Drainage Paper No. 56). FAO. https://www.fao.org/4/x0490e/x0490e00.htm

Rujukan khusus: Bab 3, persamaan 20–25 dan 52; Contoh 8 untuk Ra; bagian estimasi data meteorologi yang hilang. Rujukan ini mendasari ET0, bukan mengesahkan parameter lokasi SOMAT.

Badan Meteorologi, Klimatologi, dan Geofisika. (n.d.). Data prakiraan cuaca terbuka BMKG. https://data.bmkg.go.id/prakiraan-cuaca/ (diakses 13 November 2026).

Sumber implementasi: arsip somat-dashboard.rar, terutama app.py, physics_engine.py, et0.py, bmkg_integration.py, sensor_sheet.py, dan dua berkas unit test. Uji ulang dilakukan tanpa menghubungkan akun, database produksi, atau perangkat fisik.

Pemilihan RF, struktur basis data, aturan pembekuan, ambang kualitas, dan tahapan pengembangan pada dokumen ini adalah rancangan sistem SOMAT. Daftar ini tidak menyatakan seluruh paper batch sebelumnya telah diaudit ulang atau sudah membuktikan kinerja model di lokasi penelitian.
