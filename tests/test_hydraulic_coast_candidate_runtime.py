"""Review prototypes only; native HA templates/scripts with simulated devices.

No active configuration is changed. Shorten readback waits/backoff, not logic.
These tests cannot establish contact position, valve opening or water flow.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import unittest

import test_heating_runtime as rt
from homeassistant.components.script.config import SCRIPT_ENTITY_SCHEMA


class HydraulicCoastCandidateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = rt.HeatingRuntimeTests(methodName="runTest")
        await self.h.asyncSetUp()
        self.template = (rt.ROOT / "docs/candidates/hydraulic-coast-decision.jinja").read_text()
        self.sequence = deepcopy(rt.read("docs/candidates/emergency-zone-open.yaml")["script"]
                                 ["heating_emergency_open_zone_candidate"]["sequence"])

        def shorten(obj):
            if isinstance(obj, dict):
                if "wait_template" in obj:
                    obj["timeout"] = {"milliseconds": 35}
                if "delay" in obj:
                    obj["delay"] = {"milliseconds": 10}
                for value in obj.values():
                    shorten(value)
            elif isinstance(obj, list):
                for value in obj:
                    shorten(value)
        shorten(self.sequence)
        self.episode = "v3:[1793863626,1,[1,2,3,4,5,6,7,8]]"
        self.h.set("input_select.heating_flow_state_v4", "EMERGENCY_COOLING")
        self.h.set("input_text.heating_flow_relief_state_v1", self.episode)
        self.results = []
        self.unsub = self.h.hass.bus.async_listen(
            "heating_emergency_zone_candidate_result", lambda ev: self.results.append(dict(ev.data)))

    async def asyncTearDown(self):
        self.unsub()
        await self.h.asyncTearDown()

    def snapshot(self, **changes):
        p = dict(support="climate.1p_chodba", flow_state="NORMAL", real_requesters=0,
                 now=1000, received_at={key: 990 for key in
                                       ("block", "flow", "relay", "gas", "room", "bus", "demand")},
                 eligible=True, room=20, block=59, flow=58, relay="off", gas="off",
                 bus="connected", demand_valid=True)
        p.update(changes)
        return p

    def decision(self, p):
        result = self.h.render(self.template, {"p": p})
        return json.loads(result) if isinstance(result, str) else result

    async def worker(self, zone="climate.1p_koupelna", episode=None):
        await self.h.run_sequence(self.sequence, {"zone": zone, "episode": episode or self.episode})
        await self.h.hass.async_block_till_done()

    def temperature_calls(self):
        return [c for c in self.h.calls if c[:2] == ("climate", "set_temperature")]

    async def test_one_real_requester_retains_support_without_actuation(self):
        result = self.decision(self.snapshot(real_requesters=1))
        self.assertEqual(result["decision"], "KEEP_SUPPORT")
        self.assertFalse(result["request_normal_owner_off"])
        self.assertFalse(result["actuation_performed"])
        self.assertEqual(self.h.calls, [])

    async def test_entire_candidate_script_configuration_has_native_schema(self):
        config = rt.read("docs/candidates/emergency-zone-open.yaml")
        worker = SCRIPT_ENTITY_SCHEMA(config["script"]["heating_emergency_open_zone_candidate"])
        self.assertEqual(worker["mode"], "parallel")
        self.assertEqual(worker["max"], 8)

    async def test_zero_request_coast_does_not_self_latch_heat_request(self):
        for changes in ({"gas": "on"}, {"relay": "on"}, {"block": 60}, {"flow": 60}):
            with self.subTest(changes=changes):
                result = self.decision(self.snapshot(**changes))
                self.assertEqual(result["decision"], "HOLD_COAST")
                self.assertTrue(result["request_normal_owner_off"])
                self.assertFalse(result["physical_flow_confirmed"])

    async def test_release_requires_both_off_and_both_temperatures_below_limit(self):
        for count in (0, 2, 8):
            self.assertEqual(self.decision(self.snapshot(real_requesters=count))["decision"], "RELEASE")
        for field in ("block", "flow"):
            self.assertEqual(self.decision(self.snapshot(**{field: 60}))["decision"], "HOLD_COAST")

    async def test_invalid_and_stale_inputs_never_release(self):
        for changes in ({"block": "unknown"}, {"flow": "nan"}, {"room": None},
                        {"gas": "unavailable"}, {"relay": "unknown"}, {"bus": "disconnected"},
                        {"real_requesters": True}, {"real_requesters": -1},
                        {"real_requesters": "0"}, {"demand_valid": False}, {"now": "bad"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.decision(self.snapshot(**changes))["decision"], "UNVERIFIED")
        for key in self.snapshot()["received_at"]:
            for stamp in (954, 1001, None):
                p = self.snapshot()
                p["received_at"][key] = stamp
                self.assertEqual(self.decision(p)["decision"], "UNVERIFIED", (key, stamp))
        self.assertEqual(self.decision(None)["decision"], "UNVERIFIED")

    async def test_numeric_telemetry_strings_and_freshness_boundary(self):
        p = self.snapshot(block="59.9", flow="59.9", room="20", now="1000")
        p["received_at"] = {k: "955" for k in p["received_at"]}
        self.assertEqual(self.decision(p)["decision"], "RELEASE")

    async def test_safety_owner_and_room_limit_take_priority(self):
        for state in ("EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"):
            self.assertEqual(self.decision(self.snapshot(flow_state=state))["decision"], "HANDOFF_FLOW_V4")
        self.assertEqual(self.decision(self.snapshot(flow_state="unknown"))["decision"], "UNVERIFIED")
        for changes in ({"room": 24}, {"eligible": False}):
            self.assertEqual(self.decision(self.snapshot(real_requesters=1, **changes))["decision"],
                             "HANDOFF_REQUIRED")
        self.assertEqual(self.decision(self.snapshot(support="none"))["decision"], "NO_SUPPORT")
        self.assertEqual(self.decision(self.snapshot(support="climate.1p_koupelna"))["decision"], "UNVERIFIED")

    async def test_bathroom_target_reported_in_first_attempt(self):
        await self.worker()
        self.assertEqual(len(self.temperature_calls()), 1)
        self.assertEqual(self.results[0]["status"], "target_reported")
        self.assertEqual(self.results[0]["attempts"], 1)
        self.assertFalse(self.results[0]["physical_flow_confirmed"])
        self.assertFalse(self.results[0]["motor_step_increase"])

    async def test_failed_first_delivery_retries_once(self):
        self.h.fail_once_entity = "climate.1p_koupelna"
        self.h.fail_once_remaining = 1
        await self.worker()
        self.assertEqual(len(self.temperature_calls()), 2)
        self.assertEqual(self.results[0]["status"], "target_reported")
        self.assertEqual(self.results[0]["attempts"], 2)

    async def test_off_zone_is_put_in_heat_before_target(self):
        self.h.set("climate.1p_koupelna", "off", temperature=15)
        await self.worker()
        self.assertEqual([c[1] for c in self.h.calls], ["set_hvac_mode", "set_temperature"])
        self.assertEqual(self.results[0]["status"], "target_reported")

    async def test_motor_counter_reset_cannot_be_counted_as_increase(self):
        motor = "sensor.1p_koupelna_pocet_kroku_motoru"
        self.h.set(motor, "1000")
        original = self.h.service

        async def target_and_reset(call):
            await original(call)
            self.h.set(motor, "0")
        self.h.hass.services.async_register("climate", "set_temperature", target_and_reset)
        await self.worker()
        self.assertFalse(self.results[0]["motor_step_increase"])
        self.assertFalse(self.results[0]["physical_flow_confirmed"])

    async def test_accepted_but_not_reported_is_unconfirmed(self):
        self.h.ignore_temperature_entity = "climate.1p_koupelna"
        await self.worker()
        self.assertEqual(len(self.temperature_calls()), 2)
        self.assertEqual(self.results[0]["status"], "unconfirmed")

    async def test_stale_cached_target_without_new_report_does_not_pass(self):
        self.h.set("climate.1p_koupelna", "heat", temperature=29)
        self.h.ignore_temperature_entity = "climate.1p_koupelna"
        await self.worker()
        self.assertEqual(self.results[0]["status"], "unconfirmed")
        self.assertFalse(any(c[1] == "set_hvac_mode" for c in self.h.calls))

    async def test_one_failed_zone_does_not_cancel_other_seven(self):
        self.h.fail_entity = "climate.1p_koupelna"
        await asyncio.gather(*(self.worker(f"climate.{zone}") for zone in rt.ZONES))
        by_zone = {r["zone"]: r for r in self.results}
        self.assertEqual(len(by_zone), 8)
        self.assertEqual(by_zone[self.h.fail_entity]["status"], "unconfirmed")
        self.assertEqual(sum(r["status"] == "target_reported" for r in by_zone.values()), 7)
        self.assertTrue(all(domain == "climate" for domain, _, _ in self.h.calls))

    async def test_changed_epoch_before_run_cannot_send_a_command(self):
        self.h.set("input_text.heating_flow_relief_state_v1", self.episode.replace("1793863626", "1793864000"))
        await self.worker()
        self.assertEqual(self.h.calls, [])

    async def test_changed_epoch_during_mode_call_cannot_send_target(self):
        self.h.set("climate.1p_koupelna", "off", temperature=15)
        original = self.h.service

        async def mode_changes_epoch(call):
            await original(call)
            self.h.set("input_text.heating_flow_relief_state_v1", "new episode")
        self.h.hass.services.async_register("climate", "set_hvac_mode", mode_changes_epoch)
        await self.worker()
        self.assertEqual(self.temperature_calls(), [])

    async def test_changed_owner_during_readback_cancels_without_retry(self):
        self.h.ignore_temperature_entity = "climate.1p_koupelna"

        async def change_owner():
            while not self.temperature_calls():
                await asyncio.sleep(0)
            self.h.set("input_select.heating_flow_state_v4", "RESTORING")
        await asyncio.gather(self.worker(), change_owner())
        self.assertEqual(len(self.temperature_calls()), 1)
        self.assertEqual(self.results[0]["status"], "cancelled")

    async def test_invalid_zone_or_episode_sends_nothing(self):
        await self.worker("climate.boiler")
        for episode in ("bad", "v3:1", "v3:{}", "v3:[]", "v3:[1,1,[]]",
                        "v3:[0,1,[1,2,3,4,5,6,7,8]]"):
            await self.worker(episode=episode)
        self.assertEqual(self.h.calls, [])


if __name__ == "__main__":
    unittest.main()
