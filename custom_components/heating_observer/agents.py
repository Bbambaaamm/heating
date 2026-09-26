"""Deterministic Diagnostic and Knowledge agents.

These agents produce evidence artifacts only. They do not own or call Home
Assistant services, and a hypothesis is never promoted to a fact automatically.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any
from uuid import uuid4

from .engine import number


def _requesting(snapshot: dict[str, Any], threshold: float = 10.0) -> int | None:
    zones = snapshot.get("zones")
    if not isinstance(zones, dict) or not zones:
        return None
    valid = 0
    count = 0
    for zone in zones.values():
        pi = number(zone.get("pi"))
        if zone.get("state") not in ("heat", "off") or pi is None:
            continue
        valid += 1
        if zone.get("state") == "heat" and pi >= threshold:
            count += 1
    return count if valid == len(zones) else None


def _max_block_rise(prelude: list[dict[str, Any]]) -> float | None:
    last: tuple[float, float] | None = None
    result: float | None = None
    for sample in prelude:
        temp = number(sample.get("block"))
        t = number(sample.get("block_reported_at")) or number(sample.get("t"))
        if temp is None or t is None:
            continue
        if last is not None:
            dt = t - last[0]
            if 1 <= dt <= 45:
                rise = (temp - last[1]) / dt
                result = rise if result is None else max(result, rise)
        if last is None or t > last[0]:
            last = (t, temp)
    return result


class DiagnosticAgent:
    """Create competing hypotheses from a fault incident's recorded evidence."""

    name = "diagnostic-v1"

    def analyze(self, incident: dict[str, Any]) -> dict[str, Any]:
        prelude = deepcopy(incident.get("prelude") or [])
        fault_code = incident.get("code")
        counts = [c for c in (_requesting(s) for s in prelude) if c is not None]
        min_requesting = min(counts) if counts else None
        max_rise = _max_block_rise(prelude)
        quality = sorted({
            q for sample in prelude for q in sample.get("quality", [])
            if isinstance(q, str)
        })
        dhw_seen = any(any(s.get(key) is True for key in ("dhw", "dhw_recharging", "dhw_valve")) for s in prelude)

        facts = [
            f"Home Assistant zaznamenal přechod na servisní kód {fault_code}.",
            f"Předporuchový kontext obsahuje {len(prelude)} vzorků.",
        ]
        if min_requesting is not None:
            facts.append(f"Nejnižší pozorovaný počet hlavic s PI≥10 % byl {min_requesting}.")
        if max_rise is not None:
            facts.append(f"Nejvyšší pozorovaný růst teploty bloku byl {max_rise:.3f} K/s.")
        if quality:
            facts.append("Část předporuchových dat měla quality flags: " + ", ".join(quality) + ".")
        if dhw_seen:
            facts.append("V předporuchovém okně byl zaznamenán TUV kontext.")

        hypotheses = []

        low_flow_for = []
        low_flow_against = []
        low_flow_confidence = 0.25
        if min_requesting is not None and min_requesting < 3:
            low_flow_for.append(f"Počet requesting zón klesl až na {min_requesting}.")
            low_flow_for.append("Stejný typ proxy je ve stávajícím observeru sledován před interními restarty.")
            low_flow_confidence = 0.70 if not quality and not dhw_seen else 0.50
        elif min_requesting is not None:
            low_flow_against.append(f"V dostupném okně zůstaly alespoň {min_requesting} requesting zóny.")
        else:
            low_flow_against.append("Počet requesting zón nelze z dostupných dat spolehlivě určit.")
        low_flow_against.append("PI požadavek hlavice nepotvrzuje fyzickou polohu ventilu ani průtok.")
        hypotheses.append({
            "name": "Nedostatečná hydraulická odběrná kapacita",
            "evidence_for": low_flow_for,
            "evidence_against": low_flow_against,
            "confidence": low_flow_confidence,
            "status": "HYPOTHESIS",
        })

        heat_for = []
        heat_against = []
        heat_confidence = 0.20
        if max_rise is not None and max_rise >= 0.2:
            heat_for.append(f"Růst bloku dosáhl {max_rise:.3f} K/s, tedy překročil pozorovací hypotézu 0,2 K/s.")
            heat_confidence = 0.65 if not quality else 0.45
        elif max_rise is not None:
            heat_against.append(f"Pozorovaný růst {max_rise:.3f} K/s nebyl mimo hypotézu 0,2 K/s.")
        else:
            heat_against.append("Chybí dostatek čerstvých měření pro výpočet růstu teploty.")
        hypotheses.append({
            "name": "Rychlá akumulace tepla před poruchou",
            "evidence_for": heat_for,
            "evidence_against": heat_against,
            "confidence": heat_confidence,
            "status": "HYPOTHESIS",
        })

        telemetry_for = []
        telemetry_against = []
        telemetry_confidence = 0.15
        if quality:
            telemetry_for.append("Před poruchou byly přítomné quality flags: " + ", ".join(quality) + ".")
            telemetry_confidence = 0.55
        else:
            telemetry_against.append("V uloženém předporuchovém kontextu nejsou explicitní quality flags.")
        hypotheses.append({
            "name": "Neúplná nebo časově nesourodá telemetrie ovlivňuje interpretaci",
            "evidence_for": telemetry_for,
            "evidence_against": telemetry_against,
            "confidence": telemetry_confidence,
            "status": "HYPOTHESIS",
        })

        next_measurement = (
            "Nejcennější další měření je nezávislé potvrzení skutečného průtoku "
            "nebo fyzické polohy alespoň jedné referenční odběrné větve; PI TRV je pouze proxy."
        )
        safety_implication = (
            "Diagnostika sama nemění ochranu ani řízení. Stávající safety logika zůstává autoritativní."
        )
        return {
            "diagnostic_id": str(uuid4()),
            "agent": self.name,
            "incident_id": incident.get("incident_id"),
            "episode_id": incident.get("episode_id"),
            "fault_code": fault_code,
            "facts": facts,
            "hypotheses": hypotheses,
            "next_measurement": next_measurement,
            "safety_implication": safety_implication,
            "root_cause": "UNKNOWN",
        }


