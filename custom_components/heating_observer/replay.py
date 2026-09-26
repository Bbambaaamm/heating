"""Historical shadow-rule replay with held-out validation."""
from __future__ import annotations

from statistics import median
from typing import Any
from uuid import uuid4

from .engine import RULES, rule_description
from .permissions import PermissionManifest


def _split_holdout(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(items) < 2:
        return items[:], []
    validation_count = max(1, len(items) // 4)
    return items[:-validation_count], items[-validation_count:]


class ReplayValidationAgent:
    name = "replay-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    @staticmethod
    def _datasets(episodes: list[dict[str, Any]]):
        eligible = [e for e in episodes if e.get("eligible")]
        faults = []
        seen = set()
        normal = []
        for episode in sorted(eligible, key=lambda e: (e.get("start") or 0, e.get("id") or "")):
            if episode.get("outcome") == "fault":
                incident_id = episode.get("incident_id")
                if incident_id and incident_id not in seen:
                    seen.add(incident_id)
                    faults.append(episode)
            elif episode.get("outcome") == "observed_no_fault":
                normal.append(episode)
        evidence_faults, validation_faults = _split_holdout(faults)
        evidence_normal, validation_normal = _split_holdout(normal)
        return {
            "evidence": {"faults": evidence_faults, "normal": evidence_normal},
            "validation": {"faults": validation_faults, "normal": validation_normal},
        }

    @staticmethod
    def _score(rule: str, dataset: dict[str, list[dict[str, Any]]], lead_budget: float) -> dict[str, Any]:
        faults = dataset["faults"]
        normal = dataset["normal"]
        leads = [
            float(e["fault_leads"][rule])
            for e in faults
            if rule in (e.get("fault_leads") or {})
        ]
        detected = len(leads)
        timely = sum(lead >= lead_budget for lead in leads)
        warned_normal = sum(rule in (e.get("warned") or []) for e in normal)
        return {
            "fault_incidents": len(faults),
            "detected": detected,
            "timely": timely,
            "missed": len(faults) - detected,
            "late": detected - timely,
            "lead_median_s": median(leads) if leads else None,
            "normal_controls": len(normal),
            "warned_normal": warned_normal,
            "warned_normal_rate": warned_normal / len(normal) if normal else None,
        }

    def run(
        self,
        episodes: list[dict[str, Any]],
        *,
        revision: str,
        generation: int,
        lead_budget: float,
    ) -> dict[str, Any]:
        self.permissions.require(self.name, "replay.execute")
        datasets = self._datasets(episodes)
        rules = []
        for rule in RULES:
            evidence = self._score(rule, datasets["evidence"], lead_budget)
            validation = self._score(rule, datasets["validation"], lead_budget)
            rules.append({
                "rule": rule,
                "description": rule_description(rule),
                "evidence": evidence,
                "validation": validation,
                "operating_policy_changed": False,
            })

        descriptive_order = sorted(
            rules,
            key=lambda row: (
                -row["evidence"]["timely"],
                row["evidence"]["missed"],
                row["evidence"]["warned_normal"],
                row["rule"],
            ),
        )
        evidence_faults = len(datasets["evidence"]["faults"])
        evidence_normal = len(datasets["evidence"]["normal"])
        validation_faults = len(datasets["validation"]["faults"])
        validation_normal = len(datasets["validation"]["normal"])
        enough_for_candidate_review = (
            evidence_faults >= 3
            and evidence_normal >= 20
            and validation_faults >= 1
            and validation_normal >= 10
        )
        return {
            "replay_id": str(uuid4()),
            "agent": self.name,
            "revision": revision,
            "generation": generation,
            "lead_budget_s": lead_budget,
            "dataset": {
                "evidence_faults": evidence_faults,
                "evidence_normal_controls": evidence_normal,
                "validation_faults": validation_faults,
                "validation_normal_controls": validation_normal,
            },
            "enough_for_candidate_review": enough_for_candidate_review,
            "descriptive_rule_order": [row["rule"] for row in descriptive_order],
            "rules": rules,
            "active_protection_changed": False,
            "meaning": "offline shadow evaluation only; not proof that an intervention prevents a physical fault",
        }
