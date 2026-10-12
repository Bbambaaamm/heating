# Flow V4: cooling while emergency opening is busy

With `mode: restart`, a native `cooled` trigger can cancel the emergency
opening sequence, including while relay-off acknowledgement is still in flight
or before the second TRV batch completes. The existing progress guard protected
`reconcile` and `paths_confirmed`, leaving this cooling transition unprotected.

The standalone fixture `heating/control/flow_v4_cooled_opening.yaml` extends
that same top-level busy guard to `cooled`. Its conditions are evaluated before
HA restarts the action sequence. Cooling still runs when the automation is idle;
the existing reconcile event can observe a cooling transition skipped while
opening. Native fault triggers retain their preemption behavior.

All triggers, actions, targets, confirmation checkpoints, minimum emergency hold,
maximum timeout, restore gates, hard lockout and boiler enable restrictions are
otherwise identical to the public Flow V4 source. No collector, timer, actuator
API or helper is added. The fixture does not clear an existing hard lockout.

The native HA tests reproduce cancellation with the previous guard, cover
cooling before the first and during the second batch, startup, confirmation,
idle restoration, native fault preemption and retained hard lockout. All inputs
and services are simulated. A reported target or native heat demand is not proof
of valve movement or physical flow; source/runtime tests do not establish an
EMS fault's physical cause or replace independent service measurements.

This fixture is derived only from the already-public Flow V4 automation.
The historical root `automations.yaml` remains unchanged: do not bulk-import
that root over a live installation with later per-automation safety repairs.
Deploy this individual Flow automation only after a fresh backup, configuration
validation, conflict check and confirmation that no opening or restore is active.
Preserve existing start/relay guard configurations and any hard lockout, then
read back the exact result. Do not induce a physical fault or clear lockout to
test it.
