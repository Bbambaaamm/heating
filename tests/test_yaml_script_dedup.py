"""Regression guard: YAML packages and root scripts must not define the same script twice."""
from pathlib import Path
import json
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class YAMLScriptDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_scripts = yaml.safe_load((ROOT / "scripts.yaml").read_text(encoding="utf-8")) or {}
        cls.pkg = yaml.safe_load((ROOT / "heating/control/refactor_mode_schedule_override.yaml").read_text(encoding="utf-8"))
        cls.snapshot = json.loads((ROOT / "docs/live-storage-snapshot-2026-10-09-v4.json").read_text(encoding="utf-8"))

    def test_no_duplicate_central_zone_script(self):
        pkg_scripts = self.pkg["script"]
        self.assertEqual(set(self.root_scripts).intersection(pkg_scripts), set())
        self.assertIn("heating_apply_zone_target", pkg_scripts)
        self.assertNotIn("heating_apply_zone_target", self.root_scripts)

    def test_central_script_keeps_live_hydraulic_support(self):
        central = self.pkg["script"]["heating_apply_zone_target"]
        live_description = "Centrální aplikace cíle zóny. Respektuje aktivní hydraulickou podporu: pokud je zóna vybraná jako podpora ve Flow V4 NORMAL, běžný dispatch ji nesmí stáhnout pod 29 °C."
        self.assertEqual(central["description"], live_description)
        vars_with_guard = [
            action["variables"]["target_raw"]
            for action in central["sequence"]
            if isinstance(action, dict)
            and "target_raw" in action.get("variables", {})
        ]
        self.assertEqual(len(vars_with_guard), 1)
        target = vars_with_guard[0]
        self.assertIn("topeni_hydraulicka_podpurna_zona", target)
        self.assertIn("heating_flow_state_v4", target)
        self.assertIn("topny_system_enable", target)
        self.assertIn("[base | float(29), 29] | max", target)

    def test_root_recovery_script_matches_live_snapshot(self):
        expected = self.snapshot["objects"]["script.heating_restore_schedule_after_service"]["config"]
        self.assertEqual(self.root_scripts["heating_restore_schedule_after_service"], expected)
        sequence = expected["sequence"]
        self.assertTrue(any(
            s.get("action") == "switch.turn_off"
            and s.get("target", {}).get("entity_id") == "switch.kotel_rele_spinac"
            for s in sequence
        ))
        self.assertTrue(any(
            s.get("action") == "input_boolean.turn_off"
            and s.get("target", {}).get("entity_id") == "input_boolean.topny_system_enable"
            for s in sequence
        ))

    def test_yaml_source_keeps_one_authoritative_target_script(self):
        self.assertIn("script", self.pkg)
        self.assertEqual(
            self.pkg["script"]["heating_apply_zone_target"]["mode"], "queued"
        )
        self.assertGreaterEqual(
            self.pkg["script"]["heating_apply_zone_target"]["max"], 2
        )


if __name__ == "__main__":
    unittest.main()
