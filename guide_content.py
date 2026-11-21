"""guide_content.py - isi Panduan Pengguna (EN/ID) per peran. Data murni (tanpa Streamlit) agar mudah dites.

Aturan isi: hanya menjelaskan apa yang dilakukan pengguna di aplikasi; tidak menyatakan model tervalidasi, tidak memuat ukuran
pipa/parameter contoh, dan selalu menegaskan bahwa SOMAT menyarankan dan operator memutuskan."""
from __future__ import annotations

# (kunci, ikon, judul_en, judul_id, isi_en, isi_id)  isi = markdown
SECTIONS = (
    ("start", "🚀", "Start here", "Mulai di sini",
     """**What SOMAT does.** It estimates the field water level (h) ahead from your manual h readings, weather and plot
parameters, and suggests whether and how much to irrigate. **SOMAT only suggests. The operator decides.** No gate is
moved automatically, and approving a recommendation does not mean water has flowed.

**The daily loop (5 steps)**
1. **Observe** – open *Sensor Monitoring*; check the sensors are updating.
2. **Record h** – in *Field Observations* enter the manual water-level reading (h, cm) with its real time.
3. **Predict** – in *Prediction & Recommendation* run the calculation and publish the recommendation.
4. **Decide** – in *Operator Decision* choose **Approve**, **Modify** (change the amount) or **Delay**.
5. **Record what really happened** – in *Irrigation Execution* enter the actual volume and times.

**Example vs real data.** A banner shows the mode. Anything marked **DEMO / EXAMPLE** is practice data: never use it for a
field decision.""",
     """**Fungsi SOMAT.** SOMAT memperkirakan tinggi muka air petak (h) ke depan dari pengamatan h manual, cuaca, dan parameter
petak, lalu menyarankan perlu tidaknya irigasi dan berapa banyak. **SOMAT hanya menyarankan. Operator yang memutuskan.**
Tidak ada pintu yang digerakkan otomatis, dan menyetujui rekomendasi tidak berarti air sudah mengalir.

**Alur harian (5 langkah)**
1. **Amati** – buka *Monitoring Sensor*; pastikan sensor terus memperbarui data.
2. **Catat h** – di *Pengamatan Lapangan* isi hasil pembacaan h manual (cm) dengan waktu pengukuran yang sebenarnya.
3. **Prediksi** – di *Prediksi & Rekomendasi* jalankan perhitungan lalu terbitkan rekomendasi.
4. **Putuskan** – di *Keputusan Operator* pilih **Setujui**, **Ubah** (ganti jumlahnya), atau **Tunda**.
5. **Catat kenyataan di lapangan** – di *Pelaksanaan Irigasi* isi volume dan waktu aktual.

**Data contoh vs data nyata.** Spanduk di atas menunjukkan mode. Apa pun yang bertanda **DEMO / CONTOH** adalah data latihan:
jangan dipakai untuk keputusan di lapangan."""),

    ("operator", "👷", "Operator guide", "Panduan operator",
     """**Before you record h**
- Use the time the reading was *taken*, not the time you type it.
- A wrong entry is never overwritten: use **Correct** (creates a new record, the old one is kept) or **Void** with a reason.
  You can correct or void your own records; an administrator can do it for any record.

**Making a decision**
- A recommendation can be decided only while it is *PUBLISHED* and not expired, and only if the plot profile and the latest
  h reading are unchanged since it was published. Otherwise SOMAT refuses and tells you why; publish a new one.
- **Approve** = follow the suggested amount. **Modify** = enter your own amount/duration (give a reason in the note).
  **Delay** = do not irrigate now.
- If your role cannot record decisions, the buttons stay disabled. The check is also made on the server, not only on screen.
- Correcting a decision keeps the old one (marked superseded). Deleting (void) a decision is for administrators.

**After irrigating** – enter the *actual* volume, discharge (if measured), start/end time and, if measured, h after
irrigation in *Irrigation Execution*. This is what lets the system be evaluated honestly.

**What the statuses mean**
| Status | Meaning | What you do |
|---|---|---|
| OK / TARGET_NOT_REACHABLE | A calculation exists | Review, then decide |
| MANUAL_REQUIRED | SOMAT cannot compute safely | Decide manually; SOMAT does not guess |
| MISSING_PARAMETER | A critical plot parameter is still PENDING | Ask the administrator to complete it |
| INCOMPLETE_FORECAST | Forecast for a day is incomplete | Decide manually or wait for the next fetch |
| STALE_OBSERVATION | Last manual h is too old | Take and record a new h reading |
| DEMO | Example run | Practice only, never a field decision |""",
     """**Sebelum mencatat h**
- Pakai waktu pembacaan *dilakukan*, bukan waktu Anda mengetik.
- Catatan yang salah tidak pernah ditimpa: gunakan **Koreksi** (membuat catatan baru, yang lama tetap tersimpan) atau **Batalkan
  (VOID)** dengan alasan. Anda dapat mengoreksi atau membatalkan catatan Anda sendiri; administrator dapat melakukannya untuk
  semua catatan.

**Mengambil keputusan**
- Rekomendasi hanya dapat diputuskan selama berstatus *PUBLISHED* dan belum kedaluwarsa, serta bila profil petak dan pengamatan
  h terbaru tidak berubah sejak rekomendasi diterbitkan. Bila tidak, SOMAT menolak dan menjelaskan alasannya; terbitkan yang baru.
- **Setujui** = ikuti jumlah yang disarankan. **Ubah** = isi jumlah/durasi sendiri (tulis alasan di catatan). **Tunda** =
  tidak mengairi sekarang.
- Bila peran Anda tidak boleh mencatat keputusan, tombol tetap nonaktif. Pemeriksaannya juga dilakukan di server, bukan hanya di layar.
- Mengoreksi keputusan menyimpan yang lama (ditandai digantikan). Menghapus (VOID) keputusan hanya untuk administrator.

**Setelah mengairi** – isi volume *aktual*, debit (bila diukur), waktu mulai/selesai, dan h setelah irigasi (bila diukur) di
*Pelaksanaan Irigasi*. Data inilah yang membuat sistem bisa dievaluasi secara jujur.

**Arti status**
| Status | Arti | Yang Anda lakukan |
|---|---|---|
| OK / TARGET_NOT_REACHABLE | Perhitungan tersedia | Tinjau, lalu putuskan |
| MANUAL_REQUIRED | SOMAT tidak dapat menghitung dengan aman | Putuskan manual; SOMAT tidak menebak |
| MISSING_PARAMETER | Parameter petak yang kritis masih PENDING | Minta administrator melengkapi |
| INCOMPLETE_FORECAST | Prakiraan suatu hari tidak lengkap | Putuskan manual atau tunggu penarikan berikutnya |
| STALE_OBSERVATION | h manual terakhir terlalu lama | Ukur dan catat h yang baru |
| DEMO | Run contoh | Hanya latihan, bukan keputusan lapangan |"""),

    ("admin", "🛡️", "Administrator guide", "Panduan administrator",
     """**Users and roles** – *Administration → Users / Roles*. Built-in roles: administrator, operator, viewer. Custom roles
get only the tabs you tick. You cannot remove or deactivate the last active administrator.

**Plots and parameters** – *Administration → Plots & parameters*.
- Every parameter carries a status: **CALIBRATED** (needs assessment method, who checked, and date), **LITERATURE**,
  **EXAMPLE** or **PENDING**. Saving creates a *new profile version*; old versions are kept.
- A critical parameter left **PENDING** makes SOMAT refuse to compute (MISSING_PARAMETER). This is intentional.
- Changing the profile after a recommendation was published blocks deciding on that recommendation; publish again.
- Start a new crop cycle (planting date) only when a new season really starts; it closes the active one.

**Audit** – every decision, correction, void and parameter change is written to the audit log with who and when. Rights
are enforced on the server: hiding a button is not what protects the data.""",
     """**Pengguna dan peran** – *Administrasi → Pengguna / Peran*. Peran bawaan: administrator, operator, viewer. Peran khusus
hanya mendapat tab yang Anda centang. Administrator aktif terakhir tidak dapat dihapus atau dinonaktifkan.

**Petak dan parameter** – *Administrasi → Petak & parameter*.
- Setiap parameter punya status: **CALIBRATED** (butuh metode penilaian, pemeriksa, dan tanggal), **LITERATURE**, **EXAMPLE**,
  atau **PENDING**. Menyimpan membuat *versi profil baru*; versi lama tetap tersimpan.
- Parameter kritis yang masih **PENDING** membuat SOMAT menolak menghitung (MISSING_PARAMETER). Ini disengaja.
- Mengubah profil setelah rekomendasi terbit menghalangi keputusan atas rekomendasi itu; terbitkan ulang.
- Mulai siklus tanam baru (tanggal tanam) hanya saat musim baru benar-benar dimulai; siklus aktif akan ditutup.

**Audit** – setiap keputusan, koreksi, VOID, dan perubahan parameter tercatat di log audit beserta siapa dan kapan. Hak
akses ditegakkan di server: menyembunyikan tombol bukan yang melindungi data."""),

    ("limits", "⚠️", "What SOMAT does not claim", "Batas klaim SOMAT",
     """- SOMAT is a **prototype decision-support tool**, not an automatic controller and not a field-validated model.
- Recommendations are only as good as the latest manual h reading, the forecast and the plot parameters. When any of these is
  missing or too old, SOMAT says so instead of guessing.
- The forecast comes from BMKG. A day without enough forecast points is shown as incomplete, never filled in.
- If no rain is forecast, the calculation uses an explicit *no-rain scenario*; it is a scenario, not a BMKG forecast.
- Example (DEMO) data and the operational data are kept apart and are never mixed.
- The AWD tube (pipe) geometry is still a design item to be confirmed; no sizes are assumed by the app.""",
     """- SOMAT adalah **alat bantu keputusan tingkat prototipe**, bukan pengendali otomatis dan bukan model yang sudah divalidasi di lapangan.
- Mutu rekomendasi bergantung pada pengamatan h manual terbaru, prakiraan, dan parameter petak. Bila salah satunya hilang atau
  terlalu lama, SOMAT menyatakannya, bukan menebak.
- Prakiraan berasal dari BMKG. Hari dengan titik prakiraan yang kurang ditampilkan sebagai tidak lengkap, tidak pernah diisi sendiri.
- Bila hujan tidak diprakirakan, perhitungan memakai *skenario tanpa hujan* yang eksplisit; itu skenario, bukan prakiraan BMKG.
- Data contoh (DEMO) dan data operasional dipisahkan dan tidak pernah dicampur.
- Geometri tabung AWD (pipa) masih butuh konfirmasi; aplikasi tidak mengasumsikan ukuran apa pun."""),
)


def sections():
    return SECTIONS


def for_role(role: str):
    """Bagian yang relevan: semua orang melihat 'start' dan 'limits'; panduan administrator hanya untuk admin."""
    out = []
    for s in SECTIONS:
        if s[0] == "admin" and role != "admin":
            continue
        if s[0] == "operator" and role == "viewer":
            continue
        out.append(s)
    return out
