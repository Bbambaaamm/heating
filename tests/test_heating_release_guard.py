"""Fail-closed release guard tests."""
from __future__ import annotations

from copy import deepcopy
import unittest

from agent_platform.release_guard import classify_path, evaluate_post_deploy, evaluate_pre_deploy

SHA = "9" * 40
REVISION = "hydraulika-20260921-neoverena"
LEASE_VERIFIED_AT = 2_000_000_170.0
LEASE_UNTIL = 2_000_001_000.0


def deployment_lease(**overrides):
    value = {
        "task_id": "heating-deploy-agent-platform-0-4-2",
        "agent_id": "heating-release-agent",
        "holder": "herdr-heating",
        "fencing_token": 17,
        "lease_until": LEASE_UNTIL,
        "verification": {
            "status": "current",
            "verified_at": LEASE_VERIFIED_AT,
            "current_fencing_token": 17,
        },
    }
    value.update(overrides)
    return value


def release(**overrides):
    value = {
        "from_version": "0.4.0",
        "target_version": "0.4.1",
        "expected_sha": SHA,
        "ci": {
            "protective_checks": {"status": "success", "sha": SHA},
            "runtime_ha_2026_5_1": {"status": "success", "sha": SHA},
            "runtime_ha_2026_9_2": {"status": "success", "sha": SHA},
        },
        "deployment_lease": deployment_lease(),
        "changed_paths": [
            "custom_components/heating_observer/const.py",
            "custom_components/heating_observer/manifest.json",
            "agent_platform/release_guard.py",
            "tests/test_heating_release_guard.py",
            "docs/heating-release-0.4.1.md",
            "docs/heating-composite-flow-risk-dashboard.md",
            "docs/heating-observer.md",
        ],
    }
    value.update(overrides)
    return value


def snapshot(t=2_000_000_000.0, *, version="0.4.0", written_offset=30.0):
    return {
        "observed_at": t,
        "relay": False,
        "heating_active": False,
        "pump": False,
        "service_mode": False,
        "flow_relief_confirmed": False,
        "platform_state": "Běží",
        "platform": {
            "mode": "read_only",
            "version": version,
            "revision": REVISION,
            "actuator_control": False,
            "service_call_api": False,
            "agent_storage_error": None,
            "last_agent_written_at": t - written_offset,
            "database": {
                "events": 3358,
                "samples": 2364,
                "replays": 1,
                "intelligence_candidates": 1,
                "opportunities": 3,
            },
        },
        "safety": {
            "state": "OK",
            "violations": [],
            "actuator_control": False,
            "shutdown_endpoint_enabled": False,
        },
        "permissions": {
            "state": "PASS",
            "violations": [],
            "runtime_deployment_enabled": False,
            "default_deny": True,
        },
        "watchdog": {"state": "HEALTHY", "problems": []},
    }


