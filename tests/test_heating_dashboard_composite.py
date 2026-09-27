"""Source-only guardrails for the Composite Flow-Risk Lovelace card."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_PATH = PROJECT_ROOT / "dashboard/heating-panel-agents-composite-flow-risk-card.yaml"


class CompositeFlowRiskDashboardCardTests(unittest.TestCase):
    def setUp(self):
        self.raw = CARD_PATH.read_text(encoding="utf-8")
        self.card = yaml.safe_load(self.raw)

    def test_card_is_native_read_only_markdown_for_sections_view(self):
        self.assertEqual(self.card["type"], "markdown")
        self.assertEqual(self.card["grid_options"], {"columns": "full", "rows": "auto"})
        self.assertEqual(
            set(self.card["entity_id"]),
            {
                "sensor.heating_agent_replay",
                "sensor.heating_agent_safety",
                "sensor.heating_agent_permissions",
                "sensor.heating_agent_watchdog",
            },
        )

    def test_card_contains_composite_evidence_and_shadow_disclaimer(self):
        content = self.card["content"]
        self.assertIn("SHADOW ONLY · NO CONTROL", content)
        self.assertIn("composite_flow_risk", content)
        self.assertIn("feature-traced", content)
        self.assertIn("Evidence gate", content)
        self.assertIn("False positive", content)
        self.assertIn("validation_evaluated_after_selection", content)
        self.assertIn("active_protection_changed", content)
        self.assertIn("deployment_allowed", content)

    def test_card_has_no_control_action_or_control_entity(self):
        lower = self.raw.lower()
        forbidden = (
            "tap_action:",
            "hold_action:",
            "double_tap_action:",
            "perform_action:",
            "call-service",
            "service:",
            "switch.",
            "climate.",
            "input_boolean.",
            "input_number.",
            "script.",
            "automation.",
        )
        for token in forbidden:
            self.assertNotIn(token, lower, token)

        entities = set(re.findall(r"[a-z_]+\.[a-z0-9_]+", self.raw))
        self.assertTrue(entities)
        self.assertTrue(
            all(entity.startswith("sensor.heating_agent_") for entity in entities),
            entities,
        )


if __name__ == "__main__":
    unittest.main()
