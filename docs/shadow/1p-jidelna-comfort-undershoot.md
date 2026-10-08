# 1p_jidelna — mixed thermal-response shadow analysis

Live evidence at 2026-09-27 09:18 CEST:

- comfort samples: 2168;
- undershoot: 976 (45.02%);
- overshoot: 33.26%;
- active-no-demand: 282 (13.01%);
- demanding: 1886;
- confidence: 0.7251.

The previous overshoot opportunity auto-resolved, but the recent aggregate still
contains substantial overshoot history. A simple longer or hotter schedule is
therefore not justified.

## Gate

Use at least 4 recent distinct comfort windows and 180 recent eligible
comfort-minutes. Separate materially different window periods instead of
combining them blindly. Exclude stale/incomplete telemetry and
Safety-warning/fault windows.

## Analysis

Compare deficit/overshoot minutes, room slope, demand fraction, burner/request
phase, active-zone overlap and outside temperature. Determine whether timing
and thermal inertia can explain both sides of the distribution.

Only after persistent evidence, simulate +15 min preheat and a timing shift with
unchanged total comfort duration. Do not simulate a higher temperature target in
this phase.

Candidate criteria: >=20% predicted deficit reduction while matched-window
overshoot stays at or below baseline; <=10% normalized energy-proxy worsening
unless justified by comfort benefit; no Safety degradation. Otherwise reject.
