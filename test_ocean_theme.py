"""Uji tema Deep Ocean: SVG sah dan mengikuti nilai ukur, kartu aman, geometri navigasi, CSS tanpa JS, kontras teks.
Streamlit tidak dibutuhkan (modul sengaja bebas Streamlit untuk pembangun HTML/CSS/SVG)."""
import base64
import re
import sys
import types
import xml.etree.ElementTree as ET

import pytest

# styles.py mengimpor streamlit/PIL di tingkat modul; uji ini hanya butuh theme_for, jadi sediakan stub bila tidak terpasang.
try:
    import streamlit  # noqa: F401
except Exception:  # pragma: no cover
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (lambda f: f) if not (a and callable(a[0])) else a[0]
    st.cache_resource = st.cache_data
    st.session_state = {}
    sys.modules["streamlit"] = st
try:
    import PIL  # noqa: F401
except Exception:  # pragma: no cover
    pil = types.ModuleType("PIL")
    pil.Image = types.ModuleType("PIL.Image")
    sys.modules["PIL"], sys.modules["PIL.Image"] = pil, pil.Image

import ocean_theme as ot  # noqa: E402


def _parse(svg):
    return ET.fromstring(svg)


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------- ilustrasi ----------------
@pytest.mark.parametrize("svg", [
    ot.soil_svg(37.3), ot.soil_svg(None), ot.soil_svg(0.0), ot.soil_svg(100.0), ot.soil_svg(12.0),
    ot.canal_svg(1.13, 0.9), ot.canal_svg(None, 0.9), ot.canal_svg(0.0, 0.9), ot.canal_svg(2.5, 0.9), ot.canal_svg(0.4, 0.9),
    ot.rain_svg(0.0), ot.rain_svg(None), ot.rain_svg(3.0), ot.rain_svg(12.0), ot.rain_svg(55.0),
])
def test_all_svgs_are_well_formed_and_script_free(svg):
    root = _parse(svg)
    assert root.tag.endswith("svg")
    low = svg.lower()
    assert "<script" not in low and "onload" not in low and "javascript:" not in low and "foreignobject" not in low


def test_soil_zone_height_follows_value_and_missing_has_no_water():
    full = ot.soil_svg(37.3)
    assert 'class="zone"' in full and "37.3%" in full
    # zona lembap 37.3% dari kedalaman 148 -> y atas = 240 - 55.2
    assert f'y="{240 - 148 * 0.373:.1f}"'.replace(".0\"", "\"") in full or "y=\"184.8\"" in full
    none = ot.soil_svg(None)
    assert 'class="zone"' not in none and "No data" in none and "%" not in re.sub(r"LOW LIMIT 20%", "", none.split("<text x=\"14\"")[1])


def test_soil_below_low_limit_uses_critical_color():
    assert ot.CRIT in ot.soil_svg(12.0) and ot.CRIT not in ot.soil_svg(37.3)


def test_canal_water_level_and_minimum_line():
    ok = ot.canal_svg(1.13, 0.9)
    low = ot.canal_svg(0.5, 0.9)
    assert 'class="rise"' in ok and "MIN 0.9 m" in ok
    assert ot.CRIT not in ok and ot.CRIT in low            # di bawah minimum -> garis merah
    assert 'class="rise"' not in ot.canal_svg(None, 0.9) and "No data" in ot.canal_svg(None, 0.9)
    # permukaan air: 170 - 146 * 1.13 / 2 = 87.5
    assert 'y="87.5"' in ok


def test_rain_drops_move_only_when_rain_measured():
    dry, wet, none = ot.rain_svg(0.0), ot.rain_svg(8.0), ot.rain_svg(None)
    assert 'class="drop' not in dry and 'class="ghost"' in dry          # 0 mm: tetes bayangan statis
    assert 'class="drop' in wet and 'class="ghost"' not in wet
    assert 'class="drop' not in none and 'class="ghost"' not in none and "No data" in none
    assert ot.WARN in ot.rain_svg(25.0)                                   # >= batas: bar kuning


def test_reduced_motion_guard_in_every_svg():
    for svg in (ot.soil_svg(30), ot.canal_svg(1.0, 0.9), ot.rain_svg(2.0)):
        assert "prefers-reduced-motion:no-preference" in svg


def test_labels_are_escaped():
    svg = ot.soil_svg(30, lbl_moist="<b>x</b>", lbl_low="A&B", lbl_na="<i>")
    _parse(svg)
    assert "<b>x</b>" not in svg


# ---------------- kartu ----------------
def _spec(**kw):
    d = dict(svg=ot.soil_svg(30), alt='a "quoted" <alt>', title="T<", value=37.3, decimals=1, unit="%", sub="s&", badge_text="Normal", badge_kind="ok")
    d.update(kw)
    return d


