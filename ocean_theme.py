"""ocean_theme.py - tema "Deep Ocean" (mode gelap), ilustrasi SVG sensor, kartu ilustrasi, dan geometri navigasi sidebar.

Prinsip:
- Semua keluaran adalah string HTML/CSS/SVG murni (tanpa JavaScript). `st.markdown` tidak menjalankan skrip, dan tidak ada iframe
  tambahan, sehingga pindah tab tetap ringan (lihat catatan di ui_kit.py).
- Ilustrasi dikirim sebagai <img src="data:image/svg+xml;base64,..."> (pola yang sama dengan logo). Animasi CSS di dalam SVG tetap
  berjalan, dan @media (prefers-reduced-motion) di dalamnya mematikan gerak bila pengguna memintanya.
- Ilustrasi digerakkan oleh NILAI ukur: tidak ada nilai -> tidak ada air/zona lembap (bukan nilai karangan); hujan jatuh hanya
  bila curah hujan terukur > 0.
- Fungsi pembangun tidak memanggil Streamlit (kecuali render_steps), jadi dapat diuji tanpa sesi Streamlit.
"""
from __future__ import annotations

import base64
import html
import math
import re

# ------------------------------------------------------------------ palet
OCEAN_BG = "#000309"
ACCENT = "#22C79A"
WATER = "#3aa7d6"
WATER_2 = "#6cc3ee"
OK, WARN, CRIT = "#5fe3a1", "#f5c969", "#ff8f93"
FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap');"
HEAD_FONT = "'Space Grotesk','Inter',system-ui,sans-serif"

OCEAN_GRADIENT = (
    "radial-gradient(95% 80% at 50% 45%, #2f6a85 0%, #1d4b66 18%, #123350 34%, #0a1b30 52%, #071226 66%, "
    "#040d1c 80%, #020814 92%, #01040d 97%, #000309 100%),"
    "radial-gradient(160% 130% at 10% 10%, rgba(0,0,0,0) 38%, #000309 76%, #000208 100%),"
    "radial-gradient(160% 130% at 90% 90%, rgba(0,0,0,0) 38%, #000309 76%, #000208 100%)"
)

# ------------------------------------------------------------------ util
def _fin(x) -> bool:
    try:
        return x is not None and x == x and abs(float(x)) != float("inf")
    except Exception:
        return False


def _clip(x, lo, hi):
    return max(lo, min(hi, float(x)))


def _g(x) -> str:
    """Angka pendek untuk atribut SVG."""
    s = f"{float(x):.1f}"
    return s[:-2] if s.endswith(".0") else s


def _uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _wave(x0, y, amp, period, width) -> str:
    """Gelombang sinus sederhana (q + t berulang). Periode tetap supaya translateX(-period) tak terlihat putus."""
    n = max(2, int(math.ceil(width / (period / 2.0))))
    return f"M{_g(x0)} {_g(y)} q{_g(period / 4)} {_g(-amp)} {_g(period / 2)} 0" + f" t{_g(period / 2)} 0" * (n - 1)


def _svg(w, h, body, style, defs="") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f"<defs>{defs}</defs><style>{style}</style>{body}</svg>")


_TXT = "text{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;font-size:11px;fill:#e6eef6}"
_RM = "@media (prefers-reduced-motion:no-preference){%s}"

