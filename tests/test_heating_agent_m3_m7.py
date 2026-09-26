"""M3-M7 agent permissions, replay, safety and release gates."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from custom_components.heating_observer.database import AgentDatabase
from custom_components.heating_observer.gates import CodeAgentPlanner, DeploymentPlanner, ReleaseGate
from custom_components.heating_observer.intelligence import HeatingIntelligenceAgent
from custom_components.heating_observer.permissions import PermissionErrorDenied, PermissionManifest
from custom_components.heating_observer.replay import ReplayValidationAgent
from custom_components.heating_observer.safety import SafetySentinel
from custom_components.heating_observer.watchdog import AgentWatchdog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVARIANTS = __import__("json").loads(
    (PROJECT_ROOT / "custom_components/heating_observer/safety_invariants.json").read_text(encoding="utf-8")
)

BASE = 2_000_000_000.0


def episode(idx, *, fault=False, rule="pi10_count_lt3", lead=90.0, warned=True):
    return {
        "id": f"e-{idx}",
        "start": BASE + idx * 1000,
        "eligible": True,
        "outcome": "fault" if fault else "observed_no_fault",
        "incident_id": f"inc-{idx}" if fault else None,
        "fault_leads": {rule: lead} if fault and warned else {},
        "warned": [rule] if warned else [],
    }


def safe_sample(**overrides):
    sample = {
        "t": BASE,
        "relay": False,
        "gas": False,
        "pump": False,
        "master": True,
        "service": False,
        "mode": "Auto",
        "dhw": False,
        "dhw_recharging": False,
        "dhw_valve": False,
        "block": 40.0,
        "flow": 38.0,
        "code": 203,
        "ages": {"block": 0, "flow": 0},
    }
    sample.update(overrides)
    return sample


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionManifest.load_default()

    def test_manifest_is_default_deny_and_audits_cleanly(self):
        audit = self.permissions.audit()
        self.assertTrue(self.permissions.default_deny)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["violations"], [])
        self.assertFalse(audit["runtime_deployment_enabled"])

    def test_no_agent_can_control_home_assistant_or_execute_deployment(self):
        for agent in self.permissions.agents:
            self.assertFalse(self.permissions.allowed(agent, "ha.control"), agent)
            self.assertFalse(self.permissions.allowed(agent, "deployment.execute"), agent)
            self.assertFalse(self.permissions.allowed(agent, "git.write"), agent)

    def test_permission_enforcer_fails_closed(self):
        with self.assertRaises(PermissionErrorDenied):
            self.permissions.require("intelligence-v1", "ha.control.switch.turn_on")
        with self.assertRaises(PermissionErrorDenied):
            self.permissions.require("unknown-agent", "db.read")

    def test_path_classes_protect_control_files(self):
        self.assertEqual(self.permissions.classify_path("tests/test_x.py"), "green")
        self.assertEqual(self.permissions.classify_path("heating/observer/new.yaml"), "yellow")
        self.assertEqual(self.permissions.classify_path("heating/control/kotel_control.yaml"), "red")
        self.assertEqual(self.permissions.classify_path("automations.yaml"), "red")
        self.assertEqual(self.permissions.classify_path("unclassified/new.txt"), "red")


class ReplayAndIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionManifest.load_default()

    def test_replay_uses_held_out_fault_and_normal_sets(self):
        episodes = []
        for i in range(4):
            episodes.append(episode(i, fault=True, lead=90 + i))
        for i in range(4, 36):
            episodes.append(episode(i, fault=False, warned=(i % 8 == 0)))
        replay = ReplayValidationAgent(self.permissions).run(
            episodes, revision="test", generation=36, lead_budget=60
        )
        self.assertEqual(replay["dataset"]["evidence_faults"], 3)
        self.assertEqual(replay["dataset"]["validation_faults"], 1)
        self.assertEqual(replay["dataset"]["evidence_normal_controls"], 24)
        self.assertEqual(replay["dataset"]["validation_normal_controls"], 8)
        # 8 validation normals is intentionally below the conservative review gate.
        self.assertFalse(replay["enough_for_candidate_review"])
        self.assertFalse(replay["active_protection_changed"])

    def test_intelligence_never_activates_candidate(self):
        replay = {
            "replay_id": "r1",
            "enough_for_candidate_review": True,
            "dataset": {
                "evidence_faults": 3, "evidence_normal_controls": 30,
                "validation_faults": 1, "validation_normal_controls": 10,
            },
            "descriptive_rule_order": ["pi10_count_lt3"],
            "rules": [{
                "rule": "pi10_count_lt3",
                "description": "candidate",
                "evidence": {"timely": 3, "missed": 0, "warned_normal": 2},
                "validation": {"fault_incidents": 1, "detected": 1, "timely": 1, "missed": 0, "late": 0,
                               "lead_median_s": 90, "normal_controls": 10, "warned_normal": 1,
                               "warned_normal_rate": 0.1},
            }],
        }
        candidate = HeatingIntelligenceAgent(self.permissions).propose(replay)
        self.assertEqual(candidate["status"], "PROPOSED_FOR_HUMAN_REVIEW")
        self.assertFalse(candidate["active_policy_changed"])
        self.assertFalse(candidate["deployment_allowed"])
        self.assertTrue(candidate["requires_human_review"])


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionManifest.load_default()
        self.sentinel = SafetySentinel(self.permissions, INVARIANTS)
        self.runtime = {
            "actuator_control": False,
            "service_call_api": False,
            "agent_storage_error": None,
            "event_log_append_only": True,
        }
        self.permission_audit = self.permissions.audit()
        self.knowledge = {"facts_promoted_from_hypotheses": 0}

    def evaluate(self, sample):
        return self.sentinel.evaluate(
            sample,
            runtime=self.runtime,
            permission_audit=self.permission_audit,
            knowledge_summary=self.knowledge,
            intelligence_candidate={"active_policy_changed": False},
        )

    def test_service_mode_with_relay_is_violation(self):
        result = self.evaluate(safe_sample(service=True, relay=True))
        self.assertEqual(result["status"], "VIOLATION")
        self.assertIn("S01", [x["invariant"] for x in result["violations"]])

    def test_master_off_with_relay_is_violation(self):
        result = self.evaluate(safe_sample(master=False, relay=True))
        self.assertEqual(result["status"], "VIOLATION")
        self.assertIn("S02", [x["invariant"] for x in result["violations"]])

    def test_unknown_active_telemetry_is_warning_not_safe(self):
        result = self.evaluate(safe_sample(relay=True, block=None))
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("S05", [x["invariant"] for x in result["warnings"]])

    def test_fault_with_relay_escalates_on_repeated_observation(self):
        first = self.evaluate(safe_sample(relay=True, code=2964))
        second = self.evaluate(safe_sample(relay=True, code=2964))
        self.assertEqual(first["status"], "WARNING")
        self.assertEqual(second["status"], "VIOLATION")
        self.assertIn("S04", [x["invariant"] for x in second["violations"]])

    def test_safe_idle_state_is_ok(self):
        result = self.evaluate(safe_sample())
        self.assertEqual(result["status"], "OK")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionManifest.load_default()

    def test_red_path_requires_human_and_runtime_deployment_remains_disabled(self):
        plan = CodeAgentPlanner(self.permissions).plan(["heating/control/kotel_control.yaml"])
        self.assertEqual(plan["highest_class"], "red")
        self.assertTrue(plan["requires_safety_review"])
        self.assertFalse(plan["git_write_performed"])
        gate = ReleaseGate(self.permissions).evaluate(
            code_plan=plan,
            ci_green=True,
            safety_status="OK",
            replay={"enough_for_candidate_review": True},
        )
        self.assertEqual(gate["decision"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(gate["runtime_deployment_enabled"])
        deployment = DeploymentPlanner(self.permissions).plan("abc123")
        self.assertFalse(deployment["execution_allowed"])
        self.assertTrue(deployment["human_approval_required"])

    def test_unknown_ci_never_becomes_release_approval(self):
        plan = CodeAgentPlanner(self.permissions).plan(["tests/test_x.py"])
        gate = ReleaseGate(self.permissions).evaluate(
            code_plan=plan, ci_green=None, safety_status="OK", replay=None
        )
        self.assertEqual(gate["decision"], "AWAITING_CI")


class DatabaseAnalysisTests(unittest.TestCase):
    def test_analysis_artifacts_are_persisted_and_event_log_stays_append_only(self):
        permissions = PermissionManifest.load_default()
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDatabase(Path(tmp) / "agent.sqlite3", "test")
            db.initialize()
            replay = ReplayValidationAgent(permissions).run(
                [episode(0, fault=True), episode(1, fault=True)] +
                [episode(i, fault=False, warned=False) for i in range(2, 30)],
                revision="test", generation=30, lead_budget=60,
            )
            intelligence = HeatingIntelligenceAgent(permissions).propose(replay)
            safety = SafetySentinel(permissions, INVARIANTS).evaluate(
                safe_sample(),
                runtime={"actuator_control": False, "service_call_api": False,
                         "agent_storage_error": None, "event_log_append_only": True},
                permission_audit=permissions.audit(),
                knowledge_summary={"facts_promoted_from_hypotheses": 0},
                intelligence_candidate=intelligence,
            )
            code_plan = CodeAgentPlanner(permissions).plan([])
            gate = ReleaseGate(permissions).evaluate(
                code_plan=code_plan, ci_green=None, safety_status=safety["status"], replay=replay
            )
            watchdog = AgentWatchdog(permissions).evaluate(
                observer_storage_error=None,
                agent_storage_error=None,
                permission_audit=permissions.audit(),
                safety=safety,
                knowledge_summary={"facts_promoted_from_hypotheses": 0},
                last_agent_written_at=BASE,
                now=BASE,
            )
            db.write_analysis_bundle(
                created_at=BASE,
                replay=replay,
                intelligence=intelligence,
                safety=safety,
                permission_audit=permissions.audit(),
                release_gate=gate,
                watchdog=watchdog,
            )
            latest = db.latest_analysis()
            self.assertEqual(latest["replay"]["replay_id"], replay["replay_id"])
            self.assertEqual(latest["safety"]["status"], "OK")
            self.assertEqual(latest["permission_audit"]["status"], "PASS")
            stats = db.stats()
            self.assertEqual(stats["replays"], 1)
            self.assertEqual(stats["intelligence_candidates"], 1)
            self.assertEqual(stats["permission_audits"], 1)
            self.assertTrue(db.event_log_is_append_only())


if __name__ == "__main__":
    unittest.main()
