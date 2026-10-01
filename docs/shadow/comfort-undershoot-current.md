# Current comfort undershoot shadow program

Risk class: **YELLOW**. Production activation: **forbidden**.

This program covers the currently active 0.4.1 comfort undershoot opportunities
outside the already separate `2p_mama` experiment (#126 / PR #127):

- `1p_koupelna` — issue #129;
- `1p_kuchyn` — issue #130;
- `1p_jidelna` — issue #131.

Each zone keeps a separate evidence gate and root-cause hypothesis. Aggregate
undershoot rate alone must never trigger a live schedule or target change.

Shared read-only inputs:

- room and target temperature;
- schedule/window state;
- PI demand validity/fraction;
- burner/request phase;
- active-zone context;
- outside temperature;
- normalized heating/gas proxy where comparable;
- Safety Sentinel warnings/faults and data-quality exclusions.

Common promotion boundary: a successful shadow candidate stays YELLOW. Any
physical schedule, target, TRV or relay change requires a separate reviewed
change. No experiment in this package writes Home Assistant state.
