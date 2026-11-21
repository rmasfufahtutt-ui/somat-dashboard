"""scripts/cari_dummy.py - CARI (hanya baca) baris dummy/uji di basis data. TIDAK mengubah atau menghapus apa pun.

Pakai:  py scripts\\cari_dummy.py            (tanpa argumen: mencari 'dummy-7hari' dan 'test-powershell')
        py scripts\\cari_dummy.py kata1 kata2
Sambungan: variabel lingkungan SOMAT_DB_URL atau DATABASE_URL (isi sendiri di terminal Anda; jangan dibagikan).
Setiap kolom teks/json di semua tabel skema public dicari dengan ILIKE. Sesi dibuka READ ONLY, jadi aman."""
import os
import sys

import psycopg2
import psycopg2.extras

TERMS = sys.argv[1:] or ["dummy-7hari", "test-powershell"]
URL = os.environ.get("SOMAT_DB_URL") or os.environ.get("DATABASE_URL")
if not URL:
    sys.exit("Isi dulu variabel lingkungan SOMAT_DB_URL (lihat petunjuk), lalu jalankan lagi.")

con = psycopg2.connect(URL)
con.set_session(readonly=True, autocommit=True)
cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public' "
            "AND data_type IN ('text','character varying','json','jsonb') ORDER BY table_name, ordinal_position")
cols = cur.fetchall()
found = 0
for term in TERMS:
    print(f"\n=== '{term}' ===")
    for c in cols:
        t, k = c["table_name"], c["column_name"]
        cur.execute(f'SELECT count(*) AS n FROM "{t}" WHERE "{k}"::text ILIKE %s', (f"%{term}%",))
        n = cur.fetchone()["n"]
        if n:
            found += n
            cur.execute(f'SELECT * FROM "{t}" WHERE "{k}"::text ILIKE %s LIMIT 2', (f"%{term}%",))
            print(f"- {t}.{k}: {n} baris. Contoh:")
            for r in cur.fetchall():
                print("   ", {a: (str(b)[:60]) for a, b in list(r.items())[:8]})
print(f"\nTotal kecocokan: {found}. Tidak ada yang diubah.")
con.close()
