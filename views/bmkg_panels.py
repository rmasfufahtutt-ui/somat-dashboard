"""views/bmkg_panels.py - panel BMKG yang MEMBACA snapshot hub (tanpa pemanggilan jaringan saat render)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from i18n import L
from ui_kit import fmt_ts, table


def _age_text(state):
    age = state.age_s()
    if age is None:
        return L("never fetched", "belum pernah ditarik")
    if age < 90:
        return L("just now", "baru saja")
    if age < 5400:
        return L(f"{age / 60:.0f} min ago", f"{age / 60:.0f} menit lalu")
    return L(f"{age / 3600:.1f} h ago", f"{age / 3600:.1f} jam lalu")


def forecast_panel(snap, adm4_label="32.10.15.2003"):
    st.subheader(L("🌦️ BMKG Weather Forecast — Panongan", "🌦️ Prakiraan Cuaca BMKG — Panongan"))
    stt = snap.source("forecast")
    res = snap.forecast
    st.caption(L(f"Reference location: Panongan, Jatitujuh, Majalengka (ADM4 {adm4_label}). Fetched in the background; "
                 f"last success {_age_text(stt)}.",
                 f"Lokasi referensi: Desa Panongan, Jatitujuh, Majalengka (ADM4 {adm4_label}). Ditarik di latar belakang; "
                 f"sukses terakhir {_age_text(stt)}."))
    if not res or not res.get("rows"):
        st.info(L(f"BMKG forecast is not available yet ({stt.error or 'waiting for first fetch'}). Other modules keep working.",
                  f"Prakiraan BMKG belum tersedia ({stt.error or 'menunggu penarikan pertama'}). Modul lain tetap berjalan."))
        return
    if not stt.ok and stt.error:
        st.warning(L(f"Latest fetch failed ({stt.error}); showing the last good forecast.",
                     f"Penarikan terbaru gagal ({stt.error}); menampilkan prakiraan baik terakhir."))
    rows = res["rows"]
    loc = res.get("location", {}) or {}
    label = " · ".join(str(loc.get(k)) for k in ("desa", "kecamatan", "kotkab", "provinsi") if loc.get(k))
    if label:
        st.caption(label)
    first = rows[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(L("Next forecast", "Prakiraan terdekat"), str(first.get("weather_desc") or "—"))
    c2.metric(L("Air temperature", "Suhu udara"), f"{first['temperature']} °C" if first.get("temperature") is not None else "—")
    c3.metric(L("Humidity", "Kelembapan"), f"{first['humidity']} %" if first.get("humidity") is not None else "—")
    c4.metric(L("Wind speed", "Kecepatan angin"), f"{first['wind_speed']} km/jam" if first.get("wind_speed") is not None else "—")
    st.caption(L(f"BMKG issue: {res.get('analysis_date') or 'not supplied'} · fetched {res.get('fetched_label', '—')}",
                 f"Terbitan BMKG: {res.get('analysis_date') or 'tidak tersedia'} · ditarik {res.get('fetched_label', '—')}"))
    with st.expander(L("View full 3-day forecast (3-hour intervals)", "Tampilkan prakiraan lengkap 3 hari (interval 3 jam)")):
        out = []
        for r in rows[:24]:
            try:
                t = pd.to_datetime(r.get("local_datetime")).strftime("%d/%m/%Y %H:%M")
            except Exception:
                t = r.get("local_datetime") or "—"
            dash = lambda v: "—" if v is None else v
            out.append({L("Local time (WIB)", "Waktu lokal (WIB)"): t, L("Weather", "Cuaca"): r.get("weather_desc") or "—",
                        "TP (BMKG)": dash(r.get("precipitation_tp")), L("Temp (°C)", "Suhu (°C)"): dash(r.get("temperature")),
                        L("Humidity (%)", "Kelembapan (%)"): dash(r.get("humidity")),
                        L("Wind (km/h)", "Angin (km/jam)"): dash(r.get("wind_speed")),
                        L("Cloud (%)", "Awan (%)"): dash(r.get("cloud_cover"))})
        table(pd.DataFrame(out), key="bmkg_forecast_tbl")
        st.caption(L("Source: BMKG Open Weather Data. `tp` has no documented unit/accumulation period, so it is shown only "
                     "and never used as rainfall in the water balance.",
                     "Sumber: Data Terbuka BMKG. `tp` tidak punya satuan/periode akumulasi terdokumentasi, sehingga hanya "
                     "ditampilkan dan tidak dipakai sebagai hujan pada neraca air."))


def warning_panel(snap):
    st.subheader(L("⚠️ BMKG Early Weather Warnings", "⚠️ Peringatan Dini Cuaca BMKG"))
    stt = snap.source("warnings")
    st.caption(L("Only active CAP warnings whose affected-area text mentions Panongan, Jatitujuh, or Majalengka are shown. "
                 f"Last success {_age_text(stt)}.",
                 "Hanya peringatan CAP aktif yang teks wilayahnya menyebut Panongan, Jatitujuh, atau Majalengka. "
                 f"Sukses terakhir {_age_text(stt)}."))
    if not stt.has_data:
        st.info(L(f"BMKG warning feed not available yet ({stt.error or 'waiting for first fetch'}). Local alerts keep running.",
                  f"Feed peringatan BMKG belum tersedia ({stt.error or 'menunggu penarikan pertama'}). Peringatan lokal tetap berjalan."))
        return
    if not stt.ok and stt.error:
        st.warning(L(f"Latest fetch failed ({stt.error}); showing the last good result.",
                     f"Penarikan terbaru gagal ({stt.error}); menampilkan hasil baik terakhir."))
    if not snap.warnings:
        st.success(L("No active BMKG warning explicitly matching Panongan/Jatitujuh/Majalengka at the last check.",
                     "Tidak ada peringatan aktif BMKG yang cocok eksplisit dengan Panongan/Jatitujuh/Majalengka pada pemeriksaan terakhir."))
        return
    for w in snap.warnings:
        sev = (w.get("severity") or "Unknown").lower()
        title = w.get("headline") or w.get("event") or L("Weather warning", "Peringatan cuaca")
        box = st.error if sev in ("extreme", "severe") else (st.warning if sev == "moderate" else st.info)
        box(f"**{title}**\n\n{w.get('description') or ''}")
        meta = " · ".join(v for v in [w.get("event", ""),
                                      (L("Severity", "Tingkat keparahan") + ": " + w["severity"]) if w.get("severity") else "",
                                      (L("Urgency", "Urgensi") + ": " + w["urgency"]) if w.get("urgency") else "",
                                      (L("Effective", "Mulai berlaku") + ": " + w["effective"]) if w.get("effective") else "",
                                      (L("Valid until", "Berlaku sampai") + ": " + w["expires"]) if w.get("expires") else ""] if v)
        if meta:
            st.caption(meta)
        if w.get("areas"):
            st.caption(L("Matched affected areas: ", "Wilayah terdampak yang cocok: ") + ", ".join(w["areas"]))
        if w.get("cap_url"):
            st.markdown(f"[CAP BMKG]({w['cap_url']})")
        if w.get("web_link"):
            st.markdown(f"[Infografik BMKG]({w['web_link']})")
