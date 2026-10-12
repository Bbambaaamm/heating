"""Confirmed heat-needed eligibility, tested only with isolated HA fake devices.

Public fixtures retain their existing IDs. The root remains unchanged. No
private telemetry, live configs, physical devices or production HA are used.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy

from homeassistant.components.automation.config import PLATFORM_SCHEMA
import test_heating_runtime as runtime
import test_v4_active_start_runtime as original_start
import test_v4_thermal_guard_runtime as thermal

GUARD = "tests/fixtures/v4_confirmed_zone_guard.yaml"
START = "tests/fixtures/v4_confirmed_zone_start.yaml"
RELAY = thermal.RELAY
FEEDBACK = lambda z: f"binary_sensor.{z}_potrebne_teplo"
ACTIVE = lambda z: f"binary_sensor.zona_{z}_aktivni"
DEMAND = lambda z: f"sensor.zona_{z}_demand"
Z0, Z1, Z2 = runtime.ZONES[:3]


def seed(h, n=2):
    h.set("group.topne_zony", "on", entity_id=[f"climate.{z}" for z in runtime.ZONES])
    h.set("input_number.kotel_min_zone_demand_pct", "70")
    h.set("sensor.kotel_effective_min_active_zones", "2")
    h.set("sensor.kotel_effective_min_avg_demand_pct", "15")
    for i, z in enumerate(runtime.ZONES):
        h.set(FEEDBACK(z), "on" if i < n else "off")
        h.set(ACTIVE(z), "on")
        h.set(DEMAND(z), "90" if i < n else "0")


class ConfirmedZoneGuardRuntimeTests(thermal.V4RelayThermalGuardRuntimeTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        seed(self.h)

    def guard(self):
        return deepcopy(runtime.read(GUARD))

    async def test_root_has_one_guard_owner_and_only_relay_off_action(self):
        await super().test_root_has_one_guard_owner_and_only_relay_off_action()
        cfg = self.guard()
        public_thermal = runtime.read("tests/fixtures/v4_relay_thermal_guard.yaml")
        self.assertEqual(cfg["action"], public_thermal["action"])
        self.assertEqual(cfg["trigger"][:4], public_thermal["trigger"])
        self.assertTrue(cfg["condition"][1]["value_template"].startswith(
            public_thermal["condition"][1]["value_template"][:-3]))
        start = runtime.read(START)
        self.assertEqual(str(start["id"]), "1791376426962")
        gates = [a["variables"]["confirmed_zone_policy_ok"]
                 for a in start["action"] if "variables" in a]
        self.assertEqual(gates, [cfg["variables"]["confirmed_zone_policy_ok"]] * 2)
        PLATFORM_SCHEMA(deepcopy(start))

    async def test_heat_needed_off_stops_running_relay_with_cached_high_pi(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        before = self.room_and_control_snapshot()
        self.h.set(FEEDBACK(Z0), "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.state(DEMAND(Z0)), "90")
        self.assertEqual(self.state(ACTIVE(Z0)), "on")
        self.assertEqual(self.room_and_control_snapshot(), before)
        self.assertEqual(len(self.h.writes("switch", "turn_off")), 1)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_foreign_on_cannot_bypass_missing_feedback(self):
        await self.h.load_automations([self.guard()])
        for value in ("off", "unknown", "unavailable", "invalid", None):
            with self.subTest(value=value):
                if value is None:
                    self.h.hass.states.async_remove(FEEDBACK(Z0))
                else:
                    self.h.set(FEEDBACK(Z0), value)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_two_remaining_confirmed_zones_allow_one_to_stop(self):
        seed(self.h, 3)
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set(FEEDBACK(Z0), "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.assertEqual(self.h.calls, [])

    async def test_minimum_two_even_if_effective_helper_says_one(self):
        self.h.set("sensor.kotel_effective_min_active_zones", "1")
        self.h.set(FEEDBACK(Z0), "off")
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_stricter_count_policy_stops_two_zone_request(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set("sensor.kotel_effective_min_active_zones", "3")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_average_uses_only_confirmed_zones(self):
        for z in (Z0, Z1):
            self.h.set(DEMAND(z), "20")
        self.h.set("input_number.kotel_min_zone_demand_pct", "5")
        self.h.set("sensor.kotel_effective_min_avg_demand_pct", "30")
        self.h.set(DEMAND(Z2), "100")  # Unconfirmed cached demand must not inflate mean.
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_invalid_policy_inputs_fail_closed(self):
        await self.h.load_automations([self.guard()])
        for entity in ("input_number.kotel_min_zone_demand_pct",
                       "sensor.kotel_effective_min_active_zones",
                       "sensor.kotel_effective_min_avg_demand_pct"):
            for value in ("unknown", "unavailable", "nan", "inf", "-inf", "-1", None):
                with self.subTest(entity=entity, value=value):
                    seed(self.h)
                    if value is None:
                        self.h.hass.states.async_remove(entity)
                    else:
                        self.h.set(entity, value)
                    self.h.set(RELAY, "on")
                    await self.h.hass.async_block_till_done()
                    self.assertEqual(self.state(RELAY), "off")

    async def test_invalid_zone_demand_cannot_count_as_confirmed_path(self):
        await self.h.load_automations([self.guard()])
        for value in ("unknown", "unavailable", "nan", "inf", "-inf", "-1", "101", "1", "69"):
            with self.subTest(value=value):
                self.h.set(DEMAND(Z0), value)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")

    async def test_group_membership_change_invalidates_path_count(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set("group.topne_zony", "on", entity_id=[f"climate.{Z0}"])
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_missing_empty_unknown_or_unsupported_group_blocks(self):
        await self.h.load_automations([self.guard()])
        for members in ([], None, "invalid", ["climate.unmapped"]):
            with self.subTest(members=members):
                self.h.set("group.topne_zony", "on", entity_id=members)
                self.h.set(RELAY, "on")
                await self.h.hass.async_block_till_done()
                self.assertEqual(self.state(RELAY), "off")
        self.h.hass.states.async_remove("group.topne_zony")
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_native_hvac_off_or_zone_inactive_stops_count(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set(f"climate.{Z0}", "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")
        self.h.set(f"climate.{Z0}", "heat")
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set(ACTIVE(Z0), "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "off")

    async def test_feedback_attributes_do_not_cut_off_valid_request(self):
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.h.set(FEEDBACK(Z0), "on", diagnostic_report=1)
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.assertEqual(self.h.calls, [])


class ConfirmedZoneStartRuntimeTests(original_start.LiveV4StartRuntimeTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        seed(self.h)

    def live_start(self):
        cfg = deepcopy(runtime.read(START))
        for step in cfg["action"]:
            if "delay" in step:
                step["delay"] = {"milliseconds":70}
        return cfg

    async def test_cached_pi_with_feedback_off_never_starts(self):
        self.h.set(FEEDBACK(Z0), "off")
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_loss_during_delay_cancels_and_return_requires_full_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.03)
        self.h.set(FEEDBACK(Z0), "off")
        await asyncio.sleep(0.09)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set(FEEDBACK(Z0), "on")
        await asyncio.sleep(0.03)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_post_delay_recomputes_feedback_without_relying_on_trigger(self):
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        task = asyncio.create_task(self.h.run_sequence(self.live_start()["action"]))
        await asyncio.sleep(0.03)
        self.h.set(FEEDBACK(Z0), "off")
        await task
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_feedback_and_demand_attributes_do_not_reset_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        for i in range(5):
            self.h.set(FEEDBACK(Z0), "on", diagnostic_report=i)
            self.h.set(DEMAND(Z0), "90", diagnostic_report=i)
            await asyncio.sleep(0.02)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_benign_pi_state_changes_do_not_reset_start_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        for value in (91, 92, 93, 94, 95):
            self.h.set(DEMAND(Z0), str(value))
            await asyncio.sleep(0.02)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_pi_crossing_eligibility_floor_restarts_full_delay(self):
        await self.h.load_automations([self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.03)
        self.h.set(DEMAND(Z0), "60")
        await asyncio.sleep(0.09)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        self.h.set(DEMAND(Z0), "90")
        await asyncio.sleep(0.03)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)

    async def test_guard_and_start_do_not_chatter_after_feedback_loss(self):
        await self.h.load_automations([runtime.read(GUARD), self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.h.set(FEEDBACK(Z0), "off")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.h.hass.states.get(RELAY).state, "off")
        await asyncio.sleep(0.23)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.assertEqual(len(self.h.writes("switch", "turn_off")), 1)
        self.h.set(FEEDBACK(Z0), "on")
        await asyncio.sleep(0.03)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 2)

    async def test_original_conditions_delay_and_only_on_action_preserved(self):
        old = deepcopy(next(a for a in runtime.read("automations.yaml")
                            if str(a["id"]) == "1791376426962"))
        cfg = runtime.read(START)
        stripped = [s for s in cfg["action"] if "variables" not in s
                    and s.get("value_template") != "{{ confirmed_zone_policy_ok }}"]
        self.assertEqual(stripped, old["action"])
        self.assertEqual(cfg["trigger"][:len(old["trigger"])], old["trigger"])
        self.assertEqual(cfg["mode"], "restart")
        self.assertEqual(cfg["condition"], old["condition"])
        self.assertEqual([a for a in cfg["action"] if "action" in a],
                         [{"action":"switch.turn_on", "target":{"entity_id":RELAY}}])
        self.assertEqual(self.h.render(cfg["action"][0]["variables"]["confirmed_zone_policy_ok"]), True)
