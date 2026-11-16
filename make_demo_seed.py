"""Bangun ulang berkas seed data demo: python make_demo_seed.py
Jalankan hanya bila skenario/VERSION di demo_data.py berubah, lalu commit demo_seed/somat_demo_seed.sqlite3."""
import demo_data

if __name__ == "__main__":
    r = demo_data.build_seed()
    print("Seed dibuat:", r["path"], f"({r['bytes'] // 1024} KB)", r["dataset_id"])
