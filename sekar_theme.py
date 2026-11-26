"""sekar_theme.py - identitas visual SEKAR (tema gelap dashboard + layar login).

Hanya string CSS/HTML; tidak mengubah logika aplikasi. Dipasang SETELAH CSS lama (styles/ui_kit/ocean_theme) sehingga
aturan di sini menang. Gambar besar (banner, latar login) disajikan sebagai file statis (`static/`, butuh
`enableStaticServing = true` di .streamlit/config.toml) agar tidak di-embed base64 pada setiap rerun.
Bila file statis tidak ada/tak terjangkau, CSS jatuh ke gradasi polos (tampilan tetap utuh).
"""
from __future__ import annotations

STATIC = "app/static"
HEADER_IMG = f"{STATIC}/sekar_header.jpg"
LOGIN_BG = f"{STATIC}/sekar_login_bg.jpg"

GOLD = "#E8BE54"
GOLD_SOFT = "#F3D98B"
TEAL = "#22C79A"
NAVY_0, NAVY_1, NAVY_2 = "#04101F", "#071C31", "#0A2742"

FONT_IMPORT = ("@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800"
               "&family=Cormorant+Garamond:ital,wght@1,500;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');")
BRAND_FONT = "'Cinzel','Trajan Pro',Georgia,serif"
TAG_FONT = "'Cormorant Garamond',Georgia,serif"
UI_FONT = "'Plus Jakarta Sans','Inter',system-ui,-apple-system,'Segoe UI',sans-serif"

TAGLINE = "Where Water Meets Wisdom"
FULL_ID = "Sistem Evaluasi Kebutuhan Air dan Rekomendasi"
FULL_EN = "Adaptive Irrigation Decision Support System"


