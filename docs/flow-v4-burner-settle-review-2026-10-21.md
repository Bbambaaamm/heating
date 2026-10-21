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

## Production deployment, 21 October 2026

The user explicitly approved deployment and requested acknowledgement of the
stuck historical lock. At 11:32–11:33 Europe/Prague, the two automation objects
were updated through the HA config API with optimistic config hashes. The
live `cooled` busy-emergency guard was preserved and synchronized into source;
no other automation object was overwritten. Both objects were read back and
matched the intended configurations. They are enabled and loaded.

At 11:34:51 the historical HA lock helper was acknowledged after reading current
fault-clear ON, EMS connected, burner/relay OFF, block 30.8 C, restoration
acknowledged and the existing session path acknowledgement. At 11:35:00 the
native minute reconciliation completed RESTORING, restored the original master
preference to ON, and entered NORMAL. The separate relay-start policy retained
its 240-second post-recovery delay and all normal gates. No relay-ON command was
issued manually and no Bosch/EMS setting or fault reset was written.

The session path acknowledgement is the existing software signal; it does not
prove physical water flow. Deployment does not establish the physical cause of
the morning burner-on/relay-off indication. This acknowledgement concerns the
identified historical false latch, not a standing automatic hardlock bypass.
See `flow-v4-deployment-2026-10-21.json` for config hashes and verification.

## New boiler fault during observation

The normal policy switched the relay ON at 11:38:59. EMS reported burner ON at
11:39:19. At 11:39:29 EMS reported a **new 2964**; burner and relay switched OFF,
and native Flow V4 entered EMERGENCY_COOLING. Fault-clear returned ON at 11:39:59.
The historical hardlock helper remained OFF. This is a fresh boiler-reported
fault, not recurrence of the old stored hardlock. Sustained heating has not been
verified. No further lock acknowledgement, boiler fault reset or forced relay
start was performed. Existing native emergency/recovery control remains active.