# ------------------------------------------------------------------ ilustrasi
def soil_svg(value, low=20.0, lbl_moist="moisture", lbl_low="LOW LIMIT", lbl_na="No data") -> str:
    """Profil tanah + tanaman. Zona lembap setinggi `value`% kedalaman; garis putus-putus = batas bawah."""
    W, H, G = 420, 240, 92
    D = H - G
    has = _fin(value)
    v = _clip(value, 0, 100) if has else 0.0
    zh = D * v / 100.0
    zy = H - zh
    ly = H - D * _clip(low, 0, 100) / 100.0
    below = has and v < low
    line_c = CRIT if below else WARN
    zone = ""
    bubbles = ""
    if has and zh > 0:
        zone = (f'<g class="zone"><rect x="0" y="{_g(zy)}" width="{W}" height="{_g(zh + 2)}" fill="url(#wg)" opacity=".85"/>'
                f'<g class="wave"><path d="{_wave(-40, zy, 5, 40, W + 80)}" fill="none" stroke="#9adcf7" stroke-width="2"/></g></g>')
        if zh > 24:
            bubbles = ('<g fill="#bfe6fa">'
                       + "".join(f'<circle class="bub b{i}" cx="{x}" cy="{_g(H - 8 - (i % 2) * 6)}" r="{r}"/>'
                                 for i, (x, r) in enumerate(((90, 2), (170, 1.6), (290, 2), (350, 1.6))))
                       + "</g>")
    lab_y = max(G + 14, zy - 8) if has else G + 20
    label = (f'<text x="14" y="{_g(lab_y)}" style="font-weight:600">{html.escape(f"{v:.1f}% {lbl_moist}")}</text>' if has
             else f'<text x="14" y="{G + 20}" style="fill:#9bb2c6">{html.escape(lbl_na)}</text>')
    low_label = html.escape(f"{lbl_low} {low:g}%")
    box_w = 7.2 * len(low_label) + 14
    body = (
        f'<rect width="{W}" height="{H}" fill="#0b1626"/>'
        f'<rect width="{W}" height="{G}" fill="url(#sk)"/>'
        f'<rect y="{G}" width="{W}" height="{D}" fill="url(#sd)"/>'
        f"{zone}{bubbles}"
        f'<line x1="0" x2="{W}" y1="{_g(ly)}" y2="{_g(ly)}" stroke="{line_c}" stroke-width="1.5" stroke-dasharray="6 4"/>'
        f'<rect x="{_g(W - box_w - 8)}" y="{_g(ly - 14)}" width="{_g(box_w)}" height="18" rx="5" fill="#06121f" opacity=".88"/>'
        f'<text x="{_g(W - 8 - box_w / 2)}" y="{_g(ly - 1.5)}" text-anchor="middle" style="fill:{line_c}">{low_label}</text>'
        f"{label}"
        '<g class="plant"><path d="M210 92V44" stroke="#a9d98b" stroke-width="3.5" stroke-linecap="round"/>'
        '<path d="M210 60q-26-4-34-26 26 0 34 26Z" fill="#7ad99b"/><path d="M210 52q24-4 32-24-26 0-32 24Z" fill="#5fc98a"/>'
        '<path d="M210 44q-8-12-4-24 12 10 4 24Z" fill="#9be8ac"/></g>'
        '<g stroke="#c9a47a" stroke-width="2" fill="none" stroke-linecap="round" opacity=".9">'
        '<path d="M210 92q-8 18-26 32"/><path d="M210 92q6 26-4 56"/><path d="M210 92q10 16 30 30"/><path d="M206 148q-8 10-8 24"/></g>'
        '<g fill="#6a4d36"><circle cx="50" cy="120" r="2.2"/><circle cx="110" cy="150" r="2"/><circle cx="320" cy="128" r="2.2"/>'
        '<circle cx="372" cy="156" r="2"/></g>'
    )
    defs = ('<linearGradient id="sk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0f2842"/><stop offset="1" stop-color="#1a4670"/></linearGradient>'
            '<linearGradient id="sd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4d382a"/><stop offset="1" stop-color="#2a1d15"/></linearGradient>'
            '<linearGradient id="wg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b93c4"/><stop offset="1" stop-color="#14608a"/></linearGradient>')
    anim = _RM % (
        ".wave{animation:wv 4s linear infinite}@keyframes wv{to{transform:translateX(-40px)}}"
        ".plant{transform-origin:210px 92px;animation:sw 4.5s ease-in-out infinite alternate}"
        "@keyframes sw{from{transform:rotate(-2.5deg)}to{transform:rotate(2.5deg)}}"
        ".bub{animation:up 4s linear infinite}.b1{animation-delay:1.3s}.b2{animation-delay:2.4s}.b3{animation-delay:.6s}"
        "@keyframes up{0%{transform:translateY(0);opacity:0}15%{opacity:.8}100%{transform:translateY(-30px);opacity:0}}"
        f".zone{{animation:rz 1.2s cubic-bezier(.2,.8,.2,1) .15s both}}@keyframes rz{{from{{transform:translateY({_g(zh + 4)}px)}}to{{transform:none}}}}")
    return _svg(W, H, body, _TXT + anim, defs)


