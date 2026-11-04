"""Evidence-only Heating Intelligence Agent."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from .permissions import PermissionManifest


def review_failures(metrics: dict[str, Any]) -> list[str]:
    """Review gate only: require timely detection and <=10% warned controls.

    Calculate ratios from integer counts; never trust a cached/display rate.
    This small holdout gate is not a significance test or deployment approval.
    """
    keys = ("fault_incidents", "detected", "timely", "missed", "late",
            "normal_controls", "warned_normal")
    if not isinstance(metrics, dict) or any(type(metrics.get(k)) is not int or metrics[k] < 0 for k in keys):
        return ["missing_or_invalid_validation_counts"]
    faults, detected, timely, missed, late, normal, warned = (metrics[k] for k in keys)
    failures = []
    if detected + missed != faults or timely + late != detected or warned > normal:
        failures.append("inconsistent_validation_counts")
    if faults < 1 or normal < 10:
        failures.append("insufficient_validation_controls")
    if faults == 0 or timely != faults or late or missed:
        failures.append("not_all_faults_detected_in_time")
    if normal == 0 or warned * 10 > normal:
        failures.append("warned_normal_rate_above_10_percent")
    return failures


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
        validation = candidate.get("validation") or {}
        failures = review_failures(validation)
        status = (
            "PROPOSED_FOR_HUMAN_REVIEW"
            if not failures
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
            "review_failures": failures,
            "review_criteria": {"all_validation_faults_timely": True,
                                "warned_normal_rate_max": 0.1,
                                "validation_normal_controls_min": 10,
                                "statistical_significance_proven": False},
            "active_policy_changed": False,
            "deployment_allowed": False,
            "requires_human_review": True,
            "note": "candidate is descriptive evidence, never an active Home Assistant safety rule",
        }
