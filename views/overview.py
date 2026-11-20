"""views/overview.py - ringkasan kondisi. Hanya membaca snapshot + turunan yang sudah di-memo."""
from __future__ import annotations

from functools import lru_cache

import streamlit as st

import demo_mode
import ocean_theme
import store
from i18n import L
from legacy_prototype import ASSUMPTIONS
from ui_kit import banner, cards, chip, fmt_num, fmt_ts, make_combo_chart, memo_fig, plot, table

MODE_TEXT = {
    "LIVE": ("ok", "Live sensor data from Google Sheets (background fetch).",
             "Data sensor live dari Google Sheets (ditarik di latar belakang)."),
    "CACHED_DB": ("warn", "Showing the last archived sensor data from the database while the first live fetch completes.",
                  "Menampilkan arsip sensor terakhir dari database sambil menunggu penarikan live pertama."),
    "WAITING_FOR_DATA": ("warn", "Google Sheets is connected but has no sensor readings yet — DEMO values are shown.",
                         "Google Sheets terhubung tetapi belum ada pembacaan — nilai DEMO ditampilkan."),
    "SIMULATION_FALLBACK": ("bad", "Google Sheets unavailable — DEMO (simulated) values are shown. Not field measurements.",
                            "Google Sheets tidak terjangkau — nilai DEMO (simulasi) ditampilkan. Bukan hasil pengukuran."),
    "UNAVAILABLE": ("bad", "No usable sensor data right now (source unavailable, empty, or all readings excluded by QC). "
                    "Values are shown as unavailable; no simulated values are used in the operational workspace.",
                    "Belum ada data sensor yang dapat dipakai (sumber tak tersedia, kosong, atau semua pembacaan dikeluarkan QC). "
                    "Nilai ditampilkan tidak tersedia; nilai simulasi tidak dipakai di ruang operasional."),
    "SIMULATION": ("warn", "No sensor source configured — DEMO (simulated) values are shown. Not field measurements.",
                   "Sumber sensor belum dikonfigurasi — nilai DEMO (simulasi) ditampilkan. Bukan hasil pengukuran."),
}


def mode_banner(d):
    kind, en, idn = MODE_TEXT[d.mode]
    extra = ""
    if d.mode in ("LIVE", "CACHED_DB") and set(d.source_types) & {"DUMMY", "SIMULATED"}:
        extra = " " + L("Source type is DUMMY: readings come from a test feed, not installed devices.",
                        "Jenis sumber DUMMY: pembacaan berasal dari umpan uji, bukan perangkat terpasang.")
        kind = "warn"
    banner(L(en, idn) + extra, kind)


def render(ctx):
    d = ctx.d
    st.header(L("Conditions Overview", "Ringkasan Kondisi (Overview)"))
    ocean_theme.render_steps(L, getattr(ctx, "nav_allowed", None))
    mode_banner(d)
    lt = d.latest
    if not d.legacy_available:
        _operational_cards(d)
    else:
        _legacy_cards(d, lt)
    _tail(d, ctx)


def _fin(x) -> bool:
    try:
        return x is not None and x == x and abs(float(x)) != float("inf")
    except Exception:
        return False


def _val(x, **kw):
    """Kartu bernilai bila angka ada; bila tidak, tampil '—' (tidak tersedia), bukan 0 atau simulasi."""
    return dict(kw, target=x) if _fin(x) else dict(kw, value_text="—", badge_text=L("Unavailable", "Tidak tersedia"),
                                                    badge_kind="warn", color="orange")


@lru_cache(maxsize=48)
def _svg_soil(v, low, lm, ll, ln):
    return ocean_theme.soil_svg(v, low, lm, ll, ln)


@lru_cache(maxsize=48)
def _svg_canal(v, mn, lm, lb, ln):
    return ocean_theme.canal_svg(v, mn, 2.0, lm, lb, ln)


@lru_cache(maxsize=48)
def _svg_rain(v, lim, ll, ln):
    return ocean_theme.rain_svg(v, lim, ll, ln)


def _num_or_none(x):
    return float(x) if _fin(x) else None


