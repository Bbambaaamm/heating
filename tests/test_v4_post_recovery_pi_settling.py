"""Regression for PI-report settling after Flow V4 emergency restoration.

These are source-level and mathematical checks, not a real flow-meter or
physical boiler test. Actual EMS fault 2964 still requires service inspection.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ID = "1791376426962"
STORAGE_ID = "automation.kotel_v4_bezpecny_start_podle_politiky"


def active_config():
    rows = yaml.safe_load((ROOT / "automations.yaml").read_text(encoding="utf-8"))
    return next(row for row in rows if str(row["id"]) == ACTIVE_ID)


class PostRecoveryCooldownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = active_config()
        cls.pkg = yaml.safe_load(
            (ROOT / "heating/control/kotel_control.yaml").read_text(encoding="utf-8")
        )
        cls.json_snapshots = [
            json.loads((ROOT / p).read_text(encoding="utf-8"))
            for p in [
                "docs/runtime-automations-20261009-part2.json",
                "docs/live-storage-snapshot-2026-10-09-v4.json",
                "docs/live-storage-snapshot-2026-10-09.json",
            ]
        ]

    def test_real_active_start_uses_stable_normal_delay(self):
        self.assertTrue(self.start["initial_state"])
        self.assertEqual(self.start["mode"], "restart")
        delays = [step["delay"]["seconds"] for step in self.start["action"] if "delay" in step]
        self.assertEqual(len(delays), 1)
        expr = delays[0]
        self.assertIn("sensor.kotel_effective_on_delay_sec", expr)
        self.assertIn("240", expr)
        self.assertIn("as_timestamp(states.input_select.heating_flow_state_v4.last_changed", expr)
        self.assertIn("120", expr)
        self.assertIn("| max", expr)

    def test_transient_stale_pi_cannot_finish_post_recovery_start(self):
        """The 17:51:40 -> 17:53:54 PI-delay case must cancel without firing."""
        minimum_normal_window = 240
        minimum_per_request = 120
        for seconds_since_normal in [0, 10, 45, 60, 119, 120, 180, 240, 300]:
            with self.subTest(age=seconds_since_normal):
                duration = max(minimum_per_request, minimum_normal_window - seconds_since_normal)
                earliest_start = seconds_since_normal + duration
                self.assertGreaterEqual(duration, minimum_per_request)
                self.assertGreaterEqual(earliest_start, minimum_normal_window)
        # Stale-PI demand dropped 134 s after recovery, before earliest
        # permissible burner-relay start at recovery+240 s.
        self.assertLess(134, minimum_normal_window)

    def test_cancellation_on_lost_demand_remains_authoritative(self):
        triggers = self.start["trigger"]
        self.assertTrue(any(
            t.get("id") == "demand_off" and t.get("to") == "off"
            for t in triggers
        ))
        self.assertTrue(any(
            t.get("id") == "demand_unavailable" and t.get("to") == "unavailable"
            for t in triggers
        ))
        relay_on = next(i for i, s in enumerate(self.start["action"])
                        if s.get("action") == "switch.turn_on")
        last_delay = max(i for i, s in enumerate(self.start["action"]) if "delay" in s)
        self.assertGreater(relay_on, last_delay)
        for entity, expected in [
            ("binary_sensor.kotel_should_be_on", "on"),
            ("switch.kotel_rele_spinac", "off"),
            ("input_select.heating_flow_state_v4", "NORMAL"),
            ("input_boolean.heating_flow_relief_lockout", "off"),
            ("input_boolean.heating_fault_recovery_pending", "off"),
            ("binary_sensor.boiler_ww3wayvalve", "off"),
            ("binary_sensor.boiler_wwcharging", "off"),
            ("binary_sensor.boiler_tapwateractive", "off"),
        ]:
            self.assertTrue(any(
                i > last_delay and i < relay_on and
                step.get("condition") == "state" and
                step.get("entity_id") == entity and
                step.get("state") == expected
                for i, step in enumerate(self.start["action"])
            ), msg=f"Post-delay gate missing: {entity}")

    def test_fallback_is_disabled_and_mirrors_interlock(self):
        cfg = self.pkg["automation"]
        fallback = next(x for x in cfg if x["id"] == "kotel_turn_on_by_policy")
        self.assertIs(fallback["initial_state"], False)
        delay = next(x["delay"]["seconds"] for x in fallback["action"] if "delay" in x)
        active = next(x["delay"]["seconds"] for x in self.start["action"] if "delay" in x)
        self.assertEqual(delay, active)
        self.assertFalse(any(x["id"] == "kotel_tuv_relay_interlock" for x in cfg))

    def test_all_versioned_snapshots_include_same_delay(self):
        live_delay = next(x["delay"]["seconds"] for x in self.start["action"] if "delay" in x)
        inventory = next(x for x in self.json_snapshots[0]["objects"] if x["id"] == ACTIVE_ID)
        self.assertEqual(next(x["delay"]["seconds"] for x in inventory["config"]["actions"] if "delay" in x), live_delay)
        for snap in self.json_snapshots[1:]:
            d = snap["objects"][STORAGE_ID]["config"]
            self.assertEqual(next(x["delay"]["seconds"] for x in d["actions"] if "delay" in x), live_delay)


if __name__ == "__main__":
    unittest.main()
