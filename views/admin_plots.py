"""views/admin_plots.py - petak, siklus tanam, dan profil parameter berversi (admin)."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd
import streamlit as st

import auth
import physics_engine as pe
import repository as repo
import store
from i18n import L
from ui_kit import fmt_ts, table

STATUSES = list(repo.PARAM_STATUSES)
PLOT_PARAM_TEMPLATE = [("area_ha", "ha"), ("mu_dry", "–"), ("mu_fill", "–"), ("lead_time_h", "h"), ("h_cap_cm", "cm"),
                       ("sp_constant", "mm/day"), ("q_plot_m3s", "m³/s")]
PHASE_PARAMS = (("kc", "–"), ("trigger_h", "cm"), ("target_h", "cm"))


def _domain_name(name):
    for base in ("kc", "trigger_h", "target_h"):
        if name == base or name.startswith(base + "_"):
            return base
    return name


def _template(phases, existing):
    rows = {}
    for name, unit in PLOT_PARAM_TEMPLATE:
        rows[name] = unit
    for ph in phases:
        for base, unit in PHASE_PARAMS:
            rows[f"{base}_{ph}"] = unit
    out = []
    for name, unit in rows.items():
        e = existing.get(name)
        out.append({"name": name, "value": e["value"] if e else None, "unit": (e["unit"] if e else unit) or unit,
                    "status": e["status"] if e else "PENDING", "source": (e["source"] if e else "") or "",
                    "assessment_method": (e["assessment_method"] if e else "") or ""})
    for name, e in existing.items():          # parameter lama di luar templat tetap dibawa
        if name not in rows:
            out.append({"name": name, "value": e["value"], "unit": e["unit"], "status": e["status"],
                        "source": e["source"], "assessment_method": e["assessment_method"]})
    return out


def render():
    u = auth.current_user()
    plots = store.plots(False)
    st.subheader(L("Plots", "Petak"))
    if plots:
        df = pd.DataFrame(plots)
        table(df[["plot_id", "name", "latitude", "longitude", "elevation_m", "datum", "pipe_count", "soil_sensor_id",
                  "canal_sensor_id", "active"]], key="adm_plots")
    with st.expander(L("Add / edit plot", "Tambah / ubah petak"), expanded=not plots):
        ids = [p["plot_id"] for p in plots]
        pick = st.selectbox(L("Edit existing", "Ubah yang ada"), ["—"] + ids, key="adm_plot_pick")
        cur = next((p for p in plots if p["plot_id"] == pick), {})
        with st.form("plot_form"):
            c1, c2 = st.columns(2)
            pid = c1.text_input("ID", value=cur.get("plot_id", ""), disabled=bool(cur), max_chars=20).strip().upper()
            name = c2.text_input(L("Name", "Nama"), value=cur.get("name", ""), max_chars=60)
            c3, c4, c5 = st.columns(3)
            lat = c3.number_input(L("Latitude (°, S negative)", "Lintang (°, S negatif)"), -90.0, 90.0, float(cur.get("latitude") or -6.7), 0.0001, format="%.5f")
            lon = c4.number_input(L("Longitude (°)", "Bujur (°)"), -180.0, 180.0, float(cur.get("longitude") or 108.2), 0.0001, format="%.5f")
            elev = c5.number_input(L("Elevation (m)", "Elevasi (m)"), -100.0, 5000.0, float(cur.get("elevation_m") or 0.0), 0.1)
            c6, c7, c8 = st.columns(3)
            datum = c6.text_input(L("Elevation datum", "Datum elevasi"), value=cur.get("datum") or "")
            pipes = c7.number_input(L("Pipes in plot", "Jumlah pipa"), 0, 50, int(cur.get("pipe_count") or 0))
            csrc = c8.text_input(L("Coordinate source", "Sumber koordinat"), value=cur.get("coordinate_source") or "")
            c9, c10, c11 = st.columns(3)
            sid = c9.text_input(L("Soil sensor ID", "ID sensor tanah"), value=cur.get("soil_sensor_id") or "")
            wid = c10.text_input(L("Canal sensor ID", "ID sensor saluran"), value=cur.get("canal_sensor_id") or "")
            active = c11.checkbox(L("Active", "Aktif"), value=bool(cur.get("active", True)))
            save = st.form_submit_button(L("Save plot", "Simpan petak"), type="primary")
        if save:
            if not pid or not name.strip():
                st.error(L("ID and name are required.", "ID dan nama wajib diisi."))
            else:
                repo.upsert_plot(pid, name.strip(), u["username"], lat, lon, elev, datum, pipes or None, "", sid, wid, "", "", csrc, active)
                store.invalidate()
                st.success(L("Saved.", "Tersimpan."))
                st.rerun()
    if not plots:
        return

    st.subheader(L("Crop cycle", "Siklus tanam"))
    pid = st.selectbox(L("Plot", "Petak"), [p["plot_id"] for p in plots], key="adm_cycle_plot")
    cyc = repo.list_crop_cycles(pid) if pid else []
    if cyc:
        table(pd.DataFrame(cyc)[["cycle_id", "planting_date", "variety", "active"]], key="adm_cycles")
    with st.form("cycle_form"):
        c1, c2 = st.columns(2)
        pd_ = c1.date_input(L("Planting date", "Tanggal tanam"), value=date.today())
        var = c2.text_input(L("Variety", "Varietas"))
        add = st.form_submit_button(L("Start new cycle (closes the active one)", "Mulai siklus baru (menutup yang aktif)"))
    if add:
        repo.add_crop_cycle(pid, pd_, var, u["username"])
        store.invalidate()
        st.rerun()

    st.subheader(L("Parameter profile (versioned)", "Profil parameter (berversi)"))
    st.caption(L("Saving creates a NEW version; the previous one is closed, never edited. Values without a measured/cited basis must stay PENDING. "
                 "EXAMPLE values force DEMO mode and can never be decided operationally.",
                 "Menyimpan membuat versi BARU; versi sebelumnya ditutup, tidak diubah. Nilai tanpa dasar ukur/rujukan harus tetap PENDING. "
                 "Nilai EXAMPLE memaksa mode DEMO dan tidak pernah dapat diputuskan operasional."))
    prof = repo.get_active_profile(pid)
    versions = repo.list_profile_versions(pid)
    if versions:
        v = pd.DataFrame(versions)
        for c in ("effective_from", "effective_to"):
            v[c] = v[c].map(lambda x: fmt_ts(x) if pd.notna(x) else "")
        table(v[["version", "effective_from", "effective_to", "approved_by", "validation_status", "note"]], key="adm_versions")
    phases_df = pd.DataFrame(prof["phases"] if prof else [{"phase": "", "from_das": 0, "to_das": 0, "protected": False}])[
        ["phase", "from_das", "to_das", "protected"]]
    st.markdown("**" + L("Phase windows (days after sowing, from the protocol)", "Jendela fase (hari setelah tanam, dari protokol)") + "**")
    ph_ed = st.data_editor(phases_df, num_rows="dynamic", key=f"ph_ed_{pid}_{prof['version'] if prof else 0}", width="stretch")
    phase_names = [str(p).strip() for p in ph_ed["phase"].tolist() if str(p).strip()]
    base = _template(phase_names, prof["params"] if prof else {})
    st.markdown("**" + L("Parameters", "Parameter") + "**")
    pr_ed = st.data_editor(pd.DataFrame(base), key=f"pr_ed_{pid}_{prof['version'] if prof else 0}_{len(phase_names)}", width="stretch",
                           column_config={"status": st.column_config.SelectboxColumn("status", options=STATUSES, required=True),
                                          "name": st.column_config.TextColumn("name", disabled=True)}, hide_index=True)
    c1, c2, c3 = st.columns(3)
    vstat = c1.selectbox(L("Validation status", "Status validasi"), ["UNVALIDATED", "VALIDATED"],
                         index=1 if prof and prof["validation_status"] == "VALIDATED" else 0)
    proto = c2.text_input(L("Protocol version", "Versi protokol"), value=(prof or {}).get("protocol_version", ""))
    note = c3.text_input(L("Change note (required)", "Catatan perubahan (wajib)"))
    if st.button(L("Save as new profile version", "Simpan sebagai versi profil baru"), type="primary", key="adm_save_prof"):
        problems = []
        params = []
        for r in pr_ed.to_dict("records"):
            val = r["value"]
            val = None if val is None or (isinstance(val, float) and math.isnan(val)) else float(val)
            st_ = r["status"] or "PENDING"
            if val is not None and st_ != "PENDING" and not pe._in_domain(_domain_name(r["name"]), val):
                problems.append(f"{r['name']}={val}")
            if val is not None and st_ in ("LITERATURE", "CALIBRATED") and not str(r.get("source") or "").strip():
                problems.append(f"{r['name']}: " + L("source required", "sumber wajib"))
            params.append({**r, "value": val, "status": st_ if val is not None else "PENDING"})
        ph_rows = [{"phase": str(r["phase"]).strip(), "from_das": int(r["from_das"]), "to_das": int(r["to_das"]), "protected": bool(r["protected"])}
                   for r in ph_ed.to_dict("records") if str(r["phase"]).strip()]
        if any(p["to_das"] < p["from_das"] for p in ph_rows):
            problems.append(L("phase window: end before start", "jendela fase: akhir sebelum awal"))
        if not note.strip():
            problems.append(L("change note required", "catatan perubahan wajib"))
        if problems:
            st.error(L("Cannot save: ", "Tidak dapat menyimpan: ") + "; ".join(problems))
        else:
            repo.save_profile_version(pid, params, ph_rows, u["username"], note.strip(), vstat, proto)
            store.invalidate()
            st.success(L("New profile version saved.", "Versi profil baru tersimpan."))
            st.rerun()
