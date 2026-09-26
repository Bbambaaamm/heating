"""Objective incident detection and evidence timelines.

This module detects observations only. It does not diagnose root cause and it
never sends a command to Home Assistant.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from statistics import mean, pstdev
from uuid import uuid4

from .model import CycleSummary, FAULT_CODES, HeatingSnapshot, Incident


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


@dataclass
class BaselineModel:
    minimum_cycles: int = 20
    maximum_cycles: int = 200
    max_rises: list[float] = field(default_factory=list)
    average_requesting_zones: list[float] = field(default_factory=list)

    def add(self, cycle: CycleSummary) -> None:
        if not cycle.eligible_for_baseline:
            return
        if cycle.max_temperature_rise_c_per_min is None or cycle.average_requesting_zones is None:
            return
        self.max_rises.append(cycle.max_temperature_rise_c_per_min)
        self.average_requesting_zones.append(cycle.average_requesting_zones)
        self.max_rises = self.max_rises[-self.maximum_cycles :]
        self.average_requesting_zones = self.average_requesting_zones[-self.maximum_cycles :]

    @property
    def ready(self) -> bool:
        return len(self.max_rises) >= self.minimum_cycles

    def anomaly_thresholds(self) -> tuple[float | None, float | None]:
        if not self.ready:
            return None, None
        avg = mean(self.max_rises)
        spread = pstdev(self.max_rises)
        p95 = _percentile(self.max_rises, 0.95)
        # Descriptive outlier gate, not a boiler safety limit.
        rise_threshold = max((p95 or avg) * 1.5, avg + 3.0 * spread, (p95 or avg) + 0.5)
        low_zone_threshold = _percentile(self.average_requesting_zones, 0.10)
        return rise_threshold, low_zone_threshold

    def summary(self) -> dict:
        rise, zones = self.anomaly_thresholds()
        return {
            "cycles": len(self.max_rises),
            "ready": self.ready,
            "rise_outlier_threshold_c_per_min": rise,
            "low_requesting_zone_threshold": zones,
            "meaning": "observed baseline only; not an operating or safety limit",
        }


class Observer:
    def __init__(self, *, timeline_samples: int = 120, baseline: BaselineModel | None = None):
        self.timeline: deque[dict] = deque(maxlen=timeline_samples)
        self.baseline = baseline or BaselineModel()
        self.previous: HeatingSnapshot | None = None
        self._last_temp: tuple[float, float] | None = None
        self._incident_keys: set[str] = set()

    @staticmethod
    def _timeline_row(snapshot: HeatingSnapshot) -> dict:
        return {
            "t": snapshot.timestamp,
            "relay": snapshot.relay,
            "gas": snapshot.gas,
            "master": snapshot.master,
            "service": snapshot.service,
            "boiler_block_temperature": snapshot.boiler_block_temperature,
            "flow_temperature": snapshot.flow_temperature,
            "service_code": snapshot.service_code,
            "requesting_zones": snapshot.requesting_zone_count(),
            "quality": list(snapshot.quality),
            "physical_flow_confirmed": False,
        }

    def _incident(
        self,
        *,
        cycle_id: str | None,
        incident_type: str,
        severity: str,
        snapshot: HeatingSnapshot,
        observation: dict,
    ) -> Incident:
        return Incident(
            incident_id=str(uuid4()),
            cycle_id=cycle_id,
            incident_type=incident_type,
            severity=severity,
            occurred_at=snapshot.timestamp,
            observation=observation,
            timeline=tuple(self.timeline),
        )

    def feed(self, snapshot: HeatingSnapshot, *, cycle_id: str | None) -> list[Incident]:
        self.timeline.append(self._timeline_row(snapshot))
        incidents: list[Incident] = []
        previous = self.previous

        code = snapshot.service_code
        previous_code = previous.service_code if previous is not None else None
        fault_key = f"fault:{cycle_id or 'none'}"
        if code in FAULT_CODES and code != previous_code and fault_key not in self._incident_keys:
            self._incident_keys.add(fault_key)
            incidents.append(self._incident(
                cycle_id=cycle_id,
                incident_type="boiler_fault_code",
                severity="high",
                snapshot=snapshot,
                observation={
                    "service_code": code,
                    "statement": "Known boiler fault code transition observed.",
                    "root_cause": "UNKNOWN",
                },
            ))

        slope = None
        if snapshot.boiler_block_temperature is not None:
            if self._last_temp is not None:
                last_t, last_temp = self._last_temp
                dt = snapshot.timestamp - last_t
                if 0 < dt <= 45:
                    slope = (snapshot.boiler_block_temperature - last_temp) * 60.0 / dt
            self._last_temp = (snapshot.timestamp, snapshot.boiler_block_temperature)

        rise_threshold, low_zone_threshold = self.baseline.anomaly_thresholds()
        anomaly_key = f"thermal_outlier:{cycle_id or 'none'}"
        if (
            cycle_id is not None
            and rise_threshold is not None
            and low_zone_threshold is not None
            and slope is not None
            and slope > rise_threshold
            and snapshot.requesting_zone_count() <= low_zone_threshold
            and not snapshot.quality
            and snapshot.service is not True
            and snapshot.master is True
            and not any(value is True for value in (snapshot.dhw, snapshot.dhw_recharging, snapshot.dhw_valve))
            and anomaly_key not in self._incident_keys
        ):
            self._incident_keys.add(anomaly_key)
            incidents.append(self._incident(
                cycle_id=cycle_id,
                incident_type="rapid_temperature_rise_low_demand_outlier",
                severity="medium",
                snapshot=snapshot,
                observation={
                    "temperature_rise_c_per_min": slope,
                    "baseline_rise_outlier_threshold_c_per_min": rise_threshold,
                    "requesting_zones": snapshot.requesting_zone_count(),
                    "baseline_low_requesting_zone_threshold": low_zone_threshold,
                    "statement": "Combined statistical outlier observed.",
                    "root_cause": "UNKNOWN",
                    "physical_flow_confirmed": False,
                },
            ))

        self.previous = snapshot
        return incidents

    def observe_completed_cycle(self, cycle: CycleSummary) -> None:
        self.baseline.add(cycle)
        # Keep deduplication bounded to current/recent cycle identity.
        prefixes = (f"fault:{cycle.cycle_id}", f"thermal_outlier:{cycle.cycle_id}")
        self._incident_keys.difference_update(prefixes)
