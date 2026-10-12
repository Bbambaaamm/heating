# Confirmed zone eligibility for the existing V4 relay owners

Cached PI can stay positive after a TRV explicitly reports that it no longer
needs heat. Counting that zone until PI falls can leave an obsolete boiler
request active. The two standalone fixtures require explicit native Danfoss
"Potřebné teplo" ON as an additional eligibility input.

An eligible zone must belong to the existing supported heating group, have
native HVAC mode heat, an active zone flag, finite demand in (1,100], demand at
least the configured per-zone threshold, and native heat-needed ON. Compute
the count and average only over these zones. Require the effective policy
thresholds, with hard floors of two zones and 15 percent. Missing/invalid policy
or group inputs fail closed; OFF/unknown/unavailable/missing heat-needed does not
count. Unmapped group members block until their inventory and triggers are
reviewed. This does not establish the actual freshness of a cached ON report.

The existing safe start checks this eligibility before and after its original
delay. State transitions invalidate/restart that delay; attribute-only feedback
or demand reports do not. The existing relay guard withdraws only the relay
request immediately if the confirmed policy no longer passes. Using both owners
prevents a stale aggregate request from repeatedly turning the relay back on.
The guard retains its thermal >=72 C, invalid-temperature, Flow and lockout
checks. The normal 120-second and post-recovery 240-second start restrictions
and every original EMS/DHW/service/master condition remain unchanged.

These are **standalone candidates**, not a claim that the public root or a live
installation has been updated. Replace the existing IDs individually after a
fresh backup, isolated HA tests, valid config check, inactive recovery check,
conflict/hash comparison and exact readback. Never bulk-import the current
public automations.yaml: it still contains the historical guard. The package
aggregate sensors remain historical PI-based diagnostics; this bridge independently
checks confirmed eligibility at the relay owners. It does not install package YAML.

Only the relay may be turned off by the guard, and only the original start owns
normal relay ON. No pump, burner, EMS master, TRV target, comfort history,
hydraulic minimum, recovery automation or factory protection is changed.

Heat-needed ON is reported intent, not measured valve position or physical
flow. These changes do not prove the cause of EMS 2964 or guarantee that it
cannot recur. Natural observation and independent hydraulic verification remain
necessary. Test data are synthetic; no installation telemetry is included.

