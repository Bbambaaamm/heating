"""Exercise active V4 telemetry gates in the isolated HA Core test harness.

No production Home Assistant, physical relay, EMS device or Zigbee network is
accessed. Only the policy delay is shortened; its conditions and triggers are
loaded unchanged from automations.yaml. The existing fault-clear helper is
represented by its reported state, using its documented service-code contract.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import unittest

import test_heating_runtime as runtime


ACTIVE_ID = "1791376426962"
DEMAND = "binary_sensor.kotel_should_be_on"
FAULT_CLEAR = "binary_sensor.heating_boiler_fault_clear"
BUS = "sensor.system_bus_status"
HEATBLOCK = "sensor.boiler_heatblock"
DELAY_MS = 160


class V4StartTelemetryGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.boiler_inputs(requested=False)
        self.h.set("input_select.heating_flow_state_v4", "NORMAL")
        self.h.set("input_boolean.heating_service_mode", "off")
        self.h.set("input_boolean.heating_flow_relief_lockout", "off")
        self.h.set("input_boolean.heating_fault_recovery_pending", "off")
        self.h.set(BUS, "connected")
        self.h.set(HEATBLOCK, "25")
        self.h.set("binary_sensor.boiler_burngas", "off")
        self.report_service_code("200")

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def live_start(self):
        cfg = deepcopy(next(
            row for row in runtime.read("automations.yaml")
            if str(row["id"]) == ACTIVE_ID
        ))
        self.assertTrue(cfg["initial_state"])
        for step in cfg["action"]:
            if "delay" in step:
                step["delay"] = {"milliseconds": DELAY_MS}
        return cfg

    def report_service_code(self, code):
        """Provide the existing EMS fault-clear helper's state without EMS I/O."""
        self.h.set("sensor.boiler_servicecodenumber", code)
        clear = self.h.render(
            "{{ has_value('sensor.boiler_servicecodenumber') and "
            "states('sensor.boiler_servicecodenumber') not in "
            "['2964','2965','2966','2967'] }}"
        )
        self.h.set(FAULT_CLEAR, "on" if clear else "off")

    def assert_no_start(self):
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    def assert_pending_cancelled(self):
        policy = next(
            state for state in self.h.hass.states.async_all("automation")
            if str(state.attributes.get("id")) == ACTIVE_ID
        )
        self.assertEqual(policy.attributes["current"], 0)
        self.assert_no_start()

    async def test_critical_or_missing_service_code_blocks_stale_demand(self):
        await self.h.load_automations([self.live_start()])
        for code in ("2964", "2965", "2966", "2967", "unknown", "unavailable"):
            with self.subTest(code=code):
                self.report_service_code(code)
                # Deliberately leave derived demand ON despite the fault.
                self.h.set(DEMAND, "on")
                await asyncio.sleep(0.20)
                self.assert_no_start()
                self.h.set(DEMAND, "off")
                await asyncio.sleep(0.01)

    async def test_unavailable_fault_clear_helper_blocks_start(self):
        await self.h.load_automations([self.live_start()])
        for state in ("unknown", "unavailable"):
            with self.subTest(state=state):
                self.h.set(FAULT_CLEAR, state)
                self.h.set(DEMAND, "on")
                await asyncio.sleep(0.20)
                self.assert_no_start()
                self.h.set(DEMAND, "off")
                await asyncio.sleep(0.01)

    async def test_disconnected_or_missing_ems_blocks_start(self):
        await self.h.load_automations([self.live_start()])
        for state in ("disconnected", "unknown", "unavailable"):
            with self.subTest(state=state):
                self.h.set(BUS, state)
                self.h.set(DEMAND, "on")
                await asyncio.sleep(0.20)
                self.assert_no_start()
                self.h.set(DEMAND, "off")
                await asyncio.sleep(0.01)

    async def test_ems_loss_cancels_wait_and_reconnect_requires_full_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        await asyncio.sleep(0.04)
        self.h.set(BUS, "disconnected")
        await asyncio.sleep(0.03)
        self.assert_pending_cancelled()
        self.h.set(BUS, "connected")
        await asyncio.sleep(0.10)
        self.assert_no_start()
        await asyncio.sleep(0.10)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_fault_during_wait_cancels_and_clear_requires_full_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        await asyncio.sleep(0.04)
        self.report_service_code("2964")
        await asyncio.sleep(0.03)
        self.assert_pending_cancelled()
        self.report_service_code("200")
        await asyncio.sleep(0.10)
        self.assert_no_start()
        await asyncio.sleep(0.10)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_hot_exact_boundary_or_invalid_heatblock_blocks_start(self):
        await self.h.load_automations([self.live_start()])
        for temperature in ("72", "72.1", "80", "unknown", "unavailable", "invalid"):
            with self.subTest(temperature=temperature):
                self.h.set(HEATBLOCK, temperature)
                self.h.set(DEMAND, "on")
                await asyncio.sleep(0.20)
                self.assert_no_start()
                self.h.set(DEMAND, "off")
                await asyncio.sleep(0.01)

    async def test_exact_72_during_wait_fails_final_gate_then_cooling_restarts(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        await asyncio.sleep(0.04)
        # Native numeric_state above 72 excludes equality. The final gate
        # must reject this boundary even if no unsafe trigger fires here.
        self.h.set(HEATBLOCK, "72")
        await asyncio.sleep(0.20)
        self.assert_no_start()
        self.h.set(HEATBLOCK, "71.9")
        await asyncio.sleep(0.10)
        self.assert_no_start()
        await asyncio.sleep(0.10)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_hot_crossing_cancels_wait_and_cooling_requires_full_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        await asyncio.sleep(0.04)
        self.h.set(HEATBLOCK, "72.1")
        await asyncio.sleep(0.03)
        self.assert_pending_cancelled()
        self.h.set(HEATBLOCK, "71.9")
        await asyncio.sleep(0.10)
        self.assert_no_start()
        await asyncio.sleep(0.10)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_missing_temperature_cancels_and_valid_return_restarts(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        await asyncio.sleep(0.04)
        self.h.set(HEATBLOCK, "unavailable")
        await asyncio.sleep(0.03)
        self.assert_pending_cancelled()
        self.h.set(HEATBLOCK, "25")
        await asyncio.sleep(0.10)
        self.assert_no_start()
        await asyncio.sleep(0.10)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_safe_reports_and_telemetry_attributes_do_not_starve_start(self):
        await self.h.load_automations([self.live_start()])
        self.h.set(DEMAND, "on")
        for report in range(6):
            self.h.set(BUS, "connected", diagnostic_report=report)
            self.h.set(FAULT_CLEAR, "on", diagnostic_report=report)
            self.h.set(HEATBLOCK, str(25 + report))
            await asyncio.sleep(0.04)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)


if __name__ == "__main__":
    unittest.main()
