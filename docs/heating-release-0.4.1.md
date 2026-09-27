# Heating Agent Platform 0.4.1 — fail-closed deployment checklist

Release 0.4.1 packages the read-only Composite Flow-Risk replay from PR #117
and adds a source-only deployment decision guard. The guard does **not** deploy,
restart Home Assistant, call services, control heating or perform rollback.

## Preconditions

The release artifact must be tied to one exact 40-character Git SHA. The same
SHA must have successful:

- protective checks;
- runtime regressions on Home Assistant 2026.5.1;
- runtime regressions on Home Assistant 2026.9.2.

Every changed path must classify GREEN under
`agent_platform/policies/agent-policy.json`. Unknown paths fail closed as RED.

## Automatic PRE decision

Run:

```sh
python3 -m agent_platform.release_guard pre.json
```

The JSON document uses `"phase": "pre"`, release evidence and at least two
read-only HA snapshots. The last two snapshots must be 120–600 seconds apart.

Each snapshot must explicitly prove:

- boiler relay OFF;
- heating active OFF;
- heating pump OFF;
- service mode OFF;
- flow relief not confirmed/active;
- Agent Platform running;
- mode `read_only`;
- `actuator_control=false`;
- `service_call_api=false`;
- no agent storage error;
- Safety Sentinel `OK`, no violations;
- Permissions `PASS`, no violations;
- runtime deployment disabled;
- Watchdog `HEALTHY`, no problems;
- agent evidence writer fresh within 300 seconds;
- unchanged non-empty `site_revision`;
- expected currently installed `from_version`.

Any missing, unknown, stale or contradictory value yields `NO_GO`.
`GO` only means the separately controlled source-copy/config-check/Core-restart
procedure may proceed. It is not a deployment action.

The runtime release gate may still display `AWAITING_CI`: GitHub CI evidence
is intentionally supplied to this external guard instead of expanding HA runtime
permissions.

## Controlled deployment step after GO

1. Create a Home Assistant backup.
2. Copy the complete `custom_components/heating_observer/` directory from the
   exact CI-green release SHA. Do not mix files from different revisions.
3. Do not modify `automations.yaml`, `scripts.yaml`, `heating/control/**`,
   `heating/safety/**`, schedules, TRV targets or safety thresholds.
4. Run Home Assistant configuration check.
5. If config check fails, stop: do not restart.
6. If it passes, restart **Home Assistant Core only**.
7. Do not make the heating idle by controlling devices; if PRE becomes NO_GO,
   wait for another naturally idle window and capture two new snapshots.

## Automatic POST decision

After Core is back and the agent writer has resumed, run the guard with
`"phase": "post"`, the final PRE snapshot and a fresh POST snapshot.

POST requires:

- version exactly `0.4.1`;
- same site revision as PRE;
- Agent Platform running in read-only mode;
- no actuator/service-call capability;
- Safety `OK`;
- Permissions `PASS` with runtime deployment disabled;
- Watchdog `HEALTHY`;
- fresh agent writer;
- known heating telemetry;
- persistent evidence counters do not regress.

If Composite Flow-Risk already exists, POST additionally requires
`active_protection_changed=false`, `deployment_allowed=false` and
`validation_used_for_ranking=false`.

Absence of Composite Flow-Risk immediately after restart is **not** a failure.
Historical episodes from before 0.4.1 lack the new shadow features. The correct
behavior is to wait for new eligible feature-traced episodes; never synthesize
those historical features.

A failed POST decision is `ROLLBACK_REQUIRED`.

## Rollback

The guard only describes rollback; it never executes it.

1. Restore the previous complete `custom_components/heating_observer/`
   directory.
2. Preserve `/config/heating_observer_data/`.
3. Run Home Assistant configuration check.
4. Restart Home Assistant Core only.
5. Re-run the POST health checks against the restored version.

Full Home Assistant restore remains a last-resort recovery path; source rollback
is preferred because it does not revert unrelated HA changes.
