"""No domestic-hot-water service on this installation: regression checks."""
import json
import unittest
from pathlib import Path

from custom_components.heating_observer.permissions import PermissionManifest
from custom_components.heating_observer.safety import SafetySentinel


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "custom_components/heating_observer/safety_invariants.json"
PLATFORM_CATALOG_PATH = ROOT / "agent_platform/policies/safety-invariants.json"


class NoDhwInstallationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.permissions = PermissionManifest.load_default()
        self.sentinel = SafetySentinel(self.permissions, self.catalog)

    def evaluate(self, **overrides):
        sample = {
            "relay": False, "gas": False, "pump": False,
            "master": True, "service": False, "mode": "Auto",
            "dhw": False, "dhw_recharging": False, "dhw_valve": False,
            "block": 40.0, "flow": 38.0, "code": 203,
            "ages": {"block": 0, "flow": 0},
        }
        sample.update(overrides)
        return self.sentinel.evaluate(
            sample,
            runtime={
                "actuator_control": False, "service_call_api": False,
                "agent_storage_error": None, "event_log_append_only": True,
            },
            permission_audit=self.permissions.audit(),
            knowledge_summary={"facts_promoted_from_hypotheses": 0},
            intelligence_candidate={"active_policy_changed": False},
        )

    def test_site_rule_is_identical_in_both_policy_catalogs(self):
        platform = json.loads(PLATFORM_CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertFalse(self.catalog["site_facts"]["boiler_serves_dhw"])
        self.assertEqual(self.catalog, platform)

    def test_ems_dhw_flags_must_not_excuse_unrequested_burner_start(self):
        outcome = self.evaluate(gas=True, dhw=True, dhw_valve=True)
        self.assertEqual(outcome["status"], "WARNING")
        self.assertTrue(any(x["invariant"] == "S06" and
                            x["severity"] == "high" for x in outcome["warnings"]))
        self.assertTrue(any("no DHW" in x["message"] and
                            x["invariant"] == "S07" for x in outcome["notes"]))
        self.assertFalse(outcome["operating_policy_changed"])

    def test_ems_dhw_flag_without_burner_is_context_not_automatic_fault(self):
        outcome = self.evaluate(dhw=True)
        self.assertEqual(outcome["status"], "OK")
        self.assertFalse(any(x["invariant"] == "S06" for x in outcome["warnings"]))
        self.assertTrue(any(x["invariant"] == "S07" for x in outcome["notes"]))

    def test_burner_without_relay_warns_with_dhw_flags_off(self):
        outcome = self.evaluate(gas=True)
        self.assertTrue(any(x["invariant"] == "S06" for x in outcome["warnings"]))

    def test_normal_idle_does_not_raise_false_alarm(self):
        outcome = self.evaluate()
        self.assertEqual(outcome["status"], "OK")


if __name__ == "__main__":
    unittest.main()
