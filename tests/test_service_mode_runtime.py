"""Exercise the deployed service-mode automations using HA and fake devices."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import unittest

from homeassistant.components.automation.config import PLATFORM_SCHEMA

import test_heating_runtime as runtime


SERVICE = "input_boolean.heating_service_mode"
RESTORE = "input_boolean.heating_service_restore_main_enable"
MASTER = "input_boolean.topny_system_enable"
RELAY = "switch.kotel_rele_spinac"
FAILSAFE = "heating/control/reliability_failsafe.yaml"
ROOT_IDS = {
    "1789741778892",
    "heating_service_mode_guard",
    "heating_service_mode_hard_guard",
    "heating_boiler_low_flow_hard_guard",
}


class ServiceModeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.set(SERVICE, "off")
        self.h.set(RESTORE, "off")
        self.h.set(RELAY, "on")

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def state(self, entity):
        return self.h.hass.states.get(entity).state

    async def load_service(self, include_low_flow=False, *, startup=False):
        ids = {"heating_service_mode_guard", "heating_service_mode_hard_guard"}
        if include_low_flow:
            ids.add("heating_boiler_low_flow_hard_guard")
        automations = [a for a in runtime.read("automations.yaml") if a["id"] in ids]
        automations.append(runtime.automation(FAILSAFE, "heating_service_mode_package_hard_guard"))
        if include_low_flow:
            automations.append(runtime.automation(FAILSAFE, "heating_boiler_low_flow_package_guard"))
        await self.h.load_automations(deepcopy(automations), startup=startup)
        for entity in self.h.hass.states.async_all("automation"):
            self.assertEqual(entity.state, "on", f"Automation was rejected or disabled: {entity.entity_id}")

    async def change_service(self, state):
        self.h.set(SERVICE, state)
        await self.h.hass.async_block_till_done()

    async def test_all_new_root_automations_validate_and_enable(self):
        automations = [a for a in runtime.read("automations.yaml") if a["id"] in ROOT_IDS]
        self.assertEqual(len(automations), len(ROOT_IDS))
        for a in automations:
            with self.subTest(automation_id=a["id"]):
                PLATFORM_SCHEMA(deepcopy(a))
        await self.h.load_automations(deepcopy(automations))
        for entity in self.h.hass.states.async_all("automation"):
            self.assertEqual(entity.state, "on", entity.entity_id)

    async def test_service_stops_relay_before_valves_and_restores_enabled_master(self):
        await self.load_service()
        await self.change_service("on")
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state(RESTORE), "on")
        self.assertEqual(self.h.calls[0][:2], ("switch", "turn_off"))
        for zone in runtime.ZONES:
            self.assertEqual(self.h.hass.states.get(f"climate.{zone}").attributes["temperature"], 29)
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "on")
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(RESTORE), "off")

    async def test_service_does_not_enable_previously_disabled_master(self):
        self.h.set(MASTER, "off")
        self.h.set(RESTORE, "on")  # A completed older service session is not reused.
        await self.load_service()
        await self.change_service("on")
        self.assertEqual(self.state(RESTORE), "off")
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state(RELAY), "off")

    async def assert_restored_service_preserves_master(self, previous):
        self.h.set(MASTER, "off")
        self.h.set(RESTORE, "on")
        if previous is None:
            self.h.hass.states.async_remove(SERVICE)
        else:
            self.h.set(SERVICE, previous)
        await self.load_service()
        await self.change_service("on")
        self.assertEqual(self.state(RESTORE), "on")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state(RELAY), "off")
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "on")

    async def test_unknown_to_on_preserves_saved_master(self):
        await self.assert_restored_service_preserves_master("unknown")

    async def test_unavailable_to_on_preserves_saved_master(self):
        await self.assert_restored_service_preserves_master("unavailable")

    async def test_newly_restored_entity_preserves_saved_master(self):
        await self.assert_restored_service_preserves_master(None)

    async def test_restored_off_does_not_resume_stale_session(self):
        self.h.set(SERVICE, "unknown")
        self.h.set(RESTORE, "on")
        self.h.set(MASTER, "off")
        self.h.set(RELAY, "off")
        await self.load_service()
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state(RELAY), "off")

    async def test_startup_in_service_preserves_saved_master(self):
        self.h.set(SERVICE, "on")
        self.h.set(RESTORE, "on")
        self.h.set(MASTER, "off")
        await self.load_service(startup=True)
        await self.h.hass.async_start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RESTORE), "on")
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "off")
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "on")

    async def test_independent_guard_acts_while_valve_command_is_blocked(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        stopped = asyncio.Event()
        probe_armed = False

        async def service(call):
            entities = call.data.get("entity_id", [])
            if isinstance(entities, str):
                entities = [entities]
            if call.domain == "climate" and "climate.1p_chodba" in entities:
                entered.set()
                await release.wait()
            await self.h.service(call)
            if probe_armed and self.state(RELAY) == "off" and self.state(MASTER) == "off":
                stopped.set()

        for domain, names in {
            "climate": ["set_hvac_mode", "set_temperature"],
            "switch": ["turn_off"],
            "input_boolean": ["turn_off"],
        }.items():
            for name in names:
                self.h.hass.services.async_register(domain, name, service)
        await self.load_service()
        try:
            self.h.set(SERVICE, "on")
            await asyncio.wait_for(entered.wait(), 3)
            probe_armed = True
            self.h.set(RELAY, "on")
            self.h.set(MASTER, "on")
            await asyncio.wait_for(stopped.wait(), 1)
            self.assertFalse(release.is_set())
            self.assertEqual(self.state(RELAY), "off")
            self.assertEqual(self.state(MASTER), "off")
        finally:
            release.set()
            await self.h.hass.async_block_till_done()

    async def test_low_flow_fault_does_not_restore_master_on_service_exit(self):
        self.h.set("sensor.boiler_servicecodenumber", "200")
        self.h.set("input_boolean.boost_now", "on")
        await self.load_service(include_low_flow=True)
        self.h.set("sensor.boiler_servicecodenumber", "2964")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(SERVICE), "on")
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state("input_boolean.boost_now"), "off")
        self.assertEqual(self.state(RESTORE), "off")
        await self.change_service("off")
        self.assertEqual(self.state(MASTER), "off")
        self.assertEqual(self.state(RELAY), "off")
