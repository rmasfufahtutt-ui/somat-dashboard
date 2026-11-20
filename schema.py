"""schema.py - migrasi Neon PostgreSQL SOMAT. Semua pernyataan idempoten (aman dijalankan ulang).

v1 = skema prototipe yang sudah ada (users, decisions, audit_log, roles, sessions, pending_recommendations).
v3 = QC sensor berversi terpisah dari nilai mentah (observation_qc) dan state bias adaptif per petak/model (bias_state, bias_update_log).
v2 = Grand Framework v2 bagian 9: profil petak berversi, observations, arsip prakiraan, ET0 harian,
     pelaksanaan aktual, recommendation_runs yang tidak berubah, dan jejak audit yang diperluas.
Data lama dipertahankan: akun, role, sesi, dan keputusan lama. Keputusan simulasi lama ditandai LEGACY_SIMULATION.
"""

SCHEMA_VERSION = 3

V1 = [
    """CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'viewer',
        password_hash TEXT NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        failed_count INTEGER NOT NULL DEFAULT 0,
        locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS decisions (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        username TEXT NOT NULL,
        decision TEXT NOT NULL,
        recommended_mm DOUBLE PRECISION,
        operator_mm DOUBLE PRECISION,
        duration_h DOUBLE PRECISION,
        note TEXT NOT NULL DEFAULT '',
        new_moisture DOUBLE PRECISION,
        status TEXT,
        learning_kind TEXT,
        learning_diff DOUBLE PRECISION,
        context JSONB,
        source TEXT NOT NULL DEFAULT 'simulation'
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data TEXT",
    """CREATE TABLE IF NOT EXISTS roles (
        role_key TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        is_system BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS role_permissions (
        role_key TEXT NOT NULL REFERENCES roles(role_key) ON DELETE CASCADE,
        page_key TEXT NOT NULL,
        can_access BOOLEAN NOT NULL DEFAULT TRUE,
        PRIMARY KEY (role_key, page_key)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS edited_by TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ",
    """CREATE TABLE IF NOT EXISTS pending_recommendations (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL,
        created_by TEXT NOT NULL,
        recommended_mm DOUBLE PRECISION NOT NULL,
        duration_h DOUBLE PRECISION NOT NULL,
        priority TEXT,
        feasible BOOLEAN,
        predicted_mm DOUBLE PRECISION,
        status TEXT NOT NULL DEFAULT 'PENDING',
        resolved_by TEXT,
        resolved_at TIMESTAMPTZ
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pending_rec_status ON pending_recommendations(status)",
]

V2 = [
    """CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    # ---- identitas petak dan profil berversi ----
    """CREATE TABLE IF NOT EXISTS plots (
        plot_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        elevation_m DOUBLE PRECISION,
        datum TEXT NOT NULL DEFAULT '',
        pipe_count INTEGER,
        pipe_location TEXT NOT NULL DEFAULT '',
        soil_sensor_id TEXT,
        canal_sensor_id TEXT,
        rain_source_id TEXT,
        temp_source_id TEXT,
        coordinate_source TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS plot_profile_versions (
        profile_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL REFERENCES plots(plot_id),
        version INTEGER NOT NULL,
        effective_from TIMESTAMPTZ NOT NULL,
        effective_to TIMESTAMPTZ,
        approved_by TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED',
        protocol_version TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (plot_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS plot_parameters (
        id BIGSERIAL PRIMARY KEY,
        profile_id BIGINT NOT NULL REFERENCES plot_profile_versions(profile_id),
        name TEXT NOT NULL,
        value DOUBLE PRECISION,
        unit TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'PENDING',
        source TEXT NOT NULL DEFAULT '',
        assessment_method TEXT NOT NULL DEFAULT '',
        checked_by TEXT NOT NULL DEFAULT '',
        measured_at DATE,
        UNIQUE (profile_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS crop_cycles (
        cycle_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL REFERENCES plots(plot_id),
        planting_date DATE NOT NULL,
        variety TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS phase_rules (
        id BIGSERIAL PRIMARY KEY,
        profile_id BIGINT NOT NULL REFERENCES plot_profile_versions(profile_id),
        phase TEXT NOT NULL,
        from_das INTEGER NOT NULL,
        to_das INTEGER NOT NULL,
        protected BOOLEAN NOT NULL DEFAULT FALSE,
        protocol_version TEXT NOT NULL DEFAULT '',
        UNIQUE (profile_id, phase)
    )""",
    # ---- observations: h manual, sensor, pengamatan stasiun ----
    """CREATE TABLE IF NOT EXISTS observations (
        obs_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT,
        station_id TEXT,
        sensor_id TEXT,
        variable TEXT NOT NULL,
        value DOUBLE PRECISION,
        unit TEXT NOT NULL DEFAULT '',
        observed_at TIMESTAMPTZ NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        recorded_by TEXT,
        source_type TEXT NOT NULL,
        quality_flag TEXT NOT NULL DEFAULT 'OK',
        note TEXT NOT NULL DEFAULT '',
        record_status TEXT NOT NULL DEFAULT 'ACTIVE',
        supersedes_id BIGINT,
        ext_key TEXT,
        meta JSONB
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_obs_ext_key ON observations(ext_key) WHERE ext_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_obs_var_plot_time ON observations(variable, plot_id, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_obs_sensor_time ON observations(sensor_id, observed_at DESC)",
    """CREATE TABLE IF NOT EXISTS station_registry (
        station_id TEXT PRIMARY KEY,
        source TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT '',
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        datum TEXT NOT NULL DEFAULT '',
        interval_min INTEGER,
        access TEXT NOT NULL DEFAULT '',
        representativeness TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE
    )""",
    # ---- arsip prakiraan per penerbitan dan ET0 harian ----
    """CREATE TABLE IF NOT EXISTS weather_forecast_runs (
        run_id BIGSERIAL PRIMARY KEY,
        source TEXT NOT NULL DEFAULT 'BMKG',
        location_id TEXT NOT NULL,
        issued_at TIMESTAMPTZ,
        fetched_at TIMESTAMPTZ NOT NULL,
        payload_hash TEXT NOT NULL,
        raw_payload JSONB,
        UNIQUE (location_id, payload_hash)
    )""",
    """CREATE TABLE IF NOT EXISTS weather_forecast_values (
        run_id BIGINT NOT NULL REFERENCES weather_forecast_runs(run_id),
        valid_at TIMESTAMPTZ NOT NULL,
        variable TEXT NOT NULL,
        value DOUBLE PRECISION,
        unit TEXT NOT NULL DEFAULT '',
        quality TEXT NOT NULL DEFAULT 'OK',
        PRIMARY KEY (run_id, valid_at, variable)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_wfv_valid ON weather_forecast_values(variable, valid_at)",
    """CREATE TABLE IF NOT EXISTS et0_daily (
        id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL,
        date DATE NOT NULL,
        forecast_run_id BIGINT,
        observation_snapshot_id TEXT,
        temperature_source TEXT NOT NULL,
        method_version TEXT NOT NULL,
        config_hash TEXT NOT NULL,
        et0_mm_day DOUBLE PRECISION,
        tmin DOUBLE PRECISION,
        tmax DOUBLE PRECISION,
        n_slots INTEGER,
        status TEXT NOT NULL,
        quality TEXT NOT NULL DEFAULT '',
        latitude DOUBLE PRECISION,
        computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_et0_daily ON et0_daily
        (plot_id, date, temperature_source, config_hash, COALESCE(forecast_run_id, 0), COALESCE(observation_snapshot_id, ''))""",
    # ---- rekomendasi yang tidak berubah, keputusan, pelaksanaan ----
    """CREATE TABLE IF NOT EXISTS recommendation_runs (
        rec_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by TEXT NOT NULL,
        decision_at TIMESTAMPTZ NOT NULL,
        inputs_snapshot JSONB NOT NULL,
        inputs_hash TEXT NOT NULL,
        profile_id BIGINT,
        model_version TEXT NOT NULL DEFAULT '',
        run_mode TEXT NOT NULL,
        status_code TEXT NOT NULL,
        output JSONB NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'PUBLISHED',
        decided_at TIMESTAMPTZ,
        decided_by TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_rec_plot_status ON recommendation_runs(plot_id, status, created_at DESC)",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS rec_id BIGINT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS plot_id TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS supersedes_id BIGINT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS record_status TEXT NOT NULL DEFAULT 'ACTIVE'",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS run_mode TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS void_reason TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS voided_by TEXT",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ",
    "ALTER TABLE decisions ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_idem ON decisions(idempotency_key) WHERE idempotency_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_decisions_rec ON decisions(rec_id)",
    "UPDATE decisions SET source='LEGACY_SIMULATION' WHERE source='simulation'",
    """CREATE TABLE IF NOT EXISTS irrigation_events (
        event_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL,
        decision_id BIGINT,
        rec_id BIGINT,
        arrived_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        ended_at TIMESTAMPTZ,
        actual_volume_m3 DOUBLE PRECISION,
        actual_discharge_m3s DOUBLE PRECISION,
        measurement_method TEXT NOT NULL DEFAULT '',
        h_after_cm DOUBLE PRECISION,
        h_after_at TIMESTAMPTZ,
        note TEXT NOT NULL DEFAULT '',
        recorded_by TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        record_status TEXT NOT NULL DEFAULT 'ACTIVE',
        supersedes_id BIGINT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_events_plot ON irrigation_events(plot_id, arrived_at DESC)",
    # ---- kerangka AI offline (belum ada model yang disetujui) ----
    """CREATE TABLE IF NOT EXISTS model_registry (
        model_version TEXT PRIMARY KEY,
        target TEXT NOT NULL,
        window_days DOUBLE PRECISION,
        feature_schema JSONB,
        et0_config TEXT,
        dataset_hash TEXT,
        cutoffs JSONB,
        metrics JSONB,
        status TEXT NOT NULL DEFAULT 'CANDIDATE',
        approved_at TIMESTAMPTZ,
        approved_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS residual_labels (
        label_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL,
        support_start TIMESTAMPTZ NOT NULL,
        support_end TIMESTAMPTZ NOT NULL,
        available_at TIMESTAMPTZ NOT NULL,
        validity TEXT NOT NULL,
        residual_mm_day DOUBLE PRECISION,
        et0_config TEXT,
        profile_id BIGINT,
        meta JSONB
    )""",
    """CREATE TABLE IF NOT EXISTS prediction_log (
        prediction_id BIGSERIAL PRIMARY KEY,
        rec_id BIGINT,
        model_version TEXT NOT NULL,
        plot_id TEXT NOT NULL,
        predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        residual_mm_day DOUBLE PRECISION,
        mode TEXT NOT NULL DEFAULT 'ML_SHADOW',
        meta JSONB
    )""",
    """CREATE TABLE IF NOT EXISTS ingest_log (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source TEXT NOT NULL,
        ok BOOLEAN NOT NULL,
        rows INTEGER NOT NULL DEFAULT 0,
        message TEXT NOT NULL DEFAULT ''
    )""",
    # ---- audit diperluas (entitas, nilai lama/baru) ----
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_id TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS old_value JSONB",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS new_value JSONB",
]

V3 = [
    # ---- H07: hasil QC sensor disimpan TERPISAH dari nilai mentah, berversi, dan append-only ----
    # Satu evaluasi = himpunan baris dengan (obs_id, qc_type, evaluated_at, available_at) yang sama, satu baris per reason_code
    # (reason_code 'NONE' = lolos). available_at = saat informasi yang dipakai evaluasi itu TERSEDIA di sistem; penilaian
    # retrospektif ditambahkan sebagai evaluasi baru dan tidak mengubah apa yang tersedia pada keputusan historis.
    """CREATE TABLE IF NOT EXISTS observation_qc (
        qc_id BIGSERIAL PRIMARY KEY,
        obs_id BIGINT NOT NULL REFERENCES observations(obs_id),
        qc_type TEXT NOT NULL CHECK (qc_type IN ('ONLINE', 'RETROSPECTIVE')),
        qc_flag TEXT NOT NULL CHECK (qc_flag IN ('OK', 'SUSPECT', 'BAD')),
        reason_code TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('USE', 'USE_WITH_WARNING', 'EXCLUDE_FROM_AUTOMATIC_USE')),
        rule_version TEXT NOT NULL,
        evaluated_at TIMESTAMPTZ NOT NULL,
        available_at TIMESTAMPTZ NOT NULL,
        meta JSONB
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_obsqc_eval ON observation_qc(obs_id, qc_type, rule_version, reason_code, available_at)",
    "CREATE INDEX IF NOT EXISTS ix_obsqc_obs_avail ON observation_qc(obs_id, available_at DESC)",
    # ---- H14: state bias adaptif per petak DAN model (M1B / M2), tahan restart, label dipakai paling banyak sekali ----
    """CREATE TABLE IF NOT EXISTS bias_state (
        plot_id TEXT NOT NULL,
        model TEXT NOT NULL CHECK (model IN ('M1B', 'M2')),
        b DOUBLE PRECISION NOT NULL DEFAULT 0,
        last_update_at TIMESTAMPTZ,
        last_window_end TIMESTAMPTZ,
        n_updates INTEGER NOT NULL DEFAULT 0,
        config JSONB NOT NULL,
        version BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (plot_id, model)
    )""",
    """CREATE TABLE IF NOT EXISTS bias_update_log (
        event_id BIGSERIAL PRIMARY KEY,
        plot_id TEXT NOT NULL,
        model TEXT NOT NULL,
        label_id BIGINT REFERENCES residual_labels(label_id),
        applied BOOLEAN NOT NULL,
        reason TEXT NOT NULL,
        prediction_id BIGINT REFERENCES prediction_log(prediction_id),
        prior_ref JSONB,
        prior_issued_at TIMESTAMPTZ,
        window_start TIMESTAMPTZ,
        window_end TIMESTAMPTZ,
        residual_mm_day DOUBLE PRECISION,
        r_base_mm_day DOUBLE PRECISION,
        e_base_mm_day DOUBLE PRECISION,
        b_before DOUBLE PRECISION,
        b_after DOUBLE PRECISION,
        elapsed_days DOUBLE PRECISION,
        clipped BOOLEAN,
        config JSONB,
        at TIMESTAMPTZ NOT NULL
    )""",
    # satu label memperbarui state paling banyak sekali per (petak, model)
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_biaslog_applied ON bias_update_log(plot_id, model, label_id) WHERE applied",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_biaslog_skip ON bias_update_log(plot_id, model, label_id, reason) WHERE NOT applied",
    # ---- append-only: tabel jejak tidak boleh diubah atau dihapus ----
    """CREATE OR REPLACE FUNCTION somat_forbid_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'tabel jejak bersifat append-only';
    END;
    $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_obsqc_append_only ON observation_qc",
    "CREATE TRIGGER trg_obsqc_append_only BEFORE UPDATE OR DELETE ON observation_qc FOR EACH ROW EXECUTE FUNCTION somat_forbid_mutation()",
    "DROP TRIGGER IF EXISTS trg_biaslog_append_only ON bias_update_log",
    "CREATE TRIGGER trg_biaslog_append_only BEFORE UPDATE OR DELETE ON bias_update_log FOR EACH ROW EXECUTE FUNCTION somat_forbid_mutation()",
]

ALL_STATEMENTS = V1 + V2 + V3
