-- Heating Agent Platform 0.3 analysis/control-plane artifacts.
-- No table in this migration grants Home Assistant control.
BEGIN;

CREATE TABLE IF NOT EXISTS replay_reports (
    replay_id text PRIMARY KEY,
    generation bigint NOT NULL,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_candidates (
    candidate_id text PRIMARY KEY,
    replay_id text,
    created_at timestamptz NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_evaluations (
    evaluation_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS permission_audits (
    audit_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS release_gate_evaluations (
    gate_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    decision text NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS watchdog_evaluations (
    evaluation_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS replay_reports_generation_idx
    ON replay_reports(generation DESC);
CREATE INDEX IF NOT EXISTS safety_evaluations_created_idx
    ON safety_evaluations(created_at DESC);
CREATE INDEX IF NOT EXISTS watchdog_evaluations_created_idx
    ON watchdog_evaluations(created_at DESC);

COMMIT;
