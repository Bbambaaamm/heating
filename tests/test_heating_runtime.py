"""Isolated HA Core tests; devices and service acknowledgements are simulated.

Run: python -m unittest discover -s tests -v
HEATING_CONFIG_ROOT can point at an unchanged checkout to reproduce regressions.
No network integration, physical boiler or production HA is started.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from homeassistant.core import Context, CoreState, HomeAssistant, State
from homeassistant.config_entries import ConfigEntries
from homeassistant.setup import async_setup_component
from homeassistant.helpers import condition, trigger, entity_registry, device_registry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.helpers.script_variables import ScriptVariables
from homeassistant.helpers.template import Template
from homeassistant.helpers.trace import trace_clear, trace_get
from homeassistant.loader import async_setup
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml

ROOT = Path(os.environ.get("HEATING_CONFIG_ROOT", Path(__file__).resolve().parents[1]))
ZONES = ["sklep_michal", "prizemi_michal", "prizemi_chodba_zachod", "1p_jidelna",
         "1p_kuchyn", "1p_koupelna", "1p_chodba", "2p_mama"]
DISPATCH = "heating/control/refactor_mode_schedule_override.yaml"
BOOST = "heating/control/mode_boost.yaml"
SCHEDULE_SYNC = "heating/schedule/automation/startup/startup_schedule_sync.yaml"


def read(path):
    return load_yaml(str(ROOT / path))


def automation(path, aid):
    return next(a for a in read(path)["automation"] if a["id"] == aid)


class HeatingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.tmp.name)
        async_setup(self.hass)
        dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Prague"))
        self.calls = []
        self.fail_entity = None
        self.ignore_temperature_entity = None
        self.scripts = []
        self.set("input_select.topny_rezim", "Auto")
        self.set("sensor.heating_global_intent", "auto")
        self.set("input_boolean.topny_system_enable", "on")
        self.set("input_boolean.heating_central_dispatch_enable", "on")
        self.set("input_boolean.heating_startup_reconcile_guard", "off")
        self.set("binary_sensor.heating_dispatch_inputs_available", "on")
        self.set("binary_sensor.kotel_mode_off_block", "off")
        self.set("input_boolean.heating_debug_guard", "off")
        self.set("input_boolean.boost_now", "off")
        self.set("binary_sensor.kotel_boost_active", "off")
        self.set("input_datetime.boost_until", "2000-01-01 00:00:00")
        self.set("input_number.eco_temp_default", "15")
        self.set("input_number.boost_comfort_offset_c", "1")
        self.set("input_number.boost_minutes", "60")
        self.set("sensor.heating_schedule_windows", "ready",
                 active_helpers=[f"input_boolean.{z}_schedule_active" for z in ZONES])
        for z in ZONES:
            self.set(f"climate.{z}", "heat", temperature=18, min_temp=5, max_temp=30,
                     current_temperature=19, pi_heating_demand=30)
            self.set(f"input_number.{z}_last_comfort", "21")
            self.set(f"input_boolean.{z}_schedule_active", "on")
            self.set(f"input_boolean.schedule_enable_{z}", "on")
            self.set(f"input_boolean.{z}_manual_override", "off")
            self.set(f"input_select.{z}_manual_override_type", "Časovač")
            self.set(f"timer.{z}_manual_override", "idle")
        for domain, names in {
            "climate": ["set_temperature", "set_hvac_mode"],
            "input_boolean": ["turn_on", "turn_off"],
            "input_select": ["select_option"], "input_number": ["set_value"],
            "input_datetime": ["set_datetime"], "input_text": ["set_value"], "timer": ["cancel", "start"],
            "logbook": ["log"], "persistent_notification": ["create", "dismiss"],
            "switch": ["turn_on", "turn_off"], "number": ["set_value"],
        }.items():
            for name in names:
                self.hass.services.async_register(domain, name, self.service)
        self.hass.services.async_register("script", "heating_apply_zone_target", self.apply_service)

    async def asyncTearDown(self):
        for script in self.scripts:
            await script.async_stop()
        await self.hass.async_stop()
        self.tmp.cleanup()

    def set(self, entity, state, **attrs):
        if entity == "input_datetime.boost_until" and (parsed := dt_util.parse_datetime(state)):
            attrs.setdefault("timestamp", dt_util.as_utc(parsed).timestamp())
        self.hass.states.async_set(entity, state, attrs)

    def render(self, text, variables=None):
        return Template(text, self.hass).async_render(variables or {})

    async def service(self, call):
        data = dict(call.data)
        self.calls.append((call.domain, call.service, data))
        entity = data.get("entity_id")
        if isinstance(entity, list):
            entity = entity[0]
        if call.domain == "climate" and entity == self.fail_entity:
            raise HomeAssistantError("Injected device communication failure")
        if call.service == "set_temperature" and entity == self.ignore_temperature_entity:
            return  # Service accepted, but the device did not report the target.
        if not entity:
            return
        old = self.hass.states.get(entity)
        attrs = dict(old.attributes) if old else {}
        state = old.state if old else "unknown"
        if call.service in ("turn_on", "turn_off"):
            state = "on" if call.service == "turn_on" else "off"
        elif call.service == "set_temperature":
            attrs["temperature"] = data["temperature"]
        elif call.service == "set_hvac_mode":
            state = data["hvac_mode"]
        elif call.service == "select_option":
            state = data["option"]
        elif call.service == "set_value":
            state = str(data["value"])
        elif call.service == "set_datetime":
            state = data.get("datetime") or dt_util.as_local(
                dt_util.utc_from_timestamp(data["timestamp"])).strftime("%Y-%m-%d %H:%M:%S")
        elif call.domain == "timer":
            state = "active" if call.service == "start" else "idle"
        if call.domain == "input_datetime" and (parsed := dt_util.parse_datetime(state)):
            parsed = dt_util.as_local(dt_util.as_utc(parsed))
            attrs["timestamp"] = data.get("timestamp", parsed.timestamp())
            state = parsed.strftime("%Y-%m-%d %H:%M:%S")
        self.hass.states.async_set(entity, state, attrs, context=call.context)

    async def apply_service(self, call):
        await self.apply(**dict(call.data))

    async def run_sequence(self, sequence, variables=None, script_variables=None):
        script = Script(self.hass, cv.SCRIPT_SCHEMA(deepcopy(sequence)), "audit", "script",
                        variables=cv.SCRIPT_VARIABLES_SCHEMA(script_variables) if script_variables else None)
        self.scripts.append(script)
        await script.async_run(variables or {}, Context())

    async def run_automation(self, a, variables=None, skip_delays=True):
        seq = deepcopy(a["action"])
        if skip_delays:
            seq = [s for s in seq if "delay" not in s]
        await self.run_sequence(seq, variables, a.get("variables"))

    async def apply(self, climate_entity="climate.1p_chodba", requested_temp=21, reason="audit", **extra):
        sequence = deepcopy(read(DISPATCH)["script"]["heating_apply_zone_target"]["sequence"])
        def scale_confirmation(obj):
            if isinstance(obj, dict):
                if "wait_template" in obj and "timeout" in obj:
                    obj["timeout"] = {"milliseconds": 150}
                for value in obj.values():
                    scale_confirmation(value)
            elif isinstance(obj, list):
                for value in obj:
                    scale_confirmation(value)
        scale_confirmation(sequence)
        trace_clear()
        await self.run_sequence(sequence,
                                dict(climate_entity=climate_entity, requested_temp=requested_temp, reason=reason, **extra))
        return [entry.as_dict() for entries in (trace_get(clear=False) or {}).values() for entry in entries]

    async def assert_target_rejected(self, **kwargs):
        trace = await self.apply(**kwargs)
        self.assertTrue(any(step.get("result", {}).get("error") is True for step in trace),
                        "Rejected target must have an explicit error stop in its actual HA trace")

    async def load_automations(self, automations, *, startup=False):
        self.hass.config_entries = ConfigEntries(self.hass, {})
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass, load_empty=True)
        await entity_registry.async_load(self.hass, load_empty=True)
        await trigger.async_setup(self.hass)
        await condition.async_setup(self.hass)
        self.hass.set_state(CoreState.not_running if startup else CoreState.running)
        self.assertTrue(await async_setup_component(self.hass, "automation", {"automation": automations}))
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.hass.states.async_all("automation")), len(automations))

    def boiler_inputs(self, requested=True, relay="off"):
        for entity, value in {
            "binary_sensor.kotel_threshold_all_ok": "on" if requested else "off",
            "binary_sensor.kotel_should_be_on": "on" if requested else "off",
            "sensor.kotel_effective_on_delay_sec": "120",
            "sensor.kotel_effective_off_delay_sec": "300",
            "switch.kotel_rele_spinac": relay,
        }.items():
            self.set(entity, value)

    def fast_boiler(self, aid):
        a = automation("heating/control/kotel_control.yaml", aid)
        # Only wall-clock duration is scaled, not triggers, conditions or actions.
        def scale(obj):
            if isinstance(obj, dict):
                if "delay" in obj:
                    obj["delay"] = {"milliseconds": 70}
                for value in obj.values():
                    scale(value)
            elif isinstance(obj, list):
                for value in obj:
                    scale(value)
        scale(a)
        return a

    def expanded_blueprint(self, name, inputs):
        b = read(f"blueprints/automation/heating/{name}.yaml")
        values = {k: v.get("default") for k, v in b["blueprint"]["input"].items()}
        values.update(inputs)
        def expand(obj):
            if type(obj).__name__ == "Input":
                return values[obj.name]
            if isinstance(obj, dict):
                return {k: expand(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [expand(v) for v in obj]
            return obj
        b.pop("blueprint")
        return expand(b)

    def writes(self, domain="climate", service="set_temperature"):
        return [c for c in self.calls if c[:2] == (domain, service)]

    async def test_valid_climate_receives_mode_and_temperature(self):
        self.set("climate.1p_chodba", "off", temperature=18, min_temp=5, max_temp=30)
        await self.apply()
        self.assertEqual(len(self.writes(service="set_hvac_mode")), 1)
        self.assertEqual(self.writes()[0][2]["temperature"], 21)

    async def test_missing_temperature_attribute_is_not_equal_to_target(self):
        self.set("climate.1p_chodba", "heat", min_temp=5, max_temp=30)
        await self.apply()
        self.assertEqual(len(self.writes()), 1)

    async def test_idempotent_target_does_not_write_again(self):
        await self.apply()
        await self.apply()
        self.assertEqual(len(self.writes()), 1)

    async def test_unacknowledged_target_reports_failure_without_debug(self):
        self.ignore_temperature_entity = "climate.1p_chodba"
        await self.assert_target_rejected()
        self.assertEqual(len(self.writes()), 1, "No blind retry of an old target")
        notices = self.writes("persistent_notification", "create")
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0][2]["notification_id"], "heating_target_1p_chodba")
        self.assertFalse(any("potvrzen" in c[2].get("message", "").lower()
                             for c in self.writes("logbook", "log")))

    async def test_delayed_target_report_is_confirmed(self):
        self.ignore_temperature_entity = "climate.1p_chodba"
        task = asyncio.create_task(self.apply())
        try:
            await asyncio.sleep(0.03)
            self.assertFalse(task.done(), "Service acceptance is not confirmation")
            self.set("climate.1p_chodba", "heat", temperature=21, min_temp=5, max_temp=30)
            await task
            self.assertEqual(self.writes("persistent_notification", "create"), [])
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_superseded_target_does_not_raise_false_alarm(self):
        self.ignore_temperature_entity = "climate.1p_chodba"
        task = asyncio.create_task(self.apply())
        await asyncio.sleep(0.03)
        self.set("input_select.topny_rezim", "Eco")
        await task
        self.assertEqual(self.writes("persistent_notification", "create"), [])
        self.assertEqual(self.writes("persistent_notification", "dismiss"), [])
        self.assertEqual(self.writes("logbook", "log"), [])

    async def test_disconnected_device_is_not_confirmed_from_stale_attribute(self):
        async def disconnected(call):
            self.calls.append((call.domain, call.service, dict(call.data)))
            self.set("climate.1p_chodba", "unavailable", temperature=21)
        self.hass.services.async_register("climate", "set_temperature", disconnected)
        await self.assert_target_rejected()
        self.assertEqual(len(self.writes("persistent_notification", "create")), 1)

    async def test_unacknowledged_hvac_mode_is_not_success_when_target_matches(self):
        self.set("climate.1p_chodba", "off", temperature=21, min_temp=5, max_temp=30)
        async def ignored_mode(call):
            self.calls.append((call.domain, call.service, dict(call.data)))
        self.hass.services.async_register("climate", "set_hvac_mode", ignored_mode)
        await self.assert_target_rejected()
        self.assertEqual(self.writes(), [])

    async def test_confirmed_idempotent_target_clears_previous_failure(self):
        self.set("climate.1p_chodba", "heat", temperature=21, min_temp=5, max_temp=30)
        await self.apply()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.writes("persistent_notification", "dismiss")[0][2]["notification_id"],
                         "heating_target_1p_chodba")

    async def test_unacknowledged_first_zone_does_not_skip_remaining_zones(self):
        self.ignore_temperature_entity = "climate.sklep_michal"
        await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
        self.assertEqual(len(self.writes("persistent_notification", "create")), 1)
        for z in ZONES[1:]:
            self.assertEqual(self.hass.states.get(f"climate.{z}").attributes["temperature"], 21)

    async def test_target_clamped_to_device_limits(self):
        await self.apply(requested_temp=99)
        self.assertEqual(self.writes()[0][2]["temperature"], 30)

    async def test_invalid_targets_and_unavailable_device_never_write(self):
        for value in (None, "unknown", "nan", "inf", "bad"):
            await self.assert_target_rejected(requested_temp=value)
        self.set("climate.1p_chodba", "unavailable")
        await self.assert_target_rejected()
        self.assertEqual(self.writes(), [])
        self.assertEqual(len(self.writes("logbook", "log")), 6)

    async def test_disabled_system_cannot_apply_queued_target(self):
        self.set("input_boolean.topny_system_enable", "off")
        await self.apply()
        self.assertEqual(self.writes(), [])

    async def test_old_intent_cannot_overwrite_new_mode(self):
        a = automation(DISPATCH, "heating_dispatch_mode_schedule_override")
        seq = deepcopy(a["action"])
        seq[0] = {"delay": {"milliseconds": 30}}
        task = asyncio.create_task(self.run_sequence(seq, {}, a["variables"]))
        await asyncio.sleep(0.01)
        self.set("input_select.topny_rezim", "Off")
        self.set("sensor.heating_global_intent", "off")
        await task
        self.assertEqual(self.writes(), [])

    async def test_failure_of_first_zone_does_not_skip_other_seven(self):
        self.fail_entity = "climate.sklep_michal"
        await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
        for z in ZONES[1:]:
            self.assertEqual(self.hass.states.get(f"climate.{z}").attributes["temperature"], 21)

    async def test_dispatch_priority_manual_boost_eco_schedule(self):
        for intent, mode, expected in [("auto", "Auto", 21), ("eco", "Eco", 15), ("boost", "Boost", 22)]:
            self.set("sensor.heating_global_intent", intent)
            self.set("input_select.topny_rezim", mode)
            self.set("binary_sensor.kotel_boost_active", "on" if intent == "boost" else "off")
            await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
            self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], expected)
        self.set("input_boolean.1p_chodba_manual_override", "on")
        self.set("timer.1p_chodba_manual_override", "active")
        await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
        self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], 21)

    async def test_boost_expiry_includes_mode_only_start(self):
        a = automation(BOOST, "heating_boost_auto_clear_button")
        self.set("input_select.topny_rezim", "Boost")
        values = [self.render(c["value_template"]) for c in a["condition"] if c["condition"] == "template"]
        self.assertTrue(all(values), "Expired mode Boost must be cleared even with button off")

    async def test_boost_start_rejects_restore_transition(self):
        a = automation(BOOST, "heating_boost_start")
        self.set("input_boolean.boost_now", "on")
        from_state = None
        values = [self.render(c["value_template"], {"trigger": {"from_state": from_state}})
                  for c in a.get("condition", []) if c["condition"] == "template"]
        self.assertTrue(values and not all(values), "Restore must not create a new deadline")

    async def test_boost_start_accepts_explicit_user_restart(self):
        a = automation(BOOST, "heating_boost_start")
        values = [self.render(c["value_template"], {"trigger": {"from_state": {"state": "off"}}})
                  for c in a.get("condition", []) if c["condition"] == "template"]
        self.assertTrue(all(values))
        await self.run_automation(a)
        deadline = self.hass.states.get("input_datetime.boost_until").state
        self.assertAlmostEqual((dt_util.as_local(dt_util.as_utc(dt_util.parse_datetime(deadline))) - dt_util.now()).total_seconds(), 3600, delta=2)

    async def test_startup_auto_does_not_cancel_unexpired_boost(self):
        a = automation("heating/control/mode_auto.yaml", "heating_auto_apply_on")
        self.set("input_datetime.boost_until", (dt_util.now() + timedelta(minutes=20)).isoformat())
        self.set("binary_sensor.kotel_boost_active", "on")
        self.assertFalse(any(t.get("trigger") == "homeassistant" for t in a["trigger"]),
                         "Startup recovery belongs to reconcile, not Auto activation")

    async def test_startup_boost_does_not_turn_button_on_and_rearm(self):
        until = (dt_util.now() + timedelta(minutes=20)).isoformat()
        self.set("input_datetime.boost_until", until)
        await self.run_automation(automation("heating/control/reliability_failsafe.yaml", "heating_startup_reconcile_boost"))
        self.assertEqual(self.hass.states.get("input_boolean.boost_now").state, "off")
        self.assertEqual(self.hass.states.get("input_datetime.boost_until").state, until)

    async def test_cancel_boost_clears_deadline_and_mode(self):
        a = automation(BOOST, "heating_boost_cancel")
        self.set("input_datetime.boost_until", (dt_util.now() + timedelta(minutes=20)).isoformat())
        self.set("input_select.topny_rezim", "Boost")
        self.set("input_boolean.boost_now", "on")
        self.set("input_boolean.boost_now", "off")
        await self.run_automation(a, {"trigger": {
            "id": "button_off", "to_state": self.hass.states.get("input_boolean.boost_now")}})
        self.assertLessEqual(self.hass.states.get("input_datetime.boost_until").attributes["timestamp"], dt_util.now().timestamp())
        self.assertNotEqual(self.hass.states.get("input_select.topny_rezim").state, "Boost")

    async def test_startup_request_follows_guard_release(self):
        a = automation("heating/schedule/automation/startup/startup_schedule_sync.yaml", "heating_startup_schedule_sync")
        guard_at_request = []
        unsub = self.hass.bus.async_listen("heating_reconcile_requested", lambda e: guard_at_request.append(
            self.hass.states.get("input_boolean.heating_startup_reconcile_guard").state))
        await self.run_automation(a)
        await self.hass.async_block_till_done()
        unsub()
        self.assertEqual(guard_at_request, ["off"])

    async def test_timed_manual_restores_and_old_timer_cannot_cancel_new_type(self):
        helpers = read("heating/schedule/preferences/helpers/manual_override_helpers.yaml")
        self.assertTrue(all((helpers["timer"][f"{z}_manual_override"] or {}).get("restore") for z in ZONES))
        a = automation("heating/ui/controls/heating_timer_logic.yaml", "heating_timer_finished_turn_off_manual")
        z = "1p_chodba"
        self.set(f"input_boolean.{z}_manual_override", "on")
        self.set(f"input_select.{z}_manual_override_type", "Do další změny rozvrhu")
        await self.run_automation(a, {"trigger": {"entity_id": f"timer.{z}_manual_override"}})
        self.assertEqual(self.hass.states.get(f"input_boolean.{z}_manual_override").state, "on")

    async def test_disabled_mode_and_master_restore_instead_of_forced_on(self):
        c = read("heating/ui/controls/mode_controls.yaml")
        self.assertNotIn("initial", c["input_select"]["topny_rezim"])
        self.assertNotIn("initial", c["input_boolean"]["topny_system_enable"])

    async def test_ui_missing_temperature_is_unavailable_not_zero(self):
        sensors = read("heating/ui/dashboards/heating_templates.yaml")["template"][0]["sensor"][:8]
        for z in ZONES:
            self.set(f"climate.{z}", "unknown")
        self.assertTrue(all(self.render(s["availability"]) is False for s in sensors))

    async def test_real_ha_loader_includes_nested_packages(self):
        c = read("configuration.yaml")
        self.assertEqual(len(c["homeassistant"]["packages"]), 49)
        self.assertIn("heating_analytics", c["homeassistant"]["packages"])
        self.assertIn("vrata_ui_template", c["homeassistant"]["packages"])

    async def test_each_zone_demand_boundaries_and_window_priority(self):
        for z in ZONES:
            templates = read(f"heating/core/zone_{z}.yaml")["template"]
            demand = templates[0]["sensor"][0]
            active = templates[1]["binary_sensor"][1]
            self.assertEqual(self.render(demand["state"]), 30)
            self.set(f"sensor.zona_{z}_demand", "1")
            self.assertFalse(self.render(active["state"]))
            self.set(f"sensor.zona_{z}_demand", "2")
            self.set("input_boolean.kotel_ignore_open_windows", "off")
            self.set(f"binary_sensor.zona_{z}_okno_otevrene", "on")
            self.assertFalse(self.render(active["state"]))
            self.set("input_boolean.kotel_ignore_open_windows", "on")
            self.assertTrue(self.render(active["state"]))

    async def test_one_and_multiple_zones_aggregate(self):
        self.set("group.topne_zony", "on", entity_id=[f"climate.{z}" for z in ZONES])
        self.set("input_number.kotel_min_zone_demand_pct", "5")
        for z in ZONES:
            self.set(f"binary_sensor.zona_{z}_aktivni", "off")
            self.set(f"sensor.zona_{z}_demand", "0")
        sensors = read("heating/core/aggregate_kotel.yaml")["template"][0]["sensor"]
        for count in (1, 2, 8):
            for z in ZONES[:count]:
                self.set(f"binary_sensor.zona_{z}_aktivni", "on")
                self.set(f"sensor.zona_{z}_demand", "30")
            self.assertEqual([self.render(s["state"]) for s in sensors], [count, 30, 30])

    async def test_boost_never_relaxes_boiler_flow_safety_policy(self):
        sensors = {s["unique_id"]: s for s in read("heating/policy/policy_effective.yaml")["template"][0]["sensor"]}
        self.set("input_select.topny_rezim", "Auto")
        self.set("binary_sensor.kotel_boost_active", "on")
        self.set("input_number.kotel_min_avg_demand_pct", "0")
        self.set("input_number.kotel_min_active_zones", "0")
        self.set("input_number.kotel_on_delay_sec", "0")
        self.set("input_number.kotel_off_delay_sec", "999")
        self.assertEqual(self.render(sensors["kotel_effective_min_avg_demand_pct"]["state"]), 15)
        self.assertEqual(self.render(sensors["kotel_effective_min_active_zones"]["state"]), 2)
        self.assertEqual(self.render(sensors["kotel_effective_on_delay_sec"]["state"]), 120)
        self.assertEqual(self.render(sensors["kotel_effective_off_delay_sec"]["state"]), 30)

    async def test_relay_timing_has_independent_hard_safety_bounds(self):
        turn_on = automation("heating/control/kotel_control.yaml", "kotel_turn_on_by_policy")
        turn_off = automation("heating/control/kotel_control.yaml", "kotel_turn_off_by_policy")
        self.set("sensor.kotel_effective_on_delay_sec", "0")
        self.set("sensor.kotel_effective_off_delay_sec", "999")
        on_delay = next(step["delay"]["seconds"] for step in turn_on["action"] if "delay" in step)
        off_delay = next(step["delay"]["seconds"] for step in turn_off["action"] if "delay" in step)
        self.assertEqual(self.render(on_delay), 120)
        self.assertEqual(self.render(off_delay), 30)

    async def test_boiler_on_delay_survives_boost_attribute_reports(self):
        self.boiler_inputs(requested=False)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.boiler_inputs(requested=True)
        for minute in range(8):
            self.set("binary_sensor.kotel_boost_active", "off", remaining_min=minute)
            await asyncio.sleep(0.02)
        self.assertEqual(self.hass.states.get("switch.kotel_rele_spinac").state, "on")

    async def test_last_demand_off_delay_survives_boost_attribute_reports(self):
        self.boiler_inputs(requested=True, relay="on")
        await self.load_automations([self.fast_boiler("kotel_turn_off_by_policy")])
        self.boiler_inputs(requested=False, relay="on")
        for minute in range(8):
            self.set("binary_sensor.kotel_boost_active", "off", remaining_min=minute)
            await asyncio.sleep(0.02)
        self.assertEqual(self.hass.states.get("switch.kotel_rele_spinac").state, "off")

    async def test_policy_revoked_while_waiting_cannot_turn_on(self):
        self.boiler_inputs(requested=False)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.boiler_inputs(requested=True)
        await asyncio.sleep(0.02)
        self.boiler_inputs(requested=False)
        await asyncio.sleep(0.10)
        self.assertEqual(self.writes("switch", "turn_on"), [])

    async def test_policy_returns_while_waiting_cannot_turn_off(self):
        self.boiler_inputs(requested=True, relay="on")
        await self.load_automations([self.fast_boiler("kotel_turn_off_by_policy")])
        self.boiler_inputs(requested=False, relay="on")
        await asyncio.sleep(0.02)
        self.boiler_inputs(requested=True, relay="on")
        await asyncio.sleep(0.10)
        self.assertEqual(self.writes("switch", "turn_off"), [])

    async def test_boiler_pending_start_is_cancelled_immediately_on_lost_demand(self):
        self.boiler_inputs(requested=False)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.boiler_inputs(requested=True)
        await asyncio.sleep(0.02)
        self.set("binary_sensor.kotel_should_be_on", "unavailable")
        await asyncio.sleep(0.015)
        a = self.hass.states.async_all("automation")[0]
        self.assertEqual(a.attributes["current"], 0)
        self.assertEqual(self.writes("switch", "turn_on"), [])

    async def test_boiler_pending_stop_is_cancelled_immediately_on_returned_demand(self):
        self.boiler_inputs(requested=True, relay="on")
        await self.load_automations([self.fast_boiler("kotel_turn_off_by_policy")])
        self.boiler_inputs(requested=False, relay="on")
        await asyncio.sleep(0.02)
        self.boiler_inputs(requested=True, relay="on")
        await asyncio.sleep(0.015)
        a = self.hass.states.async_all("automation")[0]
        self.assertEqual(a.attributes["current"], 0)
        self.assertEqual(self.writes("switch", "turn_off"), [])

    async def test_boiler_cannot_start_with_stale_decision_after_mode_off(self):
        self.boiler_inputs(requested=False)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.boiler_inputs(requested=True)
        await asyncio.sleep(0.02)
        # Deliberately hold derived policy sensors at their old values.
        self.set("input_select.topny_rezim", "Off")
        await asyncio.sleep(0.10)
        self.assertEqual(self.writes("switch", "turn_on"), [])

    async def test_boiler_cannot_start_with_direct_off_block(self):
        self.boiler_inputs(requested=True)
        self.set("binary_sensor.kotel_mode_off_block", "on")
        await self.run_automation(automation("heating/control/kotel_control.yaml", "kotel_turn_on_by_policy"))
        self.assertEqual(self.writes("switch", "turn_on"), [])

    async def test_new_boiler_request_gets_full_delay_after_interruption(self):
        self.boiler_inputs(requested=False)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.boiler_inputs(requested=True)
        await asyncio.sleep(0.04)
        self.boiler_inputs(requested=False)
        await asyncio.sleep(0.01)
        self.boiler_inputs(requested=True)
        await asyncio.sleep(0.04)
        self.assertEqual(self.writes("switch", "turn_on"), [])
        await asyncio.sleep(0.06)
        self.assertEqual(len(self.writes("switch", "turn_on")), 1)

    async def test_boiler_policy_restores_all_operator_values(self):
        restored = dict(kotel_min_avg_demand_pct=35, kotel_min_zone_demand_pct=12,
                        kotel_min_active_zones=3, kotel_on_delay_sec=240,
                        kotel_off_delay_sec=420)
        async def last_state(entity):
            key = entity.entity_id.split(".")[1]
            return State(entity.entity_id, str(restored[key])) if key in restored else None
        self.hass.config_entries = ConfigEntries(self.hass, {})
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass, load_empty=True)
        await entity_registry.async_load(self.hass, load_empty=True)
        with patch("homeassistant.helpers.restore_state.RestoreEntity.async_get_last_state", new=last_state):
            self.assertTrue(await async_setup_component(self.hass, "input_number",
                            read("heating/policy/policy_config.yaml")))
            await self.hass.async_block_till_done()
        for key, value in restored.items():
            self.assertEqual(float(self.hass.states.get(f"input_number.{key}").state), value)

    async def test_switched_off_zones_do_not_keep_boiler_demand_from_stale_pi(self):
        for z in ZONES:
            t = read(f"heating/core/zone_{z}.yaml")["template"][0]["sensor"][0]
            self.set(f"climate.{z}", "off", pi_heating_demand=100)
            self.assertEqual(self.render(t["state"]), 0, z)
            self.set(f"climate.{z}", "heat", pi_heating_demand=30)
            self.assertEqual(self.render(t["state"]), 30, z)

    async def test_calendar_and_window_choices_survive_restart(self):
        helpers = {}
        for z in ZONES:
            helpers.update(read(f"heating/schedule/preferences/helpers/schedule_helpers_{z}.yaml")["input_boolean"])
        controls = read("heating/ui/controls/mode_controls.yaml")["input_boolean"]
        helpers["kotel_ignore_open_windows"] = controls["kotel_ignore_open_windows"]
        dispatch = read(DISPATCH)["input_boolean"]
        helpers.update(dispatch)
        for key in helpers:
            self.hass.states.async_remove(f"input_boolean.{key}")
        async def last_state(entity):
            return State(entity.entity_id, "off")
        self.hass.config_entries = ConfigEntries(self.hass, {})
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass, load_empty=True)
        await entity_registry.async_load(self.hass, load_empty=True)
        with patch("homeassistant.helpers.restore_state.RestoreEntity.async_get_last_state", new=last_state):
            self.assertTrue(await async_setup_component(self.hass, "input_boolean", {"input_boolean": helpers}))
            await self.hass.async_block_till_done()
        for key in helpers:
            expected = "on" if key == "heating_startup_reconcile_guard" else "off"
            self.assertEqual(self.hass.states.get(f"input_boolean.{key}").state, expected, key)

    async def test_eco_and_boost_settings_survive_restart(self):
        restored = dict(eco_temp_default=16.5, boost_minutes=30, boost_comfort_offset_c=2)
        helpers = read("heating/ui/controls/mode_controls.yaml")["input_number"]
        for key in helpers:
            self.hass.states.async_remove(f"input_number.{key}")
        async def last_state(entity):
            return State(entity.entity_id, str(restored[entity.entity_id.split(".")[1]]))
        self.hass.config_entries = ConfigEntries(self.hass, {})
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass, load_empty=True)
        await entity_registry.async_load(self.hass, load_empty=True)
        with patch("homeassistant.helpers.restore_state.RestoreEntity.async_get_last_state", new=last_state):
            self.assertTrue(await async_setup_component(self.hass, "input_number", {"input_number": helpers}))
            await self.hass.async_block_till_done()
        for key, value in restored.items():
            self.assertEqual(float(self.hass.states.get(f"input_number.{key}").state), value, key)

    async def test_relay_reconnect_reapplies_unfulfilled_request(self):
        self.boiler_inputs(requested=True, relay="unavailable")
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.set("switch.kotel_rele_spinac", "off")
        await asyncio.sleep(0.10)
        self.assertEqual(self.hass.states.get("switch.kotel_rele_spinac").state, "on")

    async def test_reload_reconciles_relay_with_current_demand(self):
        self.boiler_inputs(requested=True)
        await self.load_automations([self.fast_boiler("kotel_turn_on_by_policy")])
        self.hass.bus.async_fire("automation_reloaded")
        await asyncio.sleep(0.10)
        self.assertEqual(self.hass.states.get("switch.kotel_rele_spinac").state, "on")

    async def test_zero_zones_cannot_heat_with_zero_thresholds(self):
        self.set("binary_sensor.kotel_threshold_all_ok", "on")
        self.set("sensor.kotel_aktivni_zony_pocet", "0")
        t = read("heating/core/aggregate_kotel.yaml")["template"][1]["binary_sensor"][0]
        self.assertFalse(self.render(t["state"]))

    async def test_failsafe_must_not_reenable_explicit_off(self):
        self.set("input_select.topny_rezim", "Off")
        await self.run_automation(automation("heating/control/reliability_failsafe.yaml", "heating_failsafe_helpers_unavailable"))
        self.assertEqual(self.hass.states.get("input_select.topny_rezim").state, "Off")

    async def test_input_change_during_hvac_io_blocks_old_temperature(self):
        self.set("climate.1p_chodba", "off", temperature=18, min_temp=5, max_temp=30)
        async def slow_mode(call):
            await asyncio.sleep(0.04)
            await self.service(call)
        self.hass.services.async_register("climate", "set_hvac_mode", slow_mode)
        task = asyncio.create_task(self.apply())
        await asyncio.sleep(0.015)
        self.set("input_number.1p_chodba_last_comfort", "24")
        await task
        self.assertEqual(self.writes(), [])

    async def test_climate_reconnect_receives_current_target(self):
        self.set("climate.1p_chodba", "unavailable")
        a = automation(DISPATCH, "heating_dispatch_mode_schedule_override")
        a["action"][0] = {"delay": {"milliseconds": 15}}
        await self.load_automations([a])
        self.set("climate.1p_chodba", "heat", temperature=18, min_temp=5, max_temp=30)
        await asyncio.sleep(0.10)
        self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], 21)

    async def test_demand_stale_data_and_recovery_for_all_zones(self):
        for z in ZONES:
            t = read(f"heating/core/zone_{z}.yaml")["template"][0]["sensor"][0]
            with patch("homeassistant.util.dt.now", return_value=dt_util.now() + timedelta(minutes=121)):
                self.assertEqual(self.render(t["state"]), 0)
            self.set(f"climate.{z}", "unknown")
            self.assertFalse(self.render(t["availability"]))
            self.set(f"climate.{z}", "heat", pi_heating_demand=30)
            self.assertTrue(self.render(t["availability"]))
            self.assertEqual(self.render(t["state"]), 30)

    async def test_manual_watchdog_uses_persisted_activation_after_restart(self):
        self.set("input_boolean.1p_chodba_manual_override", "on")
        self.set("input_text.1p_chodba_manual_override_started", (dt_util.now() - timedelta(hours=25)).isoformat())
        await self.run_automation(automation("heating/control/watchdog_manual_override.yaml", "heating_watchdog_manual_override"))
        self.assertEqual(self.hass.states.get("input_boolean.1p_chodba_manual_override").state, "off")

    async def test_efficiency_score_has_no_drop_at_five_minutes(self):
        sensors = read("heating/analysis/heating_analytics.yaml")["template"][0]["sensor"]
        score = next(s for s in sensors if s.get("unique_id") == "kotel_efficiency_score")
        values = []
        for avg in [0, 4.9, 5, 5.1, 20, 30]:
            self.set("sensor.kotel_avg_cycle_min_24h", str(avg))
            values.append(self.render(score["state"]))
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(0 <= v <= 100 for v in values))

    async def test_boost_ui_counts_effective_override_only(self):
        self.set("group.topne_zony", "on", entity_id=["climate.1p_chodba"])
        self.set("binary_sensor.kotel_boost_active", "on")
        self.set("input_boolean.1p_chodba_manual_override", "on")
        self.set("timer.1p_chodba_manual_override", "paused")
        t = read("heating/ui/dashboards/heating_templates.yaml")["template"][0]["sensor"][8]
        self.assertEqual(self.render(t["state"]), 0)
        self.assertEqual(self.render(t["attributes"]["blocked_zones"]), [])

    async def test_external_sensor_cooldown_and_trailing_retry(self):
        a = self.expanded_blueprint("danfoss_external_sensor", {
            "zone_name": "test", "source_temp_sensor": "sensor.external",
            "danfoss_external_temp_number": "number.external",
            "danfoss_prefer_external_switch": "switch.external",
        })
        self.set("sensor.external", "21")
        self.set("number.external", "18")
        self.set("switch.external", "off")
        await self.run_automation(a)
        self.assertEqual(self.writes("number", "set_value"), [])
        self.assertEqual(self.hass.states.get("switch.external").state, "off")
        self.assertTrue(any(t.get("platform") == "time_pattern" for t in a["trigger"]))
        with patch("homeassistant.util.dt.now", return_value=dt_util.now() + timedelta(seconds=121)):
            await self.run_automation(a)
        self.assertEqual(self.writes("number", "set_value")[0][2]["value"], 21)
        self.assertEqual(self.hass.states.get("switch.external").state, "on")

    async def test_external_sensor_invalid_value_never_sent(self):
        a = self.expanded_blueprint("danfoss_external_sensor", {
            "zone_name": "test", "source_temp_sensor": "sensor.external",
            "danfoss_external_temp_number": "number.external",
            "danfoss_prefer_external_switch": "switch.external",
        })
        self.set("number.external", "18"); self.set("switch.external", "on")
        for bad in ["unknown", "unavailable", "NaN", "3", "36"]:
            self.set("sensor.external", bad)
            await self.run_automation(a)
        self.assertEqual(self.writes("number", "set_value"), [])

    async def test_gate_is_unavailable_when_source_is_unavailable(self):
        t = read("heating/vrata/vrata_ui_template.yaml")["template"][0]["cover"][0]
        self.set("cover.vrata_gatebox_position", "unavailable")
        self.assertFalse(self.render(t.get("availability", "{{ true }}")))

    async def test_fallback_manual_change_captured_before_reapply(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.1p_chodba")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("input_boolean.1p_chodba_manual_override", "on")
        self.set("timer.1p_chodba_manual_override", "active")
        before = self.hass.states.get("climate.1p_chodba")
        self.hass.states.async_set("climate.1p_chodba", "heat", {"temperature": 23, "min_temp": 5, "max_temp": 30}, context=Context(user_id="audit_user"))
        after = self.hass.states.get("climate.1p_chodba")
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "climate.1p_chodba", "from_state": before, "to_state": after}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("input_number.1p_chodba_last_comfort").state, "23.0")
        self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], 23)

    async def test_parentless_zigbee_ack_of_policy_target_is_not_manual_override(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.prizemi_michal")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_number.prizemi_michal_last_comfort", "20")
        self.set("binary_sensor.kotel_boost_active", "on")
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        before = self.hass.states.get("climate.prizemi_michal")
        self.hass.states.async_set("climate.prizemi_michal", "heat",
                                  dict(before.attributes, temperature=21), context=Context())
        after = self.hass.states.get("climate.prizemi_michal")
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "climate.prizemi_michal",
                                  "from_state": before, "to_state": after},
                                  "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("input_boolean.prizemi_michal_manual_override").state, "off")

        # A different parentless target is still a genuine physical-head change.
        before = after
        self.hass.states.async_set("climate.prizemi_michal", "heat",
                                  dict(before.attributes, temperature=22), context=Context())
        after = self.hass.states.get("climate.prizemi_michal")
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "climate.prizemi_michal",
                                  "from_state": before, "to_state": after},
                                  "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("input_boolean.prizemi_michal_manual_override").state, "on")

    async def test_low_flow_fault_stops_relay_before_opening_all_valves(self):
        self.set("switch.kotel_rele_spinac", "on")
        self.set("input_boolean.boost_now", "on")
        self.set("input_boolean.heating_service_mode", "off")
        a = automation("heating/control/reliability_failsafe.yaml", "heating_boiler_low_flow_package_guard")
        await self.run_automation(a, {"trigger": {"id": "2964"}})
        self.assertEqual(self.hass.states.get("switch.kotel_rele_spinac").state, "off")
        self.assertEqual(self.hass.states.get("input_boolean.topny_system_enable").state, "off")
        self.assertEqual(self.hass.states.get("input_boolean.boost_now").state, "off")
        self.assertEqual(self.hass.states.get("input_boolean.heating_service_mode").state, "on")
        for z in ZONES:
            self.assertEqual(self.hass.states.get(f"climate.{z}").attributes["temperature"], 29)
        first_control = next(c for c in self.calls if c[0] in ["switch", "climate"])
        self.assertEqual(first_control[:2], ("switch", "turn_off"))

    async def test_service_mode_package_guard_is_fast_and_independent(self):
        guard = automation(
            "heating/control/reliability_failsafe.yaml",
            "heating_service_mode_package_hard_guard",
        )
        self.assertEqual(guard["mode"], "parallel")
        self.assertEqual(
            [step["action"] for step in guard["action"]],
            ["switch.turn_off", "input_boolean.turn_off"],
        )
        self.assertNotIn("climate", str(guard["action"]))

    async def test_fallback_schedule_transition_ends_manual_without_old_target(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.1p_chodba")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("input_boolean.1p_chodba_manual_override", "on")
        self.set("input_select.1p_chodba_manual_override_type", "Do další změny rozvrhu")
        self.set("input_boolean.1p_chodba_schedule_active", "off")
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "input_boolean.1p_chodba_schedule_active"}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("input_boolean.1p_chodba_manual_override").state, "off")
        self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], 15)

    async def test_actual_boost_events_cancel_on_system_off(self):
        await self.load_automations([automation(BOOST, aid) for aid in ["heating_boost_start", "heating_boost_cancel"]])
        self.set("input_boolean.boost_now", "on")
        await self.hass.async_block_till_done()
        deadline = self.hass.states.get("input_datetime.boost_until").state
        self.assertGreater(dt_util.as_local(dt_util.as_utc(dt_util.parse_datetime(deadline))), dt_util.now())
        self.set("input_boolean.topny_system_enable", "off")
        await self.hass.async_block_till_done()
        self.set("input_boolean.topny_system_enable", "on")
        boost = read(BOOST)["template"][0]["binary_sensor"][0]
        self.assertFalse(self.render(boost["state"]))

    async def test_rapid_boost_on_off_on_preserves_latest_request(self):
        await self.load_automations([automation(BOOST, aid) for aid in ["heating_boost_start", "heating_boost_cancel"]])
        for value in ["on", "off", "on"]:
            self.set("input_boolean.boost_now", value)
        await self.hass.async_block_till_done()
        deadline = self.hass.states.get("input_datetime.boost_until").state
        self.assertGreater(dt_util.as_local(dt_util.as_utc(dt_util.parse_datetime(deadline))), dt_util.now() + timedelta(minutes=59))
        self.assertEqual(self.hass.states.get("input_boolean.boost_now").state, "on")

    async def test_duplicate_boost_state_does_not_extend_deadline(self):
        await self.load_automations([automation(BOOST, "heating_boost_start")])
        self.set("input_boolean.boost_now", "on")
        await self.hass.async_block_till_done()
        deadline = self.hass.states.get("input_datetime.boost_until").state
        self.set("input_boolean.boost_now", "on")
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("input_datetime.boost_until").state, deadline)
        self.assertEqual(len(self.writes("input_datetime", "set_datetime")), 1)

    async def test_boost_cancel_rechecks_after_service_yields_to_new_request(self):
        self.set("input_boolean.boost_now", "on")
        self.set("input_boolean.boost_now", "off")
        cancelled_state = self.hass.states.get("input_boolean.boost_now")
        restarted = False

        async def restart_after_clear(call):
            nonlocal restarted
            await self.service(call)
            if not restarted:
                restarted = True
                self.set("input_boolean.boost_now", "on")
                await self.run_automation(automation(BOOST, "heating_boost_start"))

        self.hass.services.async_register("input_text", "set_value", restart_after_clear)
        await self.run_automation(automation(BOOST, "heating_boost_cancel"), {
            "trigger": {"id": "button_off", "to_state": cancelled_state}})
        self.assertEqual(self.hass.states.get("input_boolean.boost_now").state, "on")
        self.assertGreater(self.hass.states.get("input_datetime.boost_until").attributes["timestamp"],
                           dt_util.now().timestamp() + 59 * 60)

    async def test_old_button_cancel_cannot_clear_new_mode_boost(self):
        self.set("input_boolean.boost_now", "on")
        self.set("input_boolean.boost_now", "off")
        cancelled_state = self.hass.states.get("input_boolean.boost_now")
        self.set("input_select.topny_rezim", "Boost")
        await self.run_automation(automation(BOOST, "heating_boost_start"))
        deadline = self.hass.states.get("input_datetime.boost_until").state
        await self.run_automation(automation(BOOST, "heating_boost_cancel"), {
            "trigger": {"id": "button_off", "to_state": cancelled_state}})
        self.assertEqual(self.hass.states.get("input_select.topny_rezim").state, "Boost")
        self.assertEqual(self.hass.states.get("input_datetime.boost_until").state, deadline)

    async def test_boost_is_inactive_at_exact_deadline_without_latches(self):
        now = dt_util.now()
        self.set("input_datetime.boost_until", now.isoformat())
        boost = read(BOOST)["template"][0]["binary_sensor"][0]
        with patch("homeassistant.util.dt.now", return_value=now):
            self.assertFalse(self.render(boost["state"]))

    async def test_watchdog_signature_ignores_age_but_covers_all_valves(self):
        a = automation("heating/control/watchdog_connectivity.yaml", "heating_watchdog_connectivity")
        t = a["action"][0]["variables"]["signature"]
        items = [{"climate_entity": f"climate.{z}", "climate_age_minutes": 190} for z in ZONES]
        before = self.render(t, {"items": items})
        for item in items:
            item["climate_age_minutes"] = 200
        self.assertEqual(before, self.render(t, {"items": items}))
        self.assertNotEqual(before, self.render(t, {"items": items[:-1]}))
        self.assertLessEqual(len(before), 255)

    async def test_disabled_system_blocks_fallback_writes(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.1p_chodba")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("input_boolean.topny_system_enable", "off")
        await self.run_automation(a, {"trigger": {"platform": "event"}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.writes(), [])

    async def test_fallback_missing_temperature_is_reapplied(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.1p_chodba")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("climate.1p_chodba", "heat", min_temp=5, max_temp=30)
        await self.run_automation(a, {"trigger": {"platform": "event"}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.writes()[0][2]["temperature"], 21)

    async def test_fallback_io_cannot_overwrite_new_off(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.1p_chodba")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("climate.1p_chodba", "off", temperature=18, min_temp=5, max_temp=30)
        async def change_mode(call):
            await self.service(call)
            self.set("input_select.topny_rezim", "Off")
        self.hass.services.async_register("climate", "set_hvac_mode", change_mode)
        await self.run_automation(a, {"trigger": {"platform": "event"}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(len(self.writes(service="set_hvac_mode")), 1)
        self.assertEqual(self.writes(), [])

    async def test_boost_fallback_io_cannot_overwrite_new_off(self):
        a = automation(BOOST, "heating_boost_apply_comfort_on")
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("binary_sensor.kotel_boost_active", "on")
        for z in ZONES:
            self.set(f"climate.{z}", "off", temperature=18, min_temp=5, max_temp=30)
        async def disable(call):
            await self.service(call)
            self.set("input_boolean.topny_system_enable", "off")
        self.hass.services.async_register("climate", "set_hvac_mode", disable)
        await self.run_automation(a)
        self.assertEqual(len(self.writes(service="set_hvac_mode")), 1)
        self.assertEqual(self.writes(), [])

    async def test_boost_duration_is_elapsed_minutes_across_dst_and_midnight(self):
        # Europe/Prague spring-forward, both sides of fall-back, and midnight.
        for start in [datetime(2026, 10, 25, 2, 30), datetime(2026, 3, 29, 1, 30),
                      datetime(2026, 10, 25, 1, 30), datetime(2026, 9, 16, 23, 30)]:
            local = start.replace(tzinfo=dt_util.get_default_time_zone())
            a = automation(BOOST, "heating_boost_start")
            with patch("homeassistant.util.dt.now", return_value=local), patch("homeassistant.util.dt.utcnow", return_value=dt_util.as_utc(local)):
                await self.run_automation(a)
            self.assertAlmostEqual(self.hass.states.get("input_datetime.boost_until").attributes["timestamp"] - local.timestamp(), 3600, delta=1)
            deadline = self.hass.states.get("input_text.boost_until_utc")
            self.assertIsNotNone(deadline)
            self.assertAlmostEqual(dt_util.as_timestamp(deadline.state) - local.timestamp(), 3600, delta=1)
            # Recreated state after restart still carries an unambiguous offset.
            self.set("input_text.boost_until_utc", deadline.state)
            self.set("input_boolean.boost_now", "off")
            boost = read(BOOST)["template"][0]["binary_sensor"][0]
            at_expiry = dt_util.as_local(dt_util.utc_from_timestamp(local.timestamp() + 3600))
            with patch("homeassistant.util.dt.now", return_value=at_expiry):
                self.assertFalse(self.render(boost["state"]))

    async def test_disabled_calendar_forces_eco_only_for_its_zone(self):
        for disabled in ZONES:
            with self.subTest(zone=disabled):
                for z in ZONES:
                    self.set(f"input_boolean.schedule_enable_{z}", "off" if z == disabled else "on")
                await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
                for z in ZONES:
                    self.assertEqual(self.hass.states.get(f"climate.{z}").attributes["temperature"],
                                     15 if z == disabled else 21)

    async def test_disabled_calendar_wins_over_boost_manual_and_window_changes(self):
        self.set("input_boolean.schedule_enable_sklep_michal", "off")
        self.set("input_boolean.sklep_michal_manual_override", "on")
        self.set("timer.sklep_michal_manual_override", "active")
        self.set("binary_sensor.kotel_boost_active", "on")
        for windows in ([], ["input_boolean.sklep_michal_schedule_active"]):
            self.set("sensor.heating_schedule_windows", "ready", active_helpers=windows)
            await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
            self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.assertEqual(self.hass.states.get("input_number.sklep_michal_last_comfort").state, "21")

    async def test_calendar_toggle_events_apply_eco_and_restore_current_window(self):
        a = automation(DISPATCH, "heating_dispatch_mode_schedule_override")
        a["action"][0]["delay"] = {"milliseconds": 10}
        await self.load_automations([a])
        self.set("input_boolean.schedule_enable_sklep_michal", "off")
        await asyncio.sleep(.15)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.set("input_boolean.schedule_enable_sklep_michal", "on")
        await asyncio.sleep(.15)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 21)
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.set("input_boolean.schedule_enable_sklep_michal", "off")
        await asyncio.sleep(.15)
        self.set("input_boolean.schedule_enable_sklep_michal", "on")
        await asyncio.sleep(.15)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)

    async def test_calendar_off_during_hvac_io_rejects_old_comfort(self):
        self.set("climate.1p_chodba", "off", temperature=18, min_temp=5, max_temp=30)
        async def disable_calendar(call):
            await self.service(call)
            self.set("input_boolean.schedule_enable_1p_chodba", "off")
        self.hass.services.async_register("climate", "set_hvac_mode", disable_calendar)
        await self.apply(requested_temp=21)
        self.assertEqual(self.writes(), [])
        await self.apply(requested_temp=21)
        self.assertEqual(self.hass.states.get("climate.1p_chodba").attributes["temperature"], 15)

    async def test_calendar_change_rejects_queued_snapshot(self):
        old = ["Auto", "off", "15", "1", "21", "on", "off", "Časovač", "idle", "on", True]
        self.set("input_boolean.schedule_enable_1p_chodba", "off")
        await self.apply(expected_inputs=old)
        self.assertEqual(self.writes(), [])
        old[-2] = "off"
        await self.apply(requested_temp=15, expected_inputs=old)
        self.assertEqual(self.writes()[0][2]["temperature"], 15)

    async def test_fallback_disabled_calendar_does_not_capture_manual_temperature(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.sklep_michal")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.assertEqual(a["condition"], [])  # Off must not prevent its own handler running.
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("input_boolean.schedule_enable_sklep_michal", "off")
        self.set("input_boolean.sklep_michal_manual_override", "on")
        self.set("timer.sklep_michal_manual_override", "active")
        self.set("binary_sensor.kotel_boost_active", "on")
        before = self.hass.states.get("climate.sklep_michal")
        self.hass.states.async_set("climate.sklep_michal", "heat",
                                  dict(before.attributes, temperature=25), context=Context(user_id="test-user"))
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "climate.sklep_michal",
                                  "from_state": before, "to_state": self.hass.states.get("climate.sklep_michal")},
                                  "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.assertEqual(self.hass.states.get("input_number.sklep_michal_last_comfort").state, "21")
        self.calls.clear()
        await self.run_automation(automation(BOOST, "heating_boost_apply_comfort_on"))
        self.assertFalse(any(c[2]["entity_id"] == "climate.sklep_michal" for c in self.writes()))

    async def test_disabled_calendar_never_reenables_global_off_or_master_off(self):
        self.set("input_boolean.schedule_enable_1p_chodba", "off")
        self.set("input_select.topny_rezim", "Off")
        await self.apply(requested_temp=15)
        self.assertEqual(self.writes(), [])
        self.set("input_select.topny_rezim", "Auto")
        self.set("input_boolean.topny_system_enable", "off")
        await self.apply(requested_temp=15)
        self.assertEqual(self.writes(), [])

    async def test_queued_decision_with_changed_inputs_is_rejected(self):
        snapshot = ["Auto", "off", "15", "1", "21", "on", "off", "Časovač", "idle", "on", True]
        self.set("input_select.topny_rezim", "Eco")
        await self.apply(expected_inputs=snapshot)
        self.assertEqual(self.writes(), [])
        snapshot[0] = "Eco"
        await self.apply(requested_temp=15, expected_inputs=snapshot)
        self.assertEqual(self.writes()[0][2]["temperature"], 15)

    def scheduler_rule(self, entity="switch.schedule_test", zone="sklep_michal",
                       state="on", slot=1, **attrs):
        data = dict(entities=[f"input_boolean.{zone}_schedule_active"],
                    current_slot=slot, timeslots=["00:00 - 08:00", "08:00 - 20:00", "20:00 - 00:00"],
                    actions=[{"service": "input_boolean.turn_off"},
                             {"service": "input_boolean.turn_on"},
                             {"service": "input_boolean.turn_off"}])
        data.update(attrs)
        self.set(entity, state, **data)

    def rendered_schedule_windows(self):
        sensor = read(SCHEDULE_SYNC)["template"][0]["sensor"][0]
        return self.render(sensor["attributes"]["active_helpers"])

    async def test_auto_missing_schedule_does_not_trust_restored_comfort_flag(self):
        self.set("input_number.sklep_michal_last_comfort", "20")
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        # The real reported problem: old helper ON, no Scheduler rule, Auto mode.
        await self.run_automation(automation(DISPATCH, "heating_dispatch_mode_schedule_override"))
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.assertEqual(self.hass.states.get("input_number.sklep_michal_last_comfort").state, "20")

    async def test_scheduler_window_uses_current_slot_not_enabled_switch(self):
        helper = "input_boolean.sklep_michal_schedule_active"
        for state, slot, expected in [("on", 1, [helper]), ("triggered", 1, [helper]),
                                      ("on", 0, []), ("on", 2, []), ("on", None, []),
                                      ("off", 1, []), ("unavailable", 1, []),
                                      ("unknown", 1, []), ("completed", 1, []),
                                      ("on", -1, []), ("on", 99, []),
                                      ("on", True, []), ("on", "1", [])]:
            with self.subTest(state=state, slot=slot):
                self.scheduler_rule(state=state, slot=slot)
                self.assertEqual(self.rendered_schedule_windows(), expected)
        # Index zero is valid too; it must not be mistaken for false/null.
        self.scheduler_rule(slot=0, actions=[{"service": "input_boolean.turn_on"}])
        self.assertEqual(self.rendered_schedule_windows(), [helper])

    async def test_scheduler_rules_combine_current_windows_and_reject_ambiguous_targets(self):
        self.scheduler_rule("switch.renamed_schedule", slot=1)
        self.scheduler_rule("switch.schedule_other_day", slot=None)
        self.scheduler_rule("switch.schedule_eco", slot=0)
        self.scheduler_rule("switch.schedule_duplicate", slot=1)
        self.assertEqual(self.rendered_schedule_windows(), ["input_boolean.sklep_michal_schedule_active"])
        for e in list(self.hass.states.async_all("switch")):
            self.hass.states.async_remove(e.entity_id)
        for attrs in [dict(actions=None), dict(actions=[{}, {}, {}]), dict(entities=None),
                      dict(entities="input_boolean.sklep_michal_schedule_active"),
                      dict(entities=["input_boolean.sklep_michal_schedule_active", "input_boolean.1p_chodba_schedule_active"])]:
            with self.subTest(attrs=attrs):
                self.scheduler_rule(**attrs)
                self.assertEqual(self.rendered_schedule_windows(), [])

    async def test_helper_reconciliation_repairs_both_directions_without_repeated_writes(self):
        a = automation(SCHEDULE_SYNC, "heating_sync_schedule_helpers")
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        await self.run_automation(a)
        self.assertTrue(all(self.hass.states.get(f"input_boolean.{z}_schedule_active").state == "off" for z in ZONES))
        self.set("sensor.heating_schedule_windows", "ready",
                 active_helpers=["input_boolean.sklep_michal_schedule_active"])
        await self.run_automation(a)
        self.assertEqual(self.hass.states.get("input_boolean.sklep_michal_schedule_active").state, "on")
        self.calls.clear()
        await self.run_automation(a)
        self.assertEqual(self.writes("input_boolean", "turn_on"), [])
        self.assertEqual(self.writes("input_boolean", "turn_off"), [])

    async def test_missing_schedule_does_not_cancel_manual_or_prevent_boost(self):
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.set("input_boolean.sklep_michal_manual_override", "on")
        self.set("timer.sklep_michal_manual_override", "active")
        await self.run_automation(automation(SCHEDULE_SYNC, "heating_sync_schedule_helpers"))
        self.assertEqual(self.hass.states.get("input_boolean.sklep_michal_schedule_active").state, "on")
        a = automation(DISPATCH, "heating_dispatch_mode_schedule_override")
        await self.run_automation(a)
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 21)
        self.set("input_boolean.sklep_michal_manual_override", "off")
        self.set("binary_sensor.kotel_boost_active", "on")
        await self.run_automation(a)
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 22)
        self.set("binary_sensor.kotel_boost_active", "off")
        await self.run_automation(a)
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)

    async def test_fallback_missing_schedule_uses_eco_despite_helper_on(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.sklep_michal")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.heating_central_dispatch_enable", "off")
        self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "input_select.topny_rezim"}, "this": {"entity_id": "automation.test"}})
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)

    async def test_real_window_change_ends_only_its_zones_manual_override(self):
        instance = next(a for a in read("automations.yaml") if a.get("use_blueprint", {}).get("input", {}).get("climate_entity") == "climate.sklep_michal")
        a = self.expanded_blueprint("smart_zone_schedule", instance["use_blueprint"]["input"])
        self.set("input_boolean.sklep_michal_manual_override", "on")
        self.set("input_select.sklep_michal_manual_override_type", "Do další změny rozvrhu")
        for changed_zone in ["1p_chodba", "sklep_michal"]:
            before = self.hass.states.get("sensor.heating_schedule_windows")
            self.set("sensor.heating_schedule_windows", "ready",
                     active_helpers=[h for h in before.attributes["active_helpers"]
                                     if h != f"input_boolean.{changed_zone}_schedule_active"])
            after = self.hass.states.get("sensor.heating_schedule_windows")
            await self.run_automation(a, {"trigger": {"platform": "state", "entity_id": "sensor.heating_schedule_windows",
                                                     "from_state": before, "to_state": after},
                                          "this": {"entity_id": "automation.test"}})
            self.assertEqual(self.hass.states.get("input_boolean.sklep_michal_manual_override").state,
                             "off" if changed_zone == "sklep_michal" else "on")

    async def test_window_ends_during_hvac_io_rejects_old_comfort_target(self):
        self.set("climate.1p_chodba", "off", temperature=15, min_temp=5, max_temp=30)
        async def mode_then_window_ends(call):
            await self.service(call)
            self.set("sensor.heating_schedule_windows", "ready", active_helpers=[])
        self.hass.services.async_register("climate", "set_hvac_mode", mode_then_window_ends)
        await self.apply(requested_temp=21)
        self.assertEqual(self.writes(), [], "An old comfort target must not survive a real window ending")

    async def test_actual_template_tracks_rule_addition_end_and_deletion(self):
        dispatch = automation(DISPATCH, "heating_dispatch_mode_schedule_override")
        dispatch["action"][0]["delay"] = {"milliseconds": 20}
        await self.load_automations([dispatch, automation(SCHEDULE_SYNC, "heating_sync_schedule_helpers")])
        self.hass.states.async_remove("sensor.heating_schedule_windows")
        self.assertTrue(await async_setup_component(self.hass, "template", {
            "template": read(SCHEDULE_SYNC)["template"]}))
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("sensor.heating_schedule_windows").state, "ready")
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.scheduler_rule(slot=1)
        await asyncio.sleep(1.2)  # HA domain-template rate limit is one second.
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 21)
        self.scheduler_rule(slot=2)
        await asyncio.sleep(1.2)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.scheduler_rule(slot=1)
        await asyncio.sleep(1.2)
        await self.hass.async_block_till_done()
        self.hass.states.async_remove("switch.schedule_test")
        self.hass.bus.async_fire("automation_reloaded")
        await asyncio.sleep(1.2)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("climate.sklep_michal").attributes["temperature"], 15)
        self.assertEqual(self.hass.states.get("input_boolean.sklep_michal_schedule_active").state, "off")

    async def test_datetime_consumers_use_entity_timestamp(self):
        self.set("input_datetime.heating_watchdog_connectivity_last_notify", "2026-09-16 12:00:00", timestamp=1789552800)
        self.set("input_datetime.heating_debug_until", "2026-09-16 12:00:00", timestamp=1789552800)
        a = automation("heating/control/watchdog_connectivity.yaml", "heating_watchdog_connectivity")
        self.assertEqual(self.render(a["action"][0]["variables"]["last_notify_ts"]), 1789552800)
        a = read("heating/control/runtime_debug_audit.yaml")["automation"][0]
        self.assertEqual(self.render(a["action"][0]["variables"]["debug_until_ts"]), 1789552800)

    async def test_history_windows_are_elapsed_hours_across_dst(self):
        local = datetime(2026, 10, 25, 12, 0, tzinfo=dt_util.get_default_time_zone())
        for sensor in read("heating/analysis/heating_analytics.yaml")["sensor"]:
            hours = 1 if sensor["name"].endswith("_1h") else 24
            with patch("homeassistant.util.dt.now", return_value=local), patch("homeassistant.util.dt.utcnow", return_value=dt_util.as_utc(local)):
                start, end = self.render(sensor["start"]), self.render(sensor["end"])
            self.assertEqual(dt_util.as_timestamp(end) - dt_util.as_timestamp(start), hours * 3600)


if __name__ == "__main__":
    unittest.main()
