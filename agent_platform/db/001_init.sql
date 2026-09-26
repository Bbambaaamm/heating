-- Heating Agent Platform v1: evidence-first PostgreSQL schema.
-- This schema stores observation/analysis artifacts only. It contains no HA actuator path.
BEGIN;

CREATE TABLE event_log (
    event_id uuid PRIMARY KEY,
    schema_version text NOT NULL,
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    site_revision text NOT NULL,
    source text NOT NULL,
    correlation_id text,
    causation_id uuid REFERENCES event_log(event_id),
    payload jsonb NOT NULL
);

CREATE INDEX event_log_type_time_idx ON event_log(event_type, occurred_at DESC);
CREATE INDEX event_log_revision_time_idx ON event_log(site_revision, occurred_at DESC);
CREATE INDEX event_log_correlation_idx ON event_log(correlation_id) WHERE correlation_id IS NOT NULL;

CREATE TABLE state_samples (
    event_id uuid PRIMARY KEY REFERENCES event_log(event_id),
    captured_at timestamptz NOT NULL,
    relay boolean,
    gas boolean,
    pump boolean,
    master boolean,
    service boolean,
    mode text,
    dhw boolean,
    dhw_recharging boolean,
    dhw_valve boolean,
    boiler_block_temperature double precision,
    flow_temperature double precision,
    burner_power double precision,
    service_code integer,
    quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX state_samples_time_idx ON state_samples(captured_at DESC);

CREATE TABLE zone_samples (
    sample_event_id uuid NOT NULL REFERENCES state_samples(event_id) ON DELETE RESTRICT,
    zone_id text NOT NULL,
    entity_id text NOT NULL,
    hvac_state text,
    current_temperature double precision,
    target_temperature double precision,
    pi_demand double precision,
    PRIMARY KEY (sample_event_id, zone_id)
);

CREATE TABLE heating_cycles (
    cycle_id text PRIMARY KEY,
    site_revision text NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    start_kind text NOT NULL,
    incomplete boolean NOT NULL,
    runtime_seconds double precision,
    burner_starts integer NOT NULL,
    start_boiler_temperature double precision,
    max_boiler_temperature double precision,
    max_temperature_rise_c_per_min double precision,
    min_requesting_zones integer,
    average_requesting_zones double precision,
    fault_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    service_seen boolean NOT NULL DEFAULT false,
    master_off_seen boolean NOT NULL DEFAULT false,
    dhw_seen boolean NOT NULL DEFAULT false,
    quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
    eligible_for_baseline boolean NOT NULL DEFAULT false
);

CREATE INDEX heating_cycles_revision_time_idx ON heating_cycles(site_revision, started_at DESC);
CREATE INDEX heating_cycles_baseline_idx ON heating_cycles(site_revision, eligible_for_baseline, started_at DESC);

CREATE TABLE incidents (
    incident_id uuid PRIMARY KEY,
    cycle_id text REFERENCES heating_cycles(cycle_id),
    site_revision text NOT NULL,
    incident_type text NOT NULL,
    severity text NOT NULL,
    occurred_at timestamptz NOT NULL,
    source_event_id uuid NOT NULL REFERENCES event_log(event_id),
    observation jsonb NOT NULL,
    timeline jsonb NOT NULL,
    diagnosis_state text NOT NULL DEFAULT 'pending'
);

CREATE INDEX incidents_type_time_idx ON incidents(incident_type, occurred_at DESC);
CREATE INDEX incidents_cycle_idx ON incidents(cycle_id) WHERE cycle_id IS NOT NULL;

CREATE TABLE diagnostic_reports (
    diagnostic_id text PRIMARY KEY,
    incident_id uuid NOT NULL REFERENCES incidents(incident_id),
    agent_run_id text,
    created_at timestamptz NOT NULL,
    facts jsonb NOT NULL,
    next_measurement text,
    safety_implication text
);

CREATE TABLE diagnostic_hypotheses (
    diagnostic_id text NOT NULL REFERENCES diagnostic_reports(diagnostic_id) ON DELETE CASCADE,
    hypothesis_index integer NOT NULL,
    name text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence_for jsonb NOT NULL,
    evidence_against jsonb NOT NULL,
    PRIMARY KEY (diagnostic_id, hypothesis_index)
);

CREATE TABLE protection_replays (
    replay_id text PRIMARY KEY,
    incident_id uuid REFERENCES incidents(incident_id),
    cycle_id text REFERENCES heating_cycles(cycle_id),
    protection_version text NOT NULL,
    dataset_role text NOT NULL CHECK (dataset_role IN ('evidence','validation','normal_control')),
    would_trip boolean NOT NULL,
    trip_at timestamptz,
    lead_seconds double precision,
    false_positive_candidate boolean NOT NULL DEFAULT false,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX protection_replays_version_idx ON protection_replays(protection_version, dataset_role, created_at DESC);

CREATE TABLE agent_runs (
    agent_run_id text PRIMARY KEY,
    agent text NOT NULL,
    task_type text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL,
    input_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    output_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION heating_agent_reject_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'event_log is append-only';
END;
$$;

CREATE TRIGGER event_log_no_update
BEFORE UPDATE OR DELETE ON event_log
FOR EACH ROW EXECUTE FUNCTION heating_agent_reject_event_mutation();

COMMIT;

-- Optional production optimization when TimescaleDB is available:
-- SELECT create_hypertable('state_samples', by_range('captured_at'), if_not_exists => TRUE);
-- Keep event_log itself append-only regardless of storage engine.
