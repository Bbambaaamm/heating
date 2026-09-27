-- Heating Agent Platform 0.4 autonomous improvement context and opportunity backlog.
BEGIN;

CREATE TABLE IF NOT EXISTS optimization_samples (
    sample_event_id uuid PRIMARY KEY REFERENCES state_samples(event_id),
    captured_at timestamptz NOT NULL,
    gas_heat_total_kwh double precision,
    gas_heat_month_kwh double precision,
    heat_energy_month_kwh double precision,
    outside_temperature double precision,
    outside_humidity double precision,
    family_home boolean,
    schedule_active_count integer,
    active_zones double precision,
    average_demand double precision,
    valves_unhealthy double precision,
    gas_price_czk_kwh double precision
);

CREATE INDEX IF NOT EXISTS optimization_samples_time_idx
    ON optimization_samples(captured_at DESC);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id text PRIMARY KEY,
    fingerprint text NOT NULL UNIQUE,
    category text NOT NULL,
    title text NOT NULL,
    status text NOT NULL,
    risk_class text NOT NULL,
    confidence double precision NOT NULL,
    first_seen timestamptz NOT NULL,
    last_seen timestamptz NOT NULL,
    agent text NOT NULL,
    estimated_saving_kwh_month double precision,
    evidence jsonb NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS opportunities_status_idx
    ON opportunities(status, risk_class, last_seen DESC);

COMMIT;
