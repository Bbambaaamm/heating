"""Evidence-only Heating Intelligence Agent."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from .permissions import PermissionManifest


class HeatingIntelligenceAgent:
    name = "intelligence-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def propose(self, replay: dict[str, Any]) -> dict[str, Any]:
        self.permissions.require(self.name, "candidate.propose")
        dataset = replay.get("dataset", {})
        rules = replay.get("rules", [])
        if not replay.get("enough_for_candidate_review") or not rules:
            return {
                "candidate_id": str(uuid4()),
                "agent": self.name,
                "status": "INSUFFICIENT_EVIDENCE",
                "candidate_rule": None,
                "source_replay_id": replay.get("replay_id"),
                "evidence_needed": {
                    "evidence_faults_min": 3,
                    "evidence_normal_controls_min": 20,
                    "validation_faults_min": 1,
                    "validation_normal_controls_min": 10,
                },
                "current_dataset": dataset,
                "active_policy_changed": False,
                "deployment_allowed": False,
            }

        by_rule = {row["rule"]: row for row in rules}
        ordered = [
            by_rule[name]
            for name in replay.get("descriptive_rule_order", [])
            if name in by_rule
        ]
        candidate = ordered[0] if ordered else rules[0]
        validation = candidate["validation"]
        status = (
            "PROPOSED_FOR_HUMAN_REVIEW"
            if validation["fault_incidents"] > 0 and validation["missed"] == 0
            else "VALIDATION_FAILED_OR_INCOMPLETE"
        )
        return {
            "candidate_id": str(uuid4()),
            "agent": self.name,
            "status": status,
            "candidate_rule": candidate["rule"],
            "description": candidate["description"],
            "source_replay_id": replay.get("replay_id"),
            "evidence_metrics": candidate["evidence"],
            "validation_metrics": validation,
            "active_policy_changed": False,
            "deployment_allowed": False,
            "requires_human_review": True,
            "note": "candidate is descriptive evidence, never an active Home Assistant safety rule",
        }