# ------------------------------------------------------------------ dashboard (mode gelap)
def dashboard_css(dark: bool) -> str:
    """Tema gelap SEKAR. Mode terang dibiarkan memakai CSS lama (hanya aksen emas ringan)."""
    if not dark:
        return f"""
.sekar-hero h1 .gold{{color:#8a6a12!important;-webkit-text-fill-color:#8a6a12!important;background:none!important}}
.side-brand-name{{font-family:{BRAND_FONT};letter-spacing:.14em}}
"""
    return f"""
/* ===== latar: gradasi teal (pusat bercahaya) -> biru-teal dalam di tepi, tanpa hitam pekat ===== */
.stApp{{background:#06223a!important;font-family:{UI_FONT}}}
.stApp::before{{background:
  radial-gradient(70% 58% at 64% 36%,rgba(38,170,176,.58) 0%,rgba(24,128,150,.42) 26%,rgba(14,84,116,.24) 50%,rgba(6,40,66,0) 76%),
  radial-gradient(58% 52% at 8% 92%,rgba(22,168,134,.34) 0%,rgba(10,90,96,.16) 40%,rgba(0,0,0,0) 70%),
  radial-gradient(50% 42% at 96% 4%,rgba(52,146,196,.34) 0%,rgba(0,0,0,0) 68%),
  linear-gradient(158deg,#0b4a60 0%,#09364f 40%,#062640 72%,#051c33 100%)!important}}
html,body,[data-testid="stAppViewContainer"],.stMarkdown,p,label,button,input,textarea{{font-family:{UI_FONT}}}

/* ===== sidebar ===== */
[data-testid="stSidebar"]{{background:linear-gradient(180deg,rgba(6,34,52,.88),rgba(5,24,42,.92))!important;
  border-right:1px solid rgba(56,160,200,.18)!important}}
[data-testid="stSidebarContent"]{{background-image:
  url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 160'%3E%3Cpath d='M0 0H230C150 20 70 70 0 150Z' fill='%230b3a5e' fill-opacity='.85'/%3E%3Cpath d='M230 0C150 20 70 70 0 150' fill='none' stroke='%23E8BE54' stroke-width='3'/%3E%3Cpath d='M190 0C120 22 60 62 0 118' fill='none' stroke='%23E8BE54' stroke-opacity='.45' stroke-width='1.2'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-size:300px auto;background-position:left top}}
.side-brand{{align-items:center}}
.side-brand-name{{font-family:{BRAND_FONT}!important;font-weight:800;font-size:2.0rem!important;letter-spacing:.16em;
  background:linear-gradient(180deg,{GOLD_SOFT},{GOLD} 55%,#b98a1f);-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;color:{GOLD}}}
.side-brand-sub{{font-family:{TAG_FONT};font-style:italic;font-size:1rem!important;color:#d9e6f2!important}}
.side-info-card,.side-profile{{background:rgba(8,32,54,.78)!important;border:1px solid rgba(56,160,200,.22)!important;border-radius:14px}}
[data-testid="stSidebar"] [data-testid="stAlert"]{{background:rgba(120,72,12,.35)!important;border:1px solid rgba(232,190,84,.35)!important;border-radius:12px}}
[data-testid="stSidebar"] .st-key-nav .stButton button[kind='primary'] *,
[data-testid="stSidebar"] .st-key-nav .stButton button[data-testid='stBaseButton-primary'] *{{color:{TEAL}!important}}
[data-testid="stSidebar"] .st-key-nav_logout button,[data-testid="stSidebar"] .st-key-nav_logout button p{{color:#cfe3f1!important}}

/* ===== banner DEMO ===== */
.demo-banner{{background:linear-gradient(90deg,#b9461c 0%,#d9702a 60%,#e18a34 100%)!important;color:#fff4e6!important;
  border:1px solid rgba(255,190,120,.45)!important;border-left:6px solid #ffb35c!important;border-radius:12px!important;
  box-shadow:0 8px 22px rgba(185,70,28,.28);font-size:.9rem;letter-spacing:.005em}}

/* ===== header halaman (banner sawah) ===== */
.sekar-hero{{position:relative;display:flex;align-items:center;gap:16px;margin:0 0 14px;padding:18px 22px;min-height:112px;
  border-radius:18px;overflow:hidden;border:1px solid rgba(56,160,200,.28);
  background:linear-gradient(90deg,rgba(4,16,31,.97) 0%,rgba(5,24,44,.92) 42%,rgba(5,24,44,.35) 72%,rgba(5,24,44,.05) 100%),
             url('{HEADER_IMG}') right center/cover no-repeat,linear-gradient(135deg,#0a2c48,#0b4a4a);
  box-shadow:0 14px 34px rgba(0,0,0,.35)}}
@media(min-width:801px){{.sekar-hero{{padding-right:8.5rem}}}}
.sekar-hero img{{width:64px!important;height:auto!important;max-height:80px;object-fit:contain;filter:drop-shadow(0 4px 14px rgba(232,190,84,.35))}}
.sekar-hero h1{{font-family:{UI_FONT};font-size:clamp(1.35rem,2.1vw,2.1rem)!important;font-weight:800;color:#f2f7fb!important;
  margin:0;letter-spacing:-.01em;text-shadow:0 2px 12px rgba(0,0,0,.5)}}
.sekar-hero h1 .gold{{font-family:{BRAND_FONT};letter-spacing:.12em;
  background:linear-gradient(180deg,{GOLD_SOFT},{GOLD} 60%,#b98a1f);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.sekar-hero p{{margin:6px 0 0;color:#cfe0ee!important;font-size:.93rem;text-shadow:0 1px 8px rgba(0,0,0,.6)}}

/* ===== kartu ===== */
.k-card{{background:linear-gradient(165deg,rgba(12,52,82,.78),rgba(6,26,46,.82))!important;
  border:1px solid rgba(45,190,200,.30)!important;border-top-width:2px!important;border-radius:16px!important;
  box-shadow:0 10px 26px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.04)!important;position:relative;overflow:hidden}}
.k-card::after{{content:"";position:absolute;right:-10px;bottom:-14px;width:96px;height:64px;opacity:.16;pointer-events:none;
  background:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 64'%3E%3Cg fill='none' stroke='%2322C79A' stroke-width='2.2' stroke-linecap='round'%3E%3Cpath d='M10 64C14 40 22 22 40 6'/%3E%3Cpath d='M30 64C32 44 44 28 66 14'/%3E%3Cpath d='M52 64C54 48 64 36 86 26'/%3E%3C/g%3E%3C/svg%3E") no-repeat right bottom/contain}}
.k-title{{color:#a9c3d8!important}}
.k-value{{color:#f2f7fb!important}}
.oc-card,.status-panel,div[data-testid="stExpander"],[data-testid="stPlotlyChart"],[data-testid="stDataFrame"]{{
  background:linear-gradient(165deg,rgba(10,46,74,.70),rgba(6,24,42,.78))!important;
  border:1px solid rgba(45,190,200,.26)!important;border-radius:16px!important;box-shadow:0 10px 26px rgba(0,0,0,.28)}}
div[data-testid="stExpander"] details{{background:transparent!important}}

/* ===== input / select ===== */
[data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"]{{
  background:rgba(5,22,40,.88)!important;border:1px solid rgba(56,170,210,.30)!important;border-radius:10px!important}}
[data-baseweb="select"]>div:hover,[data-baseweb="input"]:focus-within{{border-color:{TEAL}!important}}
[data-testid="stWidgetLabel"] p{{color:#cfe0ee!important;font-weight:600}}

/* ===== tombol ===== */
.block-container .stButton button[kind="primary"],.block-container .stButton button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{{
  background:linear-gradient(135deg,#1fb98d,#0f8f78)!important;border:1px solid rgba(34,199,154,.6)!important;
  box-shadow:0 8px 20px rgba(34,199,154,.25)!important;color:#fff!important}}
.block-container .stButton button[kind="secondary"],.block-container .stButton button[data-testid="stBaseButton-secondary"]{{
  background:rgba(8,34,58,.85)!important;border:1px solid rgba(56,170,210,.32)!important;color:#e6eef6!important}}
.block-container .stButton button[kind="secondary"]:hover{{border-color:{TEAL}!important}}

/* ===== tombol tema / bahasa (pil) ===== */
.st-key-theme_icon button,.st-key-lang_btn button{{background:rgba(8,34,58,.85)!important;border:1px solid rgba(56,170,210,.32)!important}}

/* ===== tab ===== */
[data-baseweb="tab-highlight"]{{background:{TEAL}!important}}
button[data-baseweb="tab"][aria-selected="true"] p{{color:{TEAL}!important}}
"""


