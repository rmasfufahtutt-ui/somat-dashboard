"""Hak aksi diperiksa di BACKEND (repositori operasional), bukan hanya di UI. Tes ini tidak butuh database:
penolakan harus terjadi SEBELUM database disentuh (bila penjaga hilang, tes gagal karena galat lain)."""
import pytest

import repository as repo
import rights


@pytest.fixture(autouse=True)
def _reset():
    yield
    rights.force(None)


def U(name, role):
    return {"username": name, "role": role}


# ---- aturan murni ----
def test_no_session_is_rejected():
    assert rights.evaluate("decision.record", None, "x") == "no_session"
    assert rights.evaluate("decision.record", {}, "x") == "no_session"


def test_actor_must_equal_session_user():
    assert rights.evaluate("decision.record", U("ani", "operator"), "budi") == "actor_mismatch"
    assert rights.evaluate("decision.record", U("ani", "admin"), "budi") == "actor_mismatch"


def test_admin_can_do_everything():
    for a in rights.KNOWN_ACTIONS:
        assert rights.evaluate(a, U("adm", "admin"), "adm", owner="orang_lain") is None, a


def test_admin_only_actions_reject_operator_and_viewer():
    for a in rights.ADMIN_ONLY:
        for role in ("operator", "viewer", "kustom"):
            assert rights.evaluate(a, U("u", role), "u") == "admin_only", (a, role)


def test_viewer_cannot_write_anything():
    for a in rights.PAGE_FOR:
        assert rights.evaluate(a, U("v", "viewer"), "v", owner="v") == "page_forbidden", a


def test_operator_owner_rule():
    op = U("ani", "operator")
    assert rights.evaluate("decision.record", op, "ani") is None
    assert rights.evaluate("observation.add", op, "ani") is None
    assert rights.evaluate("decision.correct", op, "ani", owner="ani") is None
    assert rights.evaluate("decision.correct", op, "ani", owner="budi") == "not_owner"
    assert rights.evaluate("observation.void", op, "ani", owner="budi") == "not_owner"
    assert rights.evaluate("execution.void", op, "ani", owner=None) == "not_owner"      # rekaman tidak ada/pemilik tak diketahui


def test_page_flag_from_role_table_is_respected():
    assert rights.evaluate("decision.record", U("c", "kustom"), "c", page_ok=False) == "page_forbidden"
    assert rights.evaluate("decision.record", U("c", "kustom"), "c", page_ok=True) is None


def test_unknown_action_is_strictest():
    assert rights.evaluate("sesuatu.baru", U("ani", "operator"), "ani") == "admin_only"


# ---- penjaga terpasang di setiap penulisan repositori ----
GUARDED = [
    ("upsert_plot", ("P1", "n", "ani")),
    ("save_profile_version", ("P1", [], [], "ani")),
    ("add_crop_cycle", ("P1", "2026-01-01", "v", "ani")),
    ("add_h_observation", ("P1", -5.0, "2026-01-01T00:00:00+00:00", "ani")),
    ("record_decision", (1, "ani", "DELAY", 0, 0, "", "k")),
    ("void_decision", (1, "ani", "salah")),
    ("add_irrigation_event", ("P1", 1, 1, None, None, None, 1.0, None, "m", None, None, "", "ani")),
]


@pytest.mark.parametrize("fn,args", GUARDED)
def test_viewer_rejected_before_database(fn, args):
    rights.force(("ani", "viewer"))
    with pytest.raises(PermissionError):
        getattr(repo, fn)(*args)


@pytest.mark.parametrize("fn,args", GUARDED)
def test_no_session_rejected_before_database(fn, args):
    rights.force(None)
    with pytest.raises(PermissionError) as e:
        getattr(repo, fn)(*args)
    assert e.value.args[0] == "no_session"


