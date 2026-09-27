"""Autonomous improvement agents for energy, comfort, schedules and maintenance.

All agents are proposal-only. They may create evidence-backed opportunities and
shadow experiments, but they never call Home Assistant services or mutate
heating control configuration.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any

from .permissions import PermissionManifest


def _opportunity(
    *,
    agent: str,
    category: str,
    key: str,
    title: str,
    rationale: str,
    risk_class: str,
    confidence: float,
    evidence: dict[str, Any],
    experiment: dict[str, Any] | None = None,
    changed_paths: list[str] | None = None,
    estimated_saving_kwh_month: float | None = None,
    physical_control_change: bool = False,
) -> dict[str, Any]:
    fingerprint = sha256(f"{category}:{key}".encode()).hexdigest()[:20]
    changed_paths = changed_paths or []
    return {
        "fingerprint": fingerprint,
        "agent": agent,
        "category": category,
        "title": title,
        "rationale": rationale,
        "risk_class": risk_class,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "status": "NEW",
        "evidence": evidence,
        "experiment": experiment,
        "changed_paths": changed_paths,
        "estimated_saving_kwh_month": estimated_saving_kwh_month,
        "physical_control_change": physical_control_change,
        "active_policy_changed": False,
        "deployment_allowed": False,
    }


class EnergyEfficiencyAgent:
    name = "energy-efficiency-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "optimization.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        gas_24h = summary.get("gas_heat_24h_kwh")
        outside = summary.get("outside_temperature_mean")
        if gas_24h is not None and outside is not None and outside >= 10 and gas_24h >= 10:
            out.append(_opportunity(
                agent=self.name,
                category="energy",
                key="mild-weather-gas",
                title="Ověřit snížení spotřeby v mírném počasí",
                rationale=(
                    "Za posledních 24 h je spotřeba vytápění významná i při relativně "
                    "mírné venkovní teplotě. Nejdřív shadow-testovat kratší comfort okna "
                    "a menší předstih, ne měnit aktivní teploty naslepo."
                ),
                risk_class="yellow",
                confidence=0.65,
                evidence={"gas_24h_kwh": gas_24h, "outside_mean_c": outside},
                experiment={
                    "type": "shadow_schedule_trim",
                    "variants": ["comfort_window_-15min", "preheat_-15min"],
                    "success_metrics": ["gas_kwh_per_degree_hour", "comfort_deficit_minutes", "fault_rate"],
                },
                physical_control_change=True,
            ))
        if summary.get("gas_price_czk_kwh") is None:
            out.append(_opportunity(
                agent=self.name,
                category="cost",
                key="missing-gas-tariff",
                title="Doplnit cenu plynu pro finanční optimalizaci",
                rationale=(
                    "Systém umí měřit kWh plynu, ale bez ceny za kWh neumí převádět "
                    "úspory na Kč ani prioritizovat návrhy podle návratnosti."
                ),
                risk_class="green",
                confidence=1.0,
                evidence={"gas_meter_available": summary.get("gas_meter_available", False)},
                experiment={"type": "data_input", "required_value": "gas_price_czk_kwh"},
                changed_paths=["docs/heating-agent-platform.md"],
                physical_control_change=False,
            ))
        return out


class ComfortAgent:
    name = "comfort-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "optimization.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        for zone, row in summary.get("zones", {}).items():
            active = int(row.get("comfort_samples", 0))
            if active < 12:
                continue
            over = float(row.get("overshoot_rate", 0))
            under = float(row.get("undershoot_rate", 0))
            if over >= 0.35:
                out.append(_opportunity(
                    agent=self.name,
                    category="comfort_energy",
                    key=f"{zone}:overshoot",
                    title=f"{zone}: omezit přetápění v comfort okně",
                    rationale=(
                        "Místnost je během významné části comfort okna více než 1 °C nad cílem. "
                        "Nejdřív simulovat pozdější start/nižší comfort o 0,5 °C a hlídat návrat komfortu."
                    ),
                    risk_class="yellow",
                    confidence=min(0.9, 0.5 + over / 2),
                    evidence=row,
                    experiment={
                        "type": "shadow_comfort_reduction",
                        "zone": zone,
                        "variants": ["target_-0.5C", "start_15min_later"],
                        "rollback_condition": "comfort_deficit_minutes increases materially",
                    },
                    physical_control_change=True,
                ))
            if under >= 0.35:
                out.append(_opportunity(
                    agent=self.name,
                    category="comfort",
                    key=f"{zone}:undershoot",
                    title=f"{zone}: vyřešit nedotápění během comfort okna",
                    rationale=(
                        "Místnost je často více než 1 °C pod cílem. Před prodloužením topení "
                        "porovnat předstih, PI požadavek, hydrauliku a reakci radiátoru."
                    ),
                    risk_class="yellow",
                    confidence=min(0.9, 0.5 + under / 2),
                    evidence=row,
                    experiment={"type": "root_cause_before_schedule_extension", "zone": zone},
                    physical_control_change=True,
                ))
        return out


class ScheduleOptimizationAgent:
    name = "schedule-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "optimization.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        single = summary.get("relay_on_single_schedule_fraction")
        relay_samples = int(summary.get("relay_on_samples", 0))
        if single is not None and relay_samples >= 20 and single >= 0.45:
            out.append(_opportunity(
                agent=self.name,
                category="schedule",
                key="single-zone-overlap",
                title="Otestovat lepší překryv comfort oken mezi zónami",
                rationale=(
                    "Při sepnutém požadavku kotle je často aktivní jen jedno rozvrhové okno. "
                    "Lepší překryv sousedních zón může zvýšit hydraulický odběr a snížit cyklování "
                    "bez zvyšování comfort teplot."
                ),
                risk_class="yellow",
                confidence=min(0.9, 0.5 + single / 2),
                evidence={"fraction": single, "relay_on_samples": relay_samples},
                experiment={
                    "type": "shadow_schedule_alignment",
                    "objective": "reduce internal burner restarts while preserving room comfort",
                },
                physical_control_change=True,
            ))
        return out


class HydraulicsOptimizationAgent:
    name = "hydraulics-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any], replay: dict[str, Any] | None) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "optimization.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        avg_starts = summary.get("cycle_avg_burner_starts")
        cycles = int(summary.get("cycle_count", 0))
        if avg_starts is not None and cycles >= 5 and avg_starts >= 1.5:
            out.append(_opportunity(
                agent=self.name,
                category="hydraulics",
                key="internal-restarts",
                title="Snížit interní restarty hořáku v jednom request cyklu",
                rationale=(
                    "Request cykly obsahují opakované starty hořáku. Prioritou je ověřit "
                    "časový překryv odběrných zón a skutečný průtok; safety prahy se neuvolňují."
                ),
                risk_class="yellow",
                confidence=min(0.9, 0.5 + (avg_starts - 1) / 3),
                evidence={"cycle_count": cycles, "avg_burner_starts": avg_starts},
                experiment={"type": "shadow_zone_overlap_vs_restarts"},
                physical_control_change=True,
            ))
        if replay:
            rules = {r.get("rule"): r for r in replay.get("rules", [])}
            low_zone = rules.get("pi10_count_lt3")
            if low_zone:
                ev = low_zone.get("evidence", {})
                if ev.get("detected", 0) and (ev.get("warned_normal_rate") or 0) >= 0.30:
                    out.append(_opportunity(
                        agent=self.name,
                        category="engineering",
                        key="composite-flow-risk-rule",
                        title="Vyvinout kombinované flow-risk pravidlo místo samotného počtu TRV",
                        rationale=(
                            "Nízký počet requesting zón zachycuje poruchy s předstihem, ale samotný "
                            "signál má příliš mnoho false-positive oken. Agent má hledat kombinaci "
                            "PI count + teplotní dynamika + fáze burner/request cyklu."
                        ),
                        risk_class="green",
                        confidence=0.9,
                        evidence={
                            "rule": "pi10_count_lt3",
                            "detected": ev.get("detected"),
                            "lead_median_s": ev.get("lead_median_s"),
                            "warned_normal_rate": ev.get("warned_normal_rate"),
                        },
                        experiment={
                            "type": "composite_rule_search",
                            "features": ["pi10_count", "block_rise", "burner_phase", "request_age"],
                            "validation": "held_out",
                        },
                        changed_paths=["agent_platform/**", "custom_components/heating_observer/**", "tests/**"],
                        physical_control_change=False,
                    ))
        return out


class MaintenanceAgent:
    name = "maintenance-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "maintenance.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        unhealthy = summary.get("valves_unhealthy")
        if unhealthy is not None and unhealthy > 0:
            out.append(_opportunity(
                agent=self.name,
                category="maintenance",
                key="unhealthy-valves",
                title="Prověřit nedostupné nebo nezdravé TRV",
                rationale="Nezdravá hlavice zhoršuje komfort i spolehlivost hydraulických závěrů.",
                risk_class="green",
                confidence=0.95,
                evidence={"unhealthy_valves": unhealthy},
                experiment={"type": "device_health_audit"},
                physical_control_change=False,
            ))
        if safety.get("warnings"):
            out.append(_opportunity(
                agent=self.name,
                category="maintenance",
                key="safety-warning-followup",
                title="Vyhodnotit opakované Safety Sentinel warningy",
                rationale="Safety Sentinel eviduje warningy, které mají být analyzovány dřív, než se změní v incident.",
                risk_class="green",
                confidence=0.9,
                evidence={"warnings": safety.get("warnings")},
                experiment={"type": "warning_trend_analysis"},
                physical_control_change=False,
            ))
        return out


class DataQualityAgent:
    name = "data-quality-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(self, summary: dict[str, Any], sample: dict[str, Any]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "data_quality.evaluate")
        self.permissions.require(self.name, "opportunity.propose")
        out = []
        missing = []
        for key in ("gas_heat_total_kwh", "outside_temperature", "family_home"):
            if sample.get(key) is None:
                missing.append(key)
        if missing:
            out.append(_opportunity(
                agent=self.name,
                category="data_quality",
                key="missing-optimization-context",
                title="Doplnit chybějící kontext pro optimalizační agenty",
                rationale="Bez kompletního kontextu nelze některé úsporné návrhy spolehlivě validovat.",
                risk_class="green",
                confidence=1.0,
                evidence={"missing": missing},
                experiment={"type": "sensor_data_quality_audit"},
                changed_paths=["custom_components/heating_observer/**", "tests/**"],
                physical_control_change=False,
            ))
        return out


class OpportunityOrchestrator:
    name = "opportunity-orchestrator-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def consolidate(self, opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.permissions.require(self.name, "opportunity.manage")
        unique = {}
        rank = {"red": 3, "yellow": 2, "green": 1}
        for row in opportunities:
            current = unique.get(row["fingerprint"])
            if current is None or row["confidence"] > current["confidence"]:
                unique[row["fingerprint"]] = row
        rows = list(unique.values())
        for row in rows:
            if row["risk_class"] == "green" and not row["physical_control_change"]:
                row["next_action"] = "AUTO_PR_ELIGIBLE"
            elif row["risk_class"] == "yellow":
                row["next_action"] = "SHADOW_VALIDATE_THEN_REVIEW"
            else:
                row["next_action"] = "HUMAN_SAFETY_REVIEW"
            row["priority_score"] = round(100 * row["confidence"] + 10 * rank.get(row["risk_class"], 0), 1)
        return sorted(rows, key=lambda x: (-x["priority_score"], x["category"], x["title"]))