# ------------------------------------------------------------------ layar login
def login_css() -> str:
    """Latar penuh sawah + kartu kaca. Hanya disuntik di layar login (sidebar/header disembunyikan)."""
    return f"""
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"],[data-testid="stHeader"],
.st-key-sb_toggle,.st-key-theme_icon{{display:none!important}}
.stApp{{background:#7fb0d8 url('{LOGIN_BG}') center/cover no-repeat fixed!important}}
.stApp::before{{display:none!important}}
[data-testid="stAppViewContainer"],[data-testid="stMain"]{{background:transparent!important}}
.block-container{{max-width:1320px!important;padding-top:3.2vh!important;padding-bottom:3vh!important;font-family:{UI_FONT}}}
.login-page-spacer{{height:1.5vh}}
.st-key-lang_btn{{top:.9rem!important;right:1.2rem!important}}
.st-key-lang_btn button{{background:rgba(255,255,255,.55)!important;border:1px solid rgba(10,40,70,.18)!important}}
.st-key-lang_btn button p{{color:#0b2a46!important}}

/* ----- hero kiri ----- */
.sk-hero{{display:flex;flex-direction:column;align-items:center;text-align:center;padding:2vh 0 0}}
.sk-hero img{{width:min(250px,30vw);height:auto;filter:drop-shadow(0 10px 26px rgba(8,40,70,.35))}}
.sk-title{{font-family:{BRAND_FONT};font-weight:800;font-size:clamp(3rem,6.2vw,5.2rem);letter-spacing:.14em;line-height:1;margin:.1em 0 0;
  background:linear-gradient(180deg,#fbe9ad 0%,{GOLD} 55%,#b98a1f 100%);-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;filter:drop-shadow(0 3px 10px rgba(8,30,56,.45))}}
.sk-tag{{display:flex;align-items:center;gap:14px;margin:.45rem 0 1.1rem;font-family:{TAG_FONT};font-style:italic;font-weight:600;
  font-size:clamp(1.15rem,1.7vw,1.6rem);color:#fff;text-shadow:0 2px 12px rgba(6,28,52,.6)}}
.sk-tag::before,.sk-tag::after{{content:"";width:clamp(26px,5vw,72px);height:1px;background:rgba(255,255,255,.8)}}
.sk-sub{{color:#fff;font-size:1.02rem;line-height:1.5;text-shadow:0 2px 12px rgba(6,28,52,.65);max-width:34rem}}
.sk-sub i{{display:block;font-size:.95rem;opacity:.92}}

/* ----- kartu kaca kanan ----- */
.st-key-sekar_login_card{{background:linear-gradient(160deg,rgba(255,255,255,.78),rgba(226,238,248,.66));
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.7);border-radius:30px;
  padding:2.4rem 2.2rem 1.8rem;box-shadow:0 24px 60px rgba(8,36,68,.30)}}
.st-key-sekar_login_card h2,.st-key-sekar_login_card h3{{color:#0b2a46!important;font-weight:800;letter-spacing:-.01em}}
.st-key-sekar_login_card [data-testid="stCaptionContainer"] p,.st-key-sekar_login_card p{{color:#3d556b!important}}
.st-key-sekar_login_card [data-testid="stWidgetLabel"] p{{color:#0b2a46!important}}
.st-key-sekar_login_card hr{{border-color:rgba(11,42,70,.15)!important}}
.st-key-sekar_login_card [data-baseweb="input"],.st-key-sekar_login_card [data-baseweb="base-input"]{{
  background:rgba(255,255,255,.88)!important;border:1px solid rgba(11,42,70,.18)!important;border-radius:14px!important;min-height:52px}}
.st-key-sekar_login_card input{{color:#0b2a46!important;-webkit-text-fill-color:#0b2a46!important;background:transparent!important}}
.st-key-sekar_login_card input::placeholder{{color:#6b8196!important;-webkit-text-fill-color:#6b8196!important}}
.st-key-sekar_login_card [data-baseweb="input"] svg{{fill:#516a80!important;color:#516a80!important}}
.st-key-sekar_login_card [data-testid="stForm"]{{background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important}}
.st-key-sekar_login_card [data-testid="stFormSubmitButton"] button{{width:100%;min-height:54px;border-radius:999px;
  background:#0b2a46!important;border:0!important;box-shadow:0 10px 24px rgba(11,42,70,.35)!important;font-size:1.05rem;font-weight:800}}
.st-key-sekar_login_card [data-testid="stFormSubmitButton"] button p{{color:#fff!important}}
.st-key-sekar_login_card [data-testid="stFormSubmitButton"] button:hover{{background:#12395e!important}}
.st-key-sekar_login_card .stButton button{{background:rgba(255,255,255,.7)!important;border:1px solid rgba(11,42,70,.2)!important;border-radius:12px!important}}
.st-key-sekar_login_card .stButton button p{{color:#0b2a46!important;font-weight:700}}
.st-key-sekar_login_card [data-testid="stAlert"]{{border-radius:12px}}
@media(max-width:900px){{.sk-hero img{{width:150px}}.st-key-sekar_login_card{{padding:1.6rem 1.2rem}}}}
"""
