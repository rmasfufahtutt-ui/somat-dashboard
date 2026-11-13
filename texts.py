"""texts.py - label dua bahasa untuk kode status/mode/sumber. Kode disimpan di DB; teks dihasilkan saat tampil."""
from __future__ import annotations

from i18n import L

STATUS = {
    "OK": ("OK", "OK"),
    "NEEDS_FIELD_OBSERVATION": ("Field observation needed", "Perlu pengamatan lapangan"),
    "STALE_OBSERVATION": ("Observation too old", "Pengamatan terlalu lama"),
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
    "OBSERVATION_IN_FUTURE": ("Observation time is in the future.", "Waktu pengamatan di masa depan."),
    "DURATION_NEEDS_PLOT_DISCHARGE": ("Duration needs the discharge into this plot (not canal discharge).",
                                      "Durasi memerlukan debit ke petak ini (bukan debit saluran)."),
    "UNSUPPORTED_HORIZON": ("ET0 horizon too short to find the end time.", "Horizon ET0 terlalu pendek untuk menemukan waktu selesai."),
    "TARGET_NOT_REACHABLE": ("Inflow does not outpace losses.", "Aliran masuk tidak mengungguli kehilangan."),
    "AMOUNT_UNCHANGED": ("Amount is not different from the recommendation.", "Jumlah tidak berbeda dari rekomendasi."),
    "BAD_AMOUNT": ("Amount is not a valid number.", "Jumlah bukan angka yang sah."),
    "EXCEEDS_CAP": ("Amount exceeds what the bund height allows.", "Jumlah melebihi yang diizinkan tinggi pematang."),
    "DURATION_INCONSISTENT": ("Duration is inconsistent with volume and plot discharge.", "Durasi tidak konsisten dengan volume dan debit petak."),
}
DECISION_ERR = {
    "not_found": ("Recommendation not found.", "Rekomendasi tidak ditemukan."),
    "already_handled": ("Already decided, replaced or expired — nothing was recorded.", "Sudah diputuskan, diganti, atau kedaluwarsa — tidak ada yang dicatat."),
    "expired": ("This recommendation has expired — nothing was recorded.", "Rekomendasi kedaluwarsa — tidak ada yang dicatat."),
    "not_operational": ("DEMO / manual-required runs cannot be decided operationally.", "Run DEMO / perlu-manual tidak dapat diputuskan operasional."),
    "inputs_changed": ("A newer h observation exists since this recommendation. Recalculate first.", "Ada pengamatan h yang lebih baru sejak rekomendasi ini. Hitung ulang dulu."),
}


def _pick(table, code, default=None):
    en, idn = table.get(code, (default or code, default or code))
    return L(en, idn)


def status_label(code): return _pick(STATUS, code)
def run_mode_label(code): return _pick(RUN_MODE, code)
def param_status_label(code): return _pick(PARAM_STATUS, code)
def issue_text(issue: dict): return _pick(ISSUE, issue.get("code", ""), issue.get("code", ""))
def decision_error(code): return _pick(DECISION_ERR, code, code)
