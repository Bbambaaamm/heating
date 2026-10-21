# Flow V4: retry transient restoration blockers

## Problem and resulting behavior

On 21 October 2026 at 06:30:20 Europe/Prague, the live restoration trace failed its
burner-off condition and entered HARD_LOCKOUT. EMS reported burner-off at
06:31:59, but the stored lock never cleared. The first bounded-wait proposal
would still latch permanently if the transient condition outlasted its timeout.

The production source in automations.yaml now distinguishes transient readiness
from missing restoration/path verification. When restoration and the session
path confirmation have succeeded and no lockout is already asserted, it waits
up to three minutes for explicit burner-off, valid block temperature below 60 C,
fault-clear and EMS connectivity. If a transient condition persists, it keeps
RESTORING, master OFF, relay OFF and recovery pending. An idle-only minute tick
retries the final checks. Once those checks pass, the existing normal restoration
path restores the original master preference. Relay startup stays with the
existing separate startup policy and its delays/interlocks.

Acknowledged zone targets are not repeatedly reset on every retry. Failed zone
restoration or missing path confirmation still enters HARD_LOCKOUT. An existing
hardlock is not silently erased. A native new fault or thermal emergency still
preempts the wait. Unknown or unavailable telemetry never counts as permission
to start. Waiting status includes the actual burner, fault-clear, bus and block
values in one stable notification.

## Files and regression protection

- automations.yaml: actual restoration and idle ticker source changes.
- tests/test_flow_v4_recovery_retry_runtime.py: native HA behavior tests against
  the historical failing source and changed production source.
- tests/fixtures/flow_v4_before_retry_20261021.yaml: immutable historical source.
- tests/fixtures/flow_v4_cooled_opening.yaml: existing opening-race candidate
  synchronized with the new restoration branch.
- tests/test_runtime_automation_inventory.py: preserves comparison of unchanged
  historical snapshot fields; delegates changed recovery behavior to native tests.
- AGENTS.md: records the regression requirement for future maintenance.

The tests simulate services and devices. They cover the original failure,
recovery within and after the bounded wait, communication and temperature loss,
busy-tick cancellation, preservation of a previously disabled master, new fault
preemption, unverified paths, failed restoration and retention of an existing
hardlock. They do not validate physical relay contacts, real flow or the cause
of burner-on while relay-off. No direct EMS command path is added.

## Deployment boundary

This Git change is not a live Home Assistant deployment. Changing source does
not itself migrate the existing HARD_LOCKOUT. Before production promotion,
review the safety delta and use the documented project change-control process.
The existing hardlock must be handled as a separate reviewed recovery operation;
this patch is not a command to force a burner start.
