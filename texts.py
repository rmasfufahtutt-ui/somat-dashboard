"""texts.py - label dua bahasa untuk kode status/mode/sumber. Kode disimpan di DB; teks dihasilkan saat tampil."""
from __future__ import annotations

from i18n import L

STATUS = {
    "OK": ("OK", "OK"),
    "NEEDS_FIELD_OBSERVATION": ("Field observation needed", "Perlu pengamatan lapangan"),
    "STALE_OBSERVATION": ("Observation too old", "Pengamatan terlalu lama"),
    "STATE_NOT_RECONSTRUCTABLE": ("Plot state cannot be reconstructed — new h needed", "Keadaan petak tidak dapat direkonstruksi — perlu h baru"),
    "INVALID_OBSERVATION": ("Invalid observation", "Pengamatan tidak valid"),
    "MISSING_PARAMETER": ("Parameters pending", "Parameter belum ditetapkan"),
    "INVALID_PARAMETER": ("Parameter out of domain", "Parameter di luar domain"),
    "PROTOCOL_REQUIRED": ("Phase protocol required", "Protokol fase diperlukan"),
    "PROFILE_REQUIRED": ("Plot profile required", "Profil petak diperlukan"),
    "INCOMPLETE_FORECAST": ("Forecast incomplete", "Prakiraan belum lengkap"),
    "TARGET_NOT_REACHABLE": ("Target not reachable at this discharge", "Target tidak tercapai pada debit ini"),
}
RUN_MODE = {
    "DEMO": ("DEMO — example inputs, cannot be decided operationally", "DEMO — masukan contoh, tidak dapat diputuskan operasional"),
    "BASELINE_PROVISIONAL": ("Baseline (provisional)", "Baseline (sementara)"),
    "BASELINE_VALIDATED": ("Baseline (validated)", "Baseline (tervalidasi)"),
    "ML_SHADOW": ("ML shadow (not used for decisions)", "ML bayangan (tidak dipakai keputusan)"),
    "ML_VALIDATED": ("ML (validated)", "ML (tervalidasi)"),
    "MANUAL_REQUIRED": ("Manual decision required", "Perlu keputusan manual"),
}
RUN_KIND = {"DEMO": "warn", "BASELINE_PROVISIONAL": "info", "BASELINE_VALIDATED": "ok", "ML_SHADOW": "info",
            "ML_VALIDATED": "ok", "MANUAL_REQUIRED": "bad"}
PARAM_STATUS = {"CALIBRATED": ("Calibrated", "Terkalibrasi"), "LITERATURE": ("Literature", "Literatur"),
                "EXAMPLE": ("Example", "Contoh"), "PENDING": ("Pending", "Menunggu")}