def canal_svg(level, minimum, depth=2.0, lbl_min="MIN", lbl_bed="bed", lbl_na="No data") -> str:
    """Penampang saluran trapesium. Tinggi air = level/depth; garis putus-putus = batas minimum."""
    W, H = 280, 190
    TOP, BOT = 24, 170
    HG = BOT - TOP
    TL, TR, BL, BR = 24, 256, 84, 196
    has = _fin(level)
    lv = _clip(level, 0, depth) if has else 0.0
    wh = HG * lv / depth
    surf = BOT - wh
    my = BOT - HG * _clip(minimum, 0, depth) / depth
    below = has and float(level) < float(minimum)
    line_c = CRIT if below else WARN

    def xl(y):
        return TL + (BL - TL) * (y - TOP) / HG

    def xr(y):
        return TR - (TR - BR) * (y - TOP) / HG

    poly = f"{TL},{TOP} {TR},{TOP} {BR},{BOT} {BL},{BOT}"
    water = ""
    if has and wh > 0:
        water = (f'<g clip-path="url(#tc)"><g class="rise"><rect x="0" y="{_g(surf)}" width="{W}" height="{_g(H - surf)}" fill="url(#cw)"/>'
                 f'<g class="wave"><path d="{_wave(-40, surf, 6, 40, W + 80)}" fill="none" stroke="#9adcf7" stroke-width="2.2"/></g></g></g>')
    lab = html.escape(f"{lbl_min} {minimum:g} m")
    box_w = 7.0 * len(lab) + 14
    by = min(my + 7, BOT - 22)
    body = (
        f'<rect width="{W}" height="{H}" fill="#0a1b30"/>'
        f'<polygon points="{poly}" fill="#0c2239"/>'
        f"{water}"
        f'<polygon points="{poly}" fill="none" stroke="#7fb4d6" stroke-width="2" stroke-linejoin="round"/>'
        f'<line x1="{_g(xl(my) + 10)}" x2="{_g(xr(my) - 10)}" y1="{_g(my)}" y2="{_g(my)}" stroke="{line_c}" stroke-width="1.5" stroke-dasharray="6 4"/>'
        f'<rect x="{_g(140 - box_w / 2)}" y="{_g(by)}" width="{_g(box_w)}" height="18" rx="5" fill="#06121f" opacity=".88"/>'
        f'<text x="140" y="{_g(by + 12.5)}" text-anchor="middle" style="fill:{line_c}">{lab}</text>'
        f'<text x="30" y="18">{depth:g} m</text><text x="268" y="184" text-anchor="end">{html.escape(lbl_bed)} 0 m</text>'
        + ("" if has else f'<text x="140" y="{_g((TOP + BOT) / 2 - 6)}" text-anchor="middle" style="fill:#9bb2c6">{html.escape(lbl_na)}</text>')
    )
    defs = (f'<clipPath id="tc"><polygon points="{poly}"/></clipPath>'
            '<linearGradient id="cw" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b93c4"/><stop offset="1" stop-color="#14608a"/></linearGradient>')
    anim = _RM % (
        ".wave{animation:wv 2.4s linear infinite}@keyframes wv{to{transform:translateX(-40px)}}"
        f".rise{{animation:rs 1.4s cubic-bezier(.2,.8,.2,1) .2s both}}@keyframes rs{{from{{transform:translateY({_g(wh + 4)}px)}}to{{transform:none}}}}")
    return _svg(W, H, body, _TXT + anim, defs)


