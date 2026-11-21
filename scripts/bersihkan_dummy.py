"""scripts/bersihkan_dummy.py - tandai pembacaan sensor DUMMY ('dummy-7hari') sebagai VOID. TIDAK menghapus baris.

Bawaan = PRATINJAU (tidak mengubah apa pun). Tambahkan --jalankan untuk benar-benar melakukannya.
Aman karena: hanya baris ACTIVE dengan sensor_id terisi dan plot_id kosong (pembacaan sensor, bukan catatan operator/h manual);
berjalan dalam satu transaksi; menulis satu baris audit; dapat dibalik (lihat perintah balik di akhir pratinjau).
Sambungan: variabel lingkungan SOMAT_DB_URL (isi sendiri di terminal)."""
import os
import sys

import psycopg2

TERM = "dummy-7hari"
RUN = "--jalankan" in sys.argv
URL = os.environ.get("SOMAT_DB_URL") or os.environ.get("DATABASE_URL")
if not URL:
    sys.exit("Isi dulu SOMAT_DB_URL.")
WHERE = ("meta::text ILIKE %s AND record_status='ACTIVE' AND sensor_id IS NOT NULL AND plot_id IS NULL "
         "AND variable <> 'h_cm'")
ARG = (f"%{TERM}%",)

con = psycopg2.connect(URL)
cur = con.cursor()
cur.execute(f"SELECT source_type, count(*), count(DISTINCT sensor_id), min(observed_at), max(observed_at) "
            f"FROM observations WHERE {WHERE} GROUP BY source_type ORDER BY 2 DESC", ARG)
rows = cur.fetchall()
total = sum(r[1] for r in rows)
print(f"Akan di-VOID ({TERM}):")
for st, n, ns, a, b in rows:
    print(f"  source_type={st}: {n} baris, {ns} sensor, {a:%Y-%m-%d %H:%M} s/d {b:%Y-%m-%d %H:%M}")
cur.execute("SELECT count(*) FROM observations WHERE meta::text ILIKE %s", ARG)
allm = cur.fetchone()[0]
print(f"Total cocok pola: {allm}; memenuhi syarat aman: {total}.")
if allm != total:
    print("  PERHATIAN: ada baris cocok yang TIDAK memenuhi syarat aman dan tidak akan disentuh.")
if not RUN:
    print("\nPRATINJAU saja; tidak ada yang diubah. Untuk menjalankan: py scripts\\bersihkan_dummy.py --jalankan")
    con.rollback()
    sys.exit(0)
if total == 0:
    sys.exit("Tidak ada yang perlu dilakukan.")
cur.execute(f"UPDATE observations SET record_status='VOID', note=LEFT(note || ' [VOID: data dummy dibersihkan]', 500) WHERE {WHERE}", ARG)
n = cur.rowcount
cur.execute("INSERT INTO audit_log (ts, username, action, detail) VALUES (NOW(), %s, %s, %s)",
            ("admin-skrip", "dummy_cleanup", f"{n} pembacaan sensor '{TERM}' ditandai VOID"))
con.commit()
print(f"\nSELESAI: {n} baris ditandai VOID (tidak dihapus). Dashboard hanya membaca baris ACTIVE, jadi data dummy hilang dari tampilan.")
print("Untuk membatalkan: UPDATE observations SET record_status='ACTIVE' WHERE note LIKE '%[VOID: data dummy dibersihkan]%';")
con.close()
