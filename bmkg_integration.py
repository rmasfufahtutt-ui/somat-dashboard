"""BMKG public weather forecast and CAP early-warning fetchers for SOMAT.

Modul ini TIDAK memakai Streamlit: dipanggil dari thread latar (data_hub) atau worker terjadwal.
Tampilan panel BMKG ada di views/bmkg_panels.py dan hanya membaca snapshot.

Catatan Grand Framework v2 (bagian 3.2 dan 5):
  * Prakiraan disimpan sebagai arsip per penerbitan (payload_hash + issued_at + fetched_at).
  * Field `tp` BMKG belum dikonfirmasi satuan/periode akumulasinya: ditampilkan apa adanya dan TIDAK
    dipakai sebagai hujan efektif. Ikon cuaca/tutupan awan tidak diubah menjadi hujan numerik.
  * Koordinat desa pada respons BMKG bukan otomatis koordinat petak.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

BMKG_ADM4 = "32.10.15.2003"  # Desa Panongan, Kecamatan Jatitujuh, Majalengka
BMKG_WARNING_FEED_URL = "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml"
BMKG_LOCAL_AREA_RE = re.compile(r"\b(?:panongan|jatitujuh|jati\s+tujuh|majalengka)\b", re.IGNORECASE)
WIB = timezone(timedelta(hours=7))


def _bmkg_get_text(url, timeout=15):
    """Fetch BMKG public data with a short timeout and explicit user agent."""
    request = Request(
        url,
        headers={
            "User-Agent": "SOMAT-Irrigation-Dashboard/2.0",
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


def _parse_issued(text):
    """analysis_date BMKG (UTC bila tanpa zona) -> datetime UTC berzona, atau None."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_forecast_payload(payload: dict) -> dict:
    """Payload JSON BMKG -> {location, rows, analysis_date}. Fungsi murni (mudah diuji)."""
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
                    "local_datetime": item.get("local_datetime") or "",
                    "utc_datetime": item.get("utc_datetime") or "",
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
    return {"location": location, "rows": rows, "analysis_date": analysis_date}


def fetch_bmkg_forecast(adm4=BMKG_ADM4, timeout=15):
    """Prakiraan BMKG 3 hari (interval 3 jam) untuk kode desa ADM4. Tidak melempar galat."""
    try:
        url = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=" + str(adm4)
        text = _bmkg_get_text(url, timeout=timeout)
        payload = json.loads(text)
        parsed = parse_forecast_payload(payload)
        if not parsed["rows"]:
            raise ValueError("BMKG response did not contain forecast rows")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fetched = datetime.now(timezone.utc)
        return {
            "ok": True, **parsed,
            "adm4": str(adm4),
            "issued_at": _parse_issued(parsed["analysis_date"]),
            "fetched_at": fetched,
            "fetched_label": fetched.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S WIB"),
            "payload_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "raw": payload,
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def fetch_bmkg_early_warnings(timeout=15):
    """Ambil CAP warning BMKG dan saring dampak yang menyebut Panongan/Jatitujuh/Majalengka."""
    try:
        feed_root = ET.fromstring(_bmkg_get_text(BMKG_WARNING_FEED_URL, timeout=timeout))
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
            cap_root = ET.fromstring(_bmkg_get_text(cap_url, timeout=timeout))
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

            area_nodes = [node for node in info.iter() if _xml_local_name(node.tag) == "area"]
            area_descs = [_xml_child_text(node, "areaDesc") for node in area_nodes]
            area_descs = [value for value in area_descs if value]
            location_text = " ".join([headline, description, *area_descs])
            if not BMKG_LOCAL_AREA_RE.search(location_text):
                continue

            matched_areas = [value for value in area_descs if BMKG_LOCAL_AREA_RE.search(value)]
            warnings.append({
                "event": event, "headline": headline, "description": description,
                "urgency": _xml_child_text(info, "urgency"), "severity": _xml_child_text(info, "severity"),
                "certainty": _xml_child_text(info, "certainty"), "effective": _xml_child_text(info, "effective"),
                "expires": expires, "published": published, "areas": matched_areas or area_descs,
                "cap_url": cap_url, "web_link": _xml_child_text(info, "web"),
            })

        fetched = datetime.now(timezone.utc)
        return {"ok": True, "warnings": warnings, "fetched_at": fetched,
                "fetched_label": fetched.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
