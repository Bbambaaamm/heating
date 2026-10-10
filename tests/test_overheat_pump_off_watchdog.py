"""Passive watchdog regression: residual boiler heat with EMS pump OFF.

No burner, relay, thermostat or pump is controlled by this alarm.
The test consumes the exact storage-managed watchdog mirror in automations.yaml.
"""
from pathlib import Path
import json
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
ID="1791542912666"
ENTITY="automation.topeni_watchdog_dostupnosti_a_teplot_kotle_zivy"


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for val in obj.values():
            yield from walk(val)
    elif isinstance(obj,list):
        for val in obj:
            yield from walk(val)


class PumpOffHotWatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        autos=yaml.safe_load((ROOT/"automations.yaml").read_text(encoding="utf-8"))
        cls.auto=next(a for a in autos if str(a["id"])==ID)
        cls.runtime=json.loads((ROOT/"docs/runtime-automations-20261009-part2.json").read_text(encoding="utf-8"))
        cls.snapshot=json.loads((ROOT/"docs/live-storage-snapshot-2026-10-09.json").read_text(encoding="utf-8"))

    def test_passive_overheat_triggers_and_limited_push(self):
        cfg=self.auto
        self.assertTrue(cfg["initial_state"])
        self.assertEqual(cfg["mode"],"restart")
        alarm=next(t for t in cfg["trigger"] if t.get("id")=="hot_pump_off")
        self.assertEqual(alarm["entity_id"],"sensor.boiler_heatblock")
        self.assertGreaterEqual(alarm["above"],80)
        self.assertGreaterEqual(alarm["for"]["seconds"],10)
        pump=next(t for t in cfg["trigger"] if t.get("id")=="pump_stopped")
        self.assertEqual(pump["entity_id"],"binary_sensor.boiler_heatingpump")
        self.assertEqual(pump["to"],"off")
        self.assertGreaterEqual(pump["for"]["seconds"],10)
        self.assertIn("periodic",{t.get("id") for t in cfg["trigger"]})
        branch=cfg["action"][-1]
        self.assertEqual(branch["if"],[
            {"condition":"numeric_state","entity_id":"sensor.boiler_heatblock","above":80},
            {"condition":"state","entity_id":"binary_sensor.boiler_heatingpump","state":"off"}
        ])
        event_gate=branch["then"][1]["if"][0]
        self.assertEqual(event_gate["condition"],"trigger")
        self.assertEqual(set(event_gate["id"]),{"hot_pump_off","pump_stopped"})
        self.assertNotIn("periodic",event_gate["id"])

    def test_overheat_watchdog_cannot_actuate_boiler_or_trvs(self):
        branch=self.auto["action"][-1]
        actions=[d.get("action") for d in walk(branch) if isinstance(d,dict) and "action" in d]
        self.assertEqual(set(actions),{"persistent_notification.create","notify.mobile_app_sm_s938b"})
        self.assertEqual(len(actions),2)
        self.assertFalse(any(x and x.startswith(("switch.","climate.","input_boolean.","input_select.")) for x in actions))
        self.assertEqual(branch["then"][0]["data"]["notification_id"],"heating_hot_no_pump")
        self.assertEqual(self.auto["action"][0]["if"][1]["entity_id"],"binary_sensor.boiler_burngas")
        self.assertEqual(self.auto["action"][0]["if"][1]["state"],"on")
        self.assertIn("fault_2965",{t.get("id") for t in self.auto["trigger"]})

    def test_git_yaml_matches_live_snapshot_pending_hash(self):
        snap=self.snapshot["objects"][ENTITY]
        inventory=next(x for x in self.runtime["objects"] if x["id"]==ID)
        normalize=lambda cfg:{("triggers" if k=="trigger" else "actions" if k=="action" else "conditions" if k=="condition" else k):v for k,v in cfg.items() if k!="initial_state"}
        self.assertEqual(normalize(self.auto),snap["config"])
        self.assertEqual(normalize(self.auto),inventory["config"])
        self.assertEqual(snap["config_hash"],inventory["config_hash"])


if __name__=="__main__":
    unittest.main()
