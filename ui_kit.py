"""ui_kit.py - komponen UI ringan. Kartu = satu blok markdown (tanpa iframe/JS); grafik = st.plotly_chart native;
tabel = st.dataframe. Tidak ada animasi penghitung, sehingga pindah tab tidak memuat ulang puluhan iframe."""
from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from i18n import L
from styles import theme_for

PLOTLY_CONFIG = {"displaylogo": False, "responsive": True,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}
SERIES_COLORS = ["#22A55B", "#2F80ED", "#E87924", "#A855F7", "#E4565C", "#06B6D4"]


def _T():
    return theme_for(not bool(st.session_state.get("light_mode", False)))


def fmt_ts(ts):
    """Waktu (UTC dari DB) -> teks WIB."""
    try:
        t = pd.to_datetime(ts, utc=True) if getattr(ts, "tzinfo", None) is not None or isinstance(ts, str) else pd.Timestamp(ts).tz_localize("Asia/Jakarta")
        return t.tz_convert("Asia/Jakarta").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def fmt_num(v, nd=1, dash="—"):
    try:
        f = float(v)
        return dash if f != f else f"{f:.{nd}f}"
    except (TypeError, ValueError):
        return dash


# ---------------- kartu ----------------
_PALETTE = {"green": "#22A55B", "blue": "#2F80ED", "orange": "#E87924", "red": "#E4565C"}
_BADGE = {"ok": "#16884A", "warn": "#D85A10", "info": "#256FD1", "bad": "#C03A40"}


def card_html(icon, title, note="", badge_text="", badge_kind="info", color="blue", target=None, decimals=0,
              prefix="", suffix="", value_text=None):
    value = (f"{html.escape(str(prefix))}{float(target):.{int(decimals)}f}{html.escape(str(suffix))}"
             if target is not None else html.escape(str(value_text if value_text is not None else "—")))
    badge = (f'<span class="k-badge" style="background:{_BADGE.get(badge_kind, _BADGE["info"])}">'
             f'{html.escape(str(badge_text))}</span>' if badge_text else "")
    return (f'<div class="k-card" style="border-top-color:{_PALETTE.get(color, _PALETTE["blue"])}">'
            f'<div class="k-title"><span>{html.escape(str(icon))}</span>{html.escape(str(title))}</div>'
            f'<div class="k-value">{value}</div>'
            f'<div class="k-foot">{badge}<span class="k-note">{html.escape(str(note))}</span></div></div>')


def cards(specs, columns=4):
    """Seluruh kartu dalam SATU elemen markdown (grid CSS responsif)."""
    st.markdown(f'<div class="k-grid" style="--cols:{int(columns)}">' + "".join(card_html(**s) for s in specs) + "</div>",
                unsafe_allow_html=True)


def chip(text, kind="info"):
    return f'<span class="k-badge" style="background:{_BADGE.get(kind, _BADGE["info"])}">{html.escape(str(text))}</span>'


def ui_css(dark: bool) -> str:
    t = theme_for(dark)
    return f"""
.k-grid{{display:grid;grid-template-columns:repeat(var(--cols,4),minmax(0,1fr));gap:.7rem;margin:.2rem 0 .8rem}}
.k-card{{background:{t['panel']};border:1px solid {t['border']};border-top:3px solid #2F80ED;border-radius:16px;
  padding:13px 15px;min-height:128px;box-shadow:0 8px 24px rgba(2,8,23,{'.20' if dark else '.06'})}}
.k-title{{font-size:.82rem;color:{t['muted']};font-weight:750;line-height:1.25;display:flex;gap:7px;align-items:flex-start;min-height:32px}}
.k-value{{font-size:1.7rem;font-weight:850;line-height:1.15;color:{t['text']};margin:4px 0 8px;overflow-wrap:anywhere}}
.k-foot{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}
.k-badge{{color:#fff;padding:3px 8px;border-radius:999px;font-size:.68rem;font-weight:800;white-space:nowrap}}
.k-note{{font-size:.72rem;color:{t['muted']}}}
.k-src{{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.7rem;font-weight:800;border:1px solid {t['border']};color:{t['muted']};margin-right:6px}}
.k-banner{{border:1px solid {t['border']};border-left:4px solid #E87924;border-radius:10px;padding:9px 13px;margin:.3rem 0 .8rem;
  background:{t['panel2']};color:{t['text']};font-size:.88rem}}
.k-banner.ok{{border-left-color:#22A55B}} .k-banner.bad{{border-left-color:#E4565C}} .k-banner.info{{border-left-color:#2F80ED}}
@media(max-width:900px){{.k-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:520px){{.k-grid{{grid-template-columns:minmax(0,1fr)}}}}
"""


def banner(text, kind="warn"):
    st.markdown(f'<div class="k-banner {kind}">{text}</div>', unsafe_allow_html=True)


# ---------------- tabel dan grafik ----------------
def table(data, key="table", hide_index=True, max_height=420, column_config=None):
    if data is None or len(data) == 0:
        st.info(L("No data.", "Tidak ada data."))
        return
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    st.dataframe(df, hide_index=hide_index, width="stretch", height=min(max_height, 38 + 35 * len(df)), key=key,
                 column_config=column_config)


def plot(fig, key, height=None):
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CONFIG)


SERIES_COLORS = ["#22A55B", "#2F80ED", "#E87924", "#A855F7", "#E4565C", "#06B6D4"]


