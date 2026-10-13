# 2p_mama comfort undershoot — shadow experiment

Risk class: **YELLOW**  
Production activation: **forbidden in this experiment**  
Live control changes: **none**

## Triggering evidence

The 2026-09-27 09:03 CEST Opportunity Backlog refresh reported:

- 32 comfort samples;
- 32 samples more than 1 °C below target;
- undershoot rate 1.0;
- 27 active-no-demand samples;
- 5 demanding samples;
- active-no-demand rate 0.84375;
- opportunity confidence 0.90.

The sample count is too small for any schedule or target change. In particular,
the high active-no-demand fraction means an apparent comfort deficit must not be
interpreted as insufficient boiler runtime without first separating demand,
freshness, target/window semantics and hydraulic response.

## Evidence gate

Do not progress beyond root-cause shadow analysis until both are true:

- at least **3 distinct eligible comfort windows** have been observed;
- the eligible windows contain at least **60 comfort-minutes** in total.

An eligible window needs usable room temperature, target, schedule/window state,
PI-demand context, burner/request context and outside temperature, with no
observation gap that invalidates the interval.

## Root-cause hypotheses

Evaluate each window against competing explanations rather than selecting one
cause up front:

1. heat availability starts too late for the comfort window;
2. the TRV reports little/no heating demand despite a room deficit;
3. heat demand is present but room response is weak, requiring hydraulic or
   radiator-response investigation;
4. target/window state does not represent the intended comfort period;
5. stale or incomplete telemetry explains part of the apparent deficit.

PI demand remains a proxy and does not confirm physical valve opening or water
flow.

## Metrics per window

Record only read-only evidence:

- comfort-deficit minutes (>1 °C below target);
- overshoot minutes (>1 °C above target);
- room-temperature slope;
- valid PI-demand fraction and demanding fraction;
- active-no-demand fraction;
- burner/request phase and active-zone context;
- outside-temperature mean;
- gas/heating-demand proxy where comparable;
- Safety Sentinel warnings/faults;
- data-quality exclusions.

## Shadow variants

Only after the evidence gate and persistent undershoot are satisfied, compare
the observed baseline against hypothetical variants:

- comfort/preheat begins 15 minutes earlier;
- comfort window ends 15 minutes later.

These variants are simulations only. They must not write schedules, targets,
TRVs or relay state.

## Candidate success criteria

A variant may advance only as a YELLOW candidate if matched-window analysis
indicates all of:

- predicted comfort-deficit minutes improve by **at least 20%**;
- predicted overshoot minutes do not worsen by more than **10%**;
- normalized heating-demand/gas proxy does not worsen by more than **10%**
  without corresponding comfort benefit;
- Safety warning/fault rate does not increase;
- the result is not explained by stale/missing telemetry.

These percentages are experiment-selection criteria, not operating or safety
limits.

## Reject / rollback criteria

Reject the candidate and remain observation-only if any is true:

- fewer than 3 distinct eligible comfort windows;
- fewer than 60 eligible comfort-minutes;
- room/target/PI context is stale or missing;
- the dominant evidence is no heat demand rather than insufficient delivery;
- predicted overshoot or energy proxy exceeds the bounds above;
- any Safety/fault signal is associated with the proposed variant or matched
  evidence.

Because this experiment makes no live change, rollback means discarding the
candidate and preserving the current production policy unchanged.

## Promotion boundary

Even a successful shadow result does not authorize production. Any proposal to
change schedule timing, target temperature or other physical behavior remains
YELLOW/RED review territory and requires a separate human-reviewed change.