@pytest.mark.parametrize("fn,args", GUARDED)
def test_spoofed_actor_rejected(fn, args):
    rights.force(("orang_lain", "admin"))
    with pytest.raises(PermissionError) as e:
        getattr(repo, fn)(*args)
    assert e.value.args[0] == "actor_mismatch"


def test_operator_cannot_void_decision_or_change_parameters():
    rights.force(("ani", "operator"))
    for fn, args in (("void_decision", (1, "ani", "x")), ("save_profile_version", ("P1", [], [], "ani")),
                     ("upsert_plot", ("P1", "n", "ani")), ("add_crop_cycle", ("P1", "2026-01-01", "v", "ani"))):
        with pytest.raises(PermissionError) as e:
            getattr(repo, fn)(*args)
        assert e.value.args[0] == "admin_only", fn


def test_correction_and_void_of_someone_elses_record_rejected(monkeypatch):
    monkeypatch.setattr(repo, "_owner_of", lambda *a, **k: "budi")
    rights.force(("ani", "operator"))
    for fn, args in (
        ("supersede_decision", (1, "ani", "MODIFY", 1.0, 1.0, "", "alasan")),
        ("void_observation", (1, "ani", "salah")),
        ("add_h_observation", ("P1", -5.0, "2026-01-01T00:00:00+00:00", "ani", "", "OK", 7)),
        ("void_irrigation_event", (1, "ani", "salah")),
        ("add_irrigation_event", ("P1", 1, 1, None, None, None, 1.0, None, "m", None, None, "", "ani", 7)),
    ):
        with pytest.raises(PermissionError) as e:
            getattr(repo, fn)(*args)
        assert e.value.args[0] == "not_owner", fn


def test_every_repository_write_has_a_guard():
    import inspect
    for fn in ("upsert_plot", "save_profile_version", "add_crop_cycle", "add_h_observation", "void_observation",
               "record_decision", "supersede_decision", "void_decision", "add_irrigation_event",
               "void_irrigation_event"):
        assert "rights.authorize(" in inspect.getsource(getattr(repo, fn)), fn


def test_system_context_is_explicit_and_scoped():
    rights.force(None)
    with rights.system():
        rights.authorize("decision.void", "apa-saja")        # tidak melempar
    with pytest.raises(PermissionError):
        rights.authorize("decision.void", "apa-saja")


# ---- konsumen QC berversi dan bias (bukan hanya tabel) ----
def test_summarize_versioned_qc():
    import sensor_qc
    from datetime import datetime, timezone
    t1, t2 = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [{"action": "USE", "rule_version": "v1", "available_at": t1},
            {"action": "EXCLUDE_FROM_AUTOMATIC_USE", "rule_version": "v1", "available_at": t2},
            {"action": "USE_WITH_WARNING", "rule_version": "v2", "available_at": t1}]
    s = sensor_qc.summarize_versioned(rows)
    assert s["n"] == 3 and s["actions"]["EXCLUDE_FROM_AUTOMATIC_USE"] == 1
    assert s["rule_versions"] == {"v1": 2, "v2": 1} and s["latest_available_at"] == t2
    assert sensor_qc.summarize_versioned([])["n"] == 0


def test_bias_shadow_is_recorded_but_never_applied():
    import recommendation_service as rs
    from datetime import datetime, timezone
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class R:
        @staticmethod
        def bias_for_issue_db(plot, model, at):
            return 0.4, "ACTIVE", {"n_updates": 3}

    got = rs.bias_shadow(R, "P1", now)
    assert got["applied"] is False and got["status"] == "ACTIVE" and got["bias_mm_day"] == 0.4 and got["model"] == "M1B"

    class Broken:
        @staticmethod
        def bias_for_issue_db(*a):
            raise RuntimeError("db")

    assert rs.bias_shadow(Broken, "P1", now)["status"] == "UNAVAILABLE"
    assert rs.bias_shadow(object(), "P1", now) is None        # DEMO: tidak ada state bias
