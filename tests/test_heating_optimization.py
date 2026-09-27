"""Autonomous heating improvement agents and opportunity backlog."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from custom_components.heating_observer.database import AgentDatabase
from custom_components.heating_observer.optimization import (
    ComfortAgent,
    DataQualityAgent,
    EnergyEfficiencyAgent,
    HydraulicsOptimizationAgent,
    MaintenanceAgent,
    OpportunityOrchestrator,
    ScheduleOptimizationAgent,
)
from custom_components.heating_observer.permissions import PermissionManifest

BASE = 2_100_000_000.0


def sample(t, *, gas_total=1000.0, outside=12.0, family_home=True, schedule_count=1):
    zones = {
        "1p_jidelna": {
            "state": "heat",
            "pi": 0,
            "target": 21.0,
            "room": 22.3,
            "in_window": True,
        },
        "1p_kuchyn": {
            "state": "heat",
            "pi": 25,
            "target": 21.0,
            "room": 19.5,
            "in_window": True,
        },
    }
    return {
        "t": t,
        "relay": True,
        "gas": True,
        "pump": True,
        "master": True,
        "service": False,
        "mode": "Auto",
        "dhw": False,
        "dhw_recharging": False,
        "dhw_valve": False,
        "block": 50.0,
        "flow": 45.0,
        "power": 30.0,
        "code": 203,
        "gap": False,
        "ages": {"block": 0, "flow": 0},
        "zones": zones,
        "gas_heat_total_kwh": gas_total,
        "gas_heat_month_kwh": 180.0,
        "heat_energy_month_kwh": 177.0,
        "outside_temperature": outside,
        "outside_humidity": 80.0,
        "family_home": family_home,
        "schedule_active_count": schedule_count,
        "active_zones": 1,
        "average_demand": 25,
        "valves_unhealthy": 0,
        "gas_price_czk_kwh": None,
    }


class OptimizationAgentTests(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionManifest.load_default()

    def test_energy_agent_proposes_shadow_savings_and_missing_tariff(self):
        summary = {
            "gas_heat_24h_kwh": 18.0,
            "outside_temperature_mean": 11.5,
            "gas_price_czk_kwh": None,
            "gas_meter_available": True,
            "zones": {},
        }
        rows = EnergyEfficiencyAgent(self.permissions).evaluate(summary)
        titles = [row["title"] for row in rows]
        self.assertTrue(any("mírném počasí" in title for title in titles))
        self.assertTrue(any("cenu plynu" in title for title in titles))
        mild = next(row for row in rows if row["category"] == "energy")
        self.assertEqual(mild["risk_class"], "yellow")
        self.assertTrue(mild["physical_control_change"])
        self.assertFalse(mild["deployment_allowed"])

    def test_comfort_agent_separates_overshoot_and_undershoot(self):
        summary = {
            "zones": {
                "hot": {"comfort_samples": 20, "overshoot_rate": 0.5, "undershoot_rate": 0.0},
                "cold": {"comfort_samples": 20, "overshoot_rate": 0.0, "undershoot_rate": 0.6},
            }
        }
        rows = ComfortAgent(self.permissions).evaluate(summary)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["risk_class"] == "yellow" for row in rows))

    def test_hydraulics_agent_creates_green_composite_rule_research(self):
        replay = {
            "rules": [{
                "rule": "pi10_count_lt3",
                "evidence": {"detected": 1, "lead_median_s": 170, "warned_normal_rate": 0.6},
            }]
        }
        rows = HydraulicsOptimizationAgent(self.permissions).evaluate(
            {"cycle_count": 0, "cycle_avg_burner_starts": None}, replay
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["risk_class"], "green")
        self.assertFalse(rows[0]["physical_control_change"])

    def test_hydraulics_agent_resolves_research_once_composite_replay_exists(self):
        replay = {
            "composite_flow_risk": {
                "status": "INSUFFICIENT_FEATURE_EVIDENCE",
                "active_protection_changed": False,
                "deployment_allowed": False,
            },
            "rules": [{
                "rule": "pi10_count_lt3",
                "evidence": {"detected": 1, "lead_median_s": 170, "warned_normal_rate": 0.6},
            }],
        }
        rows = HydraulicsOptimizationAgent(self.permissions).evaluate(
            {"cycle_count": 0, "cycle_avg_burner_starts": None}, replay
        )
        self.assertEqual(rows, [])

    def test_orchestrator_assigns_autonomy_by_risk(self):
        green = {
            "fingerprint": "g", "agent": "x", "category": "engineering", "title": "g",
            "rationale": "x", "risk_class": "green", "confidence": 0.9, "status": "NEW",
            "evidence": {}, "experiment": None, "changed_paths": ["tests/x.py"],
            "estimated_saving_kwh_month": None, "physical_control_change": False,
            "active_policy_changed": False, "deployment_allowed": False,
        }
        yellow = {**green, "fingerprint": "y", "title": "y", "risk_class": "yellow", "physical_control_change": True}
        rows = OpportunityOrchestrator(self.permissions).consolidate([green, yellow])
        by = {row["fingerprint"]: row for row in rows}
        self.assertEqual(by["g"]["next_action"], "AUTO_PR_ELIGIBLE")
        self.assertEqual(by["y"]["next_action"], "SHADOW_VALIDATE_THEN_REVIEW")


class OpportunityDatabaseTests(unittest.TestCase):
    def test_db_builds_24h_context_and_deduplicates_opportunities(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDatabase(Path(tmp) / "agent.sqlite3", "test")
            db.initialize()
            db.write_batch(sample(BASE, gas_total=1000.0), [], [], [], [])
            db.write_batch(sample(BASE + 3600, gas_total=1002.5), [], [], [], [])
            summary = db.optimization_summary()
            self.assertEqual(summary["samples"], 2)
            self.assertAlmostEqual(summary["gas_heat_24h_kwh"], 2.5)
            self.assertAlmostEqual(summary["outside_temperature_mean"], 12.0)
            self.assertEqual(summary["relay_on_single_schedule_fraction"], 1.0)
            self.assertIn("1p_jidelna", summary["zones"])

            rows = EnergyEfficiencyAgent(PermissionManifest.load_default()).evaluate({
                **summary,
                "gas_heat_24h_kwh": 18.0,
                "outside_temperature_mean": 12.0,
            })
            rows = OpportunityOrchestrator(PermissionManifest.load_default()).consolidate(rows)
            db.upsert_opportunities(rows, observed_at=BASE + 3600)
            db.upsert_opportunities(rows, observed_at=BASE + 7200)
            backlog = db.opportunity_summary()
            self.assertEqual(backlog["count"], len(rows))
            self.assertGreaterEqual(backlog["auto_pr_eligible"], 1)
            self.assertGreaterEqual(db.stats()["opportunities"], 1)

    def test_absent_opportunity_resolves_and_recurrence_reopens(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDatabase(Path(tmp) / "agent.sqlite3", "test")
            db.initialize()
            rows = EnergyEfficiencyAgent(PermissionManifest.load_default()).evaluate({
                "gas_heat_24h_kwh": 0,
                "outside_temperature_mean": 12,
                "gas_price_czk_kwh": None,
                "gas_meter_available": True,
                "zones": {},
            })
            rows = OpportunityOrchestrator(PermissionManifest.load_default()).consolidate(rows)
            self.assertEqual(len(rows), 1)
            db.upsert_opportunities(rows, observed_at=BASE)
            self.assertEqual(db.opportunity_summary()["items"][0]["status"], "NEW")

            db.upsert_opportunities([], observed_at=BASE + 900)
            self.assertEqual(db.opportunity_summary()["items"][0]["status"], "RESOLVED")

            db.upsert_opportunities(rows, observed_at=BASE + 1800)
            self.assertEqual(db.opportunity_summary()["items"][0]["status"], "NEW")


if __name__ == "__main__":
    unittest.main()
