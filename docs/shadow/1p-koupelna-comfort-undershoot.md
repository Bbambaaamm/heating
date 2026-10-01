# 1p_koupelna — demand vs delivery shadow analysis

Live evidence at 2026-09-27 09:18 CEST:

- comfort samples: 1971;
- undershoot: 1604 (81.38%);
- active-no-demand: 271 (13.75%);
- demanding: 1700;
- confidence: 0.90.

## Gate

Use at least 3 recent distinct comfort windows and 120 recent eligible
comfort-minutes. Exclude stale/incomplete telemetry and any Safety-warning/fault
window.

## Competing hypotheses

1. comfort heat availability starts too late;
2. demand exists but room/radiator response is weak;
3. active-zone overlap/hydraulic context limits useful delivery;
4. a minority of the deficit is explained by no-demand/TRV behavior;
5. target/window semantics or stale data explain part of the signal.

PI remains a demand proxy, not physical valve or flow proof.

## Metrics and shadow variants

Measure deficit minutes, room slope, demanding fraction, burner/request
availability, active-zone overlap, outside temperature and comparable
heating/gas proxy.

Only after persistent root-cause evidence, simulate +15 min preheat and +15 min
window extension.

Candidate criteria: >=20% predicted deficit reduction; <=10% overshoot
worsening; <=10% normalized energy-proxy worsening without matched comfort
gain; no Safety degradation. Otherwise reject and preserve production policy.
