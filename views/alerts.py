"""views/alerts.py - peringatan BMKG (snapshot) + peringatan lokal + kejadian terbaru."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from i18n import L
from ui_kit import table
from views import bmkg_panels
from views.overview import mode_banner


def render(ctx):
    d, snap = ctx.d, ctx.snap
    st.header(L("🚨 Alerts / Anomalies", "🚨 Peringatan / Anomali"))
    st.caption(L("Rule-based alerts on the latest inputs. Thresholds are example values; verify source and freshness before acting.",
                 "Peringatan berbasis aturan pada input terbaru. Ambang adalah angka contoh; periksa sumber dan kesegaran data sebelum bertindak."))
    mode_banner(d)
    bmkg_panels.warning_panel(snap)
    st.divider()
    st.subheader(L("SOMAT Local Alerts (Prototype)", "Peringatan Lokal SOMAT (Prototipe)"))
    if d.alerts:
        for a in d.alerts:
            (st.error if a["level"] == "error" else st.warning)(f"{a['title']}: {a['detail']}")
    else:
        st.success(L("✅ No active local alerts. Verify data source and freshness before operational action.",
                     "✅ Tidak ada peringatan lokal aktif. Verifikasi sumber dan kesegaran data sebelum tindakan operasional."))

    st.subheader(L("🗂️ Recent Events", "🗂️ Kejadian Terbaru"))
    inc = []
    if len(d.sensor_table):
        for _, r in d.sensor_table[d.sensor_table["Status"] == "Offline"].iterrows():
            inc.append({"Waktu": str(r["Data valid terakhir"]), "Sumber": r["Sensor"],
                        "Kejadian": L("Sensor offline (no data for more than 3 hours)", "Sensor offline (tanpa data lebih dari 3 jam)"),
                        "Tingkat": L("Warning", "Peringatan"), "Status": L("Needs checking", "Perlu diperiksa")})
    when = str(d.sensor_df["timestamp"].max()) if len(d.sensor_df) else "—"
    for a in d.alerts:
        inc.append({"Waktu": when, "Sumber": L("Alert module", "Modul peringatan"), "Kejadian": f"{a['title']}: {a['detail']}",
                    "Tingkat": L("Critical", "Kritis") if a["level"] == "error" else L("Warning", "Peringatan"),
                    "Status": L("Open", "Terbuka")})
    if inc:
        table(pd.DataFrame(inc), key="incidents")
    else:
        st.info(L("No events. All sensors are online and there are no active alerts.",
                  "Tidak ada kejadian. Seluruh sensor online dan tidak ada peringatan aktif."))