def rain_svg(value, limit=20.0, lbl_limit="High limit", lbl_na="No data", lbl_dry="No rain") -> str:
    """Awan + bar skala. Tetes hanya BERGERAK bila hujan terukur > 0; hujan 0 = tetes bayangan statis; tak ada data = awan abu."""
    W, H = 280, 190
    has = _fin(value)
    v = max(0.0, float(value)) if has else 0.0
    smax = max(2.0 * limit, math.ceil(v * 1.25 / 10.0) * 10.0) if has else 2.0 * limit
    bx0, bw = 22.0, 236.0
    fill = bw * min(v, smax) / smax if has else 0.0
    tick = bx0 + bw * min(limit, smax) / smax
    heavy = has and v >= limit
    cloud = "#9dbdd8" if has else "#6b7f93"
    if has and v > 0:
        n = 3 if v < 5 else (5 if v < limit else 7)
        xs = [118 + (i * 62.0 / max(1, n - 1)) for i in range(n)]
        drops = ('<g stroke="#8cc8ee" stroke-width="2.4" stroke-linecap="round">'
                 + "".join(f'<line class="drop d{i % 3}" x1="{_g(x)}" y1="112" x2="{_g(x - 4)}" y2="124"/>' for i, x in enumerate(xs)) + "</g>")
    elif has:
        drops = ('<g stroke="#6b90ad" stroke-width="2.2" stroke-linecap="round" stroke-dasharray="1 8">'
                 '<line class="ghost" x1="118" y1="112" x2="114" y2="146"/><line class="ghost" x1="144" y1="112" x2="140" y2="150"/>'
                 '<line class="ghost" x1="172" y1="112" x2="168" y2="146"/></g>')
    else:
        drops = ""
    lab = html.escape(f"{lbl_limit} {limit:g} mm")
    tx = _clip(tick, 70, 210)
    state = "" if has else f'<text x="140" y="140" text-anchor="middle" style="fill:#9bb2c6">{html.escape(lbl_na)}</text>'
    body = (
        f'<rect width="{W}" height="{H}" fill="url(#rk)"/>'
        f'<g class="cloud" fill="{cloud}"><circle cx="112" cy="72" r="24"/><circle cx="144" cy="60" r="31"/><circle cx="178" cy="74" r="23"/>'
        '<rect x="92" y="72" width="108" height="24" rx="12"/></g>'
        f"{drops}{state}"
        f'<rect x="{_g(bx0)}" y="160" width="{_g(bw)}" height="6" rx="3" fill="rgba(120,170,210,.22)"/>'
        f'<rect x="{_g(bx0)}" y="160" width="{_g(max(fill, 3 if has else 0))}" height="6" rx="3" fill="{WARN if heavy else ACCENT}"/>'
        f'<line x1="{_g(tick)}" x2="{_g(tick)}" y1="154" y2="172" stroke="{WARN}" stroke-width="2"/>'
        f'<text x="{_g(bx0)}" y="182">0</text><text x="{_g(tx)}" y="182" text-anchor="middle" style="fill:{WARN}">{lab}</text>'
    )
    defs = '<linearGradient id="rk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0f2842"/><stop offset="1" stop-color="#1a4670"/></linearGradient>'
    anim = _RM % (
        ".cloud{animation:dr 7s ease-in-out infinite alternate}@keyframes dr{from{transform:translateX(-10px)}to{transform:translateX(10px)}}"
        ".drop{animation:fl 1s linear infinite}.d1{animation-delay:.33s}.d2{animation-delay:.66s}"
        "@keyframes fl{0%{transform:translateY(0);opacity:0}20%{opacity:1}100%{transform:translateY(28px);opacity:0}}"
        ".ghost{animation:gh 3s ease-in-out infinite alternate}@keyframes gh{from{opacity:.25}to{opacity:.6}}")
    return _svg(W, H, body, _TXT + anim, defs)


# ------------------------------------------------------------------ kartu ilustrasi
_PILL = {"ok": "p-ok", "warn": "p-warn", "bad": "p-crit", "info": "p-info"}


def _num(v, dec) -> str:
    return f"{float(v):.{int(dec)}f}" if _fin(v) else "—"


def art_card(svg: str, alt: str, title: str, value, decimals: int, unit: str, sub: str, badge_text: str, badge_kind: str = "ok") -> str:
    return (
        '<div class="oc-card">'
        f'<img class="oc-art" alt="{html.escape(alt, quote=True)}" src="{_uri(svg)}"/>'
        f'<div class="oc-k">{html.escape(title)}</div>'
        f'<div class="oc-v">{_num(value, decimals)}<span class="oc-u"> {html.escape(unit)}</span></div>'
        f'<div class="oc-sub">{html.escape(sub)}</div>'
        f'<div class="oc-badge"><span class="oc-pill {_PILL.get(badge_kind, "p-info")}">{html.escape(badge_text)}</span></div></div>'
    )


