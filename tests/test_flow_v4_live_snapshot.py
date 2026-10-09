"""Offline structural regression checks for the live HA Flow V4 storage snapshot.

These checks intentionally do not command the boiler or claim to measure real water flow.
The JSON is an audit snapshot, not a package to load into a running HA instance.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest


SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "live-storage-snapshot-2026-10-09-v4.json"
)


def all_dicts(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from all_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from all_dicts(nested)


def is_action(action, name, target=None):
    return (
        isinstance(action, dict)
        and action.get("action") == name
        and (target is None or action.get("target", {}).get("entity_id") == target)
    )


class FlowV4LiveSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        objects = cls.snapshot["objects"]
        cls.flow = objects["automation.topeni_flow_relief_pred_restartem_horaku"]["config"]
        cls.ticker = objects["automation.topeni_v4_periodicka_kontrola_pouze_nouzoveho_chlazeni"]["config"]
        cls.start = objects["automation.kotel_v4_bezpecny_start_podle_politiky"]["config"]
        cls.restore = objects["script.heating_restore_schedule_after_service"]["config"]

    def test_every_safety_trigger_is_preserved(self):
        trigger_ids = {x.get("id") for x in self.flow["triggers"]}
        for necessary in (
            "heatblock_72",
            "fault_2964", "fault_2965", "fault_2966", "fault_2967",
            "force_emergency", "cooled", "paths_confirmed",
            "ha_start", "automation_reload", "reconcile",
            "legacy_reenabled", "service_attempt",
        ):
            with self.subTest(trigger=necessary):
                self.assertIn(necessary, trigger_ids)

    def test_periodic_emergency_tick_does_not_cancel_restoring(self):
        self.assertEqual(self.flow["mode"], "restart")
        self.assertNotIn("minute", [t.get("id") for t in self.flow["triggers"]])
        self.assertFalse(any(t.get("trigger") == "time_pattern" for t in self.flow["triggers"]))
        self.assertEqual(self.ticker["mode"], "single")
        self.assertEqual(
            self.ticker["triggers"],
            [{"trigger": "time_pattern", "minutes": "/1"}],
        )
        self.assertIn(
            {
                "condition": "state",
                "entity_id": "input_select.heating_flow_state_v4",
                "state": "EMERGENCY_COOLING",
            },
            self.ticker["conditions"],
        )
        self.assertEqual(
            self.ticker["actions"],
            [{
                "event": "heating_flow_v4_reconcile",
                "event_data": {"source": "emergency_only_periodic_tick"},
            }],
        )

    def test_emergency_turns_off_master_and_relay_before_opening_zones(self):
        sequence = self.flow["actions"][3]["then"]
        self.assertLess(
            next(i for i, x in enumerate(sequence) if is_action(x, "switch.turn_off", "switch.kotel_rele_spinac")),
            next(i for i, x in enumerate(sequence) if is_action(x, "climate.set_temperature")),
        )
        self.assertLess(
            next(i for i, x in enumerate(sequence) if is_action(x, "input_boolean.turn_off", "input_boolean.topny_system_enable")),
            next(i for i, x in enumerate(sequence) if is_action(x, "climate.set_temperature")),
        )

    def test_emergency_waits_for_confirmed_paths_or_locks_out(self):
        branch = self.flow["actions"][5]["then"]
        timeout = branch[3]
        self.assertIn("elapsed >= 120", timeout["if"][0]["value_template"])
        self.assertTrue(any(
            is_action(x, "input_boolean.turn_on", "input_boolean.heating_flow_relief_lockout")
            for x in timeout["then"]
        ))
        transition = branch[4]
        self.assertIn(
            {"condition": "numeric_state", "entity_id": "sensor.boiler_heatblock", "below": 60},
            transition["if"],
        )
        self.assertIn(
            {"condition": "state", "entity_id": "binary_sensor.boiler_burngas", "state": "off"},
            transition["if"],
        )
        path_gate = next(x for x in transition["if"] if x.get("condition") == "or")
        self.assertIn(
            {"condition": "state", "entity_id": "input_boolean.heating_flow_paths_verified_v4", "state": "on"},
            path_gate["conditions"],
        )
        self.assertIn(
            {"condition": "state", "entity_id": "input_boolean.heating_flow_relief_lockout", "state": "on"},
            path_gate["conditions"],
        )

    def test_restoring_verifies_zone_targets_ems_fault_cooling_and_paths(self):
        restoring = self.flow["actions"][6]["then"]
        self.assertTrue(any(is_action(x, "script.heating_restore_schedule_after_service") for x in restoring))
        success = restoring[6]["choose"][0]
        conds = success["conditions"]
        for expected in [
            {"condition": "state", "entity_id": "input_boolean.heating_restore_verified", "state": "on"},
            {"condition": "state", "entity_id": "input_boolean.heating_flow_relief_lockout", "state": "off"},
            {"condition": "state", "entity_id": "input_boolean.heating_flow_paths_verified_v4", "state": "on"},
            {"condition": "state", "entity_id": "binary_sensor.heating_boiler_fault_clear", "state": "on"},
            {"condition": "state", "entity_id": "sensor.system_bus_status", "state": "connected"},
            {"condition": "state", "entity_id": "binary_sensor.boiler_burngas", "state": "off"},
            {"condition": "numeric_state", "entity_id": "sensor.boiler_heatblock", "below": 60},
        ]:
            with self.subTest(condition=expected):
                self.assertIn(expected, conds)

    def test_success_clears_session_path_proof_after_normal_transition(self):
        success = self.flow["actions"][6]["then"][6]["choose"][0]["sequence"]
        to_normal = next(i for i, x in enumerate(success) if (
            is_action(x, "input_select.select_option", "input_select.heating_flow_state_v4")
            and x.get("data", {}).get("option") == "NORMAL"
        ))
        clear = next(i for i, x in enumerate(success) if (
            is_action(x, "input_boolean.turn_off", "input_boolean.heating_flow_paths_verified_v4")
        ))
        self.assertGreater(clear, to_normal)

    def test_hard_lockout_keeps_boiler_off(self):
        actions = self.flow["actions"][7]["then"]
        self.assertTrue(any(is_action(x, "switch.turn_off", "switch.kotel_rele_spinac") for x in actions))
        self.assertTrue(any(is_action(x, "input_boolean.turn_off", "input_boolean.topny_system_enable") for x in actions))

    def test_v4_never_turns_on_boiler_relay_directly(self):
        self.assertFalse(any(
            is_action(x, "switch.turn_on", "switch.kotel_rele_spinac")
            for x in all_dicts(self.flow["actions"])
        ))

    def test_start_policy_checks_lockout_tuv_and_enforces_delay(self):
        actions = self.start["actions"]
        for eid, state in [
            ("binary_sensor.kotel_should_be_on", "on"),
            ("input_boolean.topny_system_enable", "on"),
            ("input_select.heating_flow_state_v4", "NORMAL"),
            ("input_boolean.heating_flow_relief_lockout", "off"),
            ("input_boolean.heating_service_mode", "off"),
            ("binary_sensor.boiler_ww3wayvalve", "off"),
            ("binary_sensor.boiler_wwcharging", "off"),
            ("binary_sensor.boiler_tapwateractive", "off"),
        ]:
            self.assertGreaterEqual(
                sum(1 for x in actions if x.get("condition") == "state" and x.get("entity_id") == eid and (x.get("state") == state or (eid == "input_select.heating_flow_state_v4" and x.get("state") == state))),
                2,
                msg=eid,
            )
        delay = next(x["delay"] for x in actions if "delay" in x)
        self.assertIn("120", str(delay))
        self.assertTrue(is_action(actions[-1], "switch.turn_on", "switch.kotel_rele_spinac"))

    def test_demand_changes_only_restart_for_real_transitions(self):
        triggers = self.start["triggers"]
        demand = [x for x in triggers if x.get("entity_id") == "binary_sensor.kotel_should_be_on"]
        self.assertEqual({x.get("to") for x in demand}, {"on", "off"})
        self.assertFalse(any(
            isinstance(x.get("entity_id"), list)
            and "binary_sensor.kotel_should_be_on" in x["entity_id"]
            for x in triggers
        ))

    def test_restore_confirms_only_after_final_off_steps(self):
        sequence = self.restore["sequence"]
        verify = next(i for i,x in enumerate(sequence) if (
            "if" in x and any(
                is_action(y, "input_boolean.turn_on", "input_boolean.heating_restore_verified")
                for y in x.get("then", [])
            )
        ))
        self.assertTrue(any(is_action(x, "input_boolean.turn_off", "input_boolean.topny_system_enable") for x in sequence[:verify]))
        self.assertTrue(any(is_action(x, "switch.turn_off", "switch.kotel_rele_spinac") for x in sequence[:verify]))
        self.assertFalse(any(is_action(x, "input_boolean.turn_off", "input_boolean.topny_system_enable") for x in sequence[verify+1:]))

    def test_path_confirmation_is_not_physical_flow_measurement(self):
        opts = self.snapshot["objects"]["binary_sensor.heating_flow_relief_confirmed"]["options"]
        self.assertIn("pocet_kroku_motoru", opts["state"])
        self.assertIn("temperature", opts["state"])
        self.assertNotIn("sensor.boiler_pc0flow", opts["state"])


if __name__ == "__main__":
    unittest.main()
