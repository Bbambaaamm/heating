# Hydraulic support requires an independent ordinary heat request

The existing support selector can mistake the remaining demand of a previously
forced auxiliary TRV for a new independent requester. After ordinary schedules
return to ECO, the two auxiliary rooms can repeatedly request each other's
29 C target even though neither room needs its ordinary target.

The standalone fixture in `tests/fixtures/hydraulic_support_real_requester.yaml`
updates the existing support start and support guard; it does not create another
controller and must not be placed in an automatically loaded package directory.

An independent requester must have heat mode, an active zone, valid demand at
the original threshold and explicit native needed-heat ON. Its ordinary target,
computed using the existing disabled-zone, effective manual, boost, ECO and
schedule-window precedence, must still be above its reported room temperature.
The selected auxiliary is excluded. The ordinary target is clamped to the
climate's reported limits, without including the hydraulic 29 C override.
Invalid required policy/feedback/room data yields no independent requester.

A cold ECO room can still request heat. The extra predicate governs auxiliary
forcing only; the boiler's existing eligibility, minimum two confirmed zones,
minimum average demand, thermal cutoff, lockout, EMS/TUV interlocks and 120/240 s
start delays are unchanged. The support guard keeps its original 30 s settling
grace, 5 minute confirmation timeout, 15 minute failure cooldown, actions and
threshold restoration. Its existing state listeners additionally observe native
feedback and reported temperatures/targets for all supported requesters.

Native HA tests reproduce the previous forcing from a synthetic warm ECO cache,
verify rejection of self-generated demand, preserve genuine scheduled/manual/
boost/cold-ECO support, exercise invalid data, and verify threshold restoration.
All service acknowledgements are simulated. Needed-heat, target reports and
reported room temperature are not measurements of valve position or water flow.

This is a correction to auxiliary support eligibility. It does not identify the
origin of periodic EMS/TUV commands, prove physical flow, or establish that
service codes 2964-2967 cannot recur. The historical root automation source and
its snapshots remain unchanged; deploy only reviewed per-object deltas after a
fresh backup, conflict check and exact readback.
