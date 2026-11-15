"""views/guide.py - Panduan Demo: alur presentasi, diagram arsitektur, tabel hak edit/koreksi/void, dan batasan."""
from __future__ import annotations

import streamlit as st

import demo_mode
from i18n import L
from ui_kit import banner, table

ARCH_DOT = r"""
digraph G {
  rankdir=LR; fontname="Helvetica"; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, fillcolor="#EAF2FF", color="#2F80ED"];
  edge [fontname="Helvetica", fontsize=9, color="#667"];
  user [label="Pengguna\n(login / akun demo)", fillcolor="#FFF4E0", color="#E4A11B"];
  app  [label="app.py\nmode: OPERASIONAL | DEMO\n+ banner DEMO"];
  router [label="repo_router.py\n(pilih backend per sesi)"];
  subgraph cluster_ops { label="OPERASIONAL"; style="rounded,dashed"; color="#16884A"; fontcolor="#16884A";
    ops [label="repository.py\nNeon / PostgreSQL", fillcolor="#E5F7EC", color="#16884A"];
    hub [label="data_hub\n(Google Sheets, BMKG)", fillcolor="#E5F7EC", color="#16884A"]; }
  subgraph cluster_demo { label="DEMO PENELITIAN (terpisah)"; style="rounded,dashed"; color="#D85A10"; fontcolor="#D85A10";
    demo [label="demo_repository.py\nSQLite lokal (is_demo, dataset_id)", fillcolor="#FFE9DC", color="#D85A10"];
    gen  [label="demo_data.py\n6 petak, >=35 hari,\nskenario dari mesin", fillcolor="#FFE9DC", color="#D85A10"];
    wx   [label="demo_weather.py\ncuaca sintetis berlabel", fillcolor="#FFE9DC", color="#D85A10"];
    ml   [label="demo_ml.py\nRandom Forest (data sintetis)", fillcolor="#FFE9DC", color="#D85A10"]; }
  engine [label="Mesin SOMAT (SAMA)\nphysics_engine + recommendation_service\n+ et0 + labels", fillcolor="#F1E9FF", color="#7C3AED"];
  bmkg [label="BMKG asli\n(prakiraan)", fillcolor="#E5F7EC", color="#16884A"];
  user -> app; app -> router; router -> ops [label="OPERASIONAL"]; router -> demo [label="DEMO"];
  gen -> demo [label="seed / reset"]; wx -> engine [label="suhu & hujan skenario"]; ml -> engine [label="residual M2"];
  engine -> ops [label="run baseline"]; engine -> demo [label="run 'DEMO' + keputusan 'DEMO'"];
  bmkg -> hub; hub -> engine [label="baca saja (opsional di DEMO)"];
}
"""

RIGHTS = [
    # (objek, aksi, Admin, Operator, Pengamat)
    ("Pengamatan h", "Input baru", "ya", "ya", "tidak"),
    ("Pengamatan h", "Koreksi (record baru, lama SUPERSEDED)", "semua", "milik sendiri", "tidak"),
    ("Pengamatan h", "VOID (beralasan, tidak dihapus)", "semua", "milik sendiri", "tidak"),
    ("Rekomendasi", "Terbitkan (immutable)", "ya", "ya", "tidak"),
    ("Rekomendasi", "Edit / hapus", "tidak", "tidak", "tidak"),
    ("Keputusan (APPROVE/MODIFY/DELAY)", "Catat (atomik, idempoten)", "ya", "ya", "tidak"),
    ("Keputusan", "Edit = koreksi (record baru)", "semua", "milik sendiri", "tidak"),
    ("Keputusan", "Delete = VOID (beralasan)", "ya", "tidak", "tidak"),
    ("Pelaksanaan (simulasi)", "Catat", "ya", "ya", "tidak"),
    ("Pelaksanaan (simulasi)", "VOID", "semua", "milik sendiri", "tidak"),
    ("Data awal demo", "Muat / Kembalikan skenario awal / Kosongkan / Ekspor", "ya", "tidak", "tidak"),
    ("Model AI demo", "Latih", "ya", "tidak", "tidak"),
]

STEPS_ID = [
    ("Masuk", "Pilih **Demo sebagai Admin** di layar masuk (tanpa database produksi), atau masuk dengan akun nyata lalu pilih ruang kerja **Demo penelitian** di sidebar. Banner oranye DEMO PENELITIAN harus tampak."),
    ("Muat data", "Admin → **Demo** → **Muat data demo** (aman diulang: tidak menggandakan). **Kembalikan skenario awal** menghapus semua perubahan dan memuat ulang."),
    ("Ringkasan", "Menu **Ringkasan** menampilkan enam petak DEMO-P01…P06, enam skenario berbeda, dan grafik riwayat h/sensor sintetis."),
    ("Pengamatan", "Menu **Pengamatan Lapangan** → pilih petak → **Isi contoh** → simpan. Coba koreksi dan VOID. Rekomendasi memakai pengamatan aktif terbaru."),
    ("Prediksi", "Menu **Prediksi & Rekomendasi**: pilih sumber suhu (sintetis atau BMKG asli), skenario hujan, dan model M1/M2. Panel **Mengapa rekomendasi ini?** menjelaskan tiap langkah. Terbitkan (simulasi)."),
    ("Keputusan", "Menu **Keputusan Operator**: APPROVE (jumlah sama), MODIFY (jumlah harus berubah + alasan), atau DELAY. Semua berlabel SIMULASI."),
    ("Pelaksanaan", "Menu **Pelaksanaan Irigasi**: **Isi contoh** → simpan; lihat rantai SOMAT → operator → realisasi simulasi dan evaluasi prediksi vs h."),
    ("Model AI", "Admin → Demo → **Latih model demo**; lalu di Prediksi lihat perbandingan M1 vs M2 (tanpa SPconstant ganda)."),
]

