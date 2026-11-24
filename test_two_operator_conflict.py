"""Uji konflik dua operator pada jalur operasional (SQL sungguhan). HANYA untuk DB uji (somat_test).

Yang diuji: dua permintaan keputusan serentak untuk rekomendasi yang sama.
Perilaku yang diamati dari kode: yang pertama menang, yang kedua ditolak (already_handled).
Kesesuaian dengan Handbook v1.3 belum diverifikasi oleh tes ini.
"""
import threading
import uuid

import pytest

from test_decision_db import _publish, _setup

RONDE = 5


@pytest.fixture(autouse=True)
def _hanya_db_uji(pgdb):
    """Pengaman: berhenti jika database bukan somat_test."""
    with pgdb.transaction() as cur:
        cur.execute("SELECT current_database() AS db")
        nama = cur.fetchone()["db"]
    assert nama == "somat_test", f"BERHENTI: tes konflik hanya untuk somat_test, bukan '{nama}'"


def _race(repo, rec_id, specs):
    """Jalankan beberapa record_decision serentak (barrier). specs: (user, decision, mm, jam, kunci)."""
    barrier = threading.Barrier(len(specs))
    hasil = [None] * len(specs)

    def kerja(i, spec):
        user, decision, mm, jam, kunci = spec
        barrier.wait(timeout=10)
        try:
            did, dup = repo.record_decision(rec_id, user, decision, mm, jam, "uji konflik", kunci)
            hasil[i] = ("ok", did, dup)
        except repo.DecisionError as e:
            hasil[i] = ("decision_error", e.code)
        except Exception as e:  # kegagalan di luar logika keputusan (mis. koneksi)
            hasil[i] = ("error_lain", f"{type(e).__name__}: {str(e)[:200]}")

    threads = [threading.Thread(target=kerja, args=(i, s)) for i, s in enumerate(specs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return hasil


def _jumlah_keputusan(repo, rec_id):
    with repo.transaction() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM decisions WHERE rec_id=%s", (int(rec_id),))
        return int(cur.fetchone()["n"])


def test_dua_operator_kunci_berbeda_hanya_satu_menang(pgdb):
    repo = pgdb
    _setup(repo)
    for r in range(RONDE):
        out = _publish(repo)
        rid = out["rec_id"]
        specs = [("admin", "APPROVE", 10.0, None, f"konflik-{uuid.uuid4().hex}-a"),
                 ("admin", "DELAY", 0.0, 0.0, f"konflik-{uuid.uuid4().hex}-b")]
        hasil = _race(repo, rid, specs)
        ok = [h for h in hasil if h[0] == "ok"]
        assert not [h for h in hasil if h[0] == "error_lain"], f"ronde {r}: {hasil}"
        assert len(ok) == 1, f"ronde {r}: harus tepat satu pemenang, dapat {hasil}"
        kalah = [h for h in hasil if h[0] == "decision_error"]
        assert kalah == [("decision_error", "already_handled")], f"ronde {r}: {hasil}"
        assert _jumlah_keputusan(repo, rid) == 1, f"ronde {r}: baris keputusan tidak tepat satu"
        assert repo.get_run(rid)["status"] == "DECIDED", f"ronde {r}: status akhir bukan DECIDED"


def test_klik_ganda_serentak_kunci_sama_tidak_menggandakan(pgdb):
    repo = pgdb
    _setup(repo)
    for r in range(RONDE):
        out = _publish(repo)
        rid = out["rec_id"]
        kunci = f"klik-ganda-{uuid.uuid4().hex}"
        specs = [("admin", "DELAY", 0.0, 0.0, kunci), ("admin", "DELAY", 0.0, 0.0, kunci)]
        hasil = _race(repo, rid, specs)
        assert not [h for h in hasil if h[0] == "error_lain"], f"ronde {r}: {hasil}"
        ok = [h for h in hasil if h[0] == "ok"]
        assert len(ok) >= 1, f"ronde {r}: tidak ada yang berhasil: {hasil}"
        if len(ok) == 2:
            assert ok[0][1] == ok[1][1], f"ronde {r}: dua id keputusan berbeda: {hasil}"
        for h in hasil:
            if h[0] == "decision_error":
                assert h[1] == "already_handled", f"ronde {r}: {hasil}"
        assert _jumlah_keputusan(repo, rid) == 1, f"ronde {r}: keputusan terduplikasi"
