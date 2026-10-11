# V4 immediate relay request cutoff

The existing safe-start automation requires boiler block temperature strictly
below 72 °C. Previously, a running relay request could remain ON through a short
hot excursion: Flow's separate above-72 trigger has a ten-second dwell, and the
independent relay guard checked only Flow state and lockout.

The standalone replacement candidate for `heating_v4_relay_lockout_guard` also observes block temperature
state changes. With relay ON it requests only `switch.turn_off` when temperature
is 72 °C or higher, absent, unavailable, nonnumeric or nonfinite. Startup, reload
and foreign relay-ON reconciliation apply the same gate. This includes the exact
boundary that a native `above: 72` trigger would exclude.

The condition deliberately retains a small fail-closed template: native negative
state/numeric conditions can raise `ConditionError` for missing or invalid
entities. `is_state` and `is_number` permit an OFF decision even then; the numeric
conversion has an explicit default. State triggers and the relay-ON condition are
native. There is no polling collector, new automation owner or physical test.

Cooling does not directly reassert the request. The existing safe-start policy
still enforces its delay, post-recovery settling period, hydraulic minimum and
other telemetry/state guards. Flow's emergency opening/restoration, schedules,
factory pump run-on and boiler settings are unchanged.

Isolated HA Core tests cover brief excursions without dwell, exact 72 °C,
already-hot foreign ON, invalid/missing/nonfinite temperature, startup/reload,
safe reports, restart delay/telemetry cancellation and existing recovery
noninterference. Services and devices are fake.

This removes a known request-cutoff gap. It does not establish physical flow,
prove an EMS fault's cause, prevent residual heating or claim that all boiler
faults are impossible. Independent flow measurement and passive EMS attribution
remain necessary. No private configuration export or operational telemetry is
included in this source change.

This PR intentionally adds only a standalone fixture, regression tests and this
document. The root `automations.yaml` and original fixture stay unchanged; the
candidate does not install a second owner. Apply the reviewed trigger, condition
and description delta to the existing unique ID only after a fresh backup, idle
state/active-recovery check, passing runtime tests and conflict check. Verify the
complete configuration readback and unchanged Flow/safe-start controllers. A
subsequent wholesale root import would restore the original guard until the
public main-source synchronization is separately approved and completed.
