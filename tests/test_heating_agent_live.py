"""Live agent-platform storage, cycles and evidence semantics."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from custom_components.heating_observer.agents import DiagnosticAgent, KnowledgeAgent
from custom_components.heating_observer.const import ZONES
from custom_components.heating_observer.cycle import RequestCycleBuilder
from custom_components.heating_observer.database import AgentDatabase

BASE = 1_900_000_000.0


def sample(seconds, *, relay=True, gas=False, block=40.0, code=203, demand=20.0,
           service=False, master=True, gap=False):
    t = BASE + seconds
    return {
        "t": t,
        "revision": "test",
        "relay": relay,
        "gas": gas,
        "pump": relay,
        "master": master,
        "service": service,
        "mode": "Auto",
        "dhw": False,
        "dhw_recharging": False,
        "dhw_valve": False,
        "block": block,
        "flow": block - 1,
        "power": 30 if gas else 0,
        "code": code,
        "gap": gap,
        "ages": {"block": 0, "flow": 0},
        "block_reported_at": t,
        "zones": {
            zone: {
                "state": "heat",
                "pi": demand,
                "target": 21,
                "room": 20,
                "in_window": True,
            }
            for zone in ZONES
        },
    }


class RequestCycleTests(unittest.TestCase):
    def test_request_cycle_is_baseline_only_when_complete_and_clean(self):
        builder = RequestCycleBuilder("test")
        self.assertEqual(builder.feed(sample(0, relay=False)), [])
        started = builder.feed(sample(10, relay=True, gas=True, block=45))
        self.assertEqual(started[0]["kind"], "cycle_started")
        builder.feed(sample(20, relay=True, gas=False, block=46))
        builder.feed(sample(30, relay=True, gas=True, block=47))
        completed = builder.feed(sample(40, relay=False, gas=False, block=48))
        cycle = completed[0]["cycle"]
        self.assertEqual(cycle["burner_starts"], 2)
        self.assertTrue(cycle["eligible_for_baseline"])
        self.assertGreater(cycle["max_temperature_rise_c_per_min"], 0)

    def test_gap_preserves_cycle_as_evidence_but_censors_baseline(self):
        builder = RequestCycleBuilder("test", telemetry_gap=45)
        builder.feed(sample(0, relay=False))
        builder.feed(sample(10, relay=True, gas=True))
        completed = builder.feed(sample(100, relay=False, gap=True))
        cycle = completed[0]["cycle"]
        self.assertTrue(cycle["incomplete"])
        self.assertIn("capture_gap", cycle["quality_flags"])
        self.assertFalse(cycle["eligible_for_baseline"])


class AgentTests(unittest.TestCase):
    def test_diagnostic_keeps_root_cause_unknown_and_competing_hypotheses(self):
        prelude = [
            sample(0, relay=True, gas=True, block=50, demand=30),
            sample(10, relay=True, gas=True, block=54, demand=0),
            sample(20, relay=True, gas=False, block=58, demand=0),
        ]
        incident = {
            "kind": "incident_open",
            "incident_id": "incident-1",
            "episode_id": "episode-1",
            "t": BASE + 30,
            "code": 2964,
            "prelude": prelude,
        }
        report = DiagnosticAgent().analyze(incident)
        self.assertEqual(report["root_cause"], "UNKNOWN")
        self.assertGreaterEqual(len(report["hypotheses"]), 3)
        self.assertTrue(all(h["status"] == "HYPOTHESIS" for h in report["hypotheses"]))
        self.assertIn("nemění ochranu", report["safety_implication"])

    def test_knowledge_never_promotes_hypothesis_to_fact(self):
        diagnostic = {
            "incident_id": "incident-1",
            "facts": ["Pozorovaný servisní kód 2964."],
            "hypotheses": [{
                "name": "Hydraulická kapacita",
                "confidence": 0.7,
                "evidence_for": ["málo requesting zón"],
                "evidence_against": ["PI není průtok"],
            }],
            "safety_implication": "Bez změny ochrany.",
        }
        entries = KnowledgeAgent().entries_for(diagnostic, created_at=BASE)
        self.assertEqual([x["kind"] for x in entries], ["OBSERVATION", "HYPOTHESIS", "DECISION"])
        self.assertFalse(any(x.get("promoted") for x in entries))
        self.assertNotIn("FACT", [x["kind"] for x in entries])


class DatabaseTests(unittest.TestCase):
    def test_sqlite_store_is_append_only_for_raw_events_and_persists_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDatabase(Path(tmp) / "agent.sqlite3", "test")
            db.initialize()
            builder = RequestCycleBuilder("test")
            db.write_batch(sample(0, relay=False), builder.feed(sample(0, relay=False)), [], [], [])

            incident = {
                "kind": "incident_open",
                "incident_id": "incident-1",
                "episode_id": "episode-1",
                "t": BASE + 30,
                "code": 2964,
                "prelude": [sample(10, demand=0), sample(20, block=55, demand=0)],
                "request_cycle_id": None,
            }
            diagnostic = DiagnosticAgent().analyze(incident)
            knowledge = KnowledgeAgent().entries_for(diagnostic, created_at=BASE + 30)
            db.write_batch(sample(30, code=2964), [], [incident], [diagnostic], knowledge)

            stats = db.stats()
            self.assertEqual(stats["incidents"], 1)
            self.assertEqual(stats["diagnostics"], 1)
            self.assertEqual(stats["knowledge_entries"], len(knowledge))
            self.assertEqual(db.latest_diagnostic()["root_cause"], "UNKNOWN")
            self.assertEqual(db.knowledge_summary()["facts_promoted_from_hypotheses"], 0)

            raw = sqlite3.connect(db.path)
            try:
                event_id = raw.execute("SELECT event_id FROM event_log LIMIT 1").fetchone()[0]
                with self.assertRaises(sqlite3.DatabaseError):
                    raw.execute("UPDATE event_log SET source='tampered' WHERE event_id=?", (event_id,))
            finally:
                raw.close()


if __name__ == "__main__":
    unittest.main()