def _trio(sm, wl, rn, low_m=20, min_wl=None, heavy_r=20):
    """Tiga kartu bergambar (tanah, saluran, hujan). Ilustrasi mengikuti nilai ukur; nilai tak tersedia -> tanpa air/zona lembap."""
    min_wl = ASSUMPTIONS["min_water_level"] if min_wl is None else min_wl
    sm, wl, rn = _num_or_none(sm), _num_or_none(wl), _num_or_none(rn)
    na_txt = L("Fresh valid readings only (≤ 3 h)", "Hanya pembacaan valid segar (≤ 3 jam)")
    unavail = (L("Unavailable", "Tidak tersedia"), "warn")

    def badge(v, ok, low_text):
        return unavail if v is None else ((L("Normal", "Normal"), "ok") if ok else (low_text, "warn"))

    sm_b = badge(sm, sm is not None and sm >= low_m, L("Low", "Rendah"))
    wl_b = badge(wl, wl is not None and wl >= min_wl, L("Low", "Rendah"))
    rn_b = badge(rn, rn is not None and rn < heavy_r, L("High", "Tinggi"))
    no_data = L("No data", "Tidak ada data")
    soil = dict(svg=_svg_soil(sm, float(low_m), L("moisture", "lembap"), L("LOW LIMIT", "BATAS RENDAH"), no_data),
                alt=L(f"Soil profile with a plant: moisture {sm:.1f}%, low limit {low_m}%", f"Profil tanah dengan tanaman: kelembapan {sm:.1f}%, batas rendah {low_m}%")
                if sm is not None else L("Soil profile: no moisture reading", "Profil tanah: belum ada pembacaan kelembapan"),
                title=L("Soil moisture", "Kelembapan tanah"), value=sm, decimals=1, unit="%",
                sub=na_txt if sm is None else (L(f"Above the low limit of {low_m}%", f"Di atas batas rendah {low_m}%") if sm >= low_m
                                               else L(f"Below the low limit of {low_m}%", f"Di bawah batas rendah {low_m}%")),
                badge_text=sm_b[0], badge_kind=sm_b[1])
    canal = dict(svg=_svg_canal(wl, float(min_wl), L("MIN", "MIN"), L("bed", "dasar"), no_data),
                 alt=L(f"Canal cross-section: water level {wl:.2f} m, minimum {min_wl} m", f"Penampang saluran: muka air {wl:.2f} m, minimum {min_wl} m")
                 if wl is not None else L("Canal cross-section: no water level reading", "Penampang saluran: belum ada pembacaan muka air"),
                 title=L("Canal water level", "Tinggi muka air"), value=wl, decimals=2, unit="m",
                 sub=na_txt if wl is None else f"Minimum {min_wl} m", badge_text=wl_b[0], badge_kind=wl_b[1])
    rain = dict(svg=_svg_rain(rn, float(heavy_r), L("High limit", "Batas tinggi"), no_data),
                alt=L(f"Cloud: rainfall {rn:.1f} mm, high limit {heavy_r} mm", f"Awan: curah hujan {rn:.1f} mm, batas tinggi {heavy_r} mm")
                if rn is not None else L("Cloud: no rainfall reading", "Awan: belum ada pembacaan curah hujan"),
                title=L("Rainfall", "Curah hujan"), value=rn, decimals=1, unit="mm",
                sub=L("Rain gauge, last 24 h", "Rain gauge, 24 jam terakhir") if rn is None else L(f"High limit {heavy_r} mm", f"Batas tinggi {heavy_r} mm"),
                badge_text=rn_b[0], badge_kind=rn_b[1])
    st.markdown(ocean_theme.sensor_trio(soil, canal, rain), unsafe_allow_html=True)


def _operational_cards(d):
    """Ruang operasional: hanya nilai sensor nyata. Model prototipe simulasi tidak dipakai."""
    s = d.sensor_summary
    _trio(s.get("soil_moisture"), s.get("water_level"), s.get("rainfall"))
    cards([
        dict(icon="🛡️", title=L("System Status", "Status Sistem"), value_text=L("UNKNOWN", "TIDAK DIKETAHUI"),
             note=L("Crop water requirement and irrigation decisions come from the plot recommendations, not from this overview.",
                    "Kebutuhan air dan keputusan irigasi berasal dari rekomendasi petak, bukan dari ringkasan ini."),
             badge_text=L("See Recommendations", "Lihat Rekomendasi"), badge_kind="info", color="blue"),
    ], columns=1)


