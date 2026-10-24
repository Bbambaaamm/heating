"""Real HA actions/triggers with fake devices. Never contacts production."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import unittest

from homeassistant.util import dt as dt_util
import test_heating_runtime as runtime
from test_v4_confirmed_zone_runtime import seed

FLOW = "input_select.heating_flow_state_v4"
LOCK = "input_boolean.heating_flow_relief_lockout"
MASTER = "input_boolean.topny_system_enable"
TIMER = "timer.heating_lockout_limit_10m"
EVENT = "heating_flow_v4_lockout_expired"


class LockoutLimitRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.h.boiler_inputs()
        seed(self.h)
        for entity, value in {
            FLOW: "HARD_LOCKOUT", LOCK: "on", MASTER: "off", TIMER: "active",
            "input_boolean.heating_service_mode": "off",
            "input_boolean.heating_restore_verified": "on",
            "input_boolean.heating_fault_recovery_pending": "off",
            "input_boolean.heating_flow_relief_mode": "off",
            "input_boolean.heating_flow_relief_resume_armed": "on",
            "binary_sensor.heating_boiler_fault_clear": "on",
            "binary_sensor.boiler_burngas": "off",
            "sensor.boiler_heatblock": "30", "sensor.boiler_servicecodenumber": "203",
            "sensor.system_bus_status": "connected",
        }.items():
            self.h.set(entity, value)
        self.h.set("input_datetime.heating_flow_relief_started_at", "2026-01-01 00:00:00",
                   timestamp=(dt_util.utcnow()-timedelta(minutes=20)).timestamp())
        rows = runtime.read("automations.yaml")
        self.flow = deepcopy(next(a for a in rows if str(a['id']) == '1790189620167'))
        self.flow['alias'] = 'topeni_flow_relief_pred_restartem_horaku'
        self.start = deepcopy(next(a for a in rows if str(a['id']) == '1791376426962'))
        for action in self.start['action']:
            if 'delay' in action:
                action['delay'] = {'milliseconds': 50}
        self.manager = runtime.read('heating/control/lockout_limit_10m.yaml')['automation'][0]

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def state(self, entity):
        return self.h.hass.states.get(entity).state

    async def load(self, start=False):
        await self.h.load_automations([self.flow, self.manager] + ([self.start] if start else []))

    async def expire(self):
        self.h.set(TIMER, 'idle')
        self.h.hass.bus.async_fire('timer.finished', {'entity_id': TIMER})
        await self.h.hass.async_block_till_done()
        await asyncio.sleep(.03)

    async def test_expiry_unconditionally_clears_latch_and_hard_state(self):
        await self.load()
        await self.expire()
        self.assertEqual(self.state(LOCK), 'off')
        self.assertEqual(self.state(FLOW), 'NORMAL')
        self.assertEqual(self.state(MASTER), 'on')
        self.assertEqual(self.h.writes('switch','turn_on'), [])
        self.assertEqual(self.h.writes('timer','start'), [])

    async def test_fault_cannot_delay_expiry_or_force_burner_start(self):
        self.h.set('binary_sensor.heating_boiler_fault_clear','off')
        self.h.set('sensor.boiler_servicecodenumber','2964')
        await self.load(start=True)
        await self.expire()
        await asyncio.sleep(.12)
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.state(FLOW),'NORMAL')
        self.assertEqual(self.h.writes('switch','turn_on'),[])

    async def test_hot_block_or_lost_ems_still_blocks_normal_start(self):
        self.h.set('sensor.boiler_heatblock','80')
        self.h.set('sensor.system_bus_status','disconnected')
        await self.load(start=True)
        await self.expire()
        await asyncio.sleep(.12)
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.h.writes('switch','turn_on'),[])

    async def test_healthy_recovery_uses_original_delayed_start(self):
        await self.load(start=True)
        await self.expire()
        await asyncio.sleep(.12)
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(len(self.h.writes('switch','turn_on')),1)

    async def test_transitions_do_not_restart_active_timer(self):
        await self.load()
        self.h.set(FLOW,'RESTORING')
        self.h.set(FLOW,'HARD_LOCKOUT')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.h.writes('timer','start'),[])

    async def test_startup_with_expired_timer_releases_instead_of_new_ten_minutes(self):
        self.h.set(TIMER,'idle')
        await self.load()
        self.h.hass.bus.async_fire('automation_reloaded')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.state(FLOW),'NORMAL')
        self.assertEqual(self.h.writes('timer','start'),[])

    async def test_restored_active_timer_is_not_extended_at_reload(self):
        await self.load()
        self.h.hass.bus.async_fire('automation_reloaded')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(TIMER),'active')
        self.assertEqual(self.state(LOCK),'on')
        self.assertEqual(self.h.writes('timer','start'),[])

    async def test_busy_emergency_opening_is_not_cancelled_by_expiry(self):
        self.h.set(FLOW,'EMERGENCY_COOLING')
        self.h.set('sensor.boiler_heatblock','80')
        events=[]
        self.h.hass.bus.async_listen(EVENT, lambda event: events.append(event))
        # Execute the real manager actions against an explicitly busy owner.
        self.h.set('automation.topeni_flow_relief_pred_restartem_horaku','on',current=1)
        await self.h.run_sequence(self.manager['action'], {'trigger':{'id':'expired'}})
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(events,[])
        self.assertEqual(self.state(FLOW),'EMERGENCY_COOLING')

    async def test_expired_cooling_retries_when_cold_without_relatching(self):
        self.h.set(FLOW,'EMERGENCY_COOLING')
        self.h.set('sensor.boiler_heatblock','80')
        await self.load()
        await self.expire()
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.state(FLOW),'EMERGENCY_COOLING')
        self.h.set('sensor.boiler_heatblock','30')
        self.h.hass.bus.async_fire('heating_flow_v4_reconcile')
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(FLOW),'NORMAL')
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.h.writes('timer','start'),[])

    async def test_manual_master_off_preference_remains_off(self):
        self.h.set('input_boolean.heating_flow_relief_resume_armed','off')
        await self.load()
        await self.expire()
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.state(MASTER),'off')

    async def test_new_lock_starts_exactly_one_ten_minute_timer(self):
        self.h.set(FLOW,'NORMAL')
        self.h.set(LOCK,'off')
        self.h.set(TIMER,'idle')
        await self.load()
        self.h.set(LOCK,'on')
        await self.h.hass.async_block_till_done()
        self.h.set(FLOW,'HARD_LOCKOUT')
        await self.h.hass.async_block_till_done()
        calls=self.h.writes('timer','start')
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][2]['duration'],'00:10:00')

    async def test_failed_restore_clears_latch_but_does_not_enable_master(self):
        self.h.set('input_boolean.heating_restore_verified','off')
        async def failed(call):
            pass
        self.h.hass.services.async_register('script','heating_restore_schedule_after_service',failed)
        await self.load(start=True)
        await self.expire()
        self.assertEqual(self.state(LOCK),'off')
        self.assertEqual(self.state(FLOW),'NORMAL')
        self.assertEqual(self.state(MASTER),'off')
        self.assertEqual(self.h.writes('switch','turn_on'),[])

    def test_timer_is_ten_minutes_and_restores(self):
        timer=runtime.read('heating/control/lockout_limit_10m.yaml')['timer']['heating_lockout_limit_10m']
        self.assertEqual(timer['duration'],'00:10:00')
        self.assertIs(timer['restore'],True)
        self.assertEqual(timer['icon'],'mdi:timer-lock-outline')


if __name__ == '__main__':
    unittest.main()
