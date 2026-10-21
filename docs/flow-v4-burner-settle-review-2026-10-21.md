# Review candidate: wait for burner-off before finishing restoration

This is an offline proposal, not a production deployment. The active
`automations.yaml`, live HARD_LOCKOUT and boiler settings are unchanged.

## Reproduced incident

On 2026-10-21 at 06:30:20 Europe/Prague, the live Flow V4 trace reached
`action/6/then/7/choose/0/conditions/5` with `boiler_burngas=on` while it
required `off`. Restore verification, the previously latched path confirmation,
fault-clear and EMS connectivity had passed. The flow immediately entered
HARD_LOCKOUT. EMS subsequently reported burner-off at 06:31:59. This evidence
does not establish the physical cause of the reported burner-on with relay-off.

## Proposed behavior

The standalone fixture `tests/fixtures/flow_v4_burner_settle_review.yaml`
adds one bounded wait immediately before the existing final restoration gate.
If the burner state is not explicitly `off`, it waits up to three minutes for
that state. It then evaluates the existing gates, including temperature,
fault-clear, EMS connectivity, restore verification and path confirmation.
Unknown or unavailable burner states are not accepted as off. A native new
fault still preempts the restoration sequence. The three-minute limit is a
review proposal, not a manufacturer-specified safe waiting period.

This does not clear an existing lockout, disable a guard, energize the relay
during the wait or introduce direct EMS writes. Only normal restoration after
all final checks can restore the original master enable, leaving relay startup
to the existing deterministic policy. A latched path confirmation remains a
software proxy rather than a physical flow measurement.

## Validation and deployment boundary

Nine regression tests passed using Home Assistant 2026.5.1 and Python 3.14.2
with simulated services and devices. They cover reproduction of the previous
immediate lock, bounded waiting and resumption, persistent/unknown burner
states, EMS loss, thermal recheck, native fault preemption, retention of an
existing lockout, and preservation of the original configuration outside the
single wait. Repository protective checks also passed.

Run the native tests with:

```sh
python -m unittest discover -s tests -p test_flow_v4_burner_settle_review.py -v
```

The fixture is outside the live package include tree. It requires independent
review before any production promotion. These simulations do not validate
physical relay contacts, hydraulic flow, EMS mapping, or the unexplained start.
