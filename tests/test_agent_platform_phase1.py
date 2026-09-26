from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from agent_platform.collector import EntityMap, ReadOnlyCollector, ReadOnlyHaCommandPolicy
from agent_platform.cycle_builder import CycleBuilder
from agent_platform.model import CycleSummary
from agent_platform.observer import BaselineModel, Observer
from agent_platform.pipeline import Phase1Pipeline


BASE = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc).timestamp()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def item(state, ts: float, attributes=None):
    return {
        "state": str(state),
        "attributes": attributes or {},
        "last_reported": iso(ts),
        "last_updated": iso(ts),
    }


def make_states(
    ts: float,
    *,
    relay: bool = False,
    gas: bool = False,
    block: float = 50.0,
    flow: float = 45.0,
    code: int = 0,
    pi: float = 20.0,
):
    e = EntityMap()
    states = {
        e.block: item(block, ts),
        e.flow: item(flow, ts),
        e.power: item(30.0 if gas else 0.0, ts),
        e.code: item(code, ts),
        e.gas: item("on" if gas else "off", ts),
        e.pump: item("on" if relay else "off", ts),
        e.dhw: item("off", ts),
        e.dhw_recharging: item("off", ts),
        e.dhw_valve: item("off", ts),
        e.relay: item("on" if relay else "off", ts),
        e.master: item("on", ts),
        e.service: item("off", ts),
        e.mode: item("Auto", ts),
    }
    for zone in e.zones:
        states[f"climate.{zone}"] = item(
            "heat",
            ts,
            {
                "current_temperature": 20.0,
                "temperature": 21.0,
                "pi_heating_demand": pi,
            },
        )
    return states


class CollectorTests(unittest.TestCase):
    def test_policy_fails_closed_for_service_calls(self):
        ReadOnlyHaCommandPolicy.assert_allowed({"type": "get_states"})
        ReadOnlyHaCommandPolicy.assert_allowed({"type": "subscribe_events"})
        with self.assertRaises(PermissionError):
            ReadOnlyHaCommandPolicy.assert_allowed({
                "type": "call_service",
                "domain": "switch",
                "service": "turn_on",
            })

    def test_collector_normalizes_without_actuator_api(self):
        collector = ReadOnlyCollector("test-revision")
        snapshot = collector.collect(make_states(BASE), captured_at=BASE)
        self.assertEqual(snapshot.quality, ())
        self.assertEqual(snapshot.requesting_zone_count(), 8)
        self.assertFalse(hasattr(collector, "call_service"))
        self.assertFalse(hasattr(collector, "turn_on"))


class CycleBuilderTests(unittest.TestCase):
    def setUp(self):
        self.collector = ReadOnlyCollector("test-revision")
        self.builder = CycleBuilder()

    def snap(self, ts, **kwargs):
        return self.collector.collect(make_states(ts, **kwargs), captured_at=ts)

    def test_request_cycle_counts_internal_burner_restart(self):
        self.assertEqual(self.builder.feed(self.snap(BASE, relay=False, gas=False)), [])

        started = self.builder.feed(self.snap(BASE + 10, relay=True, gas=True, block=50.0))
        self.assertEqual([x.kind for x in started], ["started"])
        self.assertFalse(started[0].summary.incomplete)

        self.builder.feed(self.snap(BASE + 20, relay=True, gas=False, block=51.0))
        self.builder.feed(self.snap(BASE + 30, relay=True, gas=True, block=52.0))
        completed = self.builder.feed(self.snap(BASE + 40, relay=False, gas=False, block=52.5))

        self.assertEqual([x.kind for x in completed], ["completed"])
        summary = completed[0].summary
        self.assertEqual(summary.burner_starts, 2)
        self.assertTrue(summary.eligible_for_baseline)
        self.assertEqual(summary.fault_codes, ())
        self.assertGreater(summary.max_temperature_rise_c_per_min, 0)

    def test_unknown_start_is_preserved_but_not_baseline(self):
        started = self.builder.feed(self.snap(BASE, relay=True, gas=True))
        self.assertTrue(started[0].summary.incomplete)
        completed = self.builder.feed(self.snap(BASE + 10, relay=False, gas=False))
        self.assertFalse(completed[0].summary.eligible_for_baseline)
        self.assertEqual(completed[0].summary.start_kind, "unknown_request_history")

    def test_capture_gap_marks_cycle_incomplete(self):
        self.builder.feed(self.snap(BASE, relay=False, gas=False))
        self.builder.feed(self.snap(BASE + 10, relay=True, gas=True))
        completed = self.builder.feed(self.snap(BASE + 100, relay=False, gas=False))
        summary = completed[0].summary
        self.assertTrue(summary.incomplete)
        self.assertIn("capture_gap", summary.quality_flags)
        self.assertFalse(summary.eligible_for_baseline)


