"""Native HA regressions for cooling during Flow V4 emergency opening.

All temperatures, events and acknowledgements below are synthetic. The harness
uses fake services and never contacts HA, EMS, MQTT or a physical device.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import unittest

import test_flow_v4_opening_runtime as opening
import test_heating_runtime as runtime

FIXTURE = "heating/control/flow_v4_cooled_opening.yaml"
OLD_EVENTS = "['reconcile', 'paths_confirmed']"
NEW_EVENTS = "['reconcile', 'paths_confirmed', 'cooled']"
Harness = opening.FlowV4OpeningRuntimeTests


class FlowV4CooledRuntimeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = Harness.asyncSetUp
    asyncTearDown = Harness.asyncTearDown
    state = Harness.state
    start_and_block = Harness.start_and_block
    assert_no_boiler_enable = Harness.assert_no_boiler_enable

    async def load_flow(self, *, original=False, guard_only=False):
        self.assertFalse(guard_only)
        cfg = deepcopy(runtime.read(FIXTURE)[0])
        if original:
            text = cfg["condition"][0]["value_template"]
            self.assertEqual(text.count(NEW_EVENTS), 1)
            cfg["condition"][0]["value_template"] = text.replace(NEW_EVENTS, OLD_EVENTS)
        # Only shorten the non-safety inter-batch delay, as in the existing
        # harness. The cooling trigger and all hold/restore gates stay native.
        cfg["action"][3]["then"][16]["delay"] = {"milliseconds": 2}
        cfg["action"][1]["then"][-1]["then"][5]["delay"] = {"milliseconds": 2}
        self.second_batch = cfg["action"][3]["then"][18]["target"]["entity_id"]
        await self.h.load_automations([cfg])
        self.automation_entity = self.h.hass.states.async_all("automation")[0].entity_id

    async def block_before_first_batch(self, *, original=False):
        # Simulate the first relay-off acknowledgement still being in flight
        # when the temperature crosses the native cooling threshold.
        self.release.set()
        self.off_entered = asyncio.Event()
        self.off_release = asyncio.Event()
        self.off_cancelled = asyncio.Event()
        first = True

        async def slow_first_off(call):
            nonlocal first
            await self.h.service(call)
            if first:
                first = False
                self.off_entered.set()
                try:
                    await self.off_release.wait()
                except asyncio.CancelledError:
                    self.off_cancelled.set()
                    raise

        self.h.hass.services.async_register("switch", "turn_off", slow_first_off)
        await self.load_flow(original=original)
        self.h.hass.bus.async_fire("heating_flow_v4_force_emergency")
        await asyncio.wait_for(self.off_entered.wait(), 3)
        self.assertEqual(self.state(opening.FLOW), "EMERGENCY_COOLING")
        self.assertEqual(self.opening_calls, [])
        self.assert_no_boiler_enable()

    def cross_cooling_threshold(self):
        self.h.set("sensor.boiler_heatblock", "50")

    async def assert_all_targets_open(self):
        for zone in runtime.ZONES:
            self.assertEqual(
                self.h.hass.states.get(f"climate.{zone}").attributes["temperature"], 29
            )
        self.assert_no_boiler_enable()

    async def test_previous_guard_cooling_cancels_before_first_target_batch(self):
        await self.block_before_first_batch(original=True)
        try:
            self.cross_cooling_threshold()
            await asyncio.wait_for(self.off_cancelled.wait(), 3)
        finally:
            self.off_release.set()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.opening_calls, [])
        self.assert_no_boiler_enable()

    async def test_cooling_preserves_opening_before_first_target_batch(self):
        await self.block_before_first_batch()
        try:
            self.cross_cooling_threshold()
            await asyncio.sleep(0.04)
            self.assertFalse(self.off_cancelled.is_set())
            self.assertEqual(self.opening_calls, [])
            self.assertEqual(self.state(opening.FLOW), "EMERGENCY_COOLING")
            self.assertFalse(self.restore_called.is_set())
        finally:
            self.off_release.set()
        await self.h.hass.async_block_till_done()
        await self.assert_all_targets_open()

    async def test_previous_guard_cooling_cancels_second_target_batch(self):
        await self.start_and_block(original=True)
        self.cross_cooling_threshold()
        await asyncio.wait_for(self.cancelled.wait(), 3)
        self.release.set()
        await self.h.hass.async_block_till_done()
        for entity in self.second_batch:
            self.assertEqual(self.h.hass.states.get(entity).attributes["temperature"], 18)
        self.assert_no_boiler_enable()

    async def test_cooling_preserves_second_batch_and_latches_confirmation(self):
        await self.start_and_block()
        self.cross_cooling_threshold()
        self.h.set(opening.CONFIRMED, "on")
        await asyncio.sleep(0.04)
        self.assertFalse(self.cancelled.is_set())
        self.assertFalse(self.restore_called.is_set())
        self.release.set()
        await self.h.hass.async_block_till_done()
        await self.assert_all_targets_open()
        self.assertEqual(self.state("input_boolean.heating_flow_paths_verified_v4"), "on")

    async def test_startup_cooling_preserves_both_batches(self):
        await self.start_and_block(startup=True)
        self.cross_cooling_threshold()
        await asyncio.sleep(0.04)
        self.assertFalse(self.cancelled.is_set())
        self.release.set()
        await self.h.hass.async_block_till_done()
        await self.assert_all_targets_open()

    # Retest the unchanged native fault preemption and idle cooling handoff
    # against this exact standalone fixture rather than the historical root.
    test_native_fault_still_preempts = Harness.test_native_fault_still_preempts_busy_opening_and_keeps_relay_off
    test_idle_cooling_and_restoration_still_run = Harness.test_idle_progress_and_internal_restoring_handoff_still_run

    async def test_hard_lockout_is_not_cleared_by_idle_cooling(self):
        self.release.set()
        self.h.set(opening.FLOW, "HARD_LOCKOUT")
        self.h.set("input_boolean.heating_flow_relief_lockout", "on")
        self.h.set(opening.RELAY, "off")
        await self.load_flow()
        self.cross_cooling_threshold()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(opening.FLOW), "HARD_LOCKOUT")
        self.assertEqual(self.state("input_boolean.heating_flow_relief_lockout"), "on")
        self.assertFalse(self.restore_called.is_set())
        self.assert_no_boiler_enable()


class FlowV4CooledSourceBoundaryTests(unittest.TestCase):
    def test_fixture_only_extends_busy_progress_guard(self):
        fixture = deepcopy(runtime.read(FIXTURE)[0])
        public = next(a for a in runtime.read("automations.yaml")
                      if str(a["id"]) == "1790189620167")
        text = fixture["condition"][0]["value_template"]
        self.assertEqual(text.count(NEW_EVENTS), 1)
        fixture["condition"][0]["value_template"] = text.replace(NEW_EVENTS, OLD_EVENTS)
        self.assertEqual(fixture, public)

    def test_progress_guard_uses_busy_count_and_keeps_restart_mode(self):
        fixture = runtime.read(FIXTURE)[0]
        self.assertEqual(fixture["mode"], "restart")
        condition = fixture["condition"][0]["value_template"]
        self.assertIn("EMERGENCY_COOLING", condition)
        self.assertIn("this.attributes.current", condition)
        self.assertIn("> 0", condition)
        self.assertNotIn("2964", condition)


if __name__ == "__main__":
    unittest.main()
