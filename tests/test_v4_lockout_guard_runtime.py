"""Verify the independent V4 relay-OFF guard with isolated HA Core services.

The standalone candidate fixture is loaded unchanged. No production Home Assistant,
physical relay, EMS device or Zigbee network is accessed. The recovery test
loads the actual V4 automation and pauses a fake restore service so a foreign
relay ON can be observed while that recovery invocation remains in progress.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import unittest

from homeassistant.components.automation.config import PLATFORM_SCHEMA

import test_heating_runtime as runtime


AUTOMATIONS = "automations.yaml"
GUARD_FIXTURE = "tests/fixtures/v4_relay_lockout_guard.yaml"
GUARD_ID = "heating_v4_relay_lockout_guard"
V4_ID = "1790189620167"
RELAY = "switch.kotel_rele_spinac"
FLOW = "input_select.heating_flow_state_v4"
LOCKOUT = "input_boolean.heating_flow_relief_lockout"
MASTER = "input_boolean.topny_system_enable"


class V4RelayLockoutGuardRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.set(RELAY, "off")
        self.h.set(FLOW, "NORMAL")
        self.h.set(LOCKOUT, "off")
        self.h.set("input_boolean.heating_restore_verified", "off")

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def guard(self):
        return deepcopy(runtime.read(GUARD_FIXTURE))

    def state(self, entity):
        return self.h.hass.states.get(entity).state

    def room_and_control_snapshot(self):
        entities = [MASTER, FLOW, LOCKOUT, "input_boolean.heating_restore_verified"]
        entities += [f"climate.{zone}" for zone in runtime.ZONES]
        entities += [f"input_number.{zone}_last_comfort" for zone in runtime.ZONES]
        entities += [f"input_boolean.{zone}_manual_override" for zone in runtime.ZONES]
        return {
            entity: (self.state(entity), dict(self.h.hass.states.get(entity).attributes))
            for entity in entities
        }

    async def test_candidate_has_at_most_one_root_owner_and_only_relay_off_action(self):
        configuration = runtime.read("configuration.yaml")
        root_matches = [
            row for row in configuration["automation"]
            if str(row.get("id")) == GUARD_ID
        ]
        package_matches = []
        for package in configuration["homeassistant"]["packages"].values():
            if not isinstance(package, dict):
                continue
            rows = package.get("automation", [])
            if isinstance(rows, dict):
                rows = [rows]
            package_matches.extend(
                row for row in rows
                if isinstance(row, dict) and str(row.get("id")) == GUARD_ID
            )
        self.assertLessEqual(len(root_matches), 1, "Root/UI guard must not have duplicate owners")
        self.assertEqual(package_matches, [], "A package must not duplicate the root/UI guard")
        cfg = self.guard()
        self.assertEqual(cfg["id"], GUARD_ID)
        if root_matches:
            self.assertEqual(root_matches[0], cfg, "Installed root/UI guard must match the candidate")
        PLATFORM_SCHEMA(deepcopy(cfg))
        self.assertTrue(cfg["initial_state"])
        self.assertEqual(cfg["action"], [{
            "action": "switch.turn_off", "target": {"entity_id": RELAY}
        }])
        await self.h.load_automations([cfg])
        self.assertEqual(self.h.hass.states.async_all("automation")[0].state, "on")

    async def test_foreign_relay_on_is_stopped_in_every_v4_blocked_state(self):
        await self.h.load_automations([self.guard()])
        for flow_state in ("EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"):
            with self.subTest(flow_state=flow_state):
                self.h.set(FLOW, flow_state)
                await self.h.hass.async_block_till_done()
                before = self.room_and_control_snapshot()
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
                self.assertEqual(self.room_and_control_snapshot(), before)
        self.assertEqual(len(self.h.writes("switch", "turn_off")), 3)
        self.assertTrue(all(call[:2] == ("switch", "turn_off") for call in self.h.calls))

    async def test_lockout_assertion_stops_already_on_relay_in_normal(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.h.set(LOCKOUT, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "on")
        self.assertEqual(self.state(FLOW), "NORMAL")
        self.h.set(LOCKOUT, "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_entering_blocked_flow_state_stops_existing_relay(self):
        await self.h.load_automations([self.guard()])
        for flow_state in ("EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"):
            with self.subTest(flow_state=flow_state):
                self.h.set(FLOW, "NORMAL")
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "on")
                self.h.set(FLOW, flow_state)
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
                self.h.set(FLOW, "NORMAL")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")

    async def test_missing_unknown_unavailable_or_invalid_flow_fails_closed(self):
        await self.h.load_automations([self.guard()])
        for flow_state in ("unknown", "unavailable", "unexpected", None):
            with self.subTest(flow_state=flow_state):
                if flow_state is None:
                    self.h.hass.states.async_remove(FLOW)
                else:
                    self.h.set(FLOW, flow_state)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_missing_or_unavailable_lockout_helper_fails_closed(self):
        await self.h.load_automations([self.guard()])
        for lockout_state in ("unknown", "unavailable", None):
            with self.subTest(lockout_state=lockout_state):
                if lockout_state is None:
                    self.h.hass.states.async_remove(LOCKOUT)
                else:
                    self.h.set(LOCKOUT, lockout_state)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")

    async def test_startup_reconciles_restored_on_relay_in_hard_lockout(self):
        self.h.set(FLOW, "HARD_LOCKOUT")
        self.h.set(RELAY, "on")
        await self.h.load_automations([self.guard()], startup=True)
        await self.h.hass.async_start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(MASTER), "on")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_reload_reconciles_existing_on_relay_without_safety_edge(self):
        self.h.set(FLOW, "HARD_LOCKOUT")
        self.h.set(RELAY, "on")
        await self.h.load_automations([self.guard()])
        self.h.hass.bus.async_fire("automation_reloaded")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(FLOW), "HARD_LOCKOUT")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_normal_startup_and_reload_never_create_heat_request(self):
        await self.h.load_automations([self.guard()], startup=True)
        await self.h.hass.async_start()
        self.h.hass.bus.async_fire("automation_reloaded")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.calls, [])

    async def test_normal_operation_and_attribute_reports_are_unchanged(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        self.h.set(FLOW, "NORMAL", diagnostic_report=1)
        self.h.set(LOCKOUT, "off", diagnostic_report=1)
        self.h.hass.bus.async_fire("automation_reloaded")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.assertEqual(self.h.calls, [])

    async def test_foreign_on_does_not_restart_or_cancel_actual_v4_recovery(self):
        self.h.set(FLOW, "RESTORING")
        self.h.set("input_boolean.heating_service_mode", "off")
        self.h.set("input_boolean.heating_flow_relief_mode", "off")
        self.h.set("input_boolean.heating_fault_recovery_pending", "on")
        self.h.set("input_boolean.heating_flow_paths_verified_v4", "on")
        self.h.set("input_boolean.heating_flow_relief_resume_armed", "off")
        self.h.set("binary_sensor.heating_boiler_fault_clear", "on")
        self.h.set("sensor.system_bus_status", "connected")
        self.h.set("binary_sensor.boiler_burngas", "off")
        self.h.set("sensor.boiler_heatblock", "25")
        entered = asyncio.Event()
        release = asyncio.Event()
        relay_stopped = asyncio.Event()
        restore_calls = []

        async def slow_restore(call):
            restore_calls.append(call)
            entered.set()
            await release.wait()
            self.h.set("input_boolean.heating_restore_verified", "on")

        async def observe_relay_off(call):
            was_on = self.state(RELAY) == "on"
            await self.h.service(call)
            if entered.is_set() and was_on and self.state(RELAY) == "off":
                relay_stopped.set()

        self.h.hass.services.async_register(
            "script", "heating_restore_schedule_after_service", slow_restore
        )
        self.h.hass.services.async_register("switch", "turn_off", observe_relay_off)
        v4 = deepcopy(next(
            row for row in runtime.read("automations.yaml")
            if str(row["id"]) == V4_ID
        ))
        await self.h.load_automations([self.guard(), v4])
        try:
            self.h.hass.bus.async_fire("heating_flow_v4_reconcile")
            await asyncio.wait_for(entered.wait(), 1)
            self.h.set(RELAY, "on")
            await asyncio.wait_for(relay_stopped.wait(), 1)
            self.assertEqual(self.state(FLOW), "RESTORING")
            self.assertEqual(self.state("input_boolean.heating_restore_verified"), "off")
            self.assertEqual(len(restore_calls), 1)
            release.set()
            await self.h.hass.async_block_till_done()
            self.assertEqual(len(restore_calls), 1)
            self.assertEqual(self.state(FLOW), "NORMAL")
            self.assertEqual(self.state("input_boolean.heating_restore_verified"), "on")
            self.assertEqual(self.state(RELAY), "off")
            self.assertEqual(self.h.writes("switch", "turn_on"), [])
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