class ObserverTests(unittest.TestCase):
    def test_known_fault_creates_evidence_incident_not_diagnosis(self):
        pipeline = Phase1Pipeline("test-revision")
        pipeline.process_state_map(make_states(BASE, relay=False), captured_at=BASE)
        pipeline.process_state_map(make_states(BASE + 10, relay=True, gas=True), captured_at=BASE + 10)
        events = pipeline.process_state_map(
            make_states(BASE + 20, relay=True, gas=False, code=2964, block=60),
            captured_at=BASE + 20,
        )
        incidents = [event for event in events if event.event_type == "heating.incident.created.v1"]
        self.assertEqual(len(incidents), 1)
        data = incidents[0].data
        self.assertEqual(data["incident_type"], "boiler_fault_code")
        self.assertEqual(data["observation"]["service_code"], 2964)
        self.assertEqual(data["observation"]["root_cause"], "UNKNOWN")
        self.assertIsNone(data["diagnosis"])
        self.assertTrue(data["timeline"])

    def test_statistical_outlier_requires_baseline(self):
        baseline = BaselineModel(minimum_cycles=3)
        for index in range(3):
            baseline.add(CycleSummary(
                cycle_id=f"normal-{index}",
                site_revision="test-revision",
                started_at=BASE,
                ended_at=BASE + 60,
                start_kind="request_start",
                incomplete=False,
                runtime_seconds=60,
                burner_starts=1,
                start_boiler_temperature=45,
                max_boiler_temperature=50,
                max_temperature_rise_c_per_min=1.0,
                min_requesting_zones=3,
                average_requesting_zones=4.0,
                fault_codes=(),
                service_seen=False,
                master_off_seen=False,
                dhw_seen=False,
                quality_flags=(),
                eligible_for_baseline=True,
            ))
        observer = Observer(baseline=baseline)
        collector = ReadOnlyCollector("test-revision")

        first_states = make_states(BASE, relay=True, gas=True, block=50)
        first = collector.collect(first_states, captured_at=BASE)
        self.assertEqual(observer.feed(first, cycle_id="cycle-x"), [])

        second_states = make_states(BASE + 10, relay=True, gas=True, block=52)
        zones = EntityMap().zones
        for zone in zones[1:]:
            second_states[f"climate.{zone}"]["attributes"]["pi_heating_demand"] = 0
        second = collector.collect(second_states, captured_at=BASE + 10)
        incidents = observer.feed(second, cycle_id="cycle-x")
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].incident_type, "rapid_temperature_rise_low_demand_outlier")
        self.assertFalse(incidents[0].observation["physical_flow_confirmed"])

    def test_statistical_outlier_is_suppressed_in_service_mode(self):
        baseline = BaselineModel(minimum_cycles=1)
        baseline.add(CycleSummary(
            cycle_id="normal",
            site_revision="test-revision",
            started_at=BASE,
            ended_at=BASE + 60,
            start_kind="request_start",
            incomplete=False,
            runtime_seconds=60,
            burner_starts=1,
            start_boiler_temperature=45,
            max_boiler_temperature=50,
            max_temperature_rise_c_per_min=1.0,
            min_requesting_zones=3,
            average_requesting_zones=4.0,
            fault_codes=(),
            service_seen=False,
            master_off_seen=False,
            dhw_seen=False,
            quality_flags=(),
            eligible_for_baseline=True,
        ))
        observer = Observer(baseline=baseline)
        collector = ReadOnlyCollector("test-revision")

        first_states = make_states(BASE, relay=True, gas=True, block=50)
        first_states[EntityMap().service]["state"] = "on"
        first = collector.collect(first_states, captured_at=BASE)
        observer.feed(first, cycle_id="cycle-service")

        second_states = make_states(BASE + 10, relay=True, gas=True, block=53)
        second_states[EntityMap().service]["state"] = "on"
        for zone in EntityMap().zones[1:]:
            second_states[f"climate.{zone}"]["attributes"]["pi_heating_demand"] = 0
        second = collector.collect(second_states, captured_at=BASE + 10)
        self.assertEqual(observer.feed(second, cycle_id="cycle-service"), [])


class ContractTests(unittest.TestCase):
    def test_json_schema_is_versioned_and_contains_replay_contract(self):
        path = Path(__file__).resolve().parents[1] / "agent_platform/schemas/events.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$defs"]["baseEvent"]["properties"]["schema_version"]["const"], "1.0")
        self.assertIn("replayData", schema["$defs"])
        self.assertIn("dataset_role", schema["$defs"]["replayData"]["required"])


if __name__ == "__main__":
    unittest.main()