class KnowledgeAgent:
    """Convert diagnostics to typed knowledge entries without promotion."""

    name = "knowledge-v1"

    def entries_for(self, diagnostic: dict[str, Any], *, created_at: float) -> list[dict[str, Any]]:
        entries = []
        incident_id = diagnostic.get("incident_id")
        for fact in diagnostic.get("facts", []):
            entries.append({
                "knowledge_id": str(uuid4()),
                "kind": "OBSERVATION",
                "statement": fact,
                "source_incident_id": incident_id,
                "created_at": created_at,
                "confidence": 1.0,
                "promoted": False,
            })
        for hypothesis in diagnostic.get("hypotheses", []):
            entries.append({
                "knowledge_id": str(uuid4()),
                "kind": "HYPOTHESIS",
                "statement": hypothesis["name"],
                "source_incident_id": incident_id,
                "created_at": created_at,
                "confidence": float(hypothesis["confidence"]),
                "promoted": False,
                "evidence_for": list(hypothesis.get("evidence_for", [])),
                "evidence_against": list(hypothesis.get("evidence_against", [])),
            })
        entries.append({
            "knowledge_id": str(uuid4()),
            "kind": "DECISION",
            "statement": diagnostic["safety_implication"],
            "source_incident_id": incident_id,
            "created_at": created_at,
            "confidence": 1.0,
            "promoted": False,
        })
        return entries

    @staticmethod
    def summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(entry.get("kind", "UNKNOWN") for entry in entries)
        latest = entries[-5:]
        return {
            "entries": len(entries),
            "by_kind": dict(counts),
            "latest": latest,
            "facts_promoted_from_hypotheses": 0,
        }
