"""Observer outcomes, evidence handling and absence of actuator calls."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, UTC
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_setup as setup_loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.setup import async_setup_component

from custom_components.heating_observer import CONFIG_SCHEMA, Runtime
from custom_components.heating_observer.const import DOMAIN, INPUTS, ZONES
from custom_components.heating_observer.engine import Observer, number
from custom_components.heating_observer.storage import Journal

BASE = 1_800_000_000


def sample(seconds, *, gas=False, relay=True, block=40, code=200, service=False,
           master=True, demand=20, pump=True, **overrides):
    s = {"t": BASE + seconds, "gas": gas, "relay": relay, "block": block,
         "flow": block, "code": code, "service": service, "master": master,
         "mode": "Auto", "pump": pump, "ages": {"block": 0, "flow": 0},
         "dhw": False, "dhw_recharging": False, "dhw_valve": False,
         "block_reported_at": BASE + seconds,
         "zones": {z: {"state": "heat", "pi": demand, "target": 21, "room": 20} for z in ZONES}}
    s.update(overrides)
    return s


def finish(observer, start, *, fault=False, demand=20):
    observer.feed(sample(start, relay=False, demand=demand))
    for dt in range(10, 101, 10):
        observer.feed(sample(start + dt, gas=True, demand=demand))
    observer.feed(sample(start + 110, code=2964 if fault else 200, demand=demand))
    for dt in range(120, 411, 10):
        observer.feed(sample(start + dt, relay=False, pump=False, code=203, demand=demand))


class ObserverEngineTests(unittest.TestCase):
    def test_unknown_and_nan_never_become_safe_zero(self):
        self.assertIsNone(number("unavailable"))
        self.assertIsNone(number(float("nan")))
        self.assertIsNone(number(True))
        o = Observer("test")
        o.feed(sample(0))
        o.feed(sample(10, gas=True, block=None))
        o.feed(sample(20, gas=False))
        for t in range(30, 321, 10):
            o.feed(sample(t))
        self.assertEqual(o.report()["observed_no_fault_scored"], 0)
        self.assertEqual(o.data["episodes"][0]["outcome"], "censored")

    def test_restart_does_not_convert_interrupted_cycle_to_success(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True))
        restarted = Observer("test", deepcopy(o.data))
        self.assertEqual(restarted.report()["censored"], 1)
        self.assertEqual(restarted.report()["observed_no_fault_scored"], 0)
        self.assertFalse(restarted.data["active"])

    def test_fault_snapshot_cannot_warn_about_itself(self):
        o = Observer("test")
        o.feed(sample(0, relay=False, demand=100))
        o.feed(sample(10, gas=True, demand=100))
        o.feed(sample(20, code=2964, block=90, demand=0))
        self.assertEqual(o.data["active"]["fault_leads"], {})

    def test_warning_before_fault_has_positive_lead(self):
        o = Observer("test")
        o.feed(sample(0, relay=False, demand=0))
        for t in range(10, 101, 10):
            o.feed(sample(t, gas=True, demand=0))
        o.feed(sample(110, code=2964, demand=0))
        self.assertEqual(o.data["active"]["fault_leads"]["pi20_count_lt2"], 100)

    def test_postburn_temperature_growth_is_measured_without_claiming_cause(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True, block=70.3))
        o.feed(sample(20, block=84.4))
        o.feed(sample(30, block=96.7, code=2965))
        o.feed(sample(40, block=102.4, code=2965))
        for t in range(50, 321, 10):
            o.feed(sample(t, block=30, relay=False, code=203))
        self.assertAlmostEqual(o.data["episodes"][-1]["observed_overshoot_k"], 18)
        self.assertEqual(o.report()["fault_clusters_scored"], 1)

    def test_repeated_fault_attempts_share_incident_weight(self):
        o = Observer("test")
        finish(o, 0, fault=True)
        finish(o, 450, fault=True)
        self.assertEqual(o.report()["fault_transitions_lifetime"], 2)
        self.assertEqual(o.report()["fault_clusters_scored"], 1)

    def test_service_target_is_not_learned_as_success(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True))
        o.feed(sample(20, service=True, master=False, demand=100))
        for t in range(30, 321, 10):
            o.feed(sample(t, service=True, master=False, demand=100))
        self.assertEqual(o.report()["observed_no_fault_scored"], 0)
        self.assertFalse(o.report()["operating_policy_changed"])

    def test_internal_restart_is_separate_and_previous_tail_is_truncated(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True))
        o.feed(sample(20))
        o.feed(sample(30, gas=True))
        self.assertEqual(o.data["active"]["start_kind"], "internal_restart")
        self.assertFalse(o.data["episodes"][-1]["postrun_complete"])

    def test_time_gap_and_clock_rollback_censor_learning(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True))
        o.feed(sample(100, gas=True))
        self.assertIn("capture_gap", o.current_quality)
        o.feed(sample(90))
        self.assertEqual(o.data["episodes"][-1]["outcome"], "censored")

    def test_model_settings_do_not_silently_overwrite_existing_learning(self):
        o = Observer("test")
        with self.assertRaises(ValueError):
            Observer("test", deepcopy(o.data), lead_budget=80)

    def test_unattributed_burner_start_does_not_train_space_heating(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, relay=False, gas=True))
        o.feed(sample(20, relay=False))
        for t in range(30, 321, 10):
            o.feed(sample(t, relay=False))
        self.assertEqual(o.data["episodes"][-1]["start_kind"], "unattributed")
        self.assertEqual(o.report()["observed_no_fault_scored"], 0)

    def test_insufficient_evidence_never_selects_a_candidate(self):
        o = Observer("test")
        finish(o, 0, fault=True)
        self.assertIsNone(o.report()["candidate_for_validation"])

    def test_learning_updates_comparison_but_never_operating_policy(self):
        o = Observer("test")
        for n in range(3):
            finish(o, n * 1000, fault=True, demand=0)
        for n in range(20):
            finish(o, (n + 3) * 1000, demand=100)
        r = o.report()
        self.assertEqual(r["fault_clusters_scored"], 3)
        self.assertEqual(r["observed_no_fault_scored"], 20)
        self.assertIsNotNone(r["candidate_for_validation"])
        self.assertFalse(r["operating_policy_changed"])

    def test_first_start_after_preparation_is_not_internal_restart(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        for t in range(10, 121, 10):
            o.feed(sample(t, relay=True))
        o.feed(sample(130, gas=True))
        self.assertEqual(o.data["active"]["start_kind"], "request_start")

    def test_gap_during_postrun_is_not_counted_as_success(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True))
        o.feed(sample(20, relay=False))
        o.feed(sample(320, relay=False))
        self.assertEqual(o.report()["observed_no_fault_scored"], 0)

    def test_off_valve_with_old_high_demand_is_not_counted_as_heating(self):
        o = Observer("test")
        s = sample(0, demand=100)
        for zone in s["zones"].values():
            zone["state"] = "off"
        o.feed(s)
        self.assertIn("pi50_count_lt1", o.current_warnings)

    def test_hot_water_mode_is_excluded_even_when_ch_relay_is_on(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True, dhw=True))
        o.feed(sample(20))
        for t in range(30, 321, 10):
            o.feed(sample(t))
        self.assertEqual(o.report()["observed_no_fault_scored"], 0)

    def test_overshoot_baseline_uses_first_post_shutdown_measurement(self):
        o = Observer("test")
        o.feed(sample(0, relay=False))
        o.feed(sample(10, gas=True, block=70))
        o.feed(sample(20, block=70, block_reported_at=BASE + 10))
        self.assertIsNone(o.data["active"]["block_at_gas_off"])
        o.feed(sample(21, block=84.4))
        o.feed(sample(30, block=102.4, code=2965))
        self.assertEqual(o.data["active"]["block_at_gas_off"], 84.4)

    def test_journal_rotates_and_model_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(Path(tmp), "test", max_bytes=400, backups=2)
            o = Observer("test")
            for n in range(20):
                j.write({"n": n, "data": "x" * 100}, [], o.data, o.report(), True)
            self.assertEqual(j.load(), o.data)
            logs = list(Path(tmp).glob("samples.jsonl*"))
            self.assertLessEqual(len(logs), 3)
            self.assertTrue(all(p.stat().st_size <= 400 for p in logs))

    def test_no_service_calls_or_control_domains_are_implemented(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/heating_observer"
        for p in root.glob("*.py"):
            tree = ast.parse(p.read_text())
            self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in ("async_call", "call_service", "async_register") for n in ast.walk(tree)), p)
        self.assertEqual(sorted(p.stem for p in root.glob("*.py")), ["__init__", "agents", "const", "cycle", "database", "engine", "sensor", "storage"])


class ObserverRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.tmp.name)
        setup_loader(self.hass)
        self.cfg = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]
        self.engine = Observer(self.cfg["site_revision"])
        self.journal = Journal(Path(self.tmp.name) / "observer", self.cfg["site_revision"])
        self.runtime = Runtime(self.hass, self.cfg, self.engine, self.journal)
        self.calls = []
        self.hass.bus.async_listen("call_service", lambda event: self.calls.append(event.data))
        for key, entity in INPUTS.items():
            value = ("off" if key in ("gas", "pump", "relay", "service", "boost", "dhw", "dhw_recharging", "dhw_valve") else
                     "on" if key in ("master", "policy") else "Auto" if key == "mode" else
                     "203" if key == "code" else "25")
            self.hass.states.async_set(entity, value, {"unit_of_measurement": "°C"} if key in ("block", "flow") else {})
        for zone in ZONES:
            self.hass.states.async_set(f"climate.{zone}", "heat", {"pi_heating_demand": 20, "temperature": 21, "current_temperature": 20})

    async def asyncTearDown(self):
        await self.runtime.stop()
        await self.hass.async_stop()
        self.tmp.cleanup()

    async def drain(self):
        await self.hass.async_block_till_done()
        await self.runtime.queue.join()

    async def test_read_only_capture_persists_incident_and_reports_learning(self):
        await self.runtime.start()
        await self.drain()
        self.hass.states.async_set(INPUTS["gas"], "on")
        await self.drain()
        self.hass.states.async_set(INPUTS["code"], "2964")
        await self.drain()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.hass.states.get(INPUTS["relay"]).state, "off")
        self.assertEqual(self.hass.states.get("climate.1p_jidelna").attributes["temperature"], 21)
        records = [json.loads(line) for line in (self.journal.root / "episodes.jsonl").read_text().splitlines()]
        self.assertTrue(any(r["kind"] == "incident_open" for r in records))
        self.assertEqual(self.engine.status, "fault_observed")

    async def test_missing_temperature_remains_unknown(self):
        self.hass.states.async_set(INPUTS["block"], "unavailable")
        await self.runtime.start()
        await self.drain()
        self.assertIn("invalid_block", self.engine.current_quality)
        self.assertIsNone(self.engine.previous["block"])
        self.assertEqual(self.calls, [])

    async def test_storage_failure_is_visible_and_heating_is_untouched(self):
        with patch.object(self.journal, "write", side_effect=OSError("simulated disk full")):
            await self.runtime.start()
            await self.drain()
        self.assertEqual(self.runtime.storage_error, "OSError")
        self.assertEqual(self.calls, [])
        self.runtime.enqueue("recovery")
        await self.drain()
        self.assertIsNone(self.runtime.storage_error)
        self.assertIn("capture_gap", self.engine.current_quality)

    async def test_queue_overflow_is_visible_not_silent(self):
        for _ in range(260):
            self.runtime.enqueue("burst")
        self.assertEqual(self.runtime.dropped, 4)
        self.assertTrue(self.runtime.capture_gap)
        # Drain without creating a worker for this isolated queue-bound test.
        while not self.runtime.queue.empty():
            self.runtime.queue.get_nowait()
            self.runtime.queue.task_done()

    async def test_real_ha_loader_creates_read_only_agent_diagnostic_sensors(self):
        source = Path(__file__).resolve().parents[1] / "custom_components/heating_observer"
        target = Path(self.tmp.name) / "custom_components/heating_observer"
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        self.hass.config_entries = ConfigEntries(self.hass, {})
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass, load_empty=True)
        await entity_registry.async_load(self.hass, load_empty=True)
        self.assertTrue(await async_setup_component(self.hass, DOMAIN, {DOMAIN: self.cfg}))
        self.runtime = self.hass.data[DOMAIN]
        await self.drain()
        expected = {
            "sensor.heating_observer_status": "shadow_only",
            "sensor.heating_observer_learning": "shadow_only",
            "sensor.heating_agent_platform": "read_only",
            "sensor.heating_agent_diagnostic": None,
            "sensor.heating_agent_knowledge": None,
            "sensor.heating_agent_baseline": None,
        }
        for entity_id, mode in expected.items():
            entity = self.hass.states.get(entity_id)
            self.assertIsNotNone(entity, entity_id)
            self.assertNotEqual(entity.state, "unavailable")
            if mode is not None:
                self.assertEqual(entity.attributes["mode"], mode)
            self.assertFalse(entity.attributes.get("actuator_control", False))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
