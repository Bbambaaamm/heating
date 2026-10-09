"""Exercise the ACTIVE V4 start policy in an isolated Home Assistant runtime.

No physical relays, EMS devices, Zigbee network or Home Assistant instance are accessed.
The 120-second real delay is reduced to 70ms for deterministic tests.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import unittest

import test_heating_runtime as runtime


class LiveV4StartRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.boiler_inputs(requested=False)
        self.h.set("input_select.heating_flow_state_v4", "NORMAL")
        self.h.set("input_boolean.heating_service_mode", "off")
        self.h.set("input_boolean.heating_flow_relief_lockout", "off")
        self.h.set("input_boolean.heating_fault_recovery_pending", "off")
        self.h.set("binary_sensor.heating_boiler_fault_clear", "on")
        self.h.set("sensor.system_bus_status", "connected")
        self.h.set("sensor.boiler_heatblock", "25")
        self.h.set("binary_sensor.boiler_burngas", "off")

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def live_start(self):
        a = deepcopy(next(
            row for row in runtime.read("automations.yaml")
            if str(row["id"]) == "1791376426962"
        ))
        self.assertTrue(a["initial_state"])
        for step in a["action"]:
            if "delay" in step:
                step["delay"] = {"milliseconds": 70}
        return a

    async def test_normal_demand_starts_after_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.03)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_tuv_path_blocks_and_then_full_delay_restarts(self):
        self.h.set("binary_sensor.boiler_ww3wayvalve", "on")
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.10)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set("binary_sensor.boiler_ww3wayvalve", "off")
        await asyncio.sleep(0.03)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_hard_lockout_and_service_always_block_start(self):
        self.h.set("input_select.heating_flow_state_v4", "HARD_LOCKOUT")
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.11)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set("input_select.heating_flow_state_v4", "NORMAL")
        self.h.set("input_boolean.heating_service_mode", "on")
        await asyncio.sleep(0.11)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_demand_attribute_only_updates_do_not_restart_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        for i in range(5):
            self.h.set("binary_sensor.kotel_should_be_on", "on", pi_report=i)
            await asyncio.sleep(0.02)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)


if __name__ == "__main__":
    unittest.main()
