"""sekar_bg.py - latar dalam dashboard SEKAR (terang & gelap). Hanya CSS; tidak mengubah logika aplikasi."""
from __future__ import annotations

STATIC = "app/static"


def css(dark: bool) -> str:
    img = f"{STATIC}/sekar_bg_dark.jpg" if dark else f"{STATIC}/sekar_bg_light.jpg"
    base = "#06223a" if dark else "#eaf6fb"
    pos = "center" if dark else "right bottom"
    return f"""
html body .stApp{{background:{base} url('{img}') {pos}/cover no-repeat fixed!important}}
html body .stApp::before{{display:none!important}}
html body .stApp [data-testid="stAppViewContainer"],
html body .stApp [data-testid="stMain"],
html body .stApp [data-testid="stMainBlockContainer"],
html body .stApp [data-testid="stHeader"]{{background:transparent!important}}
"""
