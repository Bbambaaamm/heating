"""Shared deterministic data model for the Heating Agent Platform."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FAULT_CODES = frozenset({2964, 2965, 2966, 2967})


@dataclass(frozen=True)
class ZoneState:
    entity_id: str
    hvac_state: str | None
    current_temperature: float | None
    target_temperature: float | None
    pi_demand: float | None

    @property
    def requesting(self) -> bool:
        return self.hvac_state == "heat" and self.pi_demand is not None and self.pi_demand >= 10.0


@dataclass(frozen=True)
class HeatingSnapshot:
    timestamp: float
    site_revision: str
    relay: bool | None
    gas: bool | None
    pump: bool | None
    master: bool | None
    service: bool | None
    mode: str | None
    dhw: bool | None
    dhw_recharging: bool | None
    dhw_valve: bool | None
    boiler_block_temperature: float | None
    flow_temperature: float | None
    burner_power: float | None
    service_code: int | None
    zones: dict[str, ZoneState]
    quality: tuple[str, ...] = ()

    def requesting_zone_count(self) -> int:
        return sum(zone.requesting for zone in self.zones.values())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CycleSummary:
    cycle_id: str
    site_revision: str
    started_at: float
    ended_at: float | None
    start_kind: str
    incomplete: bool
    runtime_seconds: float | None
    burner_starts: int
    start_boiler_temperature: float | None
    max_boiler_temperature: float | None
    max_temperature_rise_c_per_min: float | None
    min_requesting_zones: int | None
    average_requesting_zones: float | None
    fault_codes: tuple[int, ...]
    service_seen: bool
    master_off_seen: bool
    dhw_seen: bool
    quality_flags: tuple[str, ...]
    eligible_for_baseline: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Incident:
    incident_id: str
    cycle_id: str | None
    incident_type: str
    severity: str
    occurred_at: float
    observation: dict[str, Any]
    timeline: tuple[dict[str, Any], ...]
    diagnosis: None = field(default=None, init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
