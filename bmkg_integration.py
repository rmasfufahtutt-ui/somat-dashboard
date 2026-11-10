"""BMKG public weather forecast and CAP early-warning integration for SOMAT.

Uses only Python standard-library networking/XML tools plus Streamlit and pandas,
which are already part of the SOMAT application environment.
"""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st


def _L(en, id_):
    return en if st.session_state.get("lang", "en") == "en" else id_


# ---------------- BMKG OPEN DATA (external weather context) ----------------
BMKG_ADM4 = "32.10.15.2003"  # Desa Panongan, Kecamatan Jatitujuh, Majalengka
BMKG_WARNING_FEED_URL = "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml"
BMKG_LOCAL_AREA_RE = re.compile(
    r"\b(?:panongan|jatitujuh|jati\s+tujuh|majalengka)\b", re.IGNORECASE
)

def _bmkg_get_text(url, timeout=15):
    """Fetch BMKG public data with a short timeout and explicit user agent."""
    request = Request(
        url,
        headers={
            "User-Agent": "SOMAT-Irrigation-Dashboard/1.0",
            "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _xml_local_name(tag):
    return str(tag).rsplit("}", 1)[-1].lower()


def _xml_child_text(node, child_name):
    if node is None:
        return ""
    wanted = child_name.lower()
    for child in list(node):
        if _xml_local_name(child.tag) == wanted:
            return (child.text or "").strip()
    return ""


@st.cache_data(ttl=1500, show_spinner=False)
def fetch_bmkg_forecast(adm4=BMKG_ADM4):
    """Prakiraan BMKG 3 hari (interval 3 jam) untuk kode desa ADM4."""
    try:
        url = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=" + str(adm4)
        payload = json.loads(_bmkg_get_text(url))
        location = payload.get("lokasi") or {}
        rows = []
        analysis_date = payload.get("analysis_date", "")

        for block in payload.get("data", []):
            if not isinstance(block, dict):
                continue
            if not location:
                location = block.get("lokasi") or {}
            for daily in block.get("cuaca", []):
                day_items = daily if isinstance(daily, list) else [daily]
                for item in day_items:
                    if not isinstance(item, dict):
                        continue
                    rows.append({
                        "local_datetime": item.get("local_datetime") or item.get("utc_datetime") or "",
                        "weather_desc": item.get("weather_desc") or item.get("weather_desc_en") or "—",
                        "precipitation_tp": item.get("tp"),
                        "temperature": item.get("t"),
                        "humidity": item.get("hu"),
                        "wind_speed": item.get("ws"),
                        "wind_direction": item.get("wd"),
                        "cloud_cover": item.get("tcc"),
                        "visibility": item.get("vs_text"),
                        "analysis_date": item.get("analysis_date") or "",
                    })
                    if not analysis_date and item.get("analysis_date"):
                        analysis_date = item.get("analysis_date")

        if not rows:
            raise ValueError("BMKG response did not contain forecast rows")

        return {
            "ok": True,
            "location": location,
            "forecasts": rows,
            "analysis_date": analysis_date,
            "fetched_at": datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S WIB"),
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


@st.cache_data(ttl=240, show_spinner=False)
def fetch_bmkg_early_warnings():
    """Ambil CAP warning BMKG dan saring dampak yang menyebut Panongan/Jatitujuh/Majalengka."""
    try:
        feed_root = ET.fromstring(_bmkg_get_text(BMKG_WARNING_FEED_URL))
        feed_items = [node for node in feed_root.iter() if _xml_local_name(node.tag) == "item"]
        warnings = []
        now_utc = datetime.now(timezone.utc)

        for item in feed_items[:30]:
            title = _xml_child_text(item, "title")
            link = _xml_child_text(item, "link")
            feed_description = _xml_child_text(item, "description")
            published = _xml_child_text(item, "pubDate")
            province_text = " ".join((title, feed_description, link)).lower()

            # CJB merupakan pola kode CAP yang digunakan pada contoh resmi BMKG untuk Jawa Barat.
            if "jawa barat" not in province_text and not re.search(r"/CJB[^/]*_alert\.xml", link, re.IGNORECASE):
                continue
            if not link:
                continue

            cap_url = urljoin(BMKG_WARNING_FEED_URL, link)
            cap_root = ET.fromstring(_bmkg_get_text(cap_url))
            info_nodes = [node for node in cap_root.iter() if _xml_local_name(node.tag) == "info"]
            if not info_nodes:
                continue
            info = next(
                (node for node in info_nodes if _xml_child_text(node, "language").lower() in ("id", "ind")),
                info_nodes[0],
            )

            status = _xml_child_text(cap_root, "status").lower()
            message_type = _xml_child_text(cap_root, "msgType").lower()
            if status and status != "actual":
                continue
            if message_type and message_type not in ("alert", "update"):
                continue

            expires = _xml_child_text(info, "expires")
            if expires:
                try:
                    expiry_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                    if expiry_dt <= now_utc:
                        continue
                except ValueError:
                    pass

            event = _xml_child_text(info, "event") or title or "Peringatan dini cuaca"
            headline = _xml_child_text(info, "headline") or title
            description = _xml_child_text(info, "description") or feed_description
            urgency = _xml_child_text(info, "urgency")
            severity = _xml_child_text(info, "severity")
            certainty = _xml_child_text(info, "certainty")
            effective = _xml_child_text(info, "effective")
            web_link = _xml_child_text(info, "web")

            area_nodes = [node for node in info.iter() if _xml_local_name(node.tag) == "area"]
            area_descs = [_xml_child_text(node, "areaDesc") for node in area_nodes]
            area_descs = [value for value in area_descs if value]
            location_text = " ".join([headline, description, *area_descs])
            if not BMKG_LOCAL_AREA_RE.search(location_text):
                continue

            matched_areas = [value for value in area_descs if BMKG_LOCAL_AREA_RE.search(value)]
            warnings.append({
                "event": event,
                "headline": headline,
                "description": description,
                "urgency": urgency,
                "severity": severity,
                "certainty": certainty,
                "effective": effective,
                "expires": expires,
                "published": published,
                "areas": matched_areas or area_descs,
                "cap_url": cap_url,
                "web_link": web_link,
            })

        return {
            "ok": True,
            "warnings": warnings,
            "fetched_at": datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S WIB"),
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


@st.fragment(run_every="30m")
def render_bmkg_forecast_panel():
    """Auto-refresh prakiraan tiap 30 menit selama halaman Monitoring aktif."""
    st.subheader(_L("🌦️ BMKG Weather Forecast — Panongan", "🌦️ Prakiraan Cuaca BMKG — Panongan"))
    st.caption(_L(
        "Automatic refresh: every 30 minutes while this page is open. BMKG publishes forecast updates twice daily.",
        "Pembaruan otomatis: setiap 30 menit selama halaman ini terbuka. BMKG menerbitkan pembaruan prakiraan dua kali sehari.",
    ))
    result = fetch_bmkg_forecast()
    st.caption(_L(
        "Reference location: Panongan Village, Jatitujuh, Majalengka (ADM4 32.10.15.2003).",
        "Lokasi referensi: Desa Panongan, Kecamatan Jatitujuh, Majalengka (ADM4 32.10.15.2003).",
    ))
    if not result.get("ok"):
        st.info(_L(
            f"BMKG forecast is temporarily unavailable ({result.get('error', 'connection error')}). Other SOMAT modules remain available.",
            f"Prakiraan BMKG sementara tidak dapat diakses ({result.get('error', 'gangguan koneksi')}). Modul SOMAT lainnya tetap dapat digunakan.",
        ))
        st.caption("Sumber data: BMKG — https://data.bmkg.go.id/prakiraan-cuaca/")
        return

    forecasts = result.get("forecasts", [])
    if not forecasts:
        st.info(_L("No forecast records were returned by BMKG.", "BMKG belum mengembalikan data prakiraan."))
        return

    location = result.get("location", {})
    location_label = " · ".join(
        str(location.get(key)) for key in ("desa", "kecamatan", "kotkab", "provinsi") if location.get(key)
    )
    if location_label:
        st.caption(location_label)

    first = forecasts[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(_L("Next forecast", "Prakiraan terdekat"), str(first.get("weather_desc") or "—"))
    c2.metric(_L("Air temperature", "Suhu udara"), f"{first.get('temperature')} °C" if first.get("temperature") is not None else "—")
    c3.metric(_L("Humidity", "Kelembapan"), f"{first.get('humidity')} %" if first.get("humidity") is not None else "—")
    c4.metric(_L("Wind speed", "Kecepatan angin"), f"{first.get('wind_speed')} km/jam" if first.get("wind_speed") is not None else "—")

    table_rows = []
    for row in forecasts[:24]:
        raw_time = row.get("local_datetime", "")
        try:
            time_label = pd.to_datetime(raw_time).strftime("%d/%m/%Y %H:%M")
        except Exception:
            time_label = raw_time or "—"
        table_rows.append({
            _L("Local time (WIB)", "Waktu lokal (WIB)"): time_label,
            _L("Weather", "Cuaca"): row.get("weather_desc") or "—",
            _L("TP (BMKG)", "TP (BMKG)"): row.get("precipitation_tp") if row.get("precipitation_tp") is not None else "—",
            _L("Temperature (°C)", "Suhu (°C)"): row.get("temperature") if row.get("temperature") is not None else "—",
            _L("Humidity (%)", "Kelembapan (%)"): row.get("humidity") if row.get("humidity") is not None else "—",
            _L("Wind (km/h)", "Angin (km/jam)"): row.get("wind_speed") if row.get("wind_speed") is not None else "—",
            _L("Wind direction", "Arah angin"): row.get("wind_direction") or "—",
            _L("Cloud cover (%)", "Tutupan awan (%)"): row.get("cloud_cover") if row.get("cloud_cover") is not None else "—",
            _L("Visibility", "Jarak pandang"): row.get("visibility") or "—",
        })
    # Keep the compact weather summary visible; expand the full forecast table only when needed.
    st.caption(_L(
        f"BMKG forecast updated at {result.get('analysis_date') or 'time not supplied'} · Last checked {result.get('fetched_at')}.",
        f"Pembaruan prakiraan BMKG: {result.get('analysis_date') or 'waktu tidak tersedia'} · Terakhir diperiksa {result.get('fetched_at')}.",
    ))
    with st.expander(
        _L("View full 3-day forecast (3-hour intervals)", "Tampilkan prakiraan lengkap 3 hari (interval 3 jam)"),
        expanded=False,
    ):
        st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")
        st.caption(_L(
            "Source: BMKG Open Weather Data. The sample JSON may include `tp`; BMKG's public parameter list does not define its unit/accumulation period, so it is displayed as supplied but is not yet used in the irrigation calculation. The numeric rainfall input remains the RF-01 simulated reading.",
            "Sumber: Data Terbuka BMKG. Contoh JSON dapat memuat `tp`; daftar parameter publik BMKG belum menjelaskan satuan/periode akumulasinya, sehingga nilai ditampilkan sebagaimana diterima tetapi belum digunakan dalam perhitungan irigasi. Input curah hujan numerik tetap berasal dari pembacaan simulasi RF-01.",
        ))


@st.fragment(run_every="5m")
def render_bmkg_warning_panel():
    """Auto-refresh peringatan dini tiap 5 menit selama halaman Alerts aktif."""
    st.subheader(_L("⚠️ BMKG Early Weather Warnings", "⚠️ Peringatan Dini Cuaca BMKG"))
    st.caption(_L(
        "Automatic refresh: every 5 minutes while this page is open.",
        "Pembaruan otomatis: setiap 5 menit selama halaman ini terbuka.",
    ))
    result = fetch_bmkg_early_warnings()
    st.caption(_L(
        "Only active CAP warnings whose affected-area text mentions Panongan, Jatitujuh, or Majalengka are shown.",
        "Hanya peringatan CAP aktif yang teks wilayah terdampaknya menyebut Panongan, Jatitujuh, atau Majalengka yang ditampilkan.",
    ))
    if not result.get("ok"):
        st.info(_L(
            f"BMKG warning feed is temporarily unavailable ({result.get('error', 'connection error')}). This does not affect the local SOMAT alert module.",
            f"Feed peringatan BMKG sementara tidak dapat diakses ({result.get('error', 'gangguan koneksi')}). Modul peringatan lokal SOMAT tetap berjalan.",
        ))
    elif not result.get("warnings"):
        st.success(_L(
            "No active BMKG warning explicitly matching Panongan/Jatitujuh/Majalengka was found at the last check.",
            "Tidak ditemukan peringatan aktif BMKG yang secara eksplisit cocok dengan Panongan/Jatitujuh/Majalengka pada pemeriksaan terakhir.",
        ))
    else:
        for warning in result["warnings"]:
            severity = (warning.get("severity") or "Unknown").lower()
            title = warning.get("headline") or warning.get("event") or _L("Weather warning", "Peringatan cuaca")
            details = warning.get("description") or ""
            if severity in ("extreme", "severe"):
                st.error(f"**{title}**\n\n{details}")
            elif severity == "moderate":
                st.warning(f"**{title}**\n\n{details}")
            else:
                st.info(f"**{title}**\n\n{details}")

            meta = " · ".join(value for value in [
                warning.get("event", ""),
                (_L("Severity", "Tingkat keparahan") + ": " + warning.get("severity", "")) if warning.get("severity") else "",
                (_L("Urgency", "Urgensi") + ": " + warning.get("urgency", "")) if warning.get("urgency") else "",
                (_L("Effective", "Mulai berlaku") + ": " + warning.get("effective", "")) if warning.get("effective") else "",
                (_L("Certainty", "Kepastian") + ": " + warning.get("certainty", "")) if warning.get("certainty") else "",
                (_L("Valid until", "Berlaku sampai") + ": " + warning.get("expires", "")) if warning.get("expires") else "",
            ] if value)
            if meta:
                st.caption(meta)
            if warning.get("areas"):
                st.caption(_L("Matched affected areas: ", "Wilayah terdampak yang cocok: ") + ", ".join(warning["areas"]))
            if warning.get("cap_url"):
                st.markdown(f"[Detail peringatan CAP BMKG]({warning['cap_url']})")
            if warning.get("web_link"):
                st.markdown(f"[Infografik BMKG]({warning['web_link']})")

    st.caption(_L(
        f"Source: BMKG Early Weather Warning (CAP) · Retrieved {result.get('fetched_at', '—')}.",
        f"Sumber: Peringatan Dini Cuaca BMKG (CAP) · Diambil {result.get('fetched_at', '—')}.",
    ))

