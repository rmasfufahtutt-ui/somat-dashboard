"""styles.py - tema, CSS global, dan aset logo. Semua string CSS dibangun SEKALI per kombinasi (tema, sidebar)
dan di-cache; satu rerun hanya menyuntikkan satu blok <style> (tidak ada pembangunan ulang per halaman)."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "assets" / "somat_logo.png"
IRRIGATION_LOGIN_PATH = BASE_DIR / "assets" / "irrigation_login.jpg"


def theme_for(dark: bool) -> dict:
    IS_DARK = dark
    return {
        "dark": IS_DARK,
        "bg": "#0B1220" if IS_DARK else "#F4F7FB",
        "panel": "#111B2C" if IS_DARK else "#FFFFFF",
        "panel2": "#0F1A2A" if IS_DARK else "#F8FAFD",
        "sidebar": "#080F1A" if IS_DARK else "#FFFFFF",
        "text": "#E8EEF8" if IS_DARK else "#172033",
        "muted": "#94A3B8" if IS_DARK else "#667085",
        "border": "#24324A" if IS_DARK else "#DCE3ED",
        "grid": "rgba(148,163,184,.12)" if IS_DARK else "rgba(71,85,105,.12)",
    }


@st.cache_data(show_spinner=False, max_entries=4)
def build_css(dark: bool, collapsed: bool) -> str:
    IS_DARK, COLLAPSED = bool(dark), bool(collapsed)
    THEME = theme_for(IS_DARK)

    # Mode gelap -> ikon matahari (pindah ke terang); mode terang -> ikon bulan.
    # FIX 2: kedua ikon digambar simetris di kanvas 24x24 dengan pusat (12,12),
    # stroke & ukuran sama, tanpa rotasi, supaya tepat di tengah tombol bulat.
    if IS_DARK:
        _theme_svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
            "stroke='#F59E0B' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
            "<circle cx='12' cy='12' r='4' fill='#FBBF24'/>"
            "<path d='M12 2v2M12 20v2M2 12h2M20 12h2"
            "M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41"
            "M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41'/></svg>"
        )
    else:
        # Bulan sabit (Lucide "moon"); digeser sedikit agar pusat visualnya di (12,12).
        _theme_svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
            "stroke-linecap='round' stroke-linejoin='round'>"
            "<g transform='translate(.9 -.9)'>"
            "<path d='M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z' fill='#F8D96B' "
            "stroke='#EAB308' stroke-width='2'/></g></svg>"
        )
    THEME_ICON = quote(_theme_svg, safe="")
    def _chevron_icon(direction):
        """Ikon panah ganda (chevrons-left / chevrons-right) untuk tombol sidebar."""
        path = ("m11 17-5-5 5-5M18 17l-5-5 5-5" if direction == "left"
                else "m6 17 5-5-5-5M13 17l5-5-5-5")
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
            f"stroke='{THEME['text']}' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>"
            f"<path d='{path}'/></svg>"
        )
        return quote(svg, safe="")
    _EXTRA_CSS = """
    /* ===== Menu sidebar: rata kiri, font lebih besar ===== */
    [data-testid="stSidebar"] .stButton{width:100%;}
    [data-testid="stSidebar"] .stButton button{
      justify-content:flex-start!important;text-align:left!important;
      padding:.62rem 1rem!important;min-height:50px!important;
      background:__PANEL2__;color:__TEXT__;border:1px solid __BORDER__;border-radius:12px;
    }
    [data-testid="stSidebar"] .stButton button>div,
    [data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{
      width:100%!important;display:flex!important;justify-content:flex-start!important;text-align:left!important;
    }
    [data-testid="stSidebar"] .stButton button p{
      font-size:1rem!important;font-weight:700!important;line-height:1.25!important;
      text-align:left!important;width:100%;margin:0!important;color:inherit!important;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"],
    [data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{
      background:linear-gradient(135deg,#2F80ED,#1E63C8)!important;border-color:#2F80ED!important;
      box-shadow:0 6px 16px rgba(47,128,237,.32);
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"] p,
    [data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
    [data-testid="stSidebar"] .stButton button:hover{border-color:#2F80ED!important;}
    .side-brand{display:flex;align-items:center;gap:14px;padding:14px 2px 14px;}
    .side-brand img{width:92px;height:auto;max-height:84px;object-fit:contain;flex:0 0 auto;}
    .side-brand-name{font-size:2.1rem;font-weight:850;letter-spacing:-.02em;line-height:1.05;color:__TEXT__;}
    .side-brand-sub{font-size:.92rem;line-height:1.35;color:__MUTED__;margin-top:4px;}
    [data-testid="stSidebar"] h4{font-size:1.15rem!important;margin-top:.6rem!important;}
    [data-testid="stSidebar"] [data-testid="stAlert"]{font-size:1.02rem!important;}
    [data-testid="stSidebar"] [data-testid="stAlert"] p{font-size:1.02rem!important;}
    [data-testid="stSidebar"] .stButton button{min-height:48px!important;padding:.5rem .9rem!important;}
    [data-testid="stSidebar"] .stButton button p{font-size:1rem!important;}
    .side-info-title{font-size:1.1rem!important;}
    .side-info-muted{font-size:.9rem!important;}
    .side-info-line{font-size:.98rem!important;}
    .side-flow{font-size:.98rem!important;line-height:1.65!important;}
    /* judul halaman lebih tenang */
    .block-container h2,[data-testid="stHeading"] h2{font-size:1.9rem!important;line-height:1.25!important;}
    .block-container h3,[data-testid="stHeading"] h3{font-size:1.35rem!important;}
    /* tombol aksi operator */
    .block-container [data-testid="stHorizontalBlock"] .stButton button{min-height:52px;border-radius:12px;font-weight:800;}
    .block-container [data-testid="stHorizontalBlock"] .stButton button p{font-size:1.05rem!important;font-weight:800!important;letter-spacing:.04em;}
    .block-container .stButton button[kind="primary"],.block-container .stButton button[data-testid="stBaseButton-primary"]{box-shadow:0 6px 16px rgba(47,128,237,.3);}
    /* hanya satu tombol panah sidebar yang tampil */
    .stApp:has([data-testid="stSidebar"][aria-expanded="true"]) [data-testid="stExpandSidebarButton"]{display:none!important;}
    .stApp:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stSidebarCollapseButton"]{display:none!important;}

    /* ===== HP / layar kecil: font dan jarak diperkecil ===== */
    @media(max-width:800px){
      html{font-size:14px;}
      .block-container{padding:3.2rem .8rem 2rem!important;}
      h1{font-size:1.25rem!important;}
      h2,[data-testid="stHeading"] h2{font-size:1.3rem!important;line-height:1.25!important;}
      h3,[data-testid="stHeading"] h3{font-size:1.1rem!important;}
      [data-testid="stCaptionContainer"] p{font-size:.8rem!important;}
      [data-testid="stAlert"] p,[data-testid="stAlert"]{font-size:.85rem!important;}
      .somat-header{gap:10px;}
      .somat-header img{width:46px!important;height:auto!important;}
      .somat-header h1{font-size:1.15rem!important;line-height:1.2!important;}
      .somat-header p{font-size:.78rem!important;}
      .status-panel{padding:12px 14px;}
      .status-row{font-size:.85rem!important;}
      [data-testid="stSidebar"] .stButton button p{font-size:.95rem!important;}
      .side-brand img{width:64px;}
      .side-brand-name{font-size:1.6rem;}
      .side-brand-sub{font-size:.8rem;}
      .st-key-theme_icon{top:.5rem!important;right:.6rem!important;}
      .st-key-lang_btn{top:.5rem!important;right:calc(.6rem + 46px)!important;}
    }
    """

    _LIGHT_CSS = """
    /* ===== Mode terang: paksa semua komponen Streamlit ikut berubah ===== */
    .stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"]{
      background:__BG__!important;color:__TEXT__!important;color-scheme:light;
    }
    [data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;}
    [data-testid="stToolbar"] *,[data-testid="stHeader"] svg{color:__TEXT__!important;fill:__TEXT__;}
    h1,h2,h3,h4,h5,h6,[data-testid="stHeading"],[data-testid="stHeading"] *,
    [data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] *,
    [data-testid="stWidgetLabel"],[data-testid="stWidgetLabel"] *,label,label *{color:__TEXT__!important;}
    [data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:__MUTED__!important;}
    .somat-header h1{color:__TEXT__!important;}
    .somat-header p{color:__MUTED__!important;}
    .side-info-muted{color:__MUTED__!important;}
    .status-title,.status-row,.status-row *{color:__TEXT__!important;}
    .st-ok{color:#16884A!important;} .st-warn{color:#D85A10!important;}
    /* kotak peringatan */
    [data-testid="stAlert"]{border:1px solid __BORDER__;}
    [data-testid="stAlert"] *{color:inherit!important;}
    [data-testid="stAlertContentWarning"]{color:#7A4B00;}
    [data-testid="stAlertContentSuccess"]{color:#14532D;}
    [data-testid="stAlertContentInfo"]{color:#1E3A8A;}
    [data-testid="stAlertContentError"]{color:#7F1D1D;}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){background:#FFF6DD!important;border-color:#F3D98B;}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){background:#E8F8EE!important;border-color:#A7E0BC;}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]){background:#E8F1FD!important;border-color:#AFCBF5;}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){background:#FDECEC!important;border-color:#F3B4B4;}
    /* expander */
    div[data-testid="stExpander"],div[data-testid="stExpander"] details{background:__PANEL__!important;border-color:__BORDER__!important;}
    div[data-testid="stExpander"] summary,div[data-testid="stExpander"] summary *{color:__TEXT__!important;}
    /* input */
    input,textarea,[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="base-input"]{
      background:__PANEL__!important;color:__TEXT__!important;border-color:__BORDER__!important;
    }
    [data-testid="stNumberInput"] button{background:__PANEL2__!important;color:__TEXT__!important;}
    /* tombol (di luar sidebar) */
    .stButton button,[data-testid="stFormSubmitButton"]>button{background:__PANEL__;color:__TEXT__!important;border:1px solid __BORDER__;}
    .stButton button p,[data-testid="stFormSubmitButton"]>button p{color:inherit!important;}
    .stButton button[kind="primary"],.stButton button[data-testid="stBaseButton-primary"],
    [data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{background:#2F80ED!important;border-color:#2F80ED!important;}
    .stButton button[kind="primary"] p,.stButton button[data-testid="stBaseButton-primary"] p{color:#FFFFFF!important;}
    /* sidebar */
    [data-testid="stSidebar"],[data-testid="stSidebarContent"]{background:__SIDEBAR__!important;}
    [data-testid="stSidebar"] *{color:__TEXT__;}
    [data-testid="stSidebar"] [data-testid="stAlert"] *{color:inherit!important;}
    [data-testid="stSidebar"] .stButton button[kind="primary"] *,
    [data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] *{color:#FFFFFF!important;}
    hr{border-color:__BORDER__!important;}
    code{background:__PANEL2__!important;color:__TEXT__!important;}
    """


    def _fill_css(css):
        return (css.replace("__BG__", THEME["bg"]).replace("__PANEL__", THEME["panel"])
                   .replace("__PANEL2__", THEME["panel2"]).replace("__SIDEBAR__", THEME["sidebar"])
                   .replace("__TEXT__", THEME["text"]).replace("__MUTED__", THEME["muted"])
                   .replace("__BORDER__", THEME["border"]))


    EXTRA_CSS = _fill_css(_EXTRA_CSS) + ("" if IS_DARK else _fill_css(_LIGHT_CSS))


    # ---------------- Global responsive styling ----------------
    # FIX 1 - lebar sidebar mengikuti status (penuh / mini-ikon). Di desktop sidebar
    # SELALU tampil (tidak pernah disembunyikan); tombol panah bawaan Streamlit
    # disembunyikan di desktop dan diganti satu tombol kustom (.st-key-sb_toggle).
    SB_W = "72px" if COLLAPSED else "21rem"
    MAIN_MAXW = "min(100%,1840px)!important" if COLLAPSED else "1540px"
    SB_ICON = _chevron_icon("right" if COLLAPSED else "left")

    SB_CSS = f"""
          @media(min-width:801px){{
            [data-testid="stSidebar"],[data-testid="stSidebar"][aria-expanded="false"],[data-testid="stSidebar"][aria-expanded="true"]{{
              width:{SB_W}!important;min-width:{SB_W}!important;max-width:{SB_W}!important;
              transform:none!important;margin-left:0!important;visibility:visible!important;
            }}
            [data-testid="stSidebarCollapseButton"],[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"]{{display:none!important;}}
          }}
    """

    CONTROLS_CSS = f"""
          /* ===== FIX 2: tombol tema bulat sempurna, ikon tepat di tengah ===== */
          .st-key-theme_icon{{position:fixed!important;top:.62rem!important;right:.8rem!important;z-index:999999!important;width:38px!important;height:38px!important;pointer-events:auto!important;}}
          .st-key-theme_icon button{{
            position:relative!important;box-sizing:border-box!important;
            width:38px!important;height:38px!important;min-width:38px!important;min-height:38px!important;
            aspect-ratio:1/1;padding:0!important;margin:0!important;flex:none!important;
            border-radius:50%!important;border:1px solid {THEME['border']}!important;
            background:{THEME['panel']}!important;color:transparent!important;
            box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
            display:flex!important;align-items:center!important;justify-content:center!important;
            font-size:0!important;line-height:0!important;transform:none!important;
            transition:border-color .15s ease,box-shadow .15s ease!important;
          }}
          .st-key-theme_icon button>*{{display:none!important;}}
          .st-key-theme_icon button::before{{
            content:"";position:absolute;left:50%;top:50%;width:20px;height:20px;
            transform:translate(-50%,-50%);background:center/contain no-repeat url("data:image/svg+xml,{THEME_ICON}");
          }}
          .st-key-theme_icon button:hover,.st-key-theme_icon button:focus-visible{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;transform:none!important;}}
          /* ===== FIX 1: SATU tombol buka/tutup sidebar (ikon panah ganda) ===== */
          .st-key-sb_toggle{{position:fixed!important;top:.62rem!important;left:calc({SB_W} - 19px)!important;z-index:999998!important;width:38px!important;height:38px!important;}}
          .st-key-sb_toggle button{{
            position:relative!important;box-sizing:border-box!important;
            width:38px!important;height:38px!important;min-width:38px!important;min-height:38px!important;
            padding:0!important;margin:0!important;flex:none!important;border-radius:50%!important;
            border:1px solid {THEME['border']}!important;background:{THEME['panel2']}!important;color:transparent!important;
            box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
            display:flex!important;align-items:center!important;justify-content:center!important;
            font-size:0!important;line-height:0!important;transform:none!important;
            transition:border-color .15s ease,box-shadow .15s ease!important;
          }}
          .st-key-sb_toggle button>*{{display:none!important;}}
          .st-key-sb_toggle button::before{{
            content:"";position:absolute;left:50%;top:50%;width:18px;height:18px;
            transform:translate(-50%,-50%);background:center/contain no-repeat url("data:image/svg+xml,{SB_ICON}");
          }}
          .st-key-sb_toggle button:hover,.st-key-sb_toggle button:focus-visible{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;transform:none!important;}}
          @media(max-width:800px){{.st-key-sb_toggle{{display:none!important;}}}}
          /* ===== Tombol bahasa EN / ID ===== */
          .st-key-lang_btn{{position:fixed!important;top:.62rem!important;right:calc(.8rem + 46px)!important;z-index:999999!important;height:38px!important;width:auto!important;}}
          .st-key-lang_btn button{{
            box-sizing:border-box!important;height:38px!important;min-height:38px!important;padding:0 14px!important;
            border-radius:999px!important;border:1px solid {THEME['border']}!important;
            background:{THEME['panel']}!important;
            box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
            display:flex!important;align-items:center!important;justify-content:center!important;
            transform:none!important;
          }}
          .st-key-lang_btn button p{{font-size:.82rem!important;font-weight:800!important;letter-spacing:.04em;line-height:1!important;margin:0!important;color:{THEME['text']}!important;white-space:nowrap;}}
          .st-key-lang_btn button:hover{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.2)!important;}}
    """

    MINI_TEMPLATE = """
    /* ===== FIX 1: mini-sidebar (hanya ikon) di desktop ===== */
    @media(min-width:801px){
      [data-testid="stSidebarContent"]{overflow-x:hidden!important;}
      [data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding:.4rem 0 1rem!important;}
      [data-testid="stSidebar"] [data-testid="stElementContainer"],
      [data-testid="stSidebar"] [data-testid="stMarkdown"]{width:100%!important;max-width:100%!important;display:flex!important;justify-content:center!important;}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.55rem!important;}
      [data-testid="stSidebar"] .stButton,[data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"]{width:auto!important;display:flex;justify-content:center;}
      [data-testid="stSidebar"] .stButton button{
        width:46px!important;min-width:46px!important;height:46px!important;min-height:46px!important;
        padding:0!important;justify-content:center!important;border-radius:12px!important;
      }
      [data-testid="stSidebar"] .stButton button>div,
      [data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{width:auto!important;justify-content:center!important;}
      [data-testid="stSidebar"] .stButton button p{font-size:1.3rem!important;line-height:1!important;text-align:center!important;width:auto!important;}
      [data-testid="stSidebar"] .stButton button:hover{transform:none!important;}
      .side-brand.mini{justify-content:center;padding:10px 0 8px;gap:0;}
      .side-brand.mini img{width:34px!important;max-height:40px;}
    }
    """
    MINI_CSS = _fill_css(MINI_TEMPLATE) if COLLAPSED else ""

    # Tooltip (help=...) ikut tema: latar panel, teks kontras (di mode terang sebelumnya teks gelap di latar gelap).
    TOOLTIP_CSS = f"""
          [data-testid="stTooltipContent"],[data-baseweb="tooltip"] [data-testid="stTooltipContent"]{{
            background:{THEME['panel2']}!important;color:{THEME['text']}!important;
            border:1px solid {THEME['border']}!important;border-radius:8px!important;
            box-shadow:0 8px 24px rgba(2,8,23,{'.35' if IS_DARK else '.12'})!important;
          }}
          [data-testid="stTooltipContent"] *{{color:{THEME['text']}!important;}}
          .st-key-somat_sess{{position:absolute!important;width:0!important;height:0!important;overflow:hidden!important;margin:0!important;}}
          [data-baseweb="tooltip"] > div,[data-baseweb="popover"] > div{{background:transparent!important;}}
    """


    return f'''
    <style>
      :root{{--somat-bg:{THEME['bg']};--somat-panel:{THEME['panel']};--somat-text:{THEME['text']};--somat-muted:{THEME['muted']};--somat-border:{THEME['border']};}}
      .stApp{{background:var(--somat-bg);color:var(--somat-text);}}
      [data-testid="stHeader"]{{background:transparent;}}
      [data-testid="stSidebar"]{{background:{THEME['sidebar']};border-right:1px solid {THEME['border']};}}
      {SB_CSS}
      [data-testid="stSidebarContent"]{{padding-top:.35rem!important;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,.48) transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar{{width:5px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-track{{background:transparent;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb{{background:rgba(148,163,184,.42);border-radius:999px;}}
      [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb:hover{{background:rgba(148,163,184,.68);}}
      [data-testid="stSidebar"] *{{color:{THEME['text']};}}
      /* Panah bawaan Streamlit hanya dipakai di HP/layar kecil (drawer); di desktop dipakai tombol kustom. */
      @media(max-width:800px){{
      [data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"]{{
        display:flex!important;visibility:visible!important;opacity:1!important;position:fixed!important;top:.62rem!important;z-index:999998!important;
      }}
      [data-testid="stSidebarCollapseButton"]{{left:calc(21rem - 3rem)!important;}}
      [data-testid="stExpandSidebarButton"]{{left:.65rem!important;}}
      [data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"] button{{
        width:38px!important;height:38px!important;min-height:38px!important;padding:0!important;
        border-radius:10px!important;border:1px solid {THEME['border']}!important;
        background:{THEME['panel2']}!important;color:{THEME['text']}!important;
        box-shadow:0 7px 20px rgba(2,8,23,{'.22' if IS_DARK else '.08'})!important;
        display:grid!important;place-items:center!important;font-size:0!important;line-height:1!important;
      }}
      [data-testid="stSidebarCollapseButton"] button svg, [data-testid="stExpandSidebarButton"] button svg{{display:none!important;}}
      [data-testid="stSidebarCollapseButton"] button::before{{content:"«";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stExpandSidebarButton"] button::before{{content:"»";font-size:25px;font-weight:850;line-height:1;transform:translateY(-1px);}}
      [data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stExpandSidebarButton"] button:hover{{border-color:#2F80ED!important;box-shadow:0 8px 24px rgba(47,128,237,.18)!important;}}
      }}
      {CONTROLS_CSS}
      .block-container{{padding-top:.75rem!important;padding-bottom:2.2rem!important;max-width:{MAIN_MAXW};}}
      p,li,label,.stMarkdown{{color:{THEME['text']};}}
      [data-testid="stCaptionContainer"] p{{color:{THEME['muted']}!important;}}
      hr{{border-color:{THEME['border']}!important;}}
      [data-testid="stSidebar"] .stButton button{{
        width:100%;justify-content:flex-start;border-radius:11px;min-height:42px;
        font-weight:700;border:1px solid {THEME['border']};transition:.18s ease;
      }}
      [data-testid="stSidebar"] .stButton button:hover{{transform:translateX(2px);border-color:#2F80ED;}}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:.45rem;}}
      [data-testid="stHorizontalBlock"]{{align-items:stretch!important;min-width:0!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"]{{flex:1 1 0!important;width:0!important;min-width:0!important;max-width:none!important;overflow:hidden!important;}}
      [data-testid="stHorizontalBlock"] > [data-testid="column"] iframe,
      [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stIFrame"]{{width:100%!important;max-width:100%!important;min-width:0!important;display:block!important;}}
      .side-info-card{{background:{THEME['panel2']};border:1px solid {THEME['border']};border-radius:14px;padding:12px 13px;margin-top:10px;box-shadow:0 6px 18px rgba(2,8,23,{'.15' if IS_DARK else '.04'});}}
      .side-info-title{{display:flex;gap:8px;align-items:center;font-size:.94rem;font-weight:820;margin:0 0 8px;color:{THEME['text']};}}
      .side-info-muted{{color:{THEME['muted']};font-size:.77rem;line-height:1.45;margin-bottom:6px;}}
      .side-info-line{{font-size:.82rem;line-height:1.55;color:{THEME['text']};}}
      .side-flow{{font-size:.81rem;line-height:1.55;color:{THEME['text']};letter-spacing:.002em;}}
      .side-profile{{display:flex;align-items:center;gap:11px;background:{THEME['panel2']};border:1px solid {THEME['border']};border-radius:14px;padding:10px 12px;margin-top:12px;min-width:0;}}
      .side-profile img,.side-profile-fallback{{width:42px;height:42px;min-width:42px;border-radius:50%;object-fit:cover;border:1px solid {THEME['border']};background:{THEME['panel']};}}
      .side-profile-fallback{{display:grid;place-items:center;font-weight:850;font-size:1rem;color:#fff!important;background:linear-gradient(135deg,#2563EB,#16A34A);}}
      .side-profile-name{{font-size:.91rem;font-weight:820;line-height:1.25;overflow-wrap:anywhere;color:{THEME['text']};}}
      .side-profile-caption{{font-size:.72rem;color:{THEME['muted']};margin-top:3px;}}
      .side-profile-mini{{display:flex;justify-content:center;margin:10px 0 4px;}}
      .side-profile-mini img,.side-profile-mini .side-profile-fallback{{width:40px;height:40px;border-radius:50%;object-fit:cover;}}
      .login-visual{{min-height:560px;height:100%;border-radius:24px;overflow:hidden;padding:26px 30px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;background-color:#0B1830;background-size:cover;background-position:center;box-shadow:0 18px 50px rgba(2,8,23,.22);}}
      .login-visual-brand{{display:flex;align-items:center;gap:12px;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.3);}}
      .login-visual-brand img{{width:66px;height:66px;object-fit:contain;filter:drop-shadow(0 4px 12px rgba(0,0,0,.25));}}
      .login-visual-brand strong{{display:block;font-size:1.3rem;letter-spacing:.04em;}}
      .login-visual-brand span{{display:block;font-size:.72rem;opacity:.9;max-width:260px;line-height:1.35;}}
      .login-visual-copy{{max-width:570px;color:#fff;text-shadow:0 2px 16px rgba(0,0,0,.35);}}
      .login-visual-copy small{{font-size:.72rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#BFE9FF;}}
      .login-visual-copy h2{{font-size:clamp(1.8rem,3vw,2.8rem);line-height:1.08;font-weight:850;letter-spacing:-.035em;color:#fff;margin:.65rem 0;}}
      .login-visual-copy p{{font-size:.98rem;line-height:1.6;color:rgba(255,255,255,.92);max-width:500px;margin:0;}}
      .login-visual-foot{{font-size:.75rem;color:rgba(255,255,255,.82);letter-spacing:.03em;}}
      .login-panel-brand{{display:flex;align-items:center;gap:12px;margin:2.4rem 0 1.5rem;}}
      .login-panel-brand img{{width:62px;height:62px;object-fit:contain;}}
      .login-panel-brand strong{{font-size:1.2rem;font-weight:900;letter-spacing:.035em;color:{THEME['text']};}}
      .login-panel-brand span{{display:block;font-size:.74rem;color:{THEME['muted']};line-height:1.35;}}
      .st-key-login_form [data-testid="stForm"],.st-key-login_form[data-testid="stForm"]{{background:{THEME['panel']};border:1px solid {THEME['border']};border-radius:18px;padding:1.15rem 1.25rem;box-shadow:0 12px 30px rgba(2,8,23,{'.16' if IS_DARK else '.06'});}}
      .st-key-login_form [data-testid="stFormSubmitButton"] button{{width:100%;min-height:44px;border-radius:11px;font-weight:800;}}
      div[data-testid="stExpander"]{{border-color:{THEME['border']};background:{THEME['panel']};border-radius:12px;}}
      [data-testid="stDataFrame"]{{border:1px solid {THEME['border']};border-radius:12px;overflow:hidden;}}
      [data-testid="stPlotlyChart"]{{border:1px solid {THEME['border']};border-radius:16px;background:{THEME['panel']};overflow:hidden;box-shadow:0 7px 20px rgba(2,8,23,{'.15' if IS_DARK else '.05'});}}
      .main .block-container{{animation:somatContentIn .16s ease-out;}}
      @keyframes somatContentIn{{from{{opacity:.94;transform:translateY(2px)}}to{{opacity:1;transform:translateY(0)}}}}
      .somat-header{{display:flex;align-items:center;gap:14px;margin:0 0 10px;padding:4px 0 2px;}}
      @media(min-width:801px){{.somat-header{{padding-right:8.5rem;}}}}
      .somat-header img{{width:78px;height:70px;object-fit:contain;flex:0 0 auto;filter:drop-shadow(0 5px 14px rgba(0,90,160,.12));}}
      .somat-header h1{{font-size:clamp(1.55rem,2.2vw,2.45rem);line-height:1.08;margin:0;color:{THEME['text']};font-weight:850;letter-spacing:-.035em;}}
      .somat-header p{{margin:5px 0 0;color:{THEME['muted']};font-size:.93rem;}}
      .status-panel{{background:{THEME['panel']};border:1px solid {THEME['border']};border-radius:16px;padding:16px 18px;box-shadow:0 7px 20px rgba(2,8,23,{'.16' if IS_DARK else '.05'});}}
      .status-title{{font-weight:800;color:{THEME['text']};margin-bottom:8px;}}
      .status-row{{padding:5px 0;color:{THEME['text']};font-size:.92rem;}}
      .st-ok{{color:#22A55B;font-weight:900;}} .st-warn{{color:#E87924;font-weight:900;}}
      .sim-dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#2F80ED;margin-right:8px;animation:pulse 2s infinite;}}
      @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(47,128,237,.65)}}70%{{box-shadow:0 0 0 8px rgba(47,128,237,0)}}100%{{box-shadow:0 0 0 0 rgba(47,128,237,0)}}}}
      @media(max-width:800px){{
        [data-testid="stSidebar"]{{width:min(86vw,21rem)!important;min-width:min(86vw,21rem)!important;}}
        [data-testid="stSidebarCollapseButton"]{{left:calc(min(86vw,21rem) - 3rem)!important;}}
        .block-container{{padding-left:.75rem!important;padding-right:.75rem!important;padding-top:.45rem!important;}}
        .somat-header{{gap:9px;align-items:center}} .somat-header img{{width:58px;height:53px}}
        .somat-header p{{font-size:.8rem}} h1{{font-size:1.55rem!important}}
        [data-testid="stHorizontalBlock"]{{flex-wrap:wrap!important;gap:.5rem!important;}}
        [data-testid="stHorizontalBlock"] > [data-testid="column"]{{min-width:100%!important;max-width:100%!important;flex:1 1 100%!important;width:100%!important;overflow:visible!important;}}
      }}
      @media(prefers-reduced-motion:reduce){{.sim-dot{{animation:none}}}}
      {EXTRA_CSS}
      {MINI_CSS}
      {TOOLTIP_CSS}
    </style>
    '''


# ---------------- aset ----------------

@st.cache_resource(show_spinner=False)
def _logo_b64():
    """Logo diperkecil (maks. 160 px) lalu di-cache. Sebelumnya file asli ~118 KB di-embed
    beberapa kali pada setiap rerun, memperlambat perpindahan tab."""
    for cand in (
        LOGO_PATH,
        Path.cwd() / "assets" / "somat_logo.png",
        BASE_DIR / "somat_logo.png",
        Path.cwd() / "somat_logo.png",
    ):
        try:
            if cand.exists():
                data = cand.read_bytes()
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        im = im.convert("RGBA")
                        im.thumbnail((160, 160))
                        buf = io.BytesIO()
                        im.save(buf, "PNG", optimize=True)
                        data = buf.getvalue()
                except Exception:
                    pass
                return base64.b64encode(data).decode("ascii")
        except OSError:
            pass
    return ""

LOGO_FALLBACK = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='0' y2='1'%3E"
    "%3Cstop offset='0' stop-color='%2338BDF8'/%3E%3Cstop offset='1' stop-color='%232F80ED'/%3E"
    "%3C/linearGradient%3E%3C/defs%3E"
    "%3Cpath d='M32 3C32 3 11 26 11 40a21 21 0 0 0 42 0C53 26 32 3 32 3Z' fill='url(%23g)'/%3E"
    "%3Cpath d='M32 52c0-10 3-17 12-22-1 11-5 19-12 22Z' fill='%2322A55B'/%3E"
    "%3Cpath d='M32 52c0-8-3-13-10-16 0 8 4 14 10 16Z' fill='%2384CC16'/%3E"
    "%3C/svg%3E"
)


logo_b64 = _logo_b64()
LOGO_SRC = f"data:image/png;base64,{logo_b64}" if logo_b64 else LOGO_FALLBACK

@st.cache_resource(show_spinner=False)
def _irrigation_image_b64():
    for candidate in (IRRIGATION_LOGIN_PATH, BASE_DIR / "irrigation_login.jpg", Path.cwd() / "assets" / "irrigation_login.jpg"):
        try:
            if candidate.exists():
                return base64.b64encode(candidate.read_bytes()).decode("ascii")
        except OSError:
            pass
