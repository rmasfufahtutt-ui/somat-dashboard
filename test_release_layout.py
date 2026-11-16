"""Audit K11: satu pohon rilis, satu entry point, dan panduan demo benar-benar terjangkau dari halaman sign-in."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


def test_single_release_tree_no_nested_copy():
    nested = []
    for d, dirs, files in os.walk(HERE):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", ".pytest_cache", ".demo_data", "node_modules")]
        if os.path.abspath(d) != HERE and "app.py" in files:
            nested.append(d)
    assert not nested, f"salinan pohon aplikasi ditemukan: {nested}"


def test_entry_point_is_root_app_and_is_a_thin_router():
    src = _read("app.py")
    assert "set_page_config" in src and "views" in src
    assert "streamlit run app.py" in _read("README.md")


def test_demo_guide_reachable_from_sign_in_and_not_in_role_navigation():
    login = _read("views/login.py")
    assert "guide.open_guide" in login and "Demo Guide" in login
    assert "guide" not in _read("app.py").split("PAGES_OK =", 1)[1].split("\n", 1)[0]
    m = re.search(r"APP_PAGE_KEYS\s*=\s*\(([^)]*)\)", _read("auth.py"))
    assert m and "guide" not in m.group(1)
    assert "nav_guide" not in _read("app.py")


def test_no_binary_archives_committed_in_source_tree():
    bad = []
    for d, dirs, files in os.walk(HERE):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", ".pytest_cache", "demo_seed", "assets", "docs")]
        bad += [os.path.join(d, f) for f in files if f.lower().endswith((".rar", ".zip", ".7z"))]
    assert not bad, bad
