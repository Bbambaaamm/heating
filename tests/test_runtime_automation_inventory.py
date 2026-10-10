"""Runtime HA automation inventory and single-owner safety regressions.

The snapshots record only source configurations and intended ON/OFF states.
These tests never command a real boiler, MQTT or Zigbee device.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


def normalize(cfg):
    result = dict(cfg)
    for source, target in (
        ("triggers", "trigger"),
        ("conditions", "condition"),
        ("actions", "action"),
    ):
        if source in result:
            if target in result:
                raise AssertionError(f"Duplicate keys {source}/{target}")
            result[target] = result.pop(source)
    result.pop("initial_state", None)
    return result


class HeatingRuntimeSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.automations = yaml.safe_load((ROOT / "automations.yaml").read_text(encoding="utf-8"))
        cls.by_id = {str(a["id"]): a for a in cls.automations}
        cls.pkg = yaml.safe_load((ROOT / "heating/control/kotel_control.yaml").read_text(encoding="utf-8"))
        cls.bp = yaml.load(
            (ROOT / "blueprints/automation/heating/smart_zone_schedule.yaml").read_text(encoding="utf-8"),
            Loader=BlueprintLoader,
        )
        cls.snapshots = []
        for path in sorted((ROOT / "docs").glob("runtime-automations-20261009-part*.json")):
            cls.snapshots.extend(json.loads(path.read_text(encoding="utf-8"))["objects"])

    def test_all_40_runtime_automation_ids_unique(self):
        self.assertEqual(len(self.automations), 40)
        self.assertEqual(len(self.by_id), 40)
        self.assertEqual(len(self.snapshots), 28)
        self.assertEqual(len({s["id"] for s in self.snapshots}), 28)
        # Preserve the historical snapshot; only blueprint sources and the new
        # shared presence source and independently tested guard are outside it.
        blueprints = {str(a["id"]) for a in self.automations if "use_blueprint" in a}
        self.assertEqual(len(blueprints), 10)
        self.assertEqual(
            set(self.by_id).difference(s["id"] for s in self.snapshots),
            blueprints | {"1771525903912", "heating_v4_relay_lockout_guard"},
        )

    def test_live_storage_objects_match_exact_api_snapshot(self):
        for snapshot in self.snapshots:
            with self.subTest(id=snapshot["id"]):
                self.assertIn(snapshot["id"], self.by_id)
                actual = self.by_id[snapshot["id"]]
                self.assertEqual(normalize(actual), normalize(snapshot["config"]))
                self.assertEqual(actual["initial_state"], snapshot["state"] == "on")

    def test_disabled_legacy_owners_never_activate_on_restart(self):
        ids = {
            "1790189552180", "1790189679088",
            "heating_flow_relief_fault_recovery_reconciler_v2",
            "heating_flow_relief_timeout_guard",
            "heating_observation_fault_capture_20260920",
            "heating_observation_until_fault_20260920",
            "heating_trv_test_timeout_20260920",
            "1789741778892",
            "heating_boiler_low_flow_hard_guard",
        }
        for ident in ids:
            with self.subTest(automation=ident):
                self.assertFalse(self.by_id[ident]["initial_state"])

    def test_single_active_flow_v4_and_disabled_legacy_package_start(self):
        self.assertTrue(self.by_id["1790189620167"]["initial_state"])
        self.assertTrue(self.by_id["1791376426962"]["initial_state"])
        start = next(a for a in self.pkg["automation"] if a["id"] == "kotel_turn_on_by_policy")
        self.assertIs(start["initial_state"], False)

    def test_only_one_tuv_interlock_owner(self):
        self.assertEqual(
            [a["id"] for a in self.pkg["automation"]],
            ["kotel_turn_on_by_policy", "kotel_turn_off_by_policy"],
        )
        tuv = self.by_id["1791310763182"]
        self.assertTrue(tuv["initial_state"])
        self.assertIn("switch.turn_off", [
            x.get("action") for x in tuv["action"] if isinstance(x, dict)
        ])
        sensors = {"binary_sensor.boiler_ww3wayvalve",
                   "binary_sensor.boiler_wwcharging",
                   "binary_sensor.boiler_tapwateractive"}
        self.assertEqual(set(tuv["trigger"][0]["entity_id"]), sensors)
        self.assertEqual(tuv["trigger"][0]["to"], "on")
        self.assertEqual(tuv["mode"], "restart")
        self.assertTrue(any(
            x.get("entity_id") == "switch.kotel_rele_spinac"
            and x.get("state") == "on"
            for x in tuv["condition"]
        ))

    def test_live_blueprint_mode_and_bounded_queue(self):
        self.assertEqual(self.bp["mode"], "queued")
        self.assertEqual(self.bp["max"], 20)
        self.assertEqual(self.bp["max_exceeded"], "warning")
        self.assertIs(self.bp["initial_state"], True)
        self.assertEqual(self.bp["blueprint"]["domain"], "automation")

    def test_manual_override_and_stale_decision_guard_remain(self):
        source = (ROOT / "blueprints/automation/heating/smart_zone_schedule.yaml").read_text(encoding="utf-8")
        self.assertIn("is_user_action", source)
        self.assertIn("is_internal_climate_change", source)
        self.assertIn("fallback_inputs", source)
        self.assertIn("central_dispatch_enabled", source)
        self.assertIn("not in_window", source)
        self.assertIn("manual_override_boolean", source)
        self.assertIn("states('input_select.topny_rezim')", source)

    def test_no_v4_direct_relay_on_before_policy_gate(self):
        v4 = self.by_id["1790189620167"]
        start = self.by_id["1791376426962"]
        self.assertNotIn("switch.turn_on", [
            node.get("action") for node in self._walk(v4["action"])
            if isinstance(node, dict)
        ])
        self.assertIn("switch.turn_on", [
            node.get("action") for node in self._walk(start["action"])
            if isinstance(node, dict)
        ])
        self.assertTrue(any(
            node.get("condition") == "state"
            and node.get("entity_id") == "input_select.heating_flow_state_v4"
            and node.get("state") == "NORMAL"
            for node in self._walk(start["action"])
            if isinstance(node, dict)
        ))

    @staticmethod
    def _walk(node):
        if isinstance(node, dict):
            yield node
            for val in node.values():
                yield from HeatingRuntimeSyncTests._walk(val)
        elif isinstance(node, list):
            for val in node:
                yield from HeatingRuntimeSyncTests._walk(val)


if __name__ == "__main__":
    unittest.main()
