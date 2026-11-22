"""views/demo_panels.py - komponen tampilan khusus ruang DEMO PENELITIAN.

Memakai ulang komponen yang sudah ada (cards, chip, table, plot, banner). Semua yang tampil di sini berlabel sintetis/simulasi;
sumber BMKG asli dan cuaca sintetis tidak pernah dicampur dalam satu hitungan.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auth
import demo_data
import demo_ml
import demo_mode
import demo_repository as drepo
import demo_service
import demo_weather as dw
import formstate as fs
import store
import texts
from i18n import L
from ui_kit import apply_plot_theme, banner, cards, chip, fmt_num, fmt_ts, plot, table

RAIN_CHOICES = ["DEFAULT", "NONE", "LIGHT", "TODAY_HEAVY", "HEAVY"]
RAIN_TEXT = {"DEFAULT": ("Scenario default of this plot", "Bawaan skenario petak ini"),
             "NONE": ("No rain (NO_RAIN_SCENARIO, as operational)", "Tanpa hujan (NO_RAIN_SCENARIO, seperti operasional)"),
             "LIGHT": ("Light rain (synthetic)", "Hujan ringan (sintetis)"),
             "TODAY_HEAVY": ("Heavy rain today (synthetic)", "Hujan lebat hari ini (sintetis)"),
             "HEAVY": ("Heavy rain for 3 days (synthetic)", "Hujan lebat 3 hari (sintetis)")}
DRIVER_TEXT = {dw.DRIVER_SYNTHETIC: ("Synthetic temperature (scenario)", "Suhu sintetis (skenario)"),
               dw.DRIVER_BMKG: ("Real BMKG forecast", "Prakiraan BMKG asli")}
MODEL_TEXT = {"M1": ("M1 · SPconstant (physics baseline)", "M1 · SPconstant (baseline fisika)"),
              "M2": ("M2 · demo AI residual (synthetic training)", "M2 · residual AI demo (dilatih data sintetis)")}


# ---------------------------------------------------------------------------------------------- kontrol & hitung
def controls(pid: str) -> dict:
    """Pilihan sumber suhu, hujan, dan model. State tersimpan di sesi: pindah halaman tidak mereset pilihan."""
    fs.keep("demo_driver", dw.DRIVER_SYNTHETIC, list(DRIVER_TEXT))
    fs.keep("demo_rain", "DEFAULT", RAIN_CHOICES)
    fs.keep("demo_model", "M1", list(MODEL_TEXT))
    c1, c2, c3 = st.columns(3)
    drv = c1.selectbox(L("Temperature source", "Sumber suhu"), list(DRIVER_TEXT), key="demo_driver",
                       format_func=lambda k: L(*DRIVER_TEXT[k]),
                       help=L("Real BMKG is never mixed with synthetic temperatures in one calculation.",
                              "BMKG asli tidak pernah dicampur dengan suhu sintetis dalam satu perhitungan."))
    rain = c2.selectbox(L("Rain scenario", "Skenario hujan"), RAIN_CHOICES, key="demo_rain", format_func=lambda k: L(*RAIN_TEXT[k]),
                        help=L("BMKG rain is not forecast here; rain is always an explicit, labelled scenario.",
                               "Hujan BMKG tidak diprakirakan di sini; hujan selalu berupa skenario eksplisit yang berlabel."))
    model = c3.selectbox(L("Model", "Model"), list(MODEL_TEXT), key="demo_model", format_func=lambda k: L(*MODEL_TEXT[k]))
    fs.sync("demo_driver", "demo_rain", "demo_model")
    base = demo_data.default_weather(pid)
    w = dict(base)
    w["driver"] = drv
    if rain != "DEFAULT":
        w["rain"] = rain
    return {"weather": w, "model": model}


def preview(ctx, pid: str) -> dict:
    """Hitung (tanpa menerbitkan) rekomendasi demo sesuai pilihan. -> dict hasil lengkap."""
    sel = controls(pid)
    w, model = sel["weather"], sel["model"]
    fc = getattr(ctx.snap, "forecast", None) if w["driver"] == dw.DRIVER_BMKG else None
    now = drepo.now_utc()
    ml = None
    note = None
    if model == "M2":
        cmp_ = demo_ml.compare_models(pid, now, w, forecast=fc)
        ml = cmp_["residual"]
        if cmp_["M2"] is None:
            model = "M1"
            note = (ml or {}).get("reason") or L("M2 unavailable", "M2 tidak tersedia")
            out, snap = cmp_["M1"]["output"], cmp_["M1"]["snapshot"]
        else:
            out, snap = cmp_["M2"]["output"], cmp_["M2"]["snapshot"]
    else:
        out, snap = demo_service.compute_for_plot(pid, now, w, forecast=fc, max_h_age_hours=ctx.settings.max_h_age_hours, model="M1")
    prof = drepo.get_active_profile(pid, now)
    return {"out": out, "snapshot": snap, "profile": prof, "weather": w, "model": model, "ml": ml, "fallback_note": note,
            "forecast": fc, "decision_at": now}


def publish(res: dict, pid: str, ctx, actor: str) -> dict:
    ml_res = (res.get("ml") or {}).get("residual") if res["model"] == "M2" else None
    return demo_service.publish(pid, actor, None, res["weather"], forecast=res["forecast"],
                                max_h_age_hours=ctx.settings.max_h_age_hours, model=res["model"], ml_residual=ml_res)


def fresh_h_panel(pid: str, res: dict):
    """Bila demo menunggu h baru (irigasi sejak h terakhir / h usang), tawarkan satu klik pembacaan h SIMULASI
    agar prediksi, rekomendasi, dan durasi terisi dan keputusan dapat didemonstrasikan seperti kondisi nyata."""
    if res["out"].get("status") not in demo_service.NEEDS_NEW_H:
        return
    st.info(L("**Demo is waiting for a new h reading** — as in the field, after an irrigation (or an old reading) the operator reads h again. "
              "Record a SIMULATED reading now to fill prediction, recommendation and duration. It is stored in the demo space only (labelled DEMO).",
              "**Demo menunggu pembacaan h baru** — seperti di lapangan, setelah irigasi (atau bacaan lama) operator membaca h lagi. "
              "Catat pembacaan SIMULASI sekarang agar prediksi, rekomendasi, dan durasi terisi. Hanya tersimpan di ruang demo (berlabel DEMO)."))
    if not demo_mode.can("observations"):
        st.caption(L("Your role cannot record observations.", "Role Anda tidak dapat mencatat pengamatan."))
        return
    kn = f"demo_fresh_h_{pid}"
    fs.keep(kn, demo_service.suggested_fresh_h(pid))
    c1, c2 = st.columns([1, 2])
    val = c1.number_input(L("Simulated h now (cm)", "h simulasi sekarang (cm)"), min_value=-60.0, max_value=30.0, step=0.5, key=kn)
    fs.sync(kn)
    c2.write("")
    if c2.button(L("📝 Record simulated h now", "📝 Catat h simulasi sekarang"), type="primary", key=f"demo_fresh_btn_{pid}"):
        try:
            demo_service.record_fresh_h(pid, auth.current_user()["username"], float(val))
            store.invalidate()
            st.rerun()
        except PermissionError:
            st.error(auth.auth_msg("forbidden"))
        except ValueError as e:
            st.error(str(e))


# ---------------------------------------------------------------------------------------------- label sumber
def source_badges(res: dict):
    w, snap = res["weather"], res["snapshot"]
    meta = snap.get("weather") or {}
    parts = []
    if w["driver"] == dw.DRIVER_BMKG:
        ok = meta.get("available")
        parts.append(chip(L("Temperature: real BMKG", "Suhu: BMKG asli") + ("" if ok else L(" (not available)", " (tidak tersedia)")),
                          "ok" if ok else "bad"))
        if ok and meta.get("fetched_at"):
            parts.append(chip(L("fetched ", "diambil ") + fmt_ts(meta["fetched_at"]), "info"))
        parts.append(chip(L("BMKG reference: village Panongan (ADM4); demo plot coordinates are illustrative",
                            "Acuan BMKG: Desa Panongan (ADM4); koordinat petak demo bersifat ilustratif"), "warn"))
    else:
        parts.append(chip(L("Temperature: SYNTHETIC (scenario)", "Suhu: SINTETIS (skenario)"), "warn"))
    rk = w["rain"]
    parts.append(chip(L("Rain: ", "Hujan: ") + (L("none", "tanpa hujan") if rk == "NONE" else L("synthetic scenario ", "skenario sintetis ") + rk),
                      "info" if rk == "NONE" else "warn"))
    stat = [v for v in (snap.get("parameters") or {}).values()]
    n_ex = sum(1 for p in stat if p.get("status") == "EXAMPLE")
    parts.append(chip(L(f"Parameters: {n_ex} EXAMPLE", f"Parameter: {n_ex} CONTOH"), "warn"))
    parts.append(chip(res["model"], "info"))
    st.markdown(" ".join(parts), unsafe_allow_html=True)
    if res.get("fallback_note"):
        st.warning(L("M2 is unavailable, showing M1: ", "M2 tidak tersedia, menampilkan M1: ") + str(res["fallback_note"]))


# ---------------------------------------------------------------------------------------------- penjelasan
def explain(res: dict):
    """Panel 'Mengapa rekomendasi ini?' - langkah demi langkah dengan angka yang dipakai mesin."""
    out, snap, prof = res["out"], res["snapshot"], res["profile"]
    st.subheader(L("Why this recommendation?", "Mengapa rekomendasi ini?"))
    h = snap.get("h_observation")
    if out["status"] not in ("OK", "TARGET_NOT_REACHABLE"):
        st.markdown(f"**{texts.status_label(out['status'])}** — " + (" ".join(out.get("reasons") or [])))
        st.caption(L("The engine refuses to guess: missing, stale or incomplete inputs give a status and a reason, not a number.",
                     "Mesin menolak menebak: masukan yang kurang, usang, atau tidak lengkap menghasilkan status dan alasan, bukan angka."))
        return
    steps = []
    if h:
        steps.append(L(f"1. Last field h = **{fmt_num(h['value'])} cm** at {fmt_ts(h['observed_at'])} (demo observation).",
                       f"1. h lapangan terakhir = **{fmt_num(h['value'])} cm** pada {fmt_ts(h['observed_at'])} (pengamatan demo)."))
    steps.append(L(f"2. Propagated {fmt_num(out.get('propagated_hours'), 1)} h to the decision time: h = **{fmt_num(out.get('h_decision_cm'))} cm**.",
                   f"2. Diperambat {fmt_num(out.get('propagated_hours'), 1)} jam ke waktu keputusan: h = **{fmt_num(out.get('h_decision_cm'))} cm**."))
    steps.append(L(f"3. Water needs {fmt_num(out.get('lead_time_h'), 1)} h to arrive → predicted h on arrival = **{fmt_num(out.get('h_arrival_cm'))} cm** "
                   f"(daily loss F = ETc + R_adj − Pe ≈ {fmt_num(out.get('f_mm_day_arrival'), 2)} mm/day; R_adj = {fmt_num(out.get('r_adj_mm_day'), 2)}).",
                   f"3. Air butuh {fmt_num(out.get('lead_time_h'), 1)} jam untuk tiba → prediksi h saat tiba = **{fmt_num(out.get('h_arrival_cm'))} cm** "
                   f"(kehilangan harian F = ETc + R_adj − Pe ≈ {fmt_num(out.get('f_mm_day_arrival'), 2)} mm/hari; R_adj = {fmt_num(out.get('r_adj_mm_day'), 2)})."))
    steps.append(L(f"4. Rule for phase {out.get('phase_arrival') or '-'}: irrigate if h ≤ trigger **{fmt_num(out.get('trigger_h_cm'))} cm**, refill to target **{fmt_num(out.get('target_h_cm'))} cm**.",
                   f"4. Aturan fase {out.get('phase_arrival') or '-'}: irigasi bila h ≤ pemicu **{fmt_num(out.get('trigger_h_cm'))} cm**, isi sampai target **{fmt_num(out.get('target_h_cm'))} cm**."))
    if out.get("irrigate"):
        steps.append(L(f"5. h on arrival is at/below the trigger → refill **{fmt_num(out.get('refill_mm'))} mm**, "
                       f"volume **{fmt_num(out.get('volume_m3'), 0)} m³**, duration **{fmt_num(out.get('duration_h'))} h**.",
                       f"5. h saat tiba di/di bawah pemicu → pengisian **{fmt_num(out.get('refill_mm'))} mm**, "
                       f"volume **{fmt_num(out.get('volume_m3'), 0)} m³**, durasi **{fmt_num(out.get('duration_h'))} jam**."))
    else:
        steps.append(L("5. h on arrival is still above the trigger → **no irrigation needed now**.",
                       "5. h saat tiba masih di atas pemicu → **belum perlu irigasi sekarang**."))
    for s_ in steps:
        st.markdown(s_)
    rows = [{L("Input", "Masukan"): "Kc (" + str(out.get("phase_arrival") or "-") + ")", L("Source", "Sumber"): "EXAMPLE"},
            {L("Input", "Masukan"): L("Temperature", "Suhu"), L("Source", "Sumber"): (snap.get("weather") or {}).get("label", "-")},
            {L("Input", "Masukan"): L("Rain", "Hujan"), L("Source", "Sumber"): out.get("rain_scenario", "NO_RAIN_SCENARIO")},
            {L("Input", "Masukan"): L("Run mode", "Mode run"), L("Source", "Sumber"): "DEMO"}]
    table(rows, key="demo_explain_inputs")
    if out.get("issues"):
        for i in out["issues"]:
            if i.get("code") in texts.ISSUE:
                st.caption("• " + texts.issue_text(i))
    st.caption(L("All parameters are EXAMPLE values, so the run mode is always DEMO. This explains the calculation; it is not a field result.",
                 "Semua parameter adalah nilai CONTOH, sehingga mode run selalu DEMO. Ini menjelaskan perhitungan; bukan hasil lapangan."))


# ---------------------------------------------------------------------------------------------- panel AI
def trajectory_compare(m1: dict, m2: dict | None, key: str):
    fig = go.Figure()
    for name, o, color in (("M1", m1, "#2F80ED"), ("M2", m2, "#E4A11B")):
        if not o:
            continue
        path = o.get("path") or []
        if path:
            fig.add_trace(go.Scatter(x=[p[0] for p in path], y=[p[1] for p in path], mode="lines", name=name, line=dict(width=3, color=color)))
    ref = m1 or m2
    for k_, c_, n_ in (("trigger_h_cm", "#E4565C", L("trigger", "pemicu")), ("target_h_cm", "#22A55B", "target")):
        if ref and ref.get(k_) is not None:
            fig.add_hline(y=ref[k_], line_dash="dash", line_color=c_, annotation_text=n_)
    fig.update_layout(title=L("Predicted h without irrigation: M1 vs M2", "Prediksi h tanpa irigasi: M1 vs M2"), yaxis_title="h (cm)",
                      height=320, margin=dict(l=10, r=10, t=50, b=10))
    plot(apply_plot_theme(fig), key=key)


def ai_panel(ctx, pid: str, res: dict):
    st.subheader(L("Demonstration AI model (M2)", "Model AI demonstrasi (M2)"))
    banner(demo_ml.NOTICE, "warn")
    status = demo_ml.status()
    if not status["sklearn"]:
        st.info(L("scikit-learn is not installed; only M1 is available.", "scikit-learn belum terpasang; hanya M1 yang tersedia."))
        return
    if not status["trained"]:
        st.info(L("The demo model has not been trained yet. An administrator can train it in Admin → Demo.",
                  "Model demo belum dilatih. Administrator dapat melatihnya di Admin → Demo."))
        return
    m = status["metrics"]
    t = m["test"]
    cards([dict(icon="🧪", title=L("Test windows", "Jendela uji"), value_text=str(t["n"]), note=L("temporal split, synthetic", "split temporal, sintetis"), color="blue"),
           dict(icon="📏", title="MAE residual M1", value_text=fmt_num(t["M1"]["mae_residual"], 2), note="mm/day", color="orange"),
           dict(icon="🤖", title="MAE residual M2", value_text=fmt_num(t["M2"]["mae_residual"], 2), note="mm/day", color="green"),
           dict(icon="🪣", title=L("MAE h M1 → M2", "MAE h M1 → M2"),
                value_text=f"{fmt_num(m['h_end_mae_cm']['M1'], 2)} → {fmt_num(m['h_end_mae_cm']['M2'], 2)}", note="cm", color="blue")], columns=4)
    st.caption(L("Metrics are on the held-out TEST period of a synthetic corpus whose true residual is built to differ from SPconstant. "
                 "They show that the pipeline works; they say nothing about field accuracy.",
                 "Metrik dihitung pada periode UJI terpisah dari korpus sintetis yang residual sebenarnya dibuat berbeda dari SPconstant. "
                 "Ini menunjukkan alur bekerja; tidak menyatakan apa pun tentang akurasi lapangan."))
    cmp_ = demo_ml.compare_models(pid, res["decision_at"], res["weather"], forecast=res["forecast"])
    r = cmp_["residual"] or {}
    m1, m2 = cmp_["M1"]["output"], (cmp_["M2"] or {}).get("output")
    m1b = (cmp_.get("M1B") or {}).get("output")
    rows = []
    for name, o in (("M1", m1), ("M1B", m1b), ("M2", m2)):
        if o is None:
            rows.append({L("Model", "Model"): name, L("Status", "Status"): r.get("reason", "-")})
            continue
        rows.append({L("Model", "Model"): name, "R_adj (mm/day)": fmt_num(o.get("r_adj_mm_day"), 2),
                     L("h on arrival (cm)", "h saat tiba (cm)"): fmt_num(o.get("h_arrival_cm")),
                     L("Irrigate", "Irigasi"): {True: L("yes", "ya"), False: L("no", "tidak"), None: "-"}[o.get("irrigate")],
                     L("Amount (mm)", "Jumlah (mm)"): fmt_num(o.get("total_mm")) if o.get("irrigate") else "-",
                     L("Duration (h)", "Durasi (jam)"): fmt_num(o.get("duration_h")) if o.get("duration_h") else "-"})
    table(rows, key=f"demo_cmp_{pid}")
    if cmp_["M2"] is not None:
        st.caption(L("M2 uses R_adj = ML residual + bias; SPconstant is NOT added again (no double counting). "
                     "M1B = SPconstant + the same bias, so the M1B → M2 difference comes from the ML residual only.",
                     "M2 memakai R_adj = residual ML + bias; SPconstant TIDAK ditambahkan lagi (tanpa hitung ganda). "
                     "M1B = SPconstant + bias yang sama, sehingga selisih M1B → M2 hanya berasal dari residual ML."))
        if r.get("clipped"):
            st.warning(L("The ML residual was clipped to the allowed range.", "Residual ML dipotong ke rentang yang diizinkan."))
    trajectory_compare(m1, m2, f"demo_trj_cmp_{pid}")
    with st.expander(L("Training details", "Rincian pelatihan")):
        _training_details(status, m)


_FEATURE_NAMES = {
    "tmean": ("Mean temperature", "Suhu rerata"), "dtr": ("Daily temperature range", "Rentang suhu harian"),
    "et0": ("Reference ET0", "ET0 acuan"), "etc": ("Crop ET (ETc)", "ETc tanaman"),
    "h_start": ("Water level at window start", "h awal jendela"), "kc": ("Crop coefficient Kc", "Koefisien Kc")}
_REJECT_NAMES = {
    "CROSSES_ZERO": ("h crosses 0 in window", "h melintasi 0 dalam jendela"),
    "IRRIGATION_IN_WINDOW": ("Irrigation inside window", "Ada irigasi dalam jendela"),
    "RISE_IN_WINDOW": ("h rises inside window", "h naik dalam jendela"),
    "RAIN_IN_WINDOW": ("Rain inside window", "Hujan dalam jendela"),
    "RAIN_UNKNOWN": ("Rain unknown / coverage gap", "Hujan tidak diketahui / celah cakupan"),
    "NON_RESEARCH_SOURCE": ("Source/status not accepted", "Sumber/status tidak diterima"),
    "ETC_UNAVAILABLE": ("ETc unavailable", "ETc tidak tersedia"),
    "FEATURE_UNAVAILABLE": ("Feature unavailable", "Fitur tidak tersedia")}


def _training_details(status: dict, m: dict):
    """Rincian pelatihan yang terbaca manusia (bukan JSON mentah): ringkasan, pembagian data, hiperparameter, fitur penting."""
    cfg = status.get("config") or {}
    corpus = cfg.get("corpus") or {}
    sp = m.get("split") or {}
    ch = m.get("chosen") or {}
    total = max(1, sum(int(sp.get(k, 0)) for k in ("train", "valid", "test")))

    st.markdown("**" + L("Summary", "Ringkasan") + "**")
    table([
        {L("Item", "Butir"): L("Model", "Model"), L("Value", "Nilai"): f"Random Forest (residual M2) · {status.get('model_id', '-')}"},
        {L("Item", "Butir"): L("Data source", "Sumber data"),
         L("Value", "Nilai"): L("Synthetic simulation (DEMO_SYNTHETIC) — not field data", "Simulasi sintetis (DEMO_SYNTHETIC) — bukan data lapangan")},
        {L("Item", "Butir"): L("Corpus", "Korpus"),
         L("Value", "Nilai"): L(f"{corpus.get('n_plots', '-')} virtual plots × {corpus.get('n_days', '-')} days, seed {corpus.get('seed', '-')}",
                                f"{corpus.get('n_plots', '-')} petak virtual × {corpus.get('n_days', '-')} hari, seed {corpus.get('seed', '-')}")},
        {L("Item", "Butir"): L("Candidate windows", "Jendela kandidat"),
         L("Value", "Nilai"): L(f"{corpus.get('n_windows', '-')} candidates → {corpus.get('n_valid', '-')} valid labels",
                                f"{corpus.get('n_windows', '-')} kandidat → {corpus.get('n_valid', '-')} label valid")},
    ], key="demo_train_summary")

    st.markdown("**" + L("Data split (temporal)", "Pembagian data (temporal)") + "**")
    names = {"train": ("Train", "Latih"), "valid": ("Validation", "Validasi"), "test": ("Test", "Uji"),
             "dropped": ("Dropped (crosses boundary / not yet available)", "Dibuang (melintasi batas / belum tersedia)")}
    table([{L("Set", "Set"): L(*names[k]), L("Windows", "Jendela"): int(sp.get(k, 0)),
            L("Share", "Porsi"): (f"{100.0 * int(sp.get(k, 0)) / total:.0f}%" if k != "dropped" else "—")}
           for k in ("train", "valid", "test", "dropped") if k in sp], key="demo_train_split")
    st.caption(L("Hyperparameters were chosen on the validation set; the test set is used once for reporting.",
                 "Hiperparameter dipilih pada set validasi; set uji dipakai sekali untuk laporan."))

    e = (m.get("eval") or {})
    if e:
        st.markdown("**" + L("Test-set errors (physical units)", "Galat set uji (satuan fisik)") + "**")
        rows = []
        for tgt, unit, name in (("residual_mm_day", "mm/day", L("Residual", "Residual")), ("h_end_cm", "cm", L("Final water level h", "h akhir jendela"))):
            blk = e.get(tgt) or {}
            for mod in ("M1", "M2"):
                x = blk.get(mod) or {}
                sk = blk.get("skill_rmse_M2") if mod == "M2" else None
                rows.append({L("Target", "Target"): f"{name} ({unit})", L("Model", "Model"): mod, "n": x.get("n", "-"),
                             "MAE": "-" if x.get("mae") is None else f"{x['mae']:.2f}", "RMSE": "-" if x.get("rmse") is None else f"{x['rmse']:.2f}",
                             L("Bias", "Bias"): "-" if x.get("bias") is None else f"{x['bias']:+.2f}",
                             L("Skill vs M1", "Skill vs M1"): "—" if sk is None else f"{sk:+.2f}"})
        table(rows, key="demo_train_eval")
        st.caption(L("Skill = 1 − RMSE(M2)/RMSE(M1) on the identical test sample (positive = better). M1B is not simulated in the demo. "
                     "Bias is in physical units (prediction − observation).",
                     "Skill = 1 − RMSE(M2)/RMSE(M1) pada sampel uji yang identik (positif = lebih baik). M1B tidak disimulasikan di demo. "
                     "Bias dalam satuan fisik (prediksi − pengamatan)."))

    st.markdown("**" + L("Chosen hyperparameters", "Hiperparameter terpilih") + "**")
    table([{L("Parameter", "Parameter"): "max_depth", L("Value", "Nilai"): ch.get("max_depth", "-")},
           {L("Parameter", "Parameter"): "min_samples_leaf", L("Value", "Nilai"): ch.get("min_samples_leaf", "-")},
           {L("Parameter", "Parameter"): "n_estimators", L("Value", "Nilai"): 120}], key="demo_train_hp")

    fi = m.get("feature_importance") or {}
    if fi:
        st.markdown("**" + L("Which inputs matter most", "Masukan yang paling berpengaruh") + "**")
        items = sorted(fi.items(), key=lambda kv: kv[1])
        fig = go.Figure(go.Bar(x=[round(100.0 * v, 1) for _, v in items], y=[L(*_FEATURE_NAMES.get(k, (k, k))) for k, _ in items],
                               orientation="h", marker_color="#4E8DF5",
                               text=[f"{100.0 * v:.1f}%" for _, v in items], textposition="outside", cliponaxis=False))
        fig.update_layout(height=280, margin=dict(l=10, r=40, t=10, b=10), xaxis_title=L("Importance (%)", "Kepentingan (%)"))
        plot(apply_plot_theme(fig), key="demo_train_fi")

    rej = corpus.get("rejected") or {}
    if rej:
        st.markdown("**" + L("Why windows were rejected as labels", "Alasan jendela ditolak sebagai label") + "**")
        table([{L("Reason", "Alasan"): L(*_REJECT_NAMES.get(k, (k, k))), L("Windows", "Jendela"): int(v)}
               for k, v in sorted(rej.items(), key=lambda kv: -kv[1])], key="demo_train_rej")
    st.caption(L("All of this comes from synthetic data and shows how the pipeline works. It is not evidence of field accuracy.",
                 "Seluruhnya berasal dari data sintetis dan menunjukkan cara alur bekerja. Bukan bukti akurasi lapangan."))


# ---------------------------------------------------------------------------------------------- ringkasan / grafik demo
def plots_overview(ctx):
    """Ringkasan enam petak demo: status rekomendasi per skenario + grafik riwayat (h, kelembapan, muka air, hujan)."""
    st.subheader(L("Demo plots DEMO-P01 … DEMO-P06 (synthetic)", "Petak demo DEMO-P01 … DEMO-P06 (sintetis)"))
    plots = store.plots()
    if not plots:
        st.info(L("The demo space is empty. An administrator can load it in Admin → Demo.",
                  "Ruang demo masih kosong. Administrator dapat memuatnya di Admin → Demo."))
        return
    now = drepo.now_utc()
    rows = []
    for p in plots:
        try:
            out, _ = demo_service.compute_for_plot(p["plot_id"], now, demo_data.default_weather(p["plot_id"]),
                                                   max_h_age_hours=ctx.settings.max_h_age_hours)
            status = texts.status_label(out["status"])
            irr = {True: L("irrigate", "irigasi"), False: L("not needed", "belum perlu"), None: "-"}[out.get("irrigate")]
            amt = fmt_num(out.get("total_mm")) if out.get("irrigate") else "-"
        except Exception:
            status, irr, amt = "-", "-", "-"
        h = drepo.latest_h(p["plot_id"], now)
        rows.append({L("Plot", "Petak"): p["plot_id"], L("Scenario", "Skenario"): p.get("scenario") or "-",
                     L("Last h (cm)", "h terakhir (cm)"): fmt_num(h["value"]) if h else "-",
                     L("Observed", "Diamati"): fmt_ts(h["observed_at"]) if h else "-",
                     L("Engine status", "Status mesin"): status, L("Result", "Hasil"): irr, "mm": amt,
                     L("Description", "Keterangan"): p.get("note") or ""})
    table(rows, key="demo_plots_tbl")
    ids = [p["plot_id"] for p in plots]
    fs.keep("demo_chart_plot", ids[0], ids)
    fs.keep("demo_chart_days", 35)
    pid = st.selectbox(L("Plot for charts", "Petak untuk grafik"), ids, key="demo_chart_plot")
    days = st.slider(L("History (days)", "Riwayat (hari)"), 7, 40, key="demo_chart_days")
    fs.sync("demo_chart_plot", "demo_chart_days")
    h = drepo.h_series(pid, days)
    sm = drepo.series(pid, "soil_moisture", days)
    cn = drepo.series(pid, "canal_level", days)
    rn = drepo.series(pid, "rainfall", days)
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Scatter(x=[r["observed_at"] for r in h], y=[r["value"] for r in h], mode="lines+markers", name="h (cm)",
                                   line=dict(color="#2F80ED", width=2)))
        fig.add_hline(y=0, line_dash="dot", opacity=.5)
        fig.update_layout(title=f"{pid} · h (cm) — " + L("synthetic", "sintetis"), height=300, margin=dict(l=10, r=10, t=50, b=10))
        plot(apply_plot_theme(fig), key=f"demo_h_{pid}")
    with c2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[r["observed_at"] for r in sm], y=[r["value"] for r in sm], name=L("soil moisture (%)", "kelembapan tanah (%)"),
                                 line=dict(color="#22A55B")))
        fig.add_trace(go.Scatter(x=[r["observed_at"] for r in cn], y=[r["value"] for r in cn], name=L("canal level (m)", "muka air saluran (m)"),
                                 yaxis="y2", line=dict(color="#E4A11B")))
        fig.add_trace(go.Bar(x=[r["observed_at"] for r in rn], y=[r["value"] for r in rn], name=L("rain (mm)", "hujan (mm)"), yaxis="y2",
                             marker_color="#6C8EBF", opacity=.6))
        fig.update_layout(title=f"{pid} · " + L("synthetic sensors", "sensor sintetis"), height=300, margin=dict(l=10, r=10, t=50, b=10),
                          yaxis=dict(title="%"), yaxis2=dict(title="m / mm", overlaying="y", side="right"))
        plot(apply_plot_theme(fig), key=f"demo_s_{pid}")
    st.caption(L("All curves above are synthetic demo data generated with a fixed seed; no BMKG value is mixed in.",
                 "Semua kurva di atas adalah data demo sintetis dengan seed tetap; tidak ada nilai BMKG yang dicampur."))


# ---------------------------------------------------------------------------------------------- admin demo
def _flash(kind, msg):
    st.session_state["demo_admin_flash"] = (kind, msg)


def render_admin_demo():
    """Tab Admin → Demo: muat, kembalikan skenario awal, kosongkan, ekspor, geser waktu, latih model."""
    if not demo_mode.can("admin"):
        st.error(texts.decision_error("forbidden"))
        return
    if "demo_admin_flash" in st.session_state:
        kind, msg = st.session_state.pop("demo_admin_flash")
        (st.success if kind == "success" else st.warning)(msg)
    st.caption(L("These buttons act ONLY on the separate demo repository (SQLite). The operational database is never touched.",
                 "Tombol-tombol ini HANYA bekerja pada repositori demo terpisah (SQLite). Database operasional tidak pernah disentuh."))
    loaded = drepo.is_loaded()
    counts = drepo.count_user_rows() if loaded else {}
    cards([dict(icon="🗂️", title=L("Dataset", "Dataset"), value_text=drepo.dataset_id() or L("empty", "kosong"), note=drepo.get_meta("anchor", ""), color="blue"),
           dict(icon="✍️", title=L("User-made records", "Catatan buatan pengguna"), value_text=str(sum(counts.values())),
                note=", ".join(f"{k}:{v}" for k, v in counts.items() if v) or "-", color="orange"),
           dict(icon="🧾", title="SQLite", value_text="demo", note=drepo.path()[-48:], color="blue")], columns=3)
    b1, b2, b3, b4 = st.columns(4)
    if b1.button(L("Load demo data", "Muat data demo"), key="demo_load", type="primary", width="stretch", disabled=loaded):
        r = demo_data.load()
        store.invalidate()
        _flash("success", L(f"Demo data loaded ({r['status']}).", f"Data demo dimuat ({r['status']})."))
        st.rerun()
    if b2.button(L("Restore initial scenario", "Kembalikan skenario awal"), key="demo_reset", width="stretch"):
        st.session_state["demo_confirm"] = "reset"
    if b3.button(L("Clear demo data", "Kosongkan data demo"), key="demo_clear", width="stretch"):
        st.session_state["demo_confirm"] = "clear"
    with b4:
        if loaded:
            st.download_button(L("Export demo data", "Ekspor data demo"),
                               json.dumps(drepo.export_all(), ensure_ascii=False, indent=1, default=str).encode("utf-8"),
                               file_name="somat_demo_export.json", mime="application/json", key="demo_export", width="stretch")
        else:
            st.button(L("Export demo data", "Ekspor data demo"), key="demo_export_off", disabled=True, width="stretch")
    conf = st.session_state.get("demo_confirm")
    if conf:
        msg = {"reset": L("Restoring deletes everything in the demo space (including your changes) and reloads the initial scenario.",
                          "Mengembalikan akan menghapus seluruh isi ruang demo (termasuk perubahan Anda) lalu memuat ulang skenario awal."),
               "clear": L("Clearing deletes everything in the demo space. You can load it again afterwards.",
                          "Mengosongkan menghapus seluruh isi ruang demo. Anda dapat memuatnya lagi sesudahnya.")}[conf]
        st.warning(msg)
        y, n = st.columns(2)
        if y.button(L("Yes, continue", "Ya, lanjutkan"), key="demo_confirm_yes", type="primary", width="stretch"):
            r = demo_data.reset_initial() if conf == "reset" else demo_data.clear()
            st.session_state.pop("demo_confirm", None)
            for k in list(st.session_state):
                if k.startswith(("obs_h_", "ex_", "_keep_")) or k in ("pending_recommendation", "op_modify"):
                    st.session_state.pop(k, None)
            store.invalidate()
            _flash("success", L(f"Done ({r['status']}).", f"Selesai ({r['status']})."))
            st.rerun()
        if n.button(L("Cancel", "Batal"), key="demo_confirm_no", width="stretch"):
            st.session_state.pop("demo_confirm", None)
            st.rerun()
    if loaded:
        if st.button(L("Shift demo times to now", "Geser waktu demo ke sekarang"), key="demo_shift",
                     help=L("Keeps all relationships; use when you open the demo on a different day.",
                            "Menjaga seluruh hubungan antar-catatan; pakai saat membuka demo di hari yang berbeda.")):
            r = demo_data.refresh_time()
            store.invalidate()
            _flash("success", str(r["status"]))
            st.rerun()
    st.divider()
    st.markdown("#### " + L("Demonstration AI model", "Model AI demonstrasi"))
    banner(demo_ml.NOTICE, "warn")
    s = demo_ml.status()
    st.caption(L(f"Trained: {'yes — ' + str(s['model_id']) if s['trained'] else 'no'} · scikit-learn: {'available' if s['sklearn'] else 'missing'}",
                 f"Terlatih: {'ya — ' + str(s['model_id']) if s['trained'] else 'belum'} · scikit-learn: {'tersedia' if s['sklearn'] else 'tidak ada'}"))
    if st.button(L("Train / retrain demo model", "Latih / latih ulang model demo"), key="demo_train", disabled=not s["sklearn"]):
        with st.spinner(L("Training on synthetic data…", "Melatih dari data sintetis…")):
            r = demo_ml.train(demo_mode.actor_name())
        _flash("success" if r["status"] == "TRAINED" else "warning", f"{r['status']}: {r.get('model_id', r.get('message', ''))}")
        st.rerun()
    st.divider()
    st.markdown("#### " + L("Demo audit log", "Log audit demo"))
    aud = drepo.fetch_audit(100)
    if aud:
        table(pd.DataFrame([{L("Time (WIB)", "Waktu (WIB)"): fmt_ts(r["ts"]), L("User", "Pengguna"): r["username"], L("Action", "Aksi"): r["action"],
                             L("Detail", "Detail"): r["detail"]} for r in aud]), key="demo_audit", hide_index=True)
    else:
        st.info(L("No events yet.", "Belum ada kejadian."))
