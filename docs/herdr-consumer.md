# Herdr consumer contract

This repository consumes the shared Herdr orchestration platform from https://github.com/Bbambaaamm/herdr.

The immutable platform pin is recorded in HERDR.lock. Project-specific safety, domain logic, credentials, CI/review rules and merge authority remain in this repository.

Herdr may plan, route, schedule and observe work only within the permissions granted by this consumer policy. Child agents cannot expand parent permissions.

Current policy profile: heating-safe-engineering

Hard invariants:
- repository_changes_do_not_imply_runtime_actuation
- safety_relevant_production_changes_require_explicit_project_gate

Repository ownership and runtime deployment are separate operations. Updating the Herdr pin does not silently change production runtime; deployment must follow the project-specific verified rollout path.
