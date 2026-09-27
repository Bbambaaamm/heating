"""Historical shadow-rule replay with held-out validation."""
from __future__ import annotations

from statistics import median
from typing import Any
from uuid import uuid4

from .engine import RULES, rule_description
from .permissions import PermissionManifest


_RISE_RANK = {
    "lt_0_05": 0,
    "ge_0_05": 1,
    "ge_0_1": 2,
    "ge_0_2": 3,
}
_AGE_RANK = {
    "lt_30": 0,
    "ge_30": 1,
    "ge_60": 2,
    "ge_120": 3,
}
_RISE_THRESHOLDS = (None, "ge_0_05", "ge_0_1", "ge_0_2")
_AGE_THRESHOLDS = (None, "ge_30", "ge_60", "ge_120")
_PHASES = (None, "burning", "request_preburn")


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

    @staticmethod
    def _composite_specs() -> list[dict[str, Any]]:
        specs = []
        for pi10_max in (0, 1, 2):
            for rise_min in _RISE_THRESHOLDS:
                for phase in _PHASES:
                    for request_age_min in _AGE_THRESHOLDS:
                        # PI-only rules already exist in the base replay catalog.
                        if rise_min is None and phase is None and request_age_min is None:
                            continue
                        parts = [f"pi10_le_{pi10_max}"]
                        if rise_min is not None:
                            parts.append(f"rise_{rise_min}")
                        if phase is not None:
                            parts.append(f"phase_{phase}")
                        if request_age_min is not None:
                            parts.append(f"age_{request_age_min}")
                        specs.append({
                            "rule": "composite_" + "__".join(parts),
                            "pi10_max": pi10_max,
                            "block_rise_min": rise_min,
                            "phase": phase,
                            "request_age_min": request_age_min,
                        })
        return specs

    @staticmethod
    def _feature_matches(feature: dict[str, Any], spec: dict[str, Any]) -> bool:
        try:
            pi10_count = int(feature.get("pi10_count"))
        except (TypeError, ValueError):
            return False
        if pi10_count > int(spec["pi10_max"]):
            return False

        rise_min = spec.get("block_rise_min")
        if rise_min is not None:
            current = _RISE_RANK.get(feature.get("block_rise_band"))
            required = _RISE_RANK.get(rise_min)
            if current is None or required is None or current < required:
                return False

        phase = spec.get("phase")
        if phase is not None and feature.get("phase") != phase:
            return False

        age_min = spec.get("request_age_min")
        if age_min is not None:
            current = _AGE_RANK.get(feature.get("request_age_band"))
            required = _AGE_RANK.get(age_min)
            if current is None or required is None or current < required:
                return False
        return True

    @classmethod
    def _composite_score(
        cls,
        spec: dict[str, Any],
        dataset: dict[str, list[dict[str, Any]]],
        lead_budget: float,
    ) -> dict[str, Any]:
        faults = [e for e in dataset["faults"] if e.get("shadow_fault_window")]
        normal = [e for e in dataset["normal"] if e.get("shadow_seen")]
        leads = []
        for episode in faults:
            fault_at = episode.get("fault_at")
            if fault_at is None:
                continue
            fault_at = float(fault_at)
            starts = []
            for feature in episode.get("shadow_fault_window") or []:
                if not cls._feature_matches(feature, spec):
                    continue
                start = float(feature.get("start", fault_at))
                end = float(feature.get("end", start))
                if end < fault_at - 180 or start >= fault_at:
                    continue
                starts.append(max(start, fault_at - 180))
            if starts:
                leads.append(fault_at - min(starts))

        warned_normal = sum(
            any(cls._feature_matches(feature, spec) for feature in (episode.get("shadow_seen") or []))
            for episode in normal
        )
        detected = len(leads)
        timely = sum(lead >= lead_budget for lead in leads)
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

    @classmethod
    def _composite_search(
        cls,
        datasets: dict[str, dict[str, list[dict[str, Any]]]],
        lead_budget: float,
    ) -> dict[str, Any]:
        evidence_faults = sum(bool(e.get("shadow_fault_window")) for e in datasets["evidence"]["faults"])
        evidence_normal = sum(bool(e.get("shadow_seen")) for e in datasets["evidence"]["normal"])
        validation_faults = sum(bool(e.get("shadow_fault_window")) for e in datasets["validation"]["faults"])
        validation_normal = sum(bool(e.get("shadow_seen")) for e in datasets["validation"]["normal"])
        enough = (
            evidence_faults >= 3
            and evidence_normal >= 20
            and validation_faults >= 1
            and validation_normal >= 10
        )

        rows = []
        for spec in cls._composite_specs():
            evidence = cls._composite_score(spec, datasets["evidence"], lead_budget)
            validation = cls._composite_score(spec, datasets["validation"], lead_budget)
            rows.append({
                "rule": spec["rule"],
                "definition": {
                    "pi10_max": spec["pi10_max"],
                    "block_rise_min": spec["block_rise_min"],
                    "phase": spec["phase"],
                    "request_age_min": spec["request_age_min"],
                },
                "evidence": evidence,
                "validation": validation,
                "operating_policy_changed": False,
            })

        # Rank exclusively on evidence. Held-out validation is reported afterwards,
        # never used to select or order candidates.
        ranked = sorted(
            rows,
            key=lambda row: (
                -row["evidence"]["timely"],
                row["evidence"]["missed"],
                row["evidence"]["warned_normal"],
                -(row["evidence"]["lead_median_s"] or -1),
                row["rule"],
            ),
        )
        candidate = ranked[0] if enough and ranked and ranked[0]["evidence"]["detected"] else None
        status = "INSUFFICIENT_FEATURE_EVIDENCE"
        if candidate is not None:
            validation = candidate["validation"]
            evidence = candidate["evidence"]
            low_false_positive = (
                (evidence.get("warned_normal_rate") or 0) <= 0.25
                and (validation.get("warned_normal_rate") or 0) <= 0.25
            )
            no_misses = evidence["missed"] == 0 and validation["missed"] == 0
            status = (
                "PROMISING_SHADOW_CANDIDATE"
                if low_false_positive and no_misses
                else "CANDIDATE_NEEDS_REFINEMENT"
            )

        return {
            "agent": "composite-flow-risk-v1",
            "status": status,
            "minimum_evidence": {
                "evidence_faults": 3,
                "evidence_normal_controls": 20,
                "validation_faults": 1,
                "validation_normal_controls": 10,
            },
            "dataset": {
                "evidence_faults": evidence_faults,
                "evidence_normal_controls": evidence_normal,
                "validation_faults": validation_faults,
                "validation_normal_controls": validation_normal,
            },
            "selection_basis": "evidence_only",
            "validation_used_for_ranking": False,
            "candidate_rule": candidate["rule"] if candidate else None,
            "candidate": candidate,
            "top_rules": ranked[:12],
            "active_protection_changed": False,
            "deployment_allowed": False,
            "meaning": (
                "offline shadow conjunction search over quantized proxy features; "
                "not proof of physical flow and never an operating or safety limit"
            ),
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
        composite_flow_risk = self._composite_search(datasets, lead_budget)
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
            "composite_flow_risk": composite_flow_risk,
            "active_protection_changed": False,
            "meaning": "offline shadow evaluation only; not proof that an intervention prevents a physical fault",
        }