def sensor_trio(soil: dict, canal: dict, rain: dict) -> str:
    """Tiga kartu bergambar (tanah, saluran, hujan). Setiap dict: svg, alt, title, value, decimals, unit, sub, badge_text, badge_kind."""
    return '<div class="oc-grid">' + "".join(art_card(**c) for c in (soil, canal, rain)) + "</div>"


# ------------------------------------------------------------------ navigasi + langkah
NAV_H, NAV_GAP, GROUP_M = 40, 2, 26
NAV_GROUPS = {"overview": "monitor", "monitoring": "monitor", "prediction": "decide", "operator": "decide",
              "observations": "field", "execution": "field", "alerts": "field", "manual": "account", "account": "account", "admin": "account"}
GROUP_LABELS = {"monitor": ("Monitor", "Pantau"), "decide": ("Decide", "Putuskan"), "field": ("Field", "Lapangan"), "account": ("Account", "Akun")}
NAV_ICONS = {"overview": ":material/dashboard:", "monitoring": ":material/sensors:", "prediction": ":material/trending_up:",
             "operator": ":material/fact_check:", "observations": ":material/location_on:", "execution": ":material/water_drop:",
             "alerts": ":material/notifications:", "manual": ":material/menu_book:", "account": ":material/person:", "admin": ":material/shield:"}
STEPS = (("observe", "1", "Observe", "Amati", "monitoring", "Sensor Monitoring", "Monitoring Sensor"),
         ("predict", "2", "Predict", "Prediksi", "prediction", "Prediction & Recommendation", "Prediksi & Rekomendasi"),
         ("decide", "3", "Decide", "Putuskan", "operator", "Operator Decision", "Keputusan Operator"),
         ("execute", "4", "Execute", "Laksanakan", "execution", "Irrigation Execution", "Pelaksanaan Irigasi"))
_SAFE = re.compile(r"^[a-z0-9_]+$")


def nav_geometry(pids, collapsed=False):
    """Posisi-y (px) tiap item menu dalam wadah `nav`. Semua tinggi/jarak diatur CSS sendiri sehingga dapat dihitung persis.
    Mengembalikan (offsets, firsts): firsts = {pid: group} untuk item pertama tiap grup (tempat label grup digambar)."""
    y, prev, offs, firsts = 0, None, {}, {}
    for p in pids:
        g = NAV_GROUPS.get(p, "account")
        if not collapsed and g != prev:
            y += GROUP_M
            firsts[p] = g
        offs[p] = y
        y += NAV_H + NAV_GAP
        prev = g
    return offs, firsts


