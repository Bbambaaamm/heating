"""Isolated thermal cutoff candidate; public root remains the original owner.

No physical devices or production HA are accessed. Inherit the existing safety
and recovery regressions, and add temperature/restart cases for this standalone
candidate. The main automations.yaml is intentionally not changed by this PR.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy

from homeassistant.components.automation.config import PLATFORM_SCHEMA
import test_heating_runtime as runtime
import test_v4_lockout_guard_runtime as original

RELAY = original.RELAY
FLOW = original.FLOW
AUTOMATIONS = original.AUTOMATIONS


class V4RelayThermalGuardRuntimeTests(original.V4RelayLockoutGuardRuntimeTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.h.set("sensor.boiler_heatblock", "25")

    def guard(self):
        return deepcopy(runtime.read("tests/fixtures/v4_relay_thermal_guard.yaml"))

    async def test_root_has_one_guard_owner_and_only_relay_off_action(self):
        cfg = self.guard()
        root = runtime.read("configuration.yaml")
        matches = [a for a in root["automation"] if str(a.get("id")) == original.GUARD_ID]
        self.assertEqual(len(matches), 1)
        # A candidate fixture must not imply that the published root is deployed.
        self.assertEqual(matches[0], runtime.read(original.GUARD_FIXTURE))
        self.assertEqual(cfg["id"], matches[0]["id"])
        self.assertEqual(cfg["action"], matches[0]["action"])
        self.assertEqual(cfg["action"], [{"action":"switch.turn_off", "target":{"entity_id":RELAY}}])
        PLATFORM_SCHEMA(deepcopy(cfg))
        self.assertTrue(cfg["initial_state"])
        await self.h.load_automations([cfg])
        self.assertEqual(self.h.hass.states.async_all("automation")[0].state, "on")

    async def test_short_hot_spike_stops_running_relay_without_dwell(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        before = self.room_and_control_snapshot()
        self.h.set("sensor.boiler_heatblock", "73")
        # No wall-clock sleep, numeric-state dwell or Flow emergency is needed.
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.room_and_control_snapshot(), before)
        self.h.set("sensor.boiler_heatblock", "71")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(len(self.h.writes("switch", "turn_off")), 1)
        self.assertTrue(all(call[:2] == ("switch", "turn_off") for call in self.h.calls))

    async def test_exact_start_temperature_boundary_also_blocks_running_relay(self):
        await self.h.load_automations([self.guard()])
        self.h.set("sensor.boiler_heatblock", "71.9")
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.assertEqual(self.h.calls, [])
        self.h.set("sensor.boiler_heatblock", "72")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_hot_foreign_on_and_missing_or_invalid_temperature_fail_closed(self):
        await self.h.load_automations([self.guard()])
        for temperature in ("72", "73", "unknown", "unavailable", "invalid", "nan", "inf", "-inf", None):
            with self.subTest(temperature=temperature):
                if temperature is None:
                    self.h.hass.states.async_remove("sensor.boiler_heatblock")
                else:
                    self.h.set("sensor.boiler_heatblock", temperature)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_temperature_outage_stops_existing_request_and_return_does_not_restart(self):
        await self.h.load_automations([self.guard()])
        for temperature in ("unknown", "unavailable", "invalid", "nan", "inf"):
            with self.subTest(temperature=temperature):
                self.h.set("sensor.boiler_heatblock", "25")
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "on")
                self.h.set("sensor.boiler_heatblock", temperature)
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
                self.h.set("sensor.boiler_heatblock", "25")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_startup_reconciles_hot_restored_relay_in_normal(self):
        self.h.set("sensor.boiler_heatblock", "73")
        self.h.set(RELAY, "on")
        await self.h.load_automations([self.guard()], startup=True)
        await self.h.hass.async_start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(FLOW), "NORMAL")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_reload_reconciles_hot_existing_relay_in_normal(self):
        self.h.set("sensor.boiler_heatblock", "73")
        self.h.set(RELAY, "on")
        await self.h.load_automations([self.guard()])
        self.h.hass.bus.async_fire("automation_reloaded")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(FLOW), "NORMAL")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_safe_temperature_changes_and_attribute_reports_leave_request_on(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        for temperature in ("26", "30", "71.9"):
            self.h.set("sensor.boiler_heatblock", temperature)
            await self.h.hass.async_block_till_done()
            self.assertEqual(self.state(RELAY), "on")
        self.h.set("sensor.boiler_heatblock", "71.9", diagnostic_report=1)
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.h.calls, [])

    async def test_cooling_requires_existing_policy_delay_and_all_restart_guards(self):
        self.h.boiler_inputs(requested=True, relay="on")
        for entity, state in {
            "input_boolean.heating_service_mode": "off",
            "input_boolean.heating_fault_recovery_pending": "off",
            "binary_sensor.heating_boiler_fault_clear": "on",
            "sensor.system_bus_status": "connected",
        }.items():
            self.h.set(entity, state)
        start = deepcopy(next(
            row for row in runtime.read(AUTOMATIONS)
            if str(row["id"]) == "1791376426962"
        ))
        for step in start["action"]:
            if "delay" in step:
                step["delay"] = {"milliseconds": 160}
        await self.h.load_automations([self.guard(), start])
        self.h.set("sensor.boiler_heatblock", "73")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set("sensor.boiler_heatblock", "25")
        await asyncio.sleep(0.07)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set("sensor.system_bus_status", "disconnected")
        await asyncio.sleep(0.18)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set("sensor.system_bus_status", "connected")
        await asyncio.sleep(0.07)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.13)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.assertEqual(self.state(RELAY), "on")


