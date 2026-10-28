"""Current root start/OFF pair: one-zone requests must never chatter.

All services and entities are fake. No boiler, EMS or production HA access.
Historical two-zone candidate fixtures keep their original behavior.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest

from homeassistant.components.automation.config import PLATFORM_SCHEMA
import test_heating_runtime as runtime
import test_v4_active_start_runtime as active
import test_v4_confirmed_zone_runtime as confirmed

GUARD_ID = "heating_v4_relay_lockout_guard"
START_ID = "1791376426962"
RELAY = "switch.kotel_rele_spinac"
MINIMUM = "sensor.kotel_effective_min_active_zones"


def root_config(ident):
    return deepcopy(next(a for a in runtime.read("automations.yaml")
                         if str(a["id"]) == ident))


class RootPolicyContractTests(unittest.TestCase):
    def test_root_pair_matches_reviewed_api_source_including_enabled_state(self):
        reviewed = json.loads((Path(__file__).resolve().parents[1]
                               / "docs/v4-relay-policy-config-2026-10-28.json").read_text())
        for item in reviewed["objects"].values():
            cfg = deepcopy(item["config"])
            for plural, singular in (("triggers", "trigger"), ("conditions", "condition"), ("actions", "action")):
                cfg[singular] = cfg.pop(plural)
            self.assertEqual(root_config(str(cfg["id"])), cfg)
            self.assertEqual(cfg["initial_state"], item["state"] == "on")

    def test_every_start_and_off_policy_expression_is_identical(self):
        guard, start = root_config(GUARD_ID), root_config(START_ID)
        policy = guard["variables"]["confirmed_zone_policy_ok"]
        self.assertIn("[min_z | int(99), 1] | max", policy)
        checks = [s["variables"]["confirmed_zone_policy_ok"]
                  for s in start["action"] if "variables" in s]
        self.assertEqual(checks, [policy, policy])
        triggers = {t.get("id"): t for t in start["trigger"]}
        self.assertEqual(triggers["confirmed_policy_ready"]["value_template"], policy)
        self.assertEqual(triggers["confirmed_policy_blocked"]["value_template"],
                         policy.replace("{{ ns.valid and", "{{ not (ns.valid and")
                               .replace("15] | max }}", "15] | max) }}"))

    def test_pair_has_only_expected_relay_actions_and_preserves_gates(self):
        guard, start = root_config(GUARD_ID), root_config(START_ID)
        PLATFORM_SCHEMA(deepcopy(guard))
        PLATFORM_SCHEMA(deepcopy(start))
        self.assertEqual(guard["action"], [{"action": "switch.turn_off", "target": {"entity_id": RELAY}}])
        self.assertEqual([s for s in start["action"] if "action" in s],
                         [{"action": "switch.turn_on", "target": {"entity_id": RELAY}}])
        delay_index = next(i for i, s in enumerate(start["action"]) if "delay" in s)
        for part in (start["action"][:delay_index], start["action"][delay_index + 1:]):
            for entity, value in (("binary_sensor.heating_boiler_fault_clear", "on"),
                                  ("sensor.system_bus_status", "connected"),
                                  ("input_select.heating_flow_state_v4", "NORMAL"),
                                  ("input_boolean.heating_flow_relief_lockout", "off")):
                self.assertIn({"condition": "state", "entity_id": entity, "state": value}, part)
            self.assertIn({"condition": "numeric_state", "entity_id": "sensor.boiler_heatblock", "below": 72}, part)


class CurrentRootGuardTests(confirmed.ConfirmedZoneGuardRuntimeTests):
    def guard(self):
        return root_config(GUARD_ID)

    async def test_root_has_one_guard_owner_and_only_relay_off_action(self):
        rows = runtime.read("configuration.yaml")["automation"]
        matches = [a for a in rows if str(a.get("id")) == GUARD_ID]
        self.assertEqual(matches, [self.guard()])
        PLATFORM_SCHEMA(deepcopy(matches[0]))
        await self.h.load_automations([self.guard()])
        self.assertEqual(self.h.hass.states.async_all("automation")[0].state, "on")

    async def test_minimum_two_even_if_effective_helper_says_one(self):
        # Override the historical fixture's hardcoded-two expectation.
        self.h.set(MINIMUM, "1")
        self.h.set(confirmed.FEEDBACK(confirmed.Z0), "off")
        await self.h.load_automations([self.guard()])
        self.h.set(RELAY, "on")
        await self.h.hass.async_block_till_done()
        self.assertEqual(self.state(RELAY), "on")
        self.assertEqual(self.h.calls, [])


class CurrentRootSingleZoneStartTests(active.LiveV4StartRuntimeTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        confirmed.seed(self.h, 1)
        self.h.set(MINIMUM, "1")

    async def test_start_and_guard_allow_one_zone_without_relay_chatter(self):
        await self.h.load_automations([root_config(GUARD_ID), self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.assertEqual(self.h.writes("switch", "turn_off"), [])
        self.h.hass.bus.async_fire("automation_reloaded")
        self.h.set(confirmed.DEMAND(confirmed.Z0), "91")
        await asyncio.sleep(0.16)
        self.assertEqual(self.h.hass.states.get(RELAY).state, "on")
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.assertEqual(self.h.writes("switch", "turn_off"), [])

    async def test_last_zone_feedback_loss_stops_once_and_cancels_restart(self):
        await self.h.load_automations([root_config(GUARD_ID), self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.h.set(confirmed.FEEDBACK(confirmed.Z0), "off")
        await asyncio.sleep(0.16)
        self.assertEqual(self.h.hass.states.get(RELAY).state, "off")
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        self.assertEqual(len(self.h.writes("switch", "turn_off")), 1)
        self.h.set(confirmed.FEEDBACK(confirmed.Z0), "on")
        await asyncio.sleep(0.03)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 1)
        await asyncio.sleep(0.09)
        self.assertEqual(len(self.h.writes("switch", "turn_on")), 2)

    async def test_stricter_helper_still_blocks_single_zone(self):
        self.h.set(MINIMUM, "2")
        await self.h.load_automations([root_config(GUARD_ID), self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])

    async def test_zero_confirmed_zones_never_start_even_with_stale_demand(self):
        self.h.set(confirmed.FEEDBACK(confirmed.Z0), "off")
        await self.h.load_automations([root_config(GUARD_ID), self.live_start()])
        self.h.set("binary_sensor.kotel_should_be_on", "on")
        await asyncio.sleep(0.12)
        self.assertEqual(self.h.writes("switch", "turn_on"), [])
