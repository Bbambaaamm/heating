"""Compare HA Core queue and restart execution semantics with fake events.

This is an isolated concurrency probe, not a command to the real boiler.
The actual schedule blueprint is separately validated for queued/max=20
and manual/stale-command guards in test_runtime_automation_inventory.
"""
from __future__ import annotations

import asyncio
import unittest

import test_heating_runtime as runtime


class AutomationModeComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    async def test_queued_preserves_both_events_restart_cancels_first(self):
        self.h.set("input_boolean.mode_queued_test", "off")
        self.h.set("input_boolean.mode_restart_test", "off")
        configs = []
        for mode in ("queued", "restart"):
            entity = f"input_boolean.mode_{mode}_test"
            config = {
                "id": f"test_mode_{mode}",
                "alias": f"Simulated event ingest {mode}",
                "mode": mode,
                "trigger": [{"trigger": "state", "entity_id": entity}],
                "action": [
                    {"delay": {"milliseconds": 60}},
                    {"action": "logbook.log", "data": {
                        "name": f"mode_{mode}",
                        "message": "{{ trigger.to_state.state }}",
                    }},
                ],
            }
            if mode == "queued":
                config["max"] = 20
            configs.append(config)
        await self.h.load_automations(configs)
        for mode in ("queued", "restart"):
            self.h.set(f"input_boolean.mode_{mode}_test", "on")
        await asyncio.sleep(0.01)
        for mode in ("queued", "restart"):
            self.h.set(f"input_boolean.mode_{mode}_test", "off")
        await asyncio.sleep(0.19)
        await self.h.hass.async_block_till_done()
        calls = [c[2] for c in self.h.calls if c[:2] == ("logbook", "log")]
        queued = [x["message"] for x in calls if x.get("name") == "mode_queued"]
        restart = [x["message"] for x in calls if x.get("name") == "mode_restart"]
        self.assertEqual(queued, ["on", "off"])
        self.assertEqual(restart, ["off"])


if __name__ == "__main__":
    unittest.main()
