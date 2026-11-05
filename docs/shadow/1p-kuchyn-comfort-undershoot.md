# 1p_kuchyn — persistent-demand shadow analysis

Live evidence at 2026-09-27 09:18 CEST:

- comfort samples: 2069;
- undershoot: 1276 (61.67%);
- overshoot: 6.72%;
- active-no-demand: 20 (0.97%);
- demanding: 2049;
- confidence: 0.8084.

Demand is present during almost every comfort sample, so the primary shadow
question is delivery/timing response rather than missing demand.

## Gate

Use at least 3 recent distinct comfort windows and 120 recent eligible
comfort-minutes. Exclude stale/incomplete telemetry and Safety-warning/fault
windows.

## Analysis

Compare room-temperature slope against burner/request phase, active-zone
overlap and outside temperature. Check whether the room remains below target
despite sustained demand and available heating context.

After persistence is established, simulate +15 min preheat and +15 min comfort
window extension. Do not increase target temperature in this phase.

Candidate criteria: >=20% predicted deficit reduction; <=10% overshoot
worsening; <=10% normalized energy-proxy worsening unless supported by matched
comfort gain; no Safety degradation. No live writes.