def _css_str(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _theme(dark):
    from styles import theme_for
    return theme_for(dark)


def nav_css(dark: bool, collapsed: bool, pids, active: str, lang: str = "en") -> str:
    """CSS menu sidebar: item seragam, label grup lewat ::before, dan SATU indikator (::before wadah) yang meluncur ke item aktif.
    Posisi aktif dipasang sebagai translateY di CSS yang disuntik tiap rerun; transisi CSS menganimasikan perpindahannya."""
    pids = [p for p in pids if _SAFE.match(p)]
    t = _theme(dark)
    acc = ACCENT if dark else "#0B5F51"
    offs, firsts = nav_geometry(pids, collapsed)
    y = offs.get(active, 0)
    idx = 0 if lang == "en" else 1
    out = [
        f".st-key-nav{{position:relative}}",
        f"[data-testid='stSidebar'] [data-testid='stVerticalBlock'].st-key-nav,[data-testid='stSidebar'] .st-key-nav>[data-testid='stVerticalBlock']"
        f"{{gap:{NAV_GAP}px!important;row-gap:{NAV_GAP}px!important}}",
        (f".st-key-nav::before{{content:'';position:absolute;top:0;pointer-events:none;z-index:0;height:{NAV_H}px;border-radius:11px;"
         + ("left:50%;width:46px;margin-left:-23px;" if collapsed else "left:0;right:0;")
         + f"background:rgba(34,199,154,.14);border:1px solid rgba(34,199,154,.38);box-shadow:0 0 18px rgba(34,199,154,.16);"
           f"transform:translateY({y}px)}}"),
        f"@media (prefers-reduced-motion:no-preference){{.st-key-nav::before{{transition:transform .5s cubic-bezier(.34,1.4,.5,1)}}}}",
        f"[data-testid='stSidebar'] .st-key-nav [data-testid='stElementContainer'],[data-testid='stSidebar'] .st-key-nav .stButton{{height:{NAV_H}px;position:relative;z-index:1}}",
        (f"[data-testid='stSidebar'] .st-key-nav .stButton button{{height:{NAV_H}px!important;min-height:{NAV_H}px!important;"
         f"background:transparent!important;border:0!important;box-shadow:none!important;color:{t['muted']}!important;"
         "justify-content:flex-start;gap:12px;padding:0 12px!important;transform:none!important;transition:color .2s ease,background .2s ease}"),
        f"[data-testid='stSidebar'] .st-key-nav .stButton button p{{color:inherit!important;font-size:.95rem!important;font-weight:600!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}",
        f"[data-testid='stSidebar'] .st-key-nav .stButton button:hover{{color:{t['text']}!important;background:rgba(120,170,210,.08)!important}}",
        (f"[data-testid='stSidebar'] .st-key-nav .stButton button[kind='primary'],[data-testid='stSidebar'] .st-key-nav .stButton button[data-testid='stBaseButton-primary']"
         f"{{color:{acc}!important;background:transparent!important;border:0!important;box-shadow:none!important}}"),
        f"[data-testid='stSidebar'] .st-key-nav .stButton button[kind='primary'] *,[data-testid='stSidebar'] .st-key-nav .stButton button[data-testid='stBaseButton-primary'] *{{color:{acc}!important}}",
    ]
    if collapsed:
        out.append("[data-testid='stSidebar'] .st-key-nav .stButton button p{display:none!important}")
        out.append("[data-testid='stSidebar'] .st-key-nav .stButton button{justify-content:center;padding:0!important}")
    for p, g in firsts.items():
        label = GROUP_LABELS[g][idx]
        out.append(f".st-key-nav_{p}{{margin-top:{GROUP_M}px!important;position:relative}}")
        out.append(f".st-key-nav_{p}::before{{content:\"{_css_str(label)}\";position:absolute;left:12px;top:-{GROUP_M - 6}px;font-size:11px;"
                   f"letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:{t['muted']};line-height:1;pointer-events:none}}")
    return "\n".join(out)


def steps_css(dark: bool, lang: str = "en") -> str:
    """Kartu langkah 1-4 (Observe/Predict/Decide/Execute): tombol Streamlit berwajah kartu. Nomor dan subjudul lewat pseudo-elemen."""
    t = _theme(dark)
    acc = ACCENT if dark else "#0B5F51"
    idx = 0 if lang == "en" else 1
    out = [
        ".st-key-oc_steps{margin:.1rem 0 .8rem}",
        (f".st-key-oc_steps .stButton button{{display:grid!important;grid-template-columns:36px minmax(0,1fr);grid-template-areas:'num t' 'num s';"
         f"column-gap:12px;align-items:center;justify-items:start;text-align:left;height:auto!important;min-height:66px!important;"
         f"padding:10px 14px!important;border-radius:14px!important;background:{t['panel']}!important;border:1px solid {t['border']}!important;"
         "backdrop-filter:blur(6px);transition:transform .25s ease,border-color .25s ease,box-shadow .25s ease}"),
        f".st-key-oc_steps .stButton button:hover:not(:disabled){{transform:translateY(-3px);border-color:{acc}!important;box-shadow:0 10px 24px rgba(2,8,23,.35)}}",
        ".st-key-oc_steps .stButton button:disabled{opacity:.5}",
        ".st-key-oc_steps .stButton button>div{grid-area:t;text-align:left;width:auto!important;justify-content:flex-start!important}",
        f".st-key-oc_steps .stButton button p{{font-family:{HEAD_FONT};font-size:1rem!important;font-weight:700!important;margin:0!important;text-align:left!important;color:{t['text']}!important}}",
        (f".st-key-oc_steps .stButton button::before{{grid-area:num;width:34px;height:34px;border:1.5px solid {acc};border-radius:50%;display:grid;place-items:center;"
         f"color:{acc};font-weight:700;font-size:.95rem;transition:background .25s ease,color .25s ease}}"),
        f".st-key-oc_steps .stButton button:hover:not(:disabled)::before{{background:{acc};color:#04241d}}",
        f".st-key-oc_steps .stButton button::after{{grid-area:s;font-size:.78rem;font-weight:400;color:{t['muted']};line-height:1.2}}",
    ]
    for sid, num, _en, _id, _page, sub_en, sub_id in STEPS:
        out.append(f".st-key-oc_step_{sid} button::before{{content:\"{num}\"}}")
        out.append(f".st-key-oc_step_{sid} button::after{{content:\"{_css_str((sub_en, sub_id)[idx])}\"}}")
    return "\n".join(out)


def go_page(page: str) -> None:
    import streamlit as st
    st.session_state["page"] = page


def render_steps(L, allowed=None) -> None:
    """Baris 4 langkah alur kerja; tiap kartu pindah ke halaman terkait. Halaman tanpa hak akses tampil nonaktif."""
    import streamlit as st
    with st.container(key="oc_steps"):
        cols = st.columns(4)
        for col, (sid, _n, en, idn, page, _se, _si) in zip(cols, STEPS):
            with col:
                st.button(L(en, idn), key=f"oc_step_{sid}", on_click=go_page, args=(page,), width="stretch",
                          disabled=(allowed is not None and page not in allowed))


# ------------------------------------------------------------------ CSS umum (kedua tema) + CSS gelap Deep Ocean
def base_css(dark: bool) -> str:
    """Kartu ilustrasi, lencana, bar, kartu status: dipakai di tema terang maupun gelap."""
    t = _theme(dark)
    acc = ACCENT if dark else "#0B5F51"
    if dark:
        pills = (f".oc-pill.p-ok{{background:rgba(95,227,161,.14);color:{OK}}}.oc-pill.p-warn{{background:rgba(245,201,105,.14);color:{WARN}}}"
                 f".oc-pill.p-crit{{background:rgba(255,143,147,.14);color:{CRIT}}}.oc-pill.p-info{{background:rgba(108,195,238,.14);color:{WATER_2}}}")
    else:
        pills = (".oc-pill.p-ok{background:#E3F5EA;color:#1f7a4d}.oc-pill.p-warn{background:#FDF0D5;color:#8a5a00}"
                 ".oc-pill.p-crit{background:#FBE4E4;color:#a3262a}.oc-pill.p-info{background:#E8F1FD;color:#1E3A8A}")
    return f"""
.oc-grid{{display:grid;grid-template-columns:1.55fr 1fr 1fr;gap:16px;margin:.2rem 0 1rem}}
.oc-card{{background:{t['panel']};border:1px solid {t['border']};border-radius:14px;padding:14px 16px;min-width:0;
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);transition:border-color .25s ease,box-shadow .25s ease}}
.oc-card:hover{{border-color:rgba(108,195,238,.45);box-shadow:0 8px 28px rgba(2,8,23,.30)}}
.oc-art{{width:100%;height:auto;display:block;border-radius:10px;margin:0 0 10px}}
.oc-k{{font-size:.72rem;font-weight:700;color:{t['muted']};text-transform:uppercase;letter-spacing:.09em}}
.oc-v{{font-family:{HEAD_FONT};font-size:2.1rem;font-weight:700;line-height:1.12;color:{t['text']};font-variant-numeric:tabular-nums;margin:2px 0}}
.oc-u{{font-size:.9rem;font-weight:400;color:{t['muted']}}}
.oc-sub{{font-size:.85rem;color:{t['muted']}}}
.oc-badge{{margin-top:8px}}
.oc-pill{{display:inline-flex;align-items:center;gap:6px;font-size:.7rem;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}}
.oc-pill::before{{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}}
{pills}
.k-bar{{height:8px;border-radius:4px;background:rgba(120,170,210,.15);overflow:hidden;margin:2px 0 8px;width:100%}}
.k-bar>i{{display:block;height:100%;border-radius:4px;transform-origin:left}}
.k-value{{font-family:{HEAD_FONT};font-variant-numeric:tabular-nums}}
.k-grid[style*="--cols:3"]{{grid-template-columns:1.3fr 1fr .85fr}}
.k-card.k-status{{background:linear-gradient(160deg,rgba(34,199,154,.16),{t['panel']});border-color:rgba(34,199,154,.4)}}
@media(max-width:1100px){{.oc-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.oc-grid>:first-child{{grid-column:1/-1}}}}
@media(max-width:900px){{.k-grid[style*="--cols:3"]{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:640px){{.oc-grid{{grid-template-columns:minmax(0,1fr)}}.k-grid[style*="--cols:3"]{{grid-template-columns:minmax(0,1fr)}}}}
@media (prefers-reduced-motion:no-preference){{
  .oc-card,.k-card{{animation:oc-rise .6s cubic-bezier(.2,.8,.2,1) both}}
  .oc-grid>:nth-child(2),.k-grid>:nth-child(2){{animation-delay:.07s}}.oc-grid>:nth-child(3),.k-grid>:nth-child(3){{animation-delay:.14s}}
  .k-grid>:nth-child(4){{animation-delay:.21s}}
  .k-bar>i{{animation:oc-grow 1.1s cubic-bezier(.2,.8,.2,1) .25s both}}
  .oc-pill.p-ok::before{{animation:oc-ping 2.4s ease-out infinite}}
  .st-key-oc_steps [data-testid="stColumn"],.st-key-oc_steps [data-testid="column"]{{animation:oc-rise .55s cubic-bezier(.2,.8,.2,1) both}}
  .st-key-oc_steps [data-testid="stColumn"]:nth-child(2),.st-key-oc_steps [data-testid="column"]:nth-child(2){{animation-delay:.06s}}
  .st-key-oc_steps [data-testid="stColumn"]:nth-child(3),.st-key-oc_steps [data-testid="column"]:nth-child(3){{animation-delay:.12s}}
  .st-key-oc_steps [data-testid="stColumn"]:nth-child(4),.st-key-oc_steps [data-testid="column"]:nth-child(4){{animation-delay:.18s}}
}}
@keyframes oc-rise{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}
@keyframes oc-grow{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
@keyframes oc-ping{{0%{{box-shadow:0 0 0 0 currentColor}}70%{{box-shadow:0 0 0 6px transparent}}100%{{box-shadow:0 0 0 0 transparent}}}}
"""


def dark_css() -> str:
    """Latar Deep Ocean + panel kaca (hanya mode gelap). Gradasi ada di lapisan tetap di belakang seluruh aplikasi."""
    return f"""
.stApp{{background-color:{OCEAN_BG}!important;isolation:isolate}}
.stApp::before{{content:"";position:fixed;inset:-6%;z-index:-1;pointer-events:none;will-change:transform;background:{OCEAN_GRADIENT}}}
[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],[data-testid="stHeader"]{{background:transparent!important}}
[data-testid="stSidebar"]{{background:rgba(3,10,21,.82)!important;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}}
[data-testid="stPlotlyChart"],[data-testid="stDataFrame"],div[data-testid="stExpander"]{{backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}}
[data-testid="stSidebar"] [data-testid="stAlert"]{{border-radius:10px}}
@media (prefers-reduced-motion:no-preference){{
  .stApp::before{{animation:oc-breathe 14s ease-in-out infinite alternate}}
}}
@keyframes oc-breathe{{from{{transform:scale(1) translate(0,0)}}to{{transform:scale(1.07) translate(1.5%,-1%)}}}}
"""


def global_css(dark: bool) -> str:
    """Satu paket CSS untuk disuntik bersama CSS lama (setelah build_css + ui_css). FONT_IMPORT harus paling awal di blok <style>."""
    return base_css(dark) + (dark_css() if dark else "")
