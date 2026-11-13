"""views/prediction.py - rekomendasi irigasi per petak (baseline fisika Grand Framework v2) + prototipe lama (DEMO)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auth
import recommendation_service as rsvc
import repository as repo
import store
import texts
from i18n import L
from ui_kit import apply_plot_theme, banner, cards, chip, fmt_num, fmt_ts, plot, table


@st.cache_data(ttl=15, show_spinner=False)
def _preview(plot_id, snap_version, max_age_h, _snap):
    """Hitung (tidak menerbitkan) rekomendasi untuk satu petak. Cache 15 dtk / per versi snapshot."""
    now = datetime.now(timezone.utc)
    inp = rsvc.gather_inputs(repo, plot_id, _snap, now)
    out, snapshot = rsvc.compute(max_h_age_hours=max_age_h, decision_at=now, **inp)
    return out, snapshot, inp["profile"]


def _trajectory_fig(out):
    path = out.get("path") or []
    if not path:
        return None
    x = [p[0] for p in path]
    y = [p[1] for p in path]
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers", name="h (cm)", line=dict(width=3, color="#2F80ED")))
    for key, color, name in (("trigger_h_cm", "#E4565C", L("trigger", "pemicu")), ("target_h_cm", "#22A55B", L("target", "target"))):
        if out.get(key) is not None:
            fig.add_hline(y=out[key], line_dash="dash", line_color=color, annotation_text=name)
    for key, name in (("observed_at", L("observed", "diamati")), ("decision_at", L("decision", "keputusan")),
                      ("arrival_at", L("water arrives", "air tiba"))):
        t = out.get(key)
        if t is not None:
            fig.add_vline(x=t if not isinstance(t, datetime) else t.isoformat(), line_dash="dot", opacity=.6)
    fig.update_layout(title=L("Predicted water depth h without irrigation (NO_RAIN scenario)",
                              "Prediksi tinggi air h tanpa irigasi (skenario tanpa hujan)"),
                      yaxis_title="h (cm)", xaxis_title=None, height=340, margin=dict(l=10, r=10, t=56, b=10))
    return apply_plot_theme(fig)


def _et0_table(snapshot):
    rows = []
    for e in snapshot.get("et0_daily") or []:
        rows.append({L("Date", "Tanggal"): str(e["date"]), "Tmin": fmt_num(e["tmin"]), "Tmax": fmt_num(e["tmax"]),
                     L("Slots", "Slot"): e["n"], "ET0 (mm/day)": fmt_num(e["et0_mm_day"], 2),
                     "Status": e["status"] + (" · ESTIMATED_FORECAST_EXTREMA" if e["status"] == "OK" else "")})
    return rows


def _param_table(profile):
    rows = []
    for name, p in sorted((profile.get("params") or {}).items()):
        rows.append({L("Parameter", "Parameter"): name, L("Value", "Nilai"): fmt_num(p.get("value"), 3), L("Unit", "Satuan"): p.get("unit") or "",
                     "Status": texts.param_status_label(p.get("status")), L("Source", "Sumber"): p.get("source") or ""})
    return rows


def render(ctx):
    d, snap, settings = ctx.d, ctx.snap, ctx.settings
    st.header(L("💧 Irrigation Recommendation per Plot", "💧 Rekomendasi Irigasi per Petak"))
    st.caption(L("Water-balance baseline (Grand Framework v2). Decision support only — the operator decides; nothing moves a gate automatically.",
                 "Baseline neraca air (Grand Framework v2). Hanya pendukung keputusan — operator yang memutuskan; tidak ada pintu digerakkan otomatis."))
    plots = store.plots()
    if not plots:
        st.info(L("No plots configured yet. An administrator must add a plot, its parameters and a crop cycle (Admin → Plots & parameters).",
                  "Belum ada petak. Administrator perlu menambah petak, parameter, dan siklus tanam (Admin → Petak & parameter)."))
    else:
        ids = [p["plot_id"] for p in plots]
        pid = st.selectbox(L("Plot", "Petak"), ids, format_func=lambda i: next(f"{p['plot_id']} · {p['name']}" for p in plots if p["plot_id"] == i),
                           key="pred_plot")
        out, snapshot, profile = _preview(pid, snap.version, settings.max_h_age_hours, snap)
        _recommendation_block(ctx, pid, out, snapshot, profile)

    st.divider()
    with st.expander(L("Prototype rule-based logic (DEMO, retained from the earlier dashboard)",
                       "Logika prototipe berbasis aturan (DEMO, dipertahankan dari dashboard sebelumnya)")):
        _legacy_block(d)


def _recommendation_block(ctx, pid, out, snapshot, profile):
    mode = out.get("run_mode", "MANUAL_REQUIRED")
    banner(f"{chip(mode, texts.RUN_KIND.get(mode, 'info'))} {texts.run_mode_label(mode)} · "
           f"{texts.status_label(out['status'])}", texts.RUN_KIND.get(mode, "info"))
    h = snapshot.get("h_observation")
    cards([
        dict(icon="🪣", title=L("Last field h", "h lapangan terakhir"), value_text=f"{fmt_num(h['value'])} cm" if h else "—",
             note=fmt_ts(h["observed_at"]) if h else L("no observation", "belum ada pengamatan"), badge_text="MANUAL", badge_kind="info"),
        dict(icon="⏱️", title=L("Predicted h when water arrives", "Prediksi h saat air tiba"),
             value_text=f"{fmt_num(out.get('h_arrival_cm'))} cm" if out.get("h_arrival_cm") is not None else "—",
             note=L(f"trigger {fmt_num(out.get('trigger_h_cm'))} / target {fmt_num(out.get('target_h_cm'))} cm",
                    f"pemicu {fmt_num(out.get('trigger_h_cm'))} / target {fmt_num(out.get('target_h_cm'))} cm"), color="blue"),
        dict(icon="💧", title=L("Recommended irrigation", "Irigasi disarankan"),
             value_text=(f"{fmt_num(out.get('total_mm'))} mm" if out.get("irrigate") else (L("Not needed", "Belum perlu") if out.get("irrigate") is False else "—")),
             note=(f"{fmt_num(out.get('volume_m3'), 0)} m³" if out.get("volume_m3") else ""), color="green" if out.get("irrigate") else "blue"),
        dict(icon="🚰", title=L("Duration", "Durasi"), value_text=f"{fmt_num(out.get('duration_h'))} h" if out.get("duration_h") else "—",
             note=(L("arrives ", "tiba ") + fmt_ts(out["arrival_at"])) if out.get("arrival_at") else "", color="orange"),
    ], columns=4)
    for r in out.get("reasons") or []:
        st.markdown(f"- {r}")
    for i in out.get("issues") or []:
        if i.get("code") in texts.ISSUE:
            st.caption("• " + texts.issue_text(i))

    fig = _trajectory_fig(out)
    if fig is not None:
        plot(fig, key=f"traj_{pid}")
    with st.expander(L("ET0 per date (HS_v1 from forecast temperature)", "ET0 per tanggal (HS_v1 dari suhu prakiraan)")):
        rows = _et0_table(snapshot)
        table(rows, key=f"et0_{pid}") if rows else st.info(L("No ET0 available (needs plot latitude and BMKG forecast).",
                                                          "ET0 belum tersedia (butuh lintang petak dan prakiraan BMKG)."))
        st.caption(L("Tmin/Tmax come from 3-hour forecast points → ESTIMATED_FORECAST_EXTREMA; incomplete days stay in the calendar and block the run instead of being skipped. Rain is not forecast here: NO_RAIN_SCENARIO.",
                     "Tmin/Tmax berasal dari titik prakiraan 3-jaman → ESTIMATED_FORECAST_EXTREMA; hari tidak lengkap tetap ada di kalender dan menahan run, bukan dilewati. Hujan tidak diprakirakan di sini: NO_RAIN_SCENARIO."))
    if profile:
        with st.expander(L(f"Parameters (profile v{profile['version']}, {profile['validation_status']})",
                           f"Parameter (profil v{profile['version']}, {profile['validation_status']})")):
            table(_param_table(profile), key=f"params_{pid}")

    u = auth.current_user()
    if auth.can_decide():
        can_pub = out["run_mode"] in ("BASELINE_PROVISIONAL", "BASELINE_VALIDATED", "ML_VALIDATED")
        if st.button(L("📨 Publish to Operator for decision", "📨 Terbitkan ke Operator untuk keputusan"), type="primary",
                     disabled=not can_pub, key=f"pub_{pid}"):
            try:
                res = rsvc.run_and_publish(repo, pid, ctx.snap, u["username"], ctx.settings)
                store.invalidate()
                st.success(L(f"Published as recommendation #{res['rec_id']}. Open **Operator Decision**.",
                             f"Diterbitkan sebagai rekomendasi #{res['rec_id']}. Buka **Keputusan Operator**."))
            except Exception:
                st.error(auth.auth_msg("db"))
        if not can_pub:
            st.caption(L("Only baseline runs with real parameters can be published for decision (not DEMO / manual-required).",
                         "Hanya run baseline berparameter nyata yang dapat diterbitkan untuk keputusan (bukan DEMO / perlu-manual)."))
    else:
        st.caption(L("Your role can view recommendations but not publish them.", "Role Anda dapat melihat rekomendasi tetapi tidak menerbitkannya."))


def _legacy_block(d):
    p, hyd, rec = d.prediction, d.hydraulic, d.recommendation
    st.caption(L("Rule-based prototype with assumed numbers. Kept for continuity; it never creates operational decisions.",
                 "Prototipe berbasis aturan dengan angka asumsi. Dipertahankan demi kesinambungan; tidak pernah membuat keputusan operasional."))
    lt = d.latest
    cards([
        dict(icon="🌱", title=L("Soil Moisture", "Kelembapan Tanah"), target=lt["soil_moisture"], decimals=1, suffix=" %"),
        dict(icon="🌧️", title=L("Rainfall", "Curah Hujan"), target=lt["rainfall"], decimals=1, suffix=" mm"),
        dict(icon="☀️", title="ET0 (DEMO)", target=lt["et0"], decimals=2, suffix=" mm"),
        dict(icon="💧", title=L("Irrigation Prediction", "Prediksi Irigasi"), target=p["irrigation_mm"], decimals=1, suffix=" mm"),
    ], columns=4)
    st.write(f"{L('Base demand (ET0 x Kc)', 'Kebutuhan dasar (ET0 x Kc)')}: {p['base_demand']} mm · "
             f"{L('Soil deficit', 'Kekurangan air tanah')}: {p['deficit_mm']} mm · {L('Effective rain', 'Hujan efektif')}: {p['useful_rain']} mm")
    (st.success if hyd["feasible"] else st.error)(L("Hydraulic: FEASIBLE", "Hidraulik: LAYAK") if hyd["feasible"]
                                                  else L("Hydraulic: NOT FEASIBLE", "Hidraulik: TIDAK LAYAK"))
    table(pd.DataFrame(hyd["checks"]), key="hyd_checks")
    st.write(f"**{L('Recommendation (DEMO)', 'Rekomendasi (DEMO)')}**: {rec['recommended_mm']} mm · {rec['duration_hours']} "
             f"{L('h', 'jam')} · {rec['priority']}")
    for reason in rec["reasons"]:
        st.markdown(f"- {reason}")