def apply_plot_theme(fig, height=None):
    """Terapkan tema terang/gelap SOMAT ke grafik Plotly.

    Semua warna (judul, sumbu, legenda, garis) ditulis eksplisit supaya tetap
    terbaca di mode gelap maupun terang, dan judul tidak terlalu besar.
    """
    fig.update_layout(
        template="plotly_dark" if _T()["dark"] else "plotly_white",
        colorway=SERIES_COLORS,
        paper_bgcolor=_T()["panel"],
        plot_bgcolor=_T()["panel"],
        font=dict(color=_T()["text"], size=12),
        title=dict(
            font=dict(size=15, color=_T()["text"]),
            x=0.02, xanchor="left", y=0.97, yanchor="top",
        ),
        legend=dict(font=dict(size=11, color=_T()["text"]), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=_T()["panel2"], font=dict(color=_T()["text"]), bordercolor=_T()["border"]),
        dragmode="zoom",
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=_T()["muted"],
            activecolor="#2F80ED",
        ),
    )
    if height:
        fig.update_layout(height=height)
    axis_style = dict(
        gridcolor=_T()["grid"], zerolinecolor=_T()["grid"],
        linecolor=_T()["border"],
        tickfont=dict(color=_T()["muted"], size=11),
        title_font=dict(color=_T()["text"], size=12),
    )
    fig.update_xaxes(**axis_style)
    fig.update_yaxes(**axis_style)
    return fig


def make_combo_chart(data):
    """Grafik kondisi terbaru: garis (kelembapan, muka air) + batang (hujan)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=data["date"], y=data["rainfall"], name=L("Rainfall (mm)", "Curah hujan (mm)"),
            marker_color="#7C93B5" if _T()["dark"] else "#9FB3CF", opacity=0.85,
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["soil_moisture"], mode="lines+markers",
            name=L("Soil moisture (%)", "Kelembapan tanah (%)"), line=dict(color="#22A55B", width=3),
        ),
        secondary_y=False,
    )
    # Muka air dikali 30 agar sebanding di sumbu kiri; nilai asli tampil saat hover.
    fig.add_trace(
        go.Scatter(
            x=data["date"], y=data["water_level"] * 30, mode="lines+markers",
            name=L("Water level (m, x30 scale)", "Tinggi muka air (m, skala x30)"),
            line=dict(color="#2F80ED", width=3),
            customdata=data["water_level"],
            hovertemplate="%{customdata:.2f} m<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.update_layout(
        height=360,
        # Ruang ekstra di dalam grafik agar sumbu kanan dan batang terakhir tidak terpotong.
        margin=dict(l=76, r=84, t=44, b=58),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    if len(data):
        x0 = pd.to_datetime(data["date"]).min() - pd.Timedelta(hours=12)
        x1 = pd.to_datetime(data["date"]).max() + pd.Timedelta(hours=12)
        fig.update_xaxes(range=[x0, x1], automargin=True)
    fig.update_yaxes(
        title=dict(text=L("Soil moisture (%) / water level (scaled)", "Kelembapan (%) / muka air (skala)"), font=dict(size=12, color=_T()["text"]), standoff=8),
        secondary_y=False, automargin=True,
    )
    fig.update_yaxes(
        title=dict(text=L("Rainfall (mm)", "Curah hujan (mm)"), font=dict(size=12, color=_T()["text"]), standoff=8),
        secondary_y=True, automargin=True,
    )
    return apply_plot_theme(fig)



def make_line_chart(data, column, title, y_label, bar=False):
    if bar:
        fig = px.bar(data, x="date", y=column, title=title, color_discrete_sequence=["#38A3F5"])
    else:
        fig = px.line(data, x="date", y=column, title=title, markers=True, color_discrete_sequence=["#22A55B"])
        fig.update_traces(line=dict(width=3), marker=dict(size=6))
    fig.update_layout(
        xaxis_title=L("Date", "Tanggal"),
        yaxis_title=y_label,
        height=320,
        margin=dict(l=10, r=10, t=56, b=10),
    )
    return apply_plot_theme(fig)


def sensor_donut(n_online, n_offline):
    total = max(1, int(n_online + n_offline))
    pct = lambda n: f"{100 * n / total:.1f}%"
    fig = go.Figure(data=[go.Pie(labels=["Online", "Offline"], values=[n_online, n_offline], hole=0.62, sort=False,
                                 marker=dict(colors=["#55C985", "#8F8B80"]), showlegend=False,
                                 text=[pct(n_online), pct(n_offline)], textinfo="text",
                                 textfont=dict(color=_T()["text"], size=14),
                                 hovertemplate="%{label}: %{text}<extra></extra>")])
    fig.update_layout(title=dict(text=L("Sensor Status Distribution", "Distribusi Status Sensor"), x=0.02, xanchor="left"),
                      height=330, margin=dict(l=8, r=8, t=55, b=5),
                      annotations=[dict(text=f"{total}<br>Sensor", x=0.5, y=0.5, showarrow=False,
                                        font=dict(size=19, color=_T()["text"]))])
    return apply_plot_theme(fig)


def line_by_sensor(df, title, y_label):
    fig = px.line(df, x="timestamp", y="value", color="sensor_id", title=title, color_discrete_sequence=SERIES_COLORS)
    fig.update_traces(line=dict(width=2))
    fig.update_layout(height=368, yaxis_title=y_label, xaxis_title=None, margin=dict(l=10, r=10, t=56, b=64),
                      legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, title_text="", font=dict(size=10)))
    return apply_plot_theme(fig)


_FIGS: dict = {}


def memo_fig(key, version, builder):
    """Figur Plotly di-memo per (kunci, versi data, tema, bahasa): rerun tanpa data baru tidak membangun ulang grafik."""
    k = (key, version, bool(st.session_state.get("light_mode", False)), st.session_state.get("lang", "en"))
    fig = _FIGS.get(k)
    if fig is None:
        fig = builder()
        if len(_FIGS) >= 64:
            _FIGS.pop(next(iter(_FIGS)))
        _FIGS[k] = fig
    return fig