PARAM_KIND = {"CALIBRATED": "ok", "LITERATURE": "info", "EXAMPLE": "warn", "PENDING": "bad"}
ISSUE = {
    "NO_H_OBSERVATION": ("No valid field h observation.", "Belum ada pengamatan h lapangan yang sah."),
    "IRRIGATION_SINCE_OBSERVATION": ("Irrigation was decided or executed since the last h reading.", "Ada irigasi (diputuskan/dilaksanakan) sejak pembacaan h terakhir."),
    "RAIN_SINCE_OBSERVATION": ("Measured rain since the last h reading.", "Ada hujan terukur sejak pembacaan h terakhir."),
    "PAST_RAIN_UNKNOWN": ("Rain since the last h reading could not be confirmed (gauge coverage incomplete); the past part assumes no rain.",
                          "Hujan sejak pembacaan h terakhir tidak dapat dipastikan (cakupan rain gauge tidak lengkap); bagian lalu diasumsikan tanpa hujan."),
    "OBSERVATION_IN_FUTURE": ("Observation time is in the future.", "Waktu pengamatan di masa depan."),
    "DURATION_NEEDS_PLOT_DISCHARGE": ("Duration needs the discharge into this plot (not canal discharge).",
                                      "Durasi memerlukan debit ke petak ini (bukan debit saluran)."),
    "UNSUPPORTED_HORIZON": ("ET0 horizon too short to find the end time.", "Horizon ET0 terlalu pendek untuk menemukan waktu selesai."),
    "TARGET_NOT_REACHABLE": ("Inflow does not outpace losses.", "Aliran masuk tidak mengungguli kehilangan."),
    "AMOUNT_UNCHANGED": ("Amount is not different from the recommendation.", "Jumlah tidak berbeda dari rekomendasi."),
    "BAD_AMOUNT": ("Amount is not a valid number.", "Jumlah bukan angka yang sah."),
    "EXCEEDS_CAP": ("Amount exceeds what the bund height allows.", "Jumlah melebihi yang diizinkan tinggi pematang."),
    "DURATION_INCONSISTENT": ("Duration is inconsistent with volume and plot discharge.", "Durasi tidak konsisten dengan volume dan debit petak."),
    "NO_DRIVERS": ("ET0 / forecast not yet available.", "ET0 / prakiraan belum tersedia."),
    "OUT_OF_DOMAIN": ("A parameter value is outside its allowed range.", "Nilai parameter di luar rentang yang diizinkan."),
    "TARGET_NOT_ABOVE_TRIGGER": ("Target h is not above the trigger h.", "h target tidak lebih tinggi dari h pemicu."),
    "TARGET_ABOVE_CAP": ("Target h is above the plot's h cap.", "h target melebihi batas h (h cap) petak."),
}
DECISION_ERR = {
    "not_found": ("Recommendation not found.", "Rekomendasi tidak ditemukan."),
    "already_handled": ("Already decided, replaced or expired — nothing was recorded.", "Sudah diputuskan, diganti, atau kedaluwarsa — tidak ada yang dicatat."),
    "expired": ("This recommendation has expired — nothing was recorded.", "Rekomendasi kedaluwarsa — tidak ada yang dicatat."),
    "not_operational": ("DEMO / manual-required runs cannot be decided operationally.", "Run DEMO / perlu-manual tidak dapat diputuskan operasional."),
    "not_decidable_status": ("This run's result status does not allow a decision (e.g. missing data).", "Status hasil run ini tidak memungkinkan keputusan (mis. data kurang)."),
    "profile_changed": ("The plot's parameter profile changed since this recommendation. Recalculate first.", "Profil parameter petak berubah sejak rekomendasi ini. Hitung ulang dulu."),
    "inputs_changed": ("A newer h observation exists since this recommendation. Recalculate first.", "Ada pengamatan h yang lebih baru sejak rekomendasi ini. Hitung ulang dulu."),
    "not_demo": ("This run is not a DEMO run; it cannot be decided in the demo space.", "Run ini bukan run DEMO; tidak dapat diputuskan di ruang demo."),
    "approve_invalid": ("APPROVE/MODIFY need a computed irrigation amount; this run has none.", "APPROVE/MODIFY butuh jumlah irigasi terhitung; run ini tidak punya."),
    "amount_unchanged": ("MODIFY must change the amount from the SOMAT recommendation.", "MODIFY harus mengubah jumlah dari rekomendasi SOMAT."),
    "bad_amount": ("Amount must be between 0 and 1000 mm.", "Jumlah harus antara 0 dan 1000 mm."),
    "bad_decision": ("Unknown decision type.", "Jenis keputusan tidak dikenal."),
    "forbidden": ("Your role is not allowed to do this.", "Peran Anda tidak diizinkan melakukan ini."),
    "not_active": ("This record is no longer active.", "Catatan ini sudah tidak aktif."),
}


def _pick(table, code, default=None):
    en, idn = table.get(code, (default or code, default or code))
    return L(en, idn)


def status_label(code): return _pick(STATUS, code)
def run_mode_label(code): return _pick(RUN_MODE, code)
def param_status_label(code): return _pick(PARAM_STATUS, code)
def issue_text(issue: dict): return _pick(ISSUE, issue.get("code", ""), issue.get("code", ""))
def decision_error(code): return _pick(DECISION_ERR, code, code)
