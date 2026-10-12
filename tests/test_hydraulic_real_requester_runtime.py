"""Native HA regressions for independent demand before auxiliary TRV support.

Synthetic data and fake services only; no HA, EMS, MQTT or physical device access.
The boiler's two confirmed zones and its existing relay owners are unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

from homeassistant.util import dt as dt_util
import test_heating_runtime as runtime

FIXTURE = "tests/fixtures/hydraulic_support_real_requester.yaml"
START = "heating_hydraulic_support_start"
GUARD = "heating_hydraulic_support_guard"
SUPPORT = "input_select.topeni_hydraulicka_podpurna_zona"


class HydraulicRequesterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.calls = []
        self.h.set("group.topne_zony", "on", entity_id=[f"climate.{z}" for z in runtime.ZONES])
        self.h.set("input_select.heating_flow_state_v4", "NORMAL")
        self.h.set("input_boolean.heating_service_mode", "off")
        self.h.set("input_number.kotel_min_zone_demand_pct", "70")
        self.h.set("input_boolean.topeni_hydraulicka_podpora_docasny_pi_prah", "off")
        self.h.set("input_number.topeni_hydraulicka_podpora_puvodni_min_demand_zony", "70")
        self.h.set("timer.topeni_hydraulicka_podpora_cooldown", "idle")
        self.h.set(SUPPORT, "none")
        self.h.set("sensor.kotel_aktivni_zony_pocet", "1")
        self.h.set("binary_sensor.kotel_threshold_ok_avg_demand", "on")
        for z in runtime.ZONES:
            self.h.set(f"binary_sensor.zona_{z}_aktivni", "off")
            self.h.set(f"binary_sensor.{z}_potrebne_teplo", "off")
            self.h.set(f"sensor.zona_{z}_demand", "0")
            self.h.set(f"sensor.{z}_pozadavek_na_vytapeni_pi", "0")
        for z in ["1p_chodba", "prizemi_chodba_zachod"]:
            self.h.set(f"binary_sensor.heating_valve_{z}_alive", "on")
            self.h.set(f"binary_sensor.zona_{z}_okno_otevrene", "off")
            self.h.set(f"climate.{z}", "heat", temperature=15, current_temperature=22,
                       min_temp=5, max_temp=30, pi_heating_demand=0)

        async def fake_apply(call):
            data = dict(call.data)
            self.calls.append(data)
            climate = data["climate_entity"]
            obj = self.h.hass.states.get(climate)
            attrs = dict(obj.attributes, temperature=data["requested_temp"])
            self.h.hass.states.async_set(climate, "heat", attrs)
            zid = climate.split(".")[1]
            self.h.set(f"binary_sensor.{zid}_potrebne_teplo", "on")
            self.h.set(f"sensor.{zid}_pozadavek_na_vytapeni_pi", "76")
            self.h.set("sensor.kotel_aktivni_zony_pocet", "2")

        self.h.hass.services.async_register("script", "heating_apply_zone_target", fake_apply)

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    def config(self, aid, previous=False):
        source = runtime.read("automations.yaml") if previous else runtime.read(FIXTURE)
        return deepcopy(next(a for a in source if a["id"] == aid))

    def requester(self, z="sklep_michal", *, room=19, demand=80, native="on"):
        self.h.set(f"climate.{z}", "heat", temperature=21, current_temperature=room,
                   min_temp=5, max_temp=30, pi_heating_demand=demand)
        self.h.set(f"binary_sensor.zona_{z}_aktivni", "on")
        self.h.set(f"binary_sensor.{z}_potrebne_teplo", native)
        self.h.set(f"sensor.zona_{z}_demand", str(demand))

    def count(self, *, guard=False, support="climate.1p_chodba", threshold=70):
        cfg = self.config(GUARD if guard else START)
        text = (cfg["action"][3]["variables"]["real_high_count"] if guard
                else cfg["variables"]["confirmed_real_requester_count"])
        return int(self.h.render(text, {"support_zone": support, "original_threshold": threshold}))

    async def start(self, *, previous=False):
        await self.h.load_automations([self.config(START, previous)])
        self.h.hass.bus.async_fire("heating_hydraulic_support_retry")
        await self.h.hass.async_block_till_done()

    async def test_previous_start_forces_auxiliary_from_warm_night_cache(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester("prizemi_chodba_zachod", room=22, demand=92)
        self.h.set("climate.prizemi_chodba_zachod", "heat", temperature=15,
                   current_temperature=22, min_temp=5, max_temp=30, pi_heating_demand=92)
        await self.start(previous=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["requested_temp"], 29)

    async def test_night_cache_does_not_force_auxiliary(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester("prizemi_chodba_zachod", room=22, demand=92)
        self.h.set("climate.prizemi_chodba_zachod", "heat", temperature=29,
                   current_temperature=22, min_temp=5, max_temp=30, pi_heating_demand=92)
        await self.start()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.h.hass.states.get(SUPPORT).state, "none")

    async def test_real_scheduled_request_still_opens_auxiliary(self):
        self.requester()
        await self.start()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["reason"], "hydraulic_support_single_requester")
        self.assertEqual(self.calls[0]["requested_temp"], 29)
        self.assertFalse(any(d == "switch" for d, s, data in self.h.calls))

    async def test_native_off_and_unavailable_do_not_count(self):
        self.requester()
        for value in ["off", "unknown", "unavailable", ""]:
            with self.subTest(value=value):
                self.h.set("binary_sensor.sklep_michal_potrebne_teplo", value)
                self.assertEqual(self.count(), 0)

    async def test_cold_eco_room_still_qualifies_without_active_window(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester(room=14)
        self.assertEqual(self.count(), 1)

    async def test_boost_and_effective_manual_precedence(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester(room=21.5)
        self.h.set("input_number.boost_comfort_offset_c", "0")
        self.h.set("binary_sensor.kotel_boost_active", "on")
        self.assertEqual(self.count(), 0)
        self.h.set("input_number.boost_comfort_offset_c", "1")
        self.assertEqual(self.count(), 1)
        self.h.set("binary_sensor.kotel_boost_active", "off")
        self.h.set("input_boolean.sklep_michal_manual_override", "on")
        self.h.set("input_select.sklep_michal_manual_override_type", "Časovač")
        self.h.set("timer.sklep_michal_manual_override", "active")
        self.h.set("input_number.sklep_michal_last_comfort", "23")
        self.assertEqual(self.count(), 1)
        self.h.set("timer.sklep_michal_manual_override", "idle")
        self.assertEqual(self.count(), 0)

    async def test_disabled_schedule_uses_eco_even_during_boost(self):
        self.requester()
        self.h.set("binary_sensor.kotel_boost_active", "on")
        self.h.set("input_boolean.schedule_enable_sklep_michal", "off")
        self.assertEqual(self.count(), 0)

    async def test_invalid_policy_and_room_data_fail_closed(self):
        self.requester()
        for entity in ["input_number.kotel_min_zone_demand_pct",
                       "input_number.eco_temp_default", "input_number.boost_comfort_offset_c",
                       "sensor.zona_sklep_michal_demand"]:
            original = self.h.hass.states.get(entity).state
            for value in ["unknown", "unavailable", "nan", "inf"]:
                with self.subTest(entity=entity, value=value):
                    self.h.set(entity, value)
                    self.assertEqual(self.count(), 0)
            self.h.set(entity, original)
        self.h.set("climate.sklep_michal", "heat", temperature=21, current_temperature="unknown",
                   min_temp=5, max_temp=30, pi_heating_demand=80)
        self.assertEqual(self.count(), 0)

    async def test_selected_auxiliary_never_counts_as_independent_requester(self):
        self.requester("1p_chodba", room=19, demand=76)
        self.h.set(SUPPORT, "climate.1p_chodba")
        self.assertEqual(self.count(guard=True), 0)
        self.requester("sklep_michal")
        self.assertEqual(self.count(guard=True), 1)

    async def test_guard_restores_threshold_when_ordinary_intent_is_satisfied(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester("prizemi_chodba_zachod", room=22, demand=92)
        self.h.set(SUPPORT, "climate.1p_chodba")
        self.h.set("input_boolean.topeni_hydraulicka_podpora_docasny_pi_prah", "on")
        self.h.set("input_number.kotel_min_zone_demand_pct", "17")
        real_now = dt_util.now()
        with patch.object(dt_util, "now", return_value=real_now + timedelta(seconds=31)):
            await self.h.run_automation(self.config(GUARD))
        self.assertEqual(self.h.hass.states.get(SUPPORT).state, "none")
        self.assertEqual(float(self.h.hass.states.get("input_number.kotel_min_zone_demand_pct").state), 70)
        self.assertFalse(any(d in ["switch", "number"] for d, s, data in self.h.calls))

    async def test_guard_keeps_original_settling_grace_without_lowering_threshold(self):
        self.h.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.requester("prizemi_chodba_zachod", room=22, demand=92)
        self.h.set(SUPPORT, "climate.1p_chodba")
        self.h.set("input_boolean.topeni_hydraulicka_podpora_docasny_pi_prah", "on")
        self.h.set("input_number.kotel_min_zone_demand_pct", "17")
        await self.h.run_automation(self.config(GUARD))
        self.assertEqual(self.h.hass.states.get(SUPPORT).state, "climate.1p_chodba")
        self.assertEqual(float(self.h.hass.states.get("input_number.kotel_min_zone_demand_pct").state), 70)

    async def test_two_real_requesters_need_no_auxiliary(self):
        self.requester("sklep_michal")
        self.requester("1p_jidelna")
        self.assertEqual(self.count(), 2)
        await self.start()
        self.assertEqual(self.calls, [])

    async def test_fixture_preserves_existing_actions_and_safety_owners(self):
        previous_start = self.config(START, previous=True)
        revised_start = self.config(START)
        previous_guard = self.config(GUARD, previous=True)
        revised_guard = self.config(GUARD)
        self.assertEqual(previous_start["action"], revised_start["action"])
        self.assertEqual(previous_start["trigger"], revised_start["trigger"])
        self.assertEqual(previous_start["condition"], revised_start["condition"][:-1])
        self.assertEqual(previous_guard["condition"], revised_guard["condition"])
        self.assertEqual(previous_guard["action"][0], revised_guard["action"][0])
        expected = deepcopy(previous_guard["action"])
        expected[3]["variables"]["real_high_count"] = revised_guard["action"][3]["variables"]["real_high_count"]
        self.assertEqual(expected, revised_guard["action"])
        original_root = runtime.read("automations.yaml")
        self.assertNotIn("kotel_v4", str([a["id"] for a in runtime.read(FIXTURE)]))
        self.assertTrue(any(a["id"] == "1791376426962" for a in original_root))
