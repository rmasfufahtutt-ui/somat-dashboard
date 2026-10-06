# SOMAT — Smart Adaptive Irrigation Management System

> **PROTOTYPE — SIMULATED DATA.** Seluruh data pada prototype ini dibangkitkan
> secara simulasi untuk mendemonstrasikan konsep SOMAT. Ini bukan data
> penelitian aktual dan bukan sistem operasional.

## Tentang

SOMAT adalah *decision-support system* untuk manajemen irigasi. Fokusnya bukan
AI yang kompleks, melainkan mengintegrasikan prediksi kebutuhan air dengan
kendala hidraulik untuk menghasilkan rekomendasi operasi yang dapat digunakan
operator. Operator tetap pengambil keputusan akhir; sistem tidak menggerakkan
pintu irigasi secara otomatis.

Alur konsep:

Observe → Predict → Hydraulic Feasibility Check → Recommend →
Human Validation → Operate → Feedback

## Fitur prototype

- Overview: kartu status kondisi terbaru
- Monitoring: grafik time-series 30 hari (Plotly)
- Water Demand Prediction: logika aturan sederhana (bukan model AI final)
- Hydraulic Feasibility: cek debit, muka air, dan batas pintu
- SOMAT Recommendation: jumlah, durasi, prioritas, dan alasan
- Operator Decision: APPROVE / MODIFY / DELAY + Decision Log
- Alerts / Anomaly: peringatan simulasi
- Feedback Loop: Recommendation → Operator Decision → Simulated Field Response

## Cara menjalankan di komputer

```
conda create -n somat python=3.12
conda activate somat
pip install -r requirements.txt
streamlit run app.py
```

Lalu buka `http://localhost:8501` di browser.

## Catatan penting

- Semua angka asumsi (luas areal, jam pemberian air, batas muka air,
  kapasitas pintu) ada di blok `ASSUMPTIONS` pada `app.py` dan hanya contoh.
- Logika prediksi, hidraulik, dan rekomendasi adalah rule-based prototype,
  dirancang agar mudah diganti model yang lebih baik.
- Decision Log hanya disimpan selama session dan hilang saat halaman di-refresh.

## Teknologi

Python, Streamlit, Pandas, NumPy, Plotly.