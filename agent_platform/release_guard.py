"""Fail-closed source-only deployment guard for Heating Agent Platform.

The guard evaluates JSON snapshots and CI evidence only. It never connects to
Home Assistant, never calls services and never performs deployment or rollback.
"""
from __future__ import annotations

import argparse
from fnmatch import fnmatch
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

REQUIRED_CI = (
    "protective_checks",
    "runtime_ha_2026_5_1",
    "runtime_ha_2026_9_2",
)
MIN_IDLE_CONFIRMATION_SECONDS = 120.0
MAX_IDLE_CONFIRMATION_SECONDS = 600.0
MAX_WRITER_STALENESS_SECONDS = 300.0
PERSISTENT_COUNTERS = (
    "events",
    "samples",
    "replays",
    "intelligence_candidates",
    "opportunities",
)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _policy_path() -> Path:
    return Path(__file__).resolve().parent / "policies" / "agent-policy.json"


def load_path_policy(path: Path | None = None) -> dict[str, list[str]]:
    document = json.loads((path or _policy_path()).read_text(encoding="utf-8"))
    return document.get("path_policy", {})


def classify_path(path: str, policy: dict[str, list[str]] | None = None) -> str:
    normalized = str(path).lstrip("/")
    policy = policy or load_path_policy()
    for level in ("red", "yellow", "green"):
        for pattern in policy.get(level, []):
            if fnmatch(normalized, pattern):
                return level
    return "red"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _state_health_checks(
    snapshot: dict[str, Any],
    *,
    require_idle: bool,
    expected_version: str | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    observed_at = _finite(snapshot.get("observed_at"))
    _check(checks, "observed_at_known", observed_at is not None, "snapshot observed_at must be finite")

    if require_idle:
        for key in (
            "relay",
            "heating_active",
            "pump",
            "service_mode",
            "flow_relief_confirmed",
        ):
            value = snapshot.get(key)
            _check(
                checks,
                f"idle_{key}",
                value is False,
                f"{key} must be explicitly false; got {value!r}",
            )
    else:
        for key in ("relay", "heating_active", "pump", "service_mode", "flow_relief_confirmed"):
            value = snapshot.get(key)
            _check(
                checks,
                f"known_{key}",
                isinstance(value, bool),
                f"{key} must be a known boolean after restart; got {value!r}",
            )

    platform = snapshot.get("platform") or {}
    _check(
        checks,
        "platform_running",
        snapshot.get("platform_state") == "Běží",
        f"platform_state={snapshot.get('platform_state')!r}",
    )
    _check(
        checks,
        "platform_read_only",
        platform.get("mode") == "read_only",
        f"mode={platform.get('mode')!r}",
    )
    _check(
        checks,
        "actuator_control_disabled",
        platform.get("actuator_control") is False,
        f"actuator_control={platform.get('actuator_control')!r}",
    )
    _check(
        checks,
        "service_call_api_disabled",
        platform.get("service_call_api") is False,
        f"service_call_api={platform.get('service_call_api')!r}",
    )
    _check(
        checks,
        "agent_storage_healthy",
        platform.get("agent_storage_error") is None,
        f"agent_storage_error={platform.get('agent_storage_error')!r}",
    )
    if expected_version is not None:
        _check(
            checks,
            "expected_version",
            platform.get("version") == expected_version,
            f"expected={expected_version!r}, actual={platform.get('version')!r}",
        )

    safety = snapshot.get("safety") or {}
    _check(checks, "safety_ok", safety.get("state") == "OK", f"safety={safety.get('state')!r}")
    _check(
        checks,
        "safety_no_violations",
        safety.get("violations") == [],
        f"violations={safety.get('violations')!r}",
    )
    _check(
        checks,
        "safety_actuator_control_disabled",
        safety.get("actuator_control") is False,
        f"actuator_control={safety.get('actuator_control')!r}",
    )
    _check(
        checks,
        "safety_shutdown_endpoint_disabled",
        safety.get("shutdown_endpoint_enabled") is False,
        f"shutdown_endpoint_enabled={safety.get('shutdown_endpoint_enabled')!r}",
    )

    permissions = snapshot.get("permissions") or {}
    _check(
        checks,
        "permissions_pass",
        permissions.get("state") == "PASS",
        f"permissions={permissions.get('state')!r}",
    )
    _check(
        checks,
        "permissions_no_violations",
        permissions.get("violations") == [],
        f"violations={permissions.get('violations')!r}",
    )
    _check(
        checks,
        "runtime_deployment_disabled",
        permissions.get("runtime_deployment_enabled") is False,
        f"runtime_deployment_enabled={permissions.get('runtime_deployment_enabled')!r}",
    )
    _check(
        checks,
        "permissions_default_deny",
        permissions.get("default_deny") is True,
        f"default_deny={permissions.get('default_deny')!r}",
    )

    watchdog = snapshot.get("watchdog") or {}
    _check(
        checks,
        "watchdog_healthy",
        watchdog.get("state") == "HEALTHY",
        f"watchdog={watchdog.get('state')!r}",
    )
    _check(
        checks,
        "watchdog_no_problems",
        watchdog.get("problems") == [],
        f"problems={watchdog.get('problems')!r}",
    )

    last_written = _finite(platform.get("last_agent_written_at"))
    fresh = (
        observed_at is not None
        and last_written is not None
        and -30.0 <= observed_at - last_written <= MAX_WRITER_STALENESS_SECONDS
    )
    _check(
        checks,
        "agent_writer_fresh",
        fresh,
        f"observed_at={observed_at!r}, last_agent_written_at={last_written!r}",
    )
    return checks


def _release_checks(release: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    from_version = release.get("from_version")
    target_version = release.get("target_version")
    _check(
        checks,
        "from_version_present",
        isinstance(from_version, str) and bool(from_version.strip()),
        f"from_version={from_version!r}",
    )
    _check(
        checks,
        "target_version_present",
        isinstance(target_version, str) and bool(target_version.strip()),
        f"target_version={target_version!r}",
    )
    _check(
        checks,
        "version_changes",
        isinstance(from_version, str)
        and isinstance(target_version, str)
        and from_version != target_version,
        f"from={from_version!r}, target={target_version!r}",
    )

    expected_sha = release.get("expected_sha")
    sha_valid = isinstance(expected_sha, str) and bool(_SHA40.fullmatch(expected_sha))
    _check(
        checks,
        "release_sha_valid",
        sha_valid,
        f"expected_sha={expected_sha!r}",
    )

    ci = release.get("ci") or {}
    for name in REQUIRED_CI:
        proof = ci.get(name)
        passed = (
            isinstance(proof, dict)
            and proof.get("status") == "success"
            and sha_valid
            and proof.get("sha") == expected_sha
        )
        _check(
            checks,
            f"ci_{name}",
            passed,
            f"{name}={proof!r}, expected_sha={expected_sha!r}",
        )

    changed_paths = release.get("changed_paths")
    _check(
        checks,
        "changed_paths_present",
        isinstance(changed_paths, list) and bool(changed_paths),
        "changed_paths must be a non-empty list",
    )
    if isinstance(changed_paths, list):
        policy = load_path_policy()
        for path in changed_paths:
            valid_path = isinstance(path, str) and bool(path.strip())
            level = classify_path(path, policy) if valid_path else "red"
            _check(
                checks,
                f"path_green:{path}",
                valid_path and level == "green",
                f"{path!r} classified {level}",
            )
    return checks


def evaluate_pre_deploy(payload: dict[str, Any]) -> dict[str, Any]:
    release = payload.get("release") or {}
    snapshots = payload.get("snapshots")
    checks = _release_checks(release)

    valid_snapshots = isinstance(snapshots, list) and len(snapshots) >= 2
    _check(
        checks,
        "two_idle_confirmations",
        valid_snapshots,
        f"snapshot_count={len(snapshots) if isinstance(snapshots, list) else None}",
    )

    selected = snapshots[-2:] if valid_snapshots else []
    from_version = release.get("from_version")
    for index, snapshot in enumerate(selected, start=1):
        for check in _state_health_checks(
            snapshot,
            require_idle=True,
            expected_version=from_version if isinstance(from_version, str) else None,
        ):
            checks.append({**check, "name": f"snapshot_{index}:{check['name']}"})

    if len(selected) == 2:
        first_at = _finite(selected[0].get("observed_at"))
        second_at = _finite(selected[1].get("observed_at"))
        spacing = None if first_at is None or second_at is None else second_at - first_at
        _check(
            checks,
            "idle_confirmation_spacing",
            spacing is not None
            and MIN_IDLE_CONFIRMATION_SECONDS <= spacing <= MAX_IDLE_CONFIRMATION_SECONDS,
            f"spacing_seconds={spacing!r}",
        )
        first_revision = (selected[0].get("platform") or {}).get("revision")
        second_revision = (selected[1].get("platform") or {}).get("revision")
        _check(
            checks,
            "site_revision_stable",
            isinstance(first_revision, str)
            and bool(first_revision)
            and first_revision == second_revision,
            f"first={first_revision!r}, second={second_revision!r}",
        )

    passed = all(check["passed"] for check in checks)
    return {
        "phase": "pre_deploy",
        "decision": "GO" if passed else "NO_GO",
        "safe_to_restart": passed,
        "checks": checks,
        "physical_control_change": False,
        "deployment_executed": False,
        "note": (
            "GO authorizes only the separately controlled source copy/config-check/Core-restart step. "
            "This guard never performs deployment or Home Assistant control."
        ),
    }


def evaluate_post_deploy(payload: dict[str, Any]) -> dict[str, Any]:
    release = payload.get("release") or {}
    pre = payload.get("pre_snapshot") or {}
    post = payload.get("post_snapshot") or {}
    checks = _release_checks(release)

    target_version = release.get("target_version")
    checks.extend(
        _state_health_checks(
            post,
            require_idle=False,
            expected_version=target_version if isinstance(target_version, str) else None,
        )
    )

    pre_at = _finite(pre.get("observed_at"))
    post_at = _finite(post.get("observed_at"))
    _check(
        checks,
        "post_is_newer",
        pre_at is not None and post_at is not None and post_at > pre_at,
        f"pre={pre_at!r}, post={post_at!r}",
    )

    pre_platform = pre.get("platform") or {}
    post_platform = post.get("platform") or {}
    _check(
        checks,
        "site_revision_preserved",
        isinstance(pre_platform.get("revision"), str)
        and pre_platform.get("revision") == post_platform.get("revision"),
        f"pre={pre_platform.get('revision')!r}, post={post_platform.get('revision')!r}",
    )

    pre_written = _finite(pre_platform.get("last_agent_written_at"))
    post_written = _finite(post_platform.get("last_agent_written_at"))
    _check(
        checks,
        "writer_did_not_regress",
        pre_written is not None and post_written is not None and post_written >= pre_written,
        f"pre={pre_written!r}, post={post_written!r}",
    )

    pre_db = pre_platform.get("database") or {}
    post_db = post_platform.get("database") or {}
    for key in PERSISTENT_COUNTERS:
        before = _finite(pre_db.get(key))
        after = _finite(post_db.get(key))
        _check(
            checks,
            f"counter_non_regressing:{key}",
            before is not None and after is not None and after >= before,
            f"{key}: pre={before!r}, post={after!r}",
        )

    composite = post.get("composite_flow_risk")
    warnings: list[str] = []
    if composite is None:
        warnings.append(
            "Composite replay has not been materialized yet; wait for a new eligible episode/generation. "
            "Do not synthesize historical shadow features."
        )
    else:
        _check(
            checks,
            "composite_no_active_protection",
            composite.get("active_protection_changed") is False,
            f"active_protection_changed={composite.get('active_protection_changed')!r}",
        )
        _check(
            checks,
            "composite_no_deployment",
            composite.get("deployment_allowed") is False,
            f"deployment_allowed={composite.get('deployment_allowed')!r}",
        )
        _check(
            checks,
            "composite_validation_not_ranked",
            composite.get("validation_used_for_ranking") is False,
            f"validation_used_for_ranking={composite.get('validation_used_for_ranking')!r}",
        )

    passed = all(check["passed"] for check in checks)
    return {
        "phase": "post_deploy",
        "decision": "HEALTHY" if passed else "ROLLBACK_REQUIRED",
        "rollback_required": not passed,
        "checks": checks,
        "warnings": warnings,
        "physical_control_change": False,
        "rollback_executed": False,
        "rollback_plan": (
            "Restore the previous complete custom_components/heating_observer directory, "
            "run Home Assistant config check, then restart Home Assistant Core only. "
            "Preserve heating_observer_data evidence."
        ),
    }


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    phase = payload.get("phase")
    if phase == "pre":
        return evaluate_pre_deploy(payload)
    if phase == "post":
        return evaluate_post_deploy(payload)
    return {
        "phase": phase,
        "decision": "NO_GO",
        "safe_to_restart": False,
        "checks": [{
            "name": "known_phase",
            "passed": False,
            "detail": f"phase must be 'pre' or 'post'; got {phase!r}",
        }],
        "physical_control_change": False,
        "deployment_executed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="JSON input path or '-' for stdin")
    args = parser.parse_args(argv)
    if args.input == "-":
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = evaluate(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["decision"] in ("GO", "HEALTHY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
