"""Regressions for the live 2026-10-09 boiler safety recovery and the versioned fallback.
This file intentionally does NOT modify or simulate physical HA devices.
"""
import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "docs" / "live-storage-snapshot-2026-10-09.json"
LEGACY = ROOT / "heating" / "control" / "kotel_control.yaml"


def objects():
    return json.loads(SNAP.read_text(encoding="utf-8"))["objects"]


def live(ident):
    return objects()[ident]["config"]


def each_action(item):
    if isinstance(item, dict):
        if "action" in item:
            yield item["action"]
        for value in item.values():
            yield from each_action(value)
    elif isinstance(item, list):
        for value in item:
            yield from each_action(value)


def requested_boilering(cool, burner_off, paths_confirmed, timed_out):
    """Truth table for the newly gated recovery transition, not a hardware model."""
    return cool and burner_off and (paths_confirmed or timed_out)


class LiveV4SafetySnapshotTests(unittest.TestCase):
    def test_recovery_waits_for_open_paths_or_full_timeout(self):
        v4 = live("automation.topeni_flow_relief_pred_restartem_horaku")
        emergency = v4["actions"][5]["then"]
        gate = emergency[4]["if"]
        self.assertEqual(gate[0]["entity_id"], "sensor.boiler_heatblock")
        self.assertEqual(gate[0]["below"], 60)
        self.assertEqual(gate[1]["entity_id"], "binary_sensor.boiler_burngas")
        self.assertEqual(gate[1]["state"], "off")
        or_gate = gate[2]
        self.assertEqual(or_gate["condition"], "or")
        self.assertEqual(
            {(c["entity_id"], c["state"]) for c in or_gate["conditions"]},
            {
                ("input_boolean.heating_flow_paths_verified_v4", "on"),
                ("input_boolean.heating_flow_relief_lockout", "on"),
            },
        )
        # Only the timeout action, not early cooling, can assert the lockout.
        timeout = emergency[3]
        self.assertIn("elapsed >= 120", timeout["if"][0]["value_template"])
        self.assertIn("input_boolean.heating_flow_relief_lockout",
                      str(timeout["then"]))
        self.assertFalse(requested_boilering(True, True, False, False))
        self.assertTrue(requested_boilering(True, True, True, False))
        self.assertTrue(requested_boilering(True, True, False, True))
        self.assertFalse(requested_boilering(False, True, True, False))
        self.assertFalse(requested_boilering(True, False, True, False))

    def test_critical_faults_block_relay_before_trv_opens(self):
        v4 = live("automation.topeni_flow_relief_pred_restartem_horaku")
        triggers = v4["triggers"]
        for fault in ["2964", "2965", "2966", "2967"]:
            self.assertTrue(any(t.get("entity_id") == "sensor.boiler_servicecodenumber"
                                and t.get("to") == fault for t in triggers))
        emergency = v4["actions"][3]["then"]
        actions = list(each_action(emergency))
        self.assertLess(actions.index("switch.turn_off"), actions.index("climate.set_temperature"))
        self.assertNotIn("switch.turn_on", list(each_action(v4)))

    def test_real_relay_start_retains_policy_and_delay(self):
        start = live("automation.kotel_v4_bezpecny_start_podle_politiky")
        self.assertEqual(start["mode"], "restart")
        demand = [t for t in start["triggers"]
                  if t.get("entity_id") == "binary_sensor.kotel_should_be_on"]
        self.assertEqual({t.get("to") for t in demand}, {"on", "off"})
        for t in start["triggers"]:
            group = t.get("entity_id", [])
            if isinstance(group, str):
                group = [group]
            if "binary_sensor.kotel_should_be_on" in group:
                self.assertIn(t.get("to"), ("on", "off"))
        acts = start["actions"]
        self.assertTrue(any("delay" in a and "120" in str(a["delay"]) for a in acts))
        self.assertGreaterEqual(sum(
            1 for a in acts if a.get("entity_id") == "input_boolean.topny_system_enable"
            and a.get("state") == "on"), 2)
        for ent in ["input_select.heating_flow_state_v4",
                    "input_boolean.heating_flow_relief_lockout",
                    "binary_sensor.boiler_ww3wayvalve"]:
            self.assertGreaterEqual(sum(1 for a in acts if a.get("entity_id") == ent), 2)

    def test_watchdog_is_notification_only(self):
        w = live("automation.topeni_watchdog_dostupnosti_a_teplot_kotle_zivy")
        allowed = {"persistent_notification.create", "persistent_notification.dismiss",
                   "notify.mobile_app_sm_s938b"}
        self.assertTrue(set(each_action(w)).issubset(allowed))
        ids = {t.get("id") for t in w["triggers"]}
        self.assertTrue({"hot", "lockout", "relay_stopped", "burn_stopped",
                         "bus_disconnect", "periodic", "start"}.issubset(ids))
        temp_trig = next(t for t in w["triggers"] if t.get("id") == "hot")
        self.assertEqual(temp_trig["above"], 69)


class GitFallbackPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.automations = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))["automation"]

    def test_old_enable_and_disable_policies_do_not_retrigger_on_attributes(self):
        for ident in ("kotel_turn_on_by_policy", "kotel_turn_off_by_policy"):
            policy = next(a for a in self.automations if a["id"] == ident)
            demand = []
            for t in policy["trigger"]:
                ids = t.get("entity_id", [])
                if isinstance(ids, str):
                    ids = [ids]
                if "binary_sensor.kotel_should_be_on" in ids:
                    self.assertEqual(ids, ["binary_sensor.kotel_should_be_on"])
                    self.assertIn(t.get("to"), ("on", "off"))
                    demand.append(t.get("to"))
            self.assertEqual(set(demand), {"on", "off"})


if __name__ == "__main__":
    unittest.main()