class ReleaseGuardTests(unittest.TestCase):
    def test_pre_deploy_go_requires_two_healthy_idle_snapshots(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)
        result = evaluate_pre_deploy({
            "release": release(),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "GO")
        self.assertTrue(result["safe_to_restart"])

    def test_pre_deploy_unknown_or_active_heating_fails_closed(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)
        second["relay"] = None
        result = evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})
        self.assertEqual(result["decision"], "NO_GO")

        second = snapshot(first["observed_at"] + 180)
        second["pump"] = True
        result = evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})
        self.assertEqual(result["decision"], "NO_GO")

    def test_pre_deploy_rejects_failed_ci_and_non_green_paths(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)
        bad_ci = release()
        bad_ci["ci"]["runtime_ha_2026_9_2"]["status"] = "failure"
        self.assertEqual(
            evaluate_pre_deploy({"release": bad_ci, "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

        red = release(changed_paths=["automations.yaml"])
        result = evaluate_pre_deploy({"release": red, "snapshots": [first, second]})
        self.assertEqual(result["decision"], "NO_GO")
        self.assertEqual(classify_path("automations.yaml"), "red")
        self.assertEqual(classify_path("unclassified/new.txt"), "red")

    def test_pre_deploy_rejects_ci_from_different_sha_or_missing_from_version(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)

        wrong_sha = release()
        wrong_sha["ci"]["protective_checks"]["sha"] = "8" * 40
        self.assertEqual(
            evaluate_pre_deploy({"release": wrong_sha, "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

        missing_from = release()
        missing_from.pop("from_version")
        self.assertEqual(
            evaluate_pre_deploy({"release": missing_from, "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

    def test_pre_deploy_rejects_weakened_safety_or_permission_model(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)

        second["permissions"]["default_deny"] = False
        self.assertEqual(
            evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

        second = snapshot(first["observed_at"] + 180)
        second["safety"]["shutdown_endpoint_enabled"] = True
        self.assertEqual(
            evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

        second = snapshot(first["observed_at"] + 180)
        second["safety"]["actuator_control"] = True
        self.assertEqual(
            evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})["decision"],
            "NO_GO",
        )

    def test_pre_deploy_requires_current_herdr_fencing_lease(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)

        missing = release()
        missing.pop("deployment_lease")
        result = evaluate_pre_deploy({"release": missing, "snapshots": [first, second]})
        self.assertEqual(result["decision"], "NO_GO")

        invalid_token = release(deployment_lease=deployment_lease(fencing_token=0))
        result = evaluate_pre_deploy({"release": invalid_token, "snapshots": [first, second]})
        self.assertEqual(result["decision"], "NO_GO")

        stale = deployment_lease()
        stale["verification"] = {**stale["verification"], "status": "stale"}
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=stale),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

        superseded = deployment_lease()
        superseded["verification"] = {
            **superseded["verification"],
            "current_fencing_token": superseded["fencing_token"] + 1,
        }
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=superseded),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

    def test_pre_deploy_rejects_expired_or_stale_lease_verification(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)

        expired = deployment_lease(lease_until=second["observed_at"] + 5)
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=expired),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

        old_verification = deployment_lease()
        old_verification["verification"] = {
            **old_verification["verification"],
            "verified_at": second["observed_at"] - 61,
        }
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=old_verification),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

        future_verification = deployment_lease()
        future_verification["verification"] = {
            **future_verification["verification"],
            "verified_at": second["observed_at"] + 31,
        }
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=future_verification),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

        excessive_ttl = deployment_lease(lease_until=LEASE_VERIFIED_AT + 1801)
        result = evaluate_pre_deploy({
            "release": release(deployment_lease=excessive_ttl),
            "snapshots": [first, second],
        })
        self.assertEqual(result["decision"], "NO_GO")

    def test_pre_deploy_returns_accepted_fencing_identity(self):
        first = snapshot()
        second = snapshot(first["observed_at"] + 180)
        result = evaluate_pre_deploy({"release": release(), "snapshots": [first, second]})
        self.assertEqual(result["decision"], "GO")
        self.assertEqual(result["deployment_fence"]["fencing_token"], 17)
        self.assertEqual(
            result["deployment_fence"]["task_id"],
            "heating-deploy-agent-platform-0-4-2",
        )
        self.assertTrue(result["fence_recheck_required_before_mutation"])

    def test_pre_deploy_requires_stable_idle_window(self):
        first = snapshot()
        too_soon = snapshot(first["observed_at"] + 30)
        result = evaluate_pre_deploy({"release": release(), "snapshots": [first, too_soon]})
        self.assertEqual(result["decision"], "NO_GO")

    def test_post_deploy_healthy_preserves_evidence_and_read_only_invariants(self):
        pre = snapshot()
        post = snapshot(pre["observed_at"] + 300, version="0.4.1")
        post["platform"]["database"]["events"] += 10
        post["platform"]["database"]["samples"] += 10
        post["platform"]["last_agent_written_at"] = post["observed_at"] - 10
        post["composite_flow_risk"] = {
            "active_protection_changed": False,
            "deployment_allowed": False,
            "validation_used_for_ranking": False,
        }
        result = evaluate_post_deploy({
            "release": release(),
            "pre_snapshot": pre,
            "post_snapshot": post,
        })
        self.assertEqual(result["decision"], "HEALTHY")
        self.assertFalse(result["rollback_required"])

    def test_post_deploy_missing_composite_is_warning_not_failure(self):
        pre = snapshot()
        post = snapshot(pre["observed_at"] + 300, version="0.4.1")
        post["platform"]["last_agent_written_at"] = post["observed_at"] - 10
        result = evaluate_post_deploy({
            "release": release(),
            "pre_snapshot": pre,
            "post_snapshot": post,
        })
        self.assertEqual(result["decision"], "HEALTHY")
        self.assertTrue(result["warnings"])

    def test_post_deploy_wrong_version_or_counter_regression_requires_rollback(self):
        pre = snapshot()
        wrong_version = snapshot(pre["observed_at"] + 300, version="0.4.0")
        wrong_version["platform"]["last_agent_written_at"] = wrong_version["observed_at"] - 10
        result = evaluate_post_deploy({
            "release": release(),
            "pre_snapshot": pre,
            "post_snapshot": wrong_version,
        })
        self.assertEqual(result["decision"], "ROLLBACK_REQUIRED")

        post = snapshot(pre["observed_at"] + 300, version="0.4.1")
        post["platform"]["last_agent_written_at"] = post["observed_at"] - 10
        post["platform"]["database"]["samples"] -= 1
        result = evaluate_post_deploy({
            "release": release(),
            "pre_snapshot": pre,
            "post_snapshot": post,
        })
        self.assertEqual(result["decision"], "ROLLBACK_REQUIRED")

    def test_post_deploy_rejects_any_composite_control_capability(self):
        pre = snapshot()
        post = snapshot(pre["observed_at"] + 300, version="0.4.1")
        post["platform"]["last_agent_written_at"] = post["observed_at"] - 10
        post["composite_flow_risk"] = {
            "active_protection_changed": True,
            "deployment_allowed": False,
            "validation_used_for_ranking": False,
        }
        result = evaluate_post_deploy({
            "release": release(),
            "pre_snapshot": pre,
            "post_snapshot": post,
        })
        self.assertEqual(result["decision"], "ROLLBACK_REQUIRED")


if __name__ == "__main__":
    unittest.main()
