"""Deterministic heating-request cycle state machine."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .model import CycleSummary, FAULT_CODES, HeatingSnapshot


@dataclass(frozen=True)
class CycleTransition:
    kind: str
    summary: CycleSummary


class CycleBuilder:
    """Build one request cycle from relay ON through relay OFF.

    Burner starts inside the request are counted as sub-events. Incomplete or
    intervention-affected cycles remain evidence but are never baseline input.
    """

    def __init__(self, *, telemetry_gap_seconds: float = 45.0):
        self.telemetry_gap_seconds = telemetry_gap_seconds
        self.previous: HeatingSnapshot | None = None
        self.sequence = 0
        self._active: dict | None = None
        self._last_temp: tuple[float, float] | None = None

    @property
    def active_cycle_id(self) -> str | None:
        return self._active["cycle_id"] if self._active else None

    def _start(self, snapshot: HeatingSnapshot, *, incomplete: bool, start_kind: str) -> CycleSummary:
        self.sequence += 1
        cycle_id = f"{snapshot.site_revision}-request-{self.sequence}"
        requesting = snapshot.requesting_zone_count()
        self._active = {
            "cycle_id": cycle_id,
            "site_revision": snapshot.site_revision,
            "started_at": snapshot.timestamp,
            "start_kind": start_kind,
            "incomplete": incomplete,
            "burner_starts": 1 if snapshot.gas is True else 0,
            "start_boiler_temperature": snapshot.boiler_block_temperature,
            "max_boiler_temperature": snapshot.boiler_block_temperature,
            "max_temperature_rise_c_per_min": None,
            "requesting_zones": [requesting],
            "fault_codes": set(),
            "service_seen": snapshot.service is True,
            "master_off_seen": snapshot.master is not True,
            "dhw_seen": any(value is True for value in (snapshot.dhw, snapshot.dhw_recharging, snapshot.dhw_valve)),
            "quality_flags": set(snapshot.quality),
        }
        if snapshot.service_code in FAULT_CODES:
            self._active["fault_codes"].add(snapshot.service_code)
        self._last_temp = (
            (snapshot.timestamp, snapshot.boiler_block_temperature)
            if snapshot.boiler_block_temperature is not None
            else None
        )
        return self._summary(snapshot.timestamp, ended=False)

    def _update(self, snapshot: HeatingSnapshot) -> None:
        active = self._active
        if active is None:
            return
        active["requesting_zones"].append(snapshot.requesting_zone_count())
        active["quality_flags"].update(snapshot.quality)
        active["service_seen"] |= snapshot.service is True
        active["master_off_seen"] |= snapshot.master is not True
        active["dhw_seen"] |= any(value is True for value in (snapshot.dhw, snapshot.dhw_recharging, snapshot.dhw_valve))
        if snapshot.service_code in FAULT_CODES:
            active["fault_codes"].add(snapshot.service_code)
        if snapshot.boiler_block_temperature is not None:
            current = snapshot.boiler_block_temperature
            previous_max = active["max_boiler_temperature"]
            active["max_boiler_temperature"] = current if previous_max is None else max(previous_max, current)
            if self._last_temp is not None:
                last_t, last_temp = self._last_temp
                dt = snapshot.timestamp - last_t
                if 0 < dt <= self.telemetry_gap_seconds:
                    rise = (current - last_temp) * 60.0 / dt
                    prior = active["max_temperature_rise_c_per_min"]
                    active["max_temperature_rise_c_per_min"] = rise if prior is None else max(prior, rise)
            self._last_temp = (snapshot.timestamp, current)

    def _summary(self, at: float, *, ended: bool) -> CycleSummary:
        active = self._active
        if active is None:
            raise RuntimeError("No active cycle")
        counts = active["requesting_zones"]
        quality = tuple(sorted(active["quality_flags"]))
        incomplete = bool(active["incomplete"])
        faults = tuple(sorted(active["fault_codes"]))
        eligible = (
            ended
            and not incomplete
            and not faults
            and not active["service_seen"]
            and not active["master_off_seen"]
            and not active["dhw_seen"]
            and not quality
        )
        return CycleSummary(
            cycle_id=active["cycle_id"],
            site_revision=active["site_revision"],
            started_at=active["started_at"],
            ended_at=at if ended else None,
            start_kind=active["start_kind"],
            incomplete=incomplete,
            runtime_seconds=max(0.0, at - active["started_at"]) if ended else None,
            burner_starts=active["burner_starts"],
            start_boiler_temperature=active["start_boiler_temperature"],
            max_boiler_temperature=active["max_boiler_temperature"],
            max_temperature_rise_c_per_min=active["max_temperature_rise_c_per_min"],
            min_requesting_zones=min(counts) if counts else None,
            average_requesting_zones=mean(counts) if counts else None,
            fault_codes=faults,
            service_seen=active["service_seen"],
            master_off_seen=active["master_off_seen"],
            dhw_seen=active["dhw_seen"],
            quality_flags=quality,
            eligible_for_baseline=eligible,
        )

    def feed(self, snapshot: HeatingSnapshot) -> list[CycleTransition]:
        transitions: list[CycleTransition] = []
        previous = self.previous
        gap = previous is not None and snapshot.timestamp - previous.timestamp > self.telemetry_gap_seconds

        if self._active is not None and gap:
            self._active["incomplete"] = True
            self._active["quality_flags"].add("capture_gap")

        starting = snapshot.relay is True and (previous is None or previous.relay is not True)
        if starting and self._active is None:
            incomplete = previous is None or gap or previous.relay is None
            start_kind = "unknown_request_history" if incomplete else "request_start"
            started = self._start(snapshot, incomplete=incomplete, start_kind=start_kind)
            transitions.append(CycleTransition("started", started))
        elif self._active is not None:
            if snapshot.gas is True and (previous is None or previous.gas is not True):
                self._active["burner_starts"] += 1
            self._update(snapshot)

        if self._active is not None and snapshot.relay is False:
            completed = self._summary(snapshot.timestamp, ended=True)
            transitions.append(CycleTransition("completed", completed))
            self._active = None
            self._last_temp = None

        self.previous = snapshot
        return transitions
