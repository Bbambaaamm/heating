"""Native HA regressions for concurrent progress events during Flow V4 opening.

Only fake service handlers and synthetic inputs are used. No real HA, MQTT,
EMS, relay or Zigbee device is accessed, and targets are not flow measurements.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_heating_runtime as runtime


FLOW = "input_select.heating_flow_state_v4"
RELAY = "switch.kotel_rele_spinac"
MASTER = "input_boolean.topny_system_enable"
CONFIRMED = "binary_sensor.heating_flow_relief_confirmed"


class FlowV4OpeningRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.boiler_inputs(relay="on")
        for zone in runtime.ZONES:
            self.h.set(f"sensor.{zone}_pocet_kroku_motoru", "1000")
        for entity, state in {
            FLOW: "NORMAL",
            "input_boolean.heating_service_mode": "off",
            "input_boolean.heating_flow_relief_lockout": "off",
            "input_boolean.heating_fault_recovery_pending": "off",
            "input_boolean.heating_restore_verified": "off",
            "input_boolean.heating_flow_paths_verified_v4": "off",
            "input_boolean.heating_flow_relief_mode": "off",
            "input_boolean.heating_flow_relief_resume_armed": "off",
            CONFIRMED: "off",
            "binary_sensor.heating_boiler_fault_clear": "on",
            "sensor.system_bus_status": "connected",
            "sensor.boiler_heatblock": "75",
            "binary_sensor.boiler_burngas": "off",
            "sensor.boiler_servicecodenumber": "203",
        }.items():
            self.h.set(entity, state)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.restore_called = asyncio.Event()
        self.second_batch = None
        self.opening_calls = []

        async def climate_service(call):
            entities = call.data.get("entity_id", [])
            if isinstance(entities, str):
                entities = [entities]
            if (call.service == "set_hvac_mode"
                    and "climate.prizemi_chodba_zachod" in entities):
                self.entered.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            # The shared fast fake handles one entity per call. Expand each
            # batch here so readback verifies all eight simulated targets.
            for entity in entities:
                await self.h.service(SimpleNamespace(
                    domain=call.domain, service=call.service,
                    data={**call.data, "entity_id": entity},
                    context=call.context,
                ))
                self.opening_calls.append((call.service, entity))

        for name in ("set_hvac_mode", "set_temperature"):
            self.h.hass.services.async_register("climate", name, climate_service)

        async def restore_service(call):
            self.restore_called.set()
            self.h.set("input_boolean.heating_restore_verified", "on")

        self.h.hass.services.async_register(
            "script", "heating_restore_schedule_after_service", restore_service
        )

    async def asyncTearDown(self):
        self.release.set()
        await self.h.asyncTearDown()

    def state(self, entity):
        return self.h.hass.states.get(entity).state

    async def load_flow(self, *, original=False, guard_only=False):
        cfg = deepcopy(next(
            a for a in runtime.read("automations.yaml")
            if str(a["id"]) == "1790189620167"
        ))
        if original:
            cfg["condition"] = []
        if original or guard_only:
            cfg["action"][1]["then"][-1]["then"].pop()
            cfg["action"][3]["then"].pop(19)
        # Scale only the inter-batch delay; conditions/triggers/services stay
        # the exact public source configuration.
        cfg["action"][3]["then"][16]["delay"] = {"milliseconds": 2}
        cfg["action"][1]["then"][-1]["then"][5]["delay"] = {"milliseconds": 2}
        self.second_batch = cfg["action"][3]["then"][18]["target"]["entity_id"]
        await self.h.load_automations([cfg])
        self.automation_entity = self.h.hass.states.async_all("automation")[0].entity_id

    async def start_and_block(self, *, original=False, guard_only=False, startup=False):
        if startup:
            self.h.set(FLOW, "EMERGENCY_COOLING")
        await self.load_flow(original=original, guard_only=guard_only)
        self.h.hass.bus.async_fire(
            "automation_reloaded" if startup else "heating_flow_v4_force_emergency"
        )
        await asyncio.wait_for(self.entered.wait(), 3)
        self.assertEqual(self.state(FLOW), "EMERGENCY_COOLING")
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(
            self.h.hass.states.get(self.automation_entity).attributes["current"], 1
        )

    def assert_no_boiler_enable(self):
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.assertEqual(self.state(RELAY), "off")

    async def test_original_periodic_event_cancels_before_second_target_batch(self):
        await self.start_and_block(original=True)
        self.h.hass.bus.async_fire(
            "heating_flow_v4_reconcile",
            {"source": "emergency_only_periodic_tick"},
        )
        await asyncio.wait_for(self.cancelled.wait(), 3)
        self.release.set()
        await self.h.hass.async_block_till_done()
        for entity in self.second_batch:
            self.assertEqual(self.h.hass.states.get(entity).attributes["temperature"], 18)
        self.assert_no_boiler_enable()

    async def assert_progress_does_not_cancel(self, event):
        await self.start_and_block()
        if event == "reconcile":
            self.h.hass.bus.async_fire(
                "heating_flow_v4_reconcile",
                {"source": "emergency_only_periodic_tick"},
            )
        else:
            self.h.set(CONFIRMED, "on")
        # The device handler deliberately stays blocked while HA evaluates the
        # competing event. Releasing it must still finish the original batch.
        await asyncio.sleep(0.04)
        self.assertFalse(self.cancelled.is_set())
        self.release.set()
        await self.h.hass.async_block_till_done()
        for zone in runtime.ZONES:
            self.assertEqual(
                self.h.hass.states.get(f"climate.{zone}").attributes["temperature"], 29
            )
        self.assertEqual(
            self.state("input_boolean.heating_flow_paths_verified_v4"),
            "on" if event == "paths_confirmed" else "off",
        )
        self.assert_no_boiler_enable()

    async def test_periodic_progress_preserves_both_opening_batches(self):
        await self.assert_progress_does_not_cancel("reconcile")

    async def test_path_confirmation_preserves_both_opening_batches(self):
        await self.assert_progress_does_not_cancel("paths_confirmed")

    async def test_guard_without_checkpoint_loses_busy_confirmation(self):
        await self.start_and_block(guard_only=True)
        self.h.set(CONFIRMED, "on")
        await asyncio.sleep(0.04)
        self.assertFalse(self.cancelled.is_set())
        self.release.set()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(CONFIRMED), "on")
        self.assertEqual(self.state("input_boolean.heating_flow_paths_verified_v4"), "off")
        self.assert_no_boiler_enable()

    async def test_startup_opening_preserves_confirmation_received_while_busy(self):
        await self.start_and_block(startup=True)
        self.h.set(CONFIRMED, "on")
        self.h.hass.bus.async_fire("heating_flow_v4_reconcile")
        await asyncio.sleep(0.04)
        self.assertFalse(self.cancelled.is_set())
        self.release.set()
        await self.h.hass.async_block_till_done()
        for zone in runtime.ZONES:
            self.assertEqual(
                self.h.hass.states.get(f"climate.{zone}").attributes["temperature"], 29
            )
        self.assertEqual(self.state("input_boolean.heating_flow_paths_verified_v4"), "on")
        self.assert_no_boiler_enable()

    async def test_native_fault_still_preempts_busy_opening_and_keeps_relay_off(self):
        await self.start_and_block()
        self.h.set("binary_sensor.heating_boiler_fault_clear", "off")
        self.h.set("sensor.boiler_servicecodenumber", "2965")
        await asyncio.wait_for(self.cancelled.wait(), 3)
        self.release.set()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "EMERGENCY_COOLING")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_boiler_enable()

    async def test_idle_progress_and_internal_restoring_handoff_still_run(self):
        self.release.set()
        await self.load_flow()
        self.h.hass.bus.async_fire("heating_flow_v4_force_emergency")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "EMERGENCY_COOLING")
        self.assertEqual(
            self.h.hass.states.get(self.automation_entity).attributes["current"], 0
        )
        self.h.set(CONFIRMED, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state("input_boolean.heating_flow_paths_verified_v4"), "on")
        self.h.set("sensor.boiler_heatblock", "50")
        await self.h.hass.async_block_till_done()
        await asyncio.wait_for(self.restore_called.wait(), 3)
        await self.h.hass.async_block_till_done()
        self.assertTrue(self.restore_called.is_set())
        self.assertEqual(self.state(FLOW), "NORMAL")
        self.assert_no_boiler_enable()


if __name__ == "__main__":
    unittest.main()
