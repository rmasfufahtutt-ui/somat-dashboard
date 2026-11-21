"""Panduan Pengguna: dua bahasa lengkap, sesuai peran, tabel rapi, dan tidak melampaui klaim sistem."""
import re

import guide_content as g


def test_every_section_has_both_languages():
    for key, icon, te, ti, be, bi in g.SECTIONS:
        assert all(x.strip() for x in (key, icon, te, ti, be, bi)), key
        assert te != ti and be != bi, key


def test_roles_see_the_right_sections():
    keys = lambda r: [s[0] for s in g.for_role(r)]
    assert keys("admin") == ["start", "operator", "admin", "limits"]
    assert keys("operator") == ["start", "operator", "limits"]
    assert keys("viewer") == ["start", "limits"]
    assert keys("peran_kustom") == ["start", "operator", "limits"]


def test_markdown_tables_are_well_formed():
    for key, *_rest, be, bi in g.SECTIONS:
        for body in (be, bi):
            rows = [l for l in body.splitlines() if l.startswith("|")]
            if rows:
                n = {r.count("|") for r in rows}
                assert len(n) == 1, (key, n)


def test_status_codes_match_the_system():
    import physics_engine as pe
    body = g.SECTIONS[1][4]
    for code in ("MANUAL_REQUIRED", "MISSING_PARAMETER", "INCOMPLETE_FORECAST", "STALE_OBSERVATION", "TARGET_NOT_REACHABLE"):
        assert code in body
    src = open("physics_engine.py", encoding="utf-8").read() + open("recommendation_service.py", encoding="utf-8").read()
    for code in ("MISSING_PARAMETER", "INCOMPLETE_FORECAST", "STALE_OBSERVATION", "TARGET_NOT_REACHABLE", "MANUAL_REQUIRED"):
        assert code in src, code


def test_claims_stay_within_evidence():
    text = " ".join(s[4] + s[5] for s in g.SECTIONS).lower()
    assert "only suggests" in text and "hanya menyarankan" in text
    assert "not a field-validated model" in text and "bukan model yang sudah divalidasi" in text
    assert not re.search(r"\b(diameter|dia\.)\b", text) and not re.search(r"\d+\s*(cm|mm)\s*(pipe|pipa)", text)


def test_manual_page_is_wired_into_navigation():
    import ocean_theme as ot
    assert ot.NAV_GROUPS["manual"] == "account" and "manual" in ot.NAV_ICONS
    app = open("app.py", encoding="utf-8").read()
    assert '"manual"' in app and "manual.render" in app
