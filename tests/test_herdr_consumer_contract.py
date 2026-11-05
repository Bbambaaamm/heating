from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / ".herdr" / "consumer.yaml"
LOCK = ROOT / "HERDR.lock"

EXPECTED_INVARIANTS = {
    "repository_changes_do_not_imply_runtime_actuation",
    "safety_relevant_production_changes_require_explicit_project_gate",
    "no_home_assistant_or_supervisor_write_access",
    "no_ssh_mqtt_device_or_boiler_control",
    "no_reload_restart_or_production_deployment",
    "repository_ci_is_not_live_runtime_evidence",
    "unexplained_burner_start_is_not_domestic_hot_water",
    "one_requesting_zone_is_a_valid_heating_request",
    "software_lock_maximum_is_ten_minutes",
    "hard_lockout_and_flow_v4_must_not_be_bypassed",
}


def parse_lock() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


class HerdrConsumerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.consumer = yaml.safe_load(CONSUMER.read_text(encoding="utf-8"))
        cls.lock = parse_lock()

    def test_immutable_pin_matches_lock_file(self):
        herdr = self.consumer["herdr"]
        self.assertEqual(self.lock["repository"], f"https://github.com/{herdr['repository']}")
        self.assertEqual(self.lock["ref"], herdr["ref"])
        self.assertEqual(self.lock["commit"], herdr["commit"])
        self.assertEqual(self.lock["config_schema"], str(self.consumer["schema_version"]))

    def test_heating_policy_is_fail_closed(self):
        self.assertEqual(self.consumer["consumer"], "heating")
        self.assertEqual(self.consumer["policy_profile"], "heating-safe-engineering")
        self.assertFalse(self.consumer["inheritance"]["child_may_expand_parent_permissions"])

    def test_required_safety_invariants_are_explicit(self):
        self.assertEqual(set(self.consumer["hard_invariants"]), EXPECTED_INVARIANTS)


if __name__ == "__main__":
    unittest.main()