LIMITS_ID = [
    "Semua petak, sensor, parameter, riwayat, keputusan, dan pelaksanaan di ruang DEMO **sintetis**; parameter berstatus CONTOH sehingga mode run selalu DEMO.",
    "Model AI dilatih dari korpus sintetis yang dibuat berbeda dari SPconstant; metriknya menunjukkan alur bekerja, **bukan akurasi lapangan**.",
    "Prakiraan BMKG yang dipakai (bila dipilih) adalah data asli dengan keterkinian apa adanya; bila kosong, rekomendasi menjadi INCOMPLETE_FORECAST, bukan diisi data karangan. Hujan BMKG tidak diprakirakan: hujan selalu skenario eksplisit.",
    "Cuaca sintetis diindeks relatif terhadap tanggal jangkar dataset; bila demo dibuka berhari-hari kemudian, gunakan **Geser waktu** atau **Kembalikan skenario awal** agar skenario kembali sesuai rancangan.",
]


def render(ctx=None):
    st.header(L("📘 Demo Guide", "📘 Panduan Demo"))
    if demo_mode.is_demo():
        banner(L(demo_mode.BANNER_EN, demo_mode.BANNER_ID), "warn")
    st.subheader(L("Architecture: operational vs research demo", "Arsitektur: operasional vs demo penelitian"))
    try:
        st.graphviz_chart(ARCH_DOT, width="stretch")
    except TypeError:
        st.graphviz_chart(ARCH_DOT, use_container_width=True)
    st.caption(L("Both spaces share the same engine; only inputs and the storage path differ. The demo never writes to the operational database.",
                 "Kedua ruang memakai mesin yang sama; hanya masukan dan jalur penyimpanan yang berbeda. Demo tidak pernah menulis ke database operasional."))
    st.subheader(L("Presentation flow", "Alur presentasi"))
    for i, (t, d) in enumerate(STEPS_ID, start=1):
        st.markdown(f"{i}. **{t}** — {d}")
    st.subheader(L("Who may edit, correct or void", "Siapa boleh mengedit, mengoreksi, atau membatalkan"))
    table([{L("Object", "Objek"): o, L("Action", "Aksi"): a, "Admin": ad, "Operator": op, L("Viewer", "Pengamat"): v}
           for o, a, ad, op, v in RIGHTS], key="guide_rights")
    st.caption(L("Nothing is physically deleted: corrections create new records and the old ones become SUPERSEDED; cancellations are VOID with a reason. "
                 "Permissions are checked again in the backend, not only in the buttons.",
                 "Tidak ada yang dihapus fisik: koreksi membuat record baru dan yang lama menjadi SUPERSEDED; pembatalan berupa VOID beralasan. "
                 "Izin diperiksa ulang di backend, bukan hanya pada tombol."))
    st.subheader(L("What is real and what is synthetic", "Yang nyata dan yang sintetis"))
    table([{L("Item", "Item"): "BMKG", L("In the demo", "Di demo"): L("Real, external source; shown with freshness; optional temperature driver", "Asli, sumber eksternal; tampil dengan keterkinian; pilihan sumber suhu"), L("Label", "Label"): "BMKG"},
           {L("Item", "Item"): L("Plots, sensors, h history", "Petak, sensor, riwayat h"), L("In the demo", "Di demo"): L("Synthetic, fixed seed", "Sintetis, seed tetap"), L("Label", "Label"): "DEMO / SINTETIS"},
           {L("Item", "Item"): L("Parameters", "Parameter"), L("In the demo", "Di demo"): L("Example values, not calibrated", "Nilai contoh, belum dikalibrasi"), L("Label", "Label"): "EXAMPLE"},
           {L("Item", "Item"): L("Decisions & execution", "Keputusan & pelaksanaan"), L("In the demo", "Di demo"): L("Simulated, stored with source DEMO", "Simulasi, tersimpan dengan source DEMO"), L("Label", "Label"): "SIMULASI"},
           {L("Item", "Item"): "AI M2", L("In the demo", "Di demo"): L("Random Forest trained on synthetic data", "Random Forest dilatih dari data sintetis"), L("Label", "Label"): "MODEL AI DEMONSTRASI"}],
          key="guide_real")
    st.subheader(L("Limits to state honestly", "Batasan yang perlu disampaikan"))
    for t in LIMITS_ID:
        st.markdown("- " + t)
