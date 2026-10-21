"""Exercise the real recovery source with native HA and simulated devices."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import unittest

import test_heating_runtime as runtime

BASELINE = "tests/fixtures/flow_v4_before_retry_20261021.yaml"
FLOW = "input_select.heating_flow_state_v4"
LOCK = "input_boolean.heating_flow_relief_lockout"
MASTER = "input_boolean.topny_system_enable"
RELAY = "switch.kotel_rele_spinac"
BURNER = "binary_sensor.boiler_burngas"
MARKER = "Čekání na telemetrii a odeznění přechodné překážky"


def restoration(config):
    return next(step for step in config["action"] if any(
        c.get("entity_id") == FLOW and c.get("state") == "RESTORING"
        for c in step.get("if", [])
    ))["then"]


class RecoveryRetryRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.boiler_inputs(relay="off")
        self.restored = asyncio.Event()
        self.restore_count = 0
        for entity, state in {
            FLOW: "RESTORING", LOCK: "off", MASTER: "off", RELAY: "off",
            BURNER: "on", "input_boolean.heating_service_mode": "off",
            "input_boolean.heating_flow_paths_verified_v4": "on",
            "input_boolean.heating_restore_verified": "off",
            "input_boolean.heating_flow_relief_resume_armed": "on",
            "input_boolean.heating_fault_recovery_pending": "on",
            "input_boolean.heating_flow_relief_mode": "off",
            "binary_sensor.heating_boiler_fault_clear": "on",
            "binary_sensor.heating_flow_relief_confirmed": "off",
            "sensor.system_bus_status": "connected",
            "sensor.boiler_heatblock": "38", "sensor.boiler_servicecodenumber": "203",
        }.items():
            self.h.set(entity, state)
        for zone in runtime.ZONES:
            self.h.set(f"sensor.{zone}_pocet_kroku_motoru", "1000")

        async def restore(call):
            self.restore_count += 1
            self.h.set("input_boolean.heating_restore_verified", "on")
            self.restored.set()

        self.h.hass.services.async_register("script", "heating_restore_schedule_after_service", restore)

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def state(self, entity):
        return self.h.hass.states.get(entity).state

    async def start(self, *, previous=False, initial_lock=False):
        rows = runtime.read("automations.yaml")
        config = deepcopy(runtime.read(BASELINE)[0] if previous else next(
            a for a in rows if str(a['id']) == '1790189620167'))
        # Match the production entity registry ID; only the display alias changes.
        config['alias'] = 'topeni_flow_relief_pred_restartem_horaku'
        def shorten(value):
            if isinstance(value, dict):
                if 'timeout' in value:
                    value['timeout'] = {'milliseconds': 250}
                for child in value.values():
                    shorten(child)
            elif isinstance(value, list):
                for child in value:
                    shorten(child)
        shorten(config)
        ticker = deepcopy(next(a for a in rows if str(a['id']) == '1791543743116'))
        ticker['alias'] = 'recovery_retry_tick'
        if initial_lock:
            self.h.set(FLOW, "HARD_LOCKOUT")
            self.h.set(LOCK, "on")
        await self.h.load_automations([config, ticker])
        self.h.hass.bus.async_fire("heating_flow_v4_reconcile")

    async def tick(self):
        await self.h.hass.services.async_call('automation', 'trigger', {
            'entity_id': 'automation.recovery_retry_tick', 'skip_condition': False,
        }, blocking=True)

    async def wait_until_restored(self):
        await asyncio.wait_for(self.restored.wait(), 3)
        await asyncio.sleep(0.02)

    def assert_no_relay_start(self):
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_previous_flow_immediately_latches_when_burner_reappears(self):
        await self.start(previous=True)
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "HARD_LOCKOUT")
        self.assertEqual(self.state(LOCK), "on")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()

    async def test_candidate_waits_without_enable_then_rechecks_after_burner_off(self):
        await self.start()
        await self.wait_until_restored()
        self.assertEqual(self.state(FLOW), "RESTORING")
        self.assertEqual(self.state(LOCK), "off")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()
        self.h.set(BURNER, "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "NORMAL")
        self.assertEqual(self.state(MASTER), "on")
        self.assert_no_relay_start()

    async def test_burner_timeout_remains_retryable_then_recovers_without_second_restore(self):
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "RESTORING")
        self.assertEqual(self.state(LOCK), "off")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()
        self.h.set(BURNER, 'off')
        await self.tick()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')
        self.assertEqual(self.state(MASTER), 'on')
        self.assertEqual(self.restore_count, 1)
        self.assert_no_relay_start()

    async def test_unknown_burner_does_not_count_as_off(self):
        self.h.set(BURNER, "unknown")
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "RESTORING")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()

    async def test_ems_loss_during_wait_fails_final_recheck(self):
        await self.start()
        await self.wait_until_restored()
        self.h.set("sensor.system_bus_status", "disconnected")
        self.h.set(BURNER, "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "RESTORING")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()
        self.h.set('sensor.system_bus_status', 'connected')
        await self.tick()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')

    async def test_temperature_rise_below_emergency_threshold_fails_final_gate(self):
        await self.start()
        await self.wait_until_restored()
        self.h.set("sensor.boiler_heatblock", "65")
        self.h.set(BURNER, "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "RESTORING")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()
        self.h.set('sensor.boiler_heatblock', '38')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')

    async def test_existing_hard_lockout_is_never_cleared(self):
        self.h.set(BURNER, "off")
        await self.start(initial_lock=True)
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "HARD_LOCKOUT")
        self.assertEqual(self.state(LOCK), "on")
        self.assertEqual(self.state(MASTER), "off")
        self.assertFalse(self.restored.is_set())
        self.assert_no_relay_start()

    async def test_tick_does_not_cancel_active_readiness_wait(self):
        await self.start()
        await self.wait_until_restored()
        await self.tick()
        await asyncio.sleep(0.02)
        self.assertEqual(self.state(FLOW), 'RESTORING')
        self.assertEqual(self.restore_count, 1)
        self.assertEqual(self.h.hass.states.get(
            'automation.topeni_flow_relief_pred_restartem_horaku').attributes['current'], 1)
        self.h.set(BURNER, 'off')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')
        self.assertEqual(self.restore_count, 1)
        self.assert_no_relay_start()

    async def test_unverified_paths_still_lock_out(self):
        self.h.set('input_boolean.heating_flow_paths_verified_v4', 'off')
        self.h.set(BURNER, 'off')
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'HARD_LOCKOUT')
        self.assertEqual(self.state(MASTER), 'off')
        self.assert_no_relay_start()

    async def test_failed_zone_restoration_still_lock_out(self):
        async def no_ack(call):
            self.restore_count += 1
        self.h.hass.services.async_register('script', 'heating_restore_schedule_after_service', no_ack)
        self.h.set(BURNER, 'off')
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'HARD_LOCKOUT')
        self.assertEqual(self.state(MASTER), 'off')
        self.assert_no_relay_start()

    async def test_invalid_temperature_never_enables_then_recovers(self):
        self.h.set('sensor.boiler_heatblock', 'unavailable')
        self.h.set(BURNER, 'off')
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'RESTORING')
        self.assertEqual(self.state(MASTER), 'off')
        self.assert_no_relay_start()
        self.h.set('sensor.boiler_heatblock', '38')
        await self.tick()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')

    async def test_retry_preserves_original_master_off_preference(self):
        self.h.set('input_boolean.heating_flow_relief_resume_armed', 'off')
        await self.start()
        await self.h.hass.async_block_till_done()
        self.h.set(BURNER, 'off')
        await self.tick()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'NORMAL')
        self.assertEqual(self.state(MASTER), 'off')
        self.assert_no_relay_start()

    async def test_unacknowledged_relay_off_never_enables_master(self):
        async def no_relay_ack(call):
            self.h.calls.append((call.domain, call.service, dict(call.data)))
        self.h.hass.services.async_register('switch', 'turn_off', no_relay_ack)
        self.h.set(RELAY, 'on')
        self.h.set(BURNER, 'off')
        await self.start()
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), 'RESTORING')
        self.assertEqual(self.state(MASTER), 'off')
        self.assertEqual(self.h.writes('switch', 'turn_on'), [])

    async def test_native_fault_preempts_wait_and_keeps_controls_off(self):
        await self.start()
        await self.wait_until_restored()
        self.h.set("binary_sensor.heating_boiler_fault_clear", "off")
        self.h.set("sensor.boiler_servicecodenumber", "2964")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW), "EMERGENCY_COOLING")
        self.assertEqual(self.state(MASTER), "off")
        self.assert_no_relay_start()


if __name__ == "__main__":
    unittest.main()
