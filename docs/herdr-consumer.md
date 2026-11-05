# Herdr consumer contract

This repository consumes the shared Herdr orchestration platform from https://github.com/Bbambaaamm/herdr.

The immutable platform pin is recorded in `HERDR.lock`. Project-specific safety, domain logic, credentials, CI/review rules and merge authority remain in this repository. The pin must match `.herdr/consumer.yaml` exactly.

## Repository-only Hermes pilot

The first integration stage is controlled by [heating issue #172](https://github.com/Bbambaaamm/heating/issues/172) and the matching Herdr change. It is intentionally narrower than the future full architecture:

- one root issue and one `heating-hermes` coordinator;
- Hermes transport only, with no child delegation;
- isolated Git worktree for reading, editing, tests, documentation and a reviewable pull request;
- fresh maintainer approval bound to the current issue revision before intake;
- no merge, deployment or runtime activation implied by a successful pull request.

The pilot has no authority to write Home Assistant or Supervisor state, use SSH, publish MQTT commands, control a device or boiler, reload or restart services, deploy to production, or treat repository CI as evidence of live runtime safety. Those boundaries apply even if an issue asks for a broader action.

The current `HERDR.lock` remains on `v0.3.0-rc.8`. The pilot must not be activated from an unpinned Herdr branch. Activation waits for the reviewed Herdr work to be released as a new immutable version, pinned here, validated in CI and accepted through a separate canary/release decision.

## Policy

Current policy profile: `heating-safe-engineering`.

Herdr may plan, route, schedule and observe repository work only within the permissions granted by this consumer policy. Child agents cannot expand parent permissions.

Hard invariants:

- `repository_changes_do_not_imply_runtime_actuation`
- `safety_relevant_production_changes_require_explicit_project_gate`
- `no_home_assistant_or_supervisor_write_access`
- `no_ssh_mqtt_device_or_boiler_control`
- `no_reload_restart_or_production_deployment`
- `repository_ci_is_not_live_runtime_evidence`
- `unexplained_burner_start_is_not_domestic_hot_water`
- `one_requesting_zone_is_a_valid_heating_request`
- `software_lock_maximum_is_ten_minutes`
- `hard_lockout_and_flow_v4_must_not_be_bypassed`

Repository ownership and runtime deployment are separate operations. Updating the Herdr pin does not silently change production runtime; deployment must follow the project-specific verified rollout path. The later full architecture requires its own reviewed capability expansion, immutable release, canary evidence and human safety approval.