def test_art_card_escapes_and_embeds_image_as_data_uri():
    h = ot.art_card(**_spec())
    assert "<script" not in h and 'alt="a &quot;quoted&quot; &lt;alt&gt;"' in h and "T&lt;" in h and "s&amp;" in h
    m = re.search(r'src="data:image/svg\+xml;base64,([^"]+)"', h)
    assert m and base64.b64decode(m.group(1)).decode().startswith("<svg")
    assert "37.3" in h and "oc-pill p-ok" in h


def test_missing_value_shows_dash_not_zero():
    h = ot.art_card(**_spec(value=None))
    assert ">—<" in h and "0.0" not in h
    h2 = ot.art_card(**_spec(value=float("nan")))
    assert ">—<" in h2


def test_sensor_trio_has_three_cards():
    s = _spec()
    assert ot.sensor_trio(s, s, s).count('class="oc-card"') == 3


# ---------------- navigasi ----------------
PIDS = ["overview", "monitoring", "prediction", "operator", "observations", "execution", "alerts", "account", "admin"]


def test_nav_geometry_offsets_are_exact():
    offs, firsts = ot.nav_geometry(PIDS)
    stride = ot.NAV_H + ot.NAV_GAP
    assert offs["overview"] == ot.GROUP_M and firsts == {"overview": "monitor", "prediction": "decide", "observations": "field", "account": "account"}
    assert offs["monitoring"] == offs["overview"] + stride
    assert offs["prediction"] == offs["monitoring"] + stride + ot.GROUP_M       # grup baru: tambah margin
    assert offs["admin"] == offs["account"] + stride
    # tanpa grup (sidebar ringkas): jarak seragam
    o2, f2 = ot.nav_geometry(PIDS, collapsed=True)
    assert f2 == {} and [o2[p] for p in PIDS] == [i * stride for i in range(len(PIDS))]


def test_nav_geometry_handles_filtered_menu():
    offs, firsts = ot.nav_geometry(["overview", "monitoring", "account"])
    assert firsts == {"overview": "monitor", "account": "account"}
    assert offs["account"] == offs["monitoring"] + (ot.NAV_H + ot.NAV_GAP) + ot.GROUP_M


def test_nav_tabs_are_tight():
    """Permintaan pengguna: jarak antar tab jangan terlalu jauh."""
    assert ot.NAV_H <= 42 and ot.NAV_GAP <= 4 and ot.GROUP_M <= 28


def test_nav_css_moves_indicator_to_active_item():
    offs, _ = ot.nav_geometry(PIDS)
    for active in PIDS:
        css = ot.nav_css(True, False, PIDS, active, "en")
        assert f"transform:translateY({offs[active]}px)" in css
    assert 'content:"Monitor"' in ot.nav_css(True, False, PIDS, "overview", "en") and 'content:"Pantau"' in ot.nav_css(True, False, PIDS, "overview", "id")
    assert "transition:transform" in ot.nav_css(True, False, PIDS, "overview")      # transisi hanya di blok no-preference
    assert "prefers-reduced-motion:no-preference" in ot.nav_css(True, False, PIDS, "overview")


def test_nav_css_ignores_unsafe_ids():
    css = ot.nav_css(True, False, ["overview", "x}{evil", "admin"], "overview")
    assert "evil" not in css


def test_steps_css_texts_follow_language():
    en, idn = ot.steps_css(True, "en"), ot.steps_css(True, "id")
    assert 'content:"Sensor Monitoring"' in en and 'content:"Monitoring Sensor"' in idn


# ---------------- CSS ----------------
def test_global_css_has_no_script_and_dark_background():
    dark, light = ot.global_css(True), ot.global_css(False)
    assert "<script" not in dark.lower() and "javascript:" not in dark.lower()
    assert "radial-gradient" in dark and "radial-gradient" not in light     # tema terang tidak berubah
    assert dark.count("{") == dark.count("}") and light.count("{") == light.count("}")
    assert "prefers-reduced-motion:no-preference" in dark


def test_balanced_braces_in_all_css():
    for css in (ot.nav_css(True, False, PIDS, "admin"), ot.nav_css(False, True, PIDS, "admin"), ot.steps_css(True), ot.steps_css(False)):
        assert css.count("{") == css.count("}")


# ---------------- kontras (WCAG AA 4.5:1) di titik gradasi paling terang ----------------
def test_text_contrast_on_glass_panel_over_brightest_glow():
    from styles import theme_for
    t = theme_for(True)
    m = re.match(r"rgba\((\d+),(\d+),(\d+),([.\d]+)\)", t["panel"])
    pr, pg, pb, pa = int(m[1]), int(m[2]), int(m[3]), float(m[4])
    for glow in ("#2f6a85", "#1d4b66", "#000309"):
        g = _hex(glow)
        panel = tuple(pa * c + (1 - pa) * gc for c, gc in zip((pr, pg, pb), g))
        for name in ("text", "muted"):
            assert _ratio(_hex(t[name]), panel) >= 4.5, (name, glow)
        for status in (ot.OK, ot.WARN, ot.CRIT, ot.ACCENT, ot.WATER_2):
            assert _ratio(_hex(status), panel) >= 4.5, (status, glow)