def _legacy_cards(d, lt):
    """Ruang DEMO / prototipe: tiga kartu bergambar + debit, kebutuhan air tanaman, status sistem."""
    low_m, heavy_r = 20, 20
    q_ok = lt["available_discharge"] >= d.hydraulic["required_discharge"]
    normal = d.system_status == "NORMAL"
    ok = lambda b, a, c: (a if b else c)
    _trio(lt["soil_moisture"], lt["water_level"], lt["rainfall"], low_m=low_m, heavy_r=heavy_r)
    req, avail = float(d.hydraulic["required_discharge"]), float(lt["available_discharge"])
    cards([
        dict(icon="💧", title=L("Available Discharge", "Debit Tersedia"), target=lt["available_discharge"], decimals=3,
             suffix=" m³/s", bars=[(100, "#3aa7d6"), (100 * req / avail if avail > 0 else 100, "#f5c969")],
             note=L(f"Required {req:.3f} m³/s (DEMO model)", f"Dibutuhkan {req:.3f} m³/s (model DEMO)"),
             badge_text=ok(q_ok, L("Sufficient", "Cukup"), L("Short", "Kurang")), badge_kind=ok(q_ok, "ok", "warn"),
             color=ok(q_ok, "blue", "orange")),
        dict(icon="🌾", title=L("Crop Water Requirement", "Kebutuhan Air Tanaman"), target=lt["crop_water_requirement"],
             decimals=1, suffix=L(" mm/day", " mm/hari"),
             note=L(f"Predicted irrigation {d.prediction['irrigation_mm']} mm (DEMO)",
                    f"Irigasi prediksi {d.prediction['irrigation_mm']} mm (DEMO)"), badge_text=L("Prototype", "Prototipe"),
             badge_kind="info", color="blue"),
        dict(icon="🛡️", title=L("System Status", "Status Sistem"), value_text="NORMAL" if normal else L("ATTENTION", "PERHATIAN"),
             note=L("No active alerts", "Tidak ada peringatan aktif") if normal else L("Operator validation needed", "Perlu validasi operator"),
             badge_text="Normal" if normal else L("Attention", "Perhatian"), badge_kind=ok(normal, "ok", "warn"),
             color=ok(normal, "green", "red"), cls="k-status" if normal else ""),
    ], columns=3)


def _tail(d, ctx):
    lt = d.latest
    low_m, heavy_r = 20, 20
    sm_ok = _fin(lt['soil_moisture']) and lt['soil_moisture'] >= low_m
    wl_ok = _fin(lt['water_level']) and lt['water_level'] >= ASSUMPTIONS['min_water_level']
    rain_ok = _fin(lt['rainfall']) and lt['rainfall'] < heavy_r
    if demo_mode.is_demo():
        from views import demo_panels
        demo_panels.plots_overview(ctx)

    # ---- petak (v2): h terakhir, status rekomendasi ----
    st.subheader(L("Plots (field-observed water depth h)", "Petak (tinggi air h hasil pengamatan lapangan)"))
    ov = store.plot_overview()
    if not ov:
        st.info(L("No plots yet. An administrator can add plots and parameters in Admin → Plots & parameters.",
                  "Belum ada petak. Administrator dapat menambah petak dan parameter di Admin → Petak & parameter."))
    else:
        rows = []
        for r in ov:
            h, pend, prof = r["h"], r["pending"], r["profile"]
            rows.append({L("Plot", "Petak"): f"{r['plot']['plot_id']} · {r['plot']['name']}",
                         L("Last h (cm)", "h terakhir (cm)"): fmt_num(h["value"]) if h else "—",
                         L("Observed at", "Diamati"): fmt_ts(h["observed_at"]) if h else L("no observation", "belum ada pengamatan"),
                         L("Profile", "Profil"): f"v{prof['version']} · {prof['validation_status']}" if prof else "—",
                         L("Recommendation", "Rekomendasi"): (f"#{pend['rec_id']} · {pend['status_code']} · {pend['run_mode']}"
                                                              if pend else "—")})
        table(rows, key="ov_plots")

    st.markdown(f'<div class="k-banner info">{chip(L("Status", "Status"), "info")} '
                + L("System and field status", "Status sistem dan lahan") + ": "
                + " · ".join([("✔" if sm_ok else "⚠") + " " + L("soil moisture", "kelembapan tanah"),
                              ("✔" if wl_ok else "⚠") + " " + L("water level", "muka air"),
                              ("✔" if rain_ok else "⚠") + " " + L("rainfall", "hujan"),
                              *([("✔" if d.hydraulic["feasible"] else "⚠") + " " + L("hydraulics (DEMO)", "hidraulik (DEMO)"),
                                 ("✔" if not d.alerts else "⚠") + " " + L(f"{len(d.alerts)} alert(s)", f"{len(d.alerts)} peringatan")]
                                if d.legacy_available else [])])
                + "</div>", unsafe_allow_html=True)

    st.header(L("Latest Conditions Chart (Last 14 Days)", "Grafik Kondisi Terbaru (14 Hari Terakhir)"))
    st.caption(L("Drag to zoom. Days without readings are left blank, not filled with invented numbers.",
                 "Drag untuk zoom. Hari tanpa pembacaan dibiarkan kosong, tidak diisi angka buatan."))
    plot(memo_fig("ov_combo", d.version, lambda: make_combo_chart(d.sensor_daily.tail(14))), key="ov_combo", height=360)
