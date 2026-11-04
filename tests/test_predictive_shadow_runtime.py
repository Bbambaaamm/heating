"""Actual HA scripts: forecast failures, partial zone failures and heartbeat."""
from copy import deepcopy
from datetime import timedelta
import unittest

from homeassistant.components.automation.config import PLATFORM_SCHEMA
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

import test_heating_runtime as runtime


PATH = "automations.yaml"
CANDIDATE_PATH = "docs/candidates/predictive-shadow-candidate.yaml"
HEARTBEAT = "input_datetime.predictive_heating_heartbeat"
SUMMARY = "input_text.predictive_heating_run_status"


class PredictionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = runtime.HeatingRuntimeTests()
        await self.h.asyncSetUp()
        self.a = deepcopy(next(a for a in runtime.read(PATH)
                               if str(a.get("id")) == "predictive_heating_shadow_recalc"))
        PLATFORM_SCHEMA(deepcopy(self.a))
        self.failure = None
        self.write_failure = None
        self.silent_write_failure = None
        self.forecast = {"weather.forecast_domov": {"forecast": [{
            "datetime": (dt_util.utcnow()+timedelta(hours=2)).isoformat(),
            "temperature": 5, "wind_speed": 10, "cloud_coverage": 50,
        }]}}
        self.h.set("weather.forecast_domov", "cloudy", temperature=6, wind_speed=5, cloud_coverage=60)
        self.h.set(HEARTBEAT, "2000-01-01 00:00:00")
        for zone in self.a["variables"]["zones"]:
            self.h.set(zone["temp"], "18")
            self.h.set(zone["status"], "previous result")
            self.h.set(zone["schedule"], "off")
            self.h.set("input_number.ph_"+zone["z"]+"_bias_min", "10")
            self.h.set("switch.scheduler_"+zone["z"], "on", entities=[zone["schedule"]],
                       next_slot=0, actions=[{"service":"input_boolean.turn_on"}],
                       next_trigger=(dt_util.utcnow()+timedelta(hours=2)).isoformat())
        async def weather(call):
            if self.failure:
                raise self.failure
            return self.forecast
        self.h.hass.services.async_register("weather", "get_forecasts", weather,
                                            supports_response=SupportsResponse.ONLY)
        original = self.h.service
        async def writer(call):
            entity = call.data.get("entity_id")
            if entity == self.write_failure:
                raise HomeAssistantError("Injected status helper write failure")
            if entity == self.silent_write_failure:
                return
            return await original(call)
        self.h.hass.services.async_register("input_text", "set_value", writer)

    async def asyncTearDown(self):
        await self.h.asyncTearDown()

    async def run_candidate(self):
        await self.h.run_automation(self.a)

    def statuses(self):
        return [self.h.hass.states.get(z["status"]).state for z in self.a["variables"]["zones"]]

    def summary(self):
        return self.h.hass.states.get(SUMMARY).state

    def heartbeat(self):
        return self.h.hass.states.get(HEARTBEAT).state

    async def test_full_forecast_writes_all_zones_and_preserves_model_bias(self):
        await self.run_candidate()
        self.assertTrue(self.summary().startswith("OK"), self.summary())
        self.assertIn("zápisy 8/8", self.summary())
        self.assertNotEqual(self.heartbeat(), "2000-01-01 00:00:00")
        self.assertTrue(all("cíl" in x for x in self.statuses()), self.statuses())
        # First zone: gap3/rate7.35*60 * (cold1.1+wind.03) +10 +bias10 =48min.
        self.assertIn("48 min", self.statuses()[0])
        allowed = {("input_text", "set_value"), ("input_datetime", "set_datetime")}
        self.assertTrue(all((d,s) in allowed for d,s,_ in self.h.calls))
        helpers = {z["status"] for z in self.a["variables"]["zones"]} | {
            HEARTBEAT, SUMMARY, "input_datetime.predictive_heating_last_attempt"}
        for _,_,data in self.h.calls:
            entities=data.get("entity_id",[])
            if isinstance(entities,str):
                entities=[entities]
            self.assertTrue(set(entities)<=helpers, data)

    async def test_weather_service_failure_is_explicit_fallback_not_abort(self):
        self.failure = ServiceValidationError("Service call requested response data but did not match any entities")
        await self.run_candidate()
        self.assertTrue(self.summary().startswith("DEGRADED"), self.summary())
        self.assertIn("předpověď 0/8", self.summary())
        self.assertTrue(all("náhradní aktuální počasí" in x for x in self.statuses()))
        self.assertNotEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_weather_unavailable_updates_statuses_but_not_success_heartbeat(self):
        self.failure = HomeAssistantError("weather offline")
        self.h.set("weather.forecast_domov", "unavailable", temperature=6, wind_speed=5, cloud_coverage=60)
        await self.run_candidate()
        self.assertTrue(self.summary().startswith("INCOMPLETE"), self.summary())
        self.assertTrue(all("predikce nedostupná" in x for x in self.statuses()), self.statuses())
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_empty_and_malformed_forecasts_use_marked_fallback(self):
        for result in ({}, {"weather.forecast_domov":None}, {"weather.forecast_domov":{"forecast":"broken"}},
                       {"weather.forecast_domov":{"forecast":[{"datetime":"bad","temperature":"nan"}]}}):
            self.forecast = result
            await self.run_candidate()
            self.assertTrue(self.summary().startswith("DEGRADED"), self.summary())

    async def test_single_failed_zone_does_not_block_remaining_zones_or_claim_success(self):
        self.write_failure = self.a["variables"]["zones"][1]["status"]
        await self.run_candidate()
        self.assertIn("zápisy 7/8", self.summary())
        self.assertIn("cíl", self.statuses()[-1])
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_silent_write_failure_does_not_count_as_completed(self):
        self.silent_write_failure = self.a["variables"]["zones"][1]["status"]
        await self.run_candidate()
        self.assertIn("zápisy 7/8", self.summary())
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_missing_temperature_is_reported_and_not_success(self):
        self.h.set(self.a["variables"]["zones"][0]["temp"], "unavailable")
        await self.run_candidate()
        self.assertIn("chybí teplotní data", self.statuses()[0])
        self.assertIn("platná data 7/8", self.summary())
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_weather_entity_missing_never_fabricates_default_temperature(self):
        self.forecast = {}
        self.h.hass.states.async_remove("weather.forecast_domov")
        await self.run_candidate()
        self.assertIn("zápisy 8/8", self.summary())
        self.assertIn("platná data 0/8", self.summary())
        self.assertTrue(all("predikce nedostupná" in x for x in self.statuses()))
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_identical_old_result_does_not_prove_a_new_write(self):
        await self.run_candidate()
        self.h.set(HEARTBEAT, "2000-01-01 00:00:00")
        self.silent_write_failure = self.a["variables"]["zones"][1]["status"]
        await self.run_candidate()
        self.assertIn("zápisy 7/8", self.summary())
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_stale_weather_fallback_is_not_treated_as_current(self):
        self.forecast = {}
        stale=dt_util.utcnow()-timedelta(hours=2)
        self.h.hass.states.async_set_internal(
            "weather.forecast_domov", "cloudy",
            {"temperature":6,"wind_speed":5,"cloud_coverage":60},
            True, None, None, stale.timestamp(),
        )
        await self.run_candidate()
        self.assertIn("platná data 0/8",self.summary())
        self.assertEqual(self.heartbeat(), "2000-01-01 00:00:00")

    async def test_candidate_is_disabled_and_not_in_live_package_include(self):
        candidate=runtime.read(CANDIDATE_PATH)["automation"][0]
        self.assertFalse(candidate["initial_state"])
        self.assertFalse(CANDIDATE_PATH.startswith("heating/"))
        self.assertTrue(self.a["initial_state"])
        for key in ("variables","trigger","condition","action","mode"):
            self.assertEqual(self.a[key],candidate[key],key)
