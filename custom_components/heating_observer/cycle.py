"""Request-cycle builder for the passive heating observer.

Consumes the observer's already-normalized snapshots. It never reads or writes
Home Assistant directly and has no actuator API.
"""
from __future__ import annotations

from copy import deepcopy
from statistics import mean
from typing import Any

from .engine import FAULTS, number


def _requesting_zones(sample: dict[str, Any], threshold: float = 10.0) -> int:
    result = 0
    for zone in sample.get("zones", {}).values():
        pi = number(zone.get("pi"))
        if zone.get("state") == "heat" and pi is not None and pi >= threshold:
            result += 1
    return result


class RequestCycleBuilder:
    """Build a request cycle from relay ON through relay OFF.

    A Home Assistant restart during an already-active request creates an
    incomplete cycle. Such a cycle stays as evidence but is never baseline data.
    """

    def __init__(self, revision: str, *, telemetry_gap: float = 45.0):
        self.revision = revision
        self.telemetry_gap = telemetry_gap
        self.previous: dict[str, Any] | None = None
        self.active: dict[str, Any] | None = None
        self.last_temperature: tuple[float, float] | None = None

    def _start(self, sample: dict[str, Any], *, incomplete: bool) -> dict[str, Any]:
        t = float(sample["t"])
        cycle_id = f"{self.revision}-request-{int(t * 1000)}"
        temp = number(sample.get("block"))
        requesting = _requesting_zones(sample)
        self.active = {
            "cycle_id": cycle_id,
            "site_revision": self.revision,
            "started_at": t,
            "start_kind": "unknown_request_history" if incomplete else "request_start",
            "incomplete": incomplete,
            "burner_starts": 1 if sample.get("gas") is True else 0,
            "start_boiler_temperature": temp,
            "max_boiler_temperature": temp,
            "max_temperature_rise_c_per_min": None,
            "requesting_zones": [requesting],
            "fault_codes": [],
            "service_seen": sample.get("service") is True,
            "master_off_seen": sample.get("master") is not True,
            "dhw_seen": any(sample.get(x) is True for x in ("dhw", "dhw_recharging", "dhw_valve")),
            "quality_flags": set(),
        }
        self.last_temperature = (t, temp) if temp is not None else None
        return self._summary(t, ended=False)

    def _quality_flags(self, sample: dict[str, Any]) -> set[str]:
        flags = set()
        if sample.get("gap"):
            flags.add("capture_gap")
        for key in ("block", "flow"):
            if number(sample.get(key)) is None:
                flags.add(f"invalid_{key}")
            age = number(sample.get("ages", {}).get(key))
            if age is None or age < 0 or age > self.telemetry_gap:
                flags.add(f"stale_{key}")
        if sample.get("relay") is None:
            flags.add("unknown_relay")
        if sample.get("master") is None:
            flags.add("unknown_master")
        if sample.get("service") is None:
            flags.add("unknown_service")
        if len(sample.get("zones", {})) != 8:
            flags.add("unknown_zone_proxy")
        return flags

    def _update(self, sample: dict[str, Any]) -> None:
        active = self.active
        if active is None:
            return
        t = float(sample["t"])
        requesting = _requesting_zones(sample)
        active["requesting_zones"].append(requesting)
        active["quality_flags"].update(self._quality_flags(sample))
        active["service_seen"] |= sample.get("service") is True
        active["master_off_seen"] |= sample.get("master") is not True
        active["dhw_seen"] |= any(sample.get(x) is True for x in ("dhw", "dhw_recharging", "dhw_valve"))
        code = number(sample.get("code"))
        if code is not None and int(code) in FAULTS and int(code) not in active["fault_codes"]:
            active["fault_codes"].append(int(code))
        temp = number(sample.get("block"))
        if temp is not None:
            previous_max = active["max_boiler_temperature"]
            active["max_boiler_temperature"] = temp if previous_max is None else max(previous_max, temp)
            reported_at = number(sample.get("block_reported_at")) or t
            if self.last_temperature is not None:
                last_t, last_temp = self.last_temperature
                dt = reported_at - last_t
                if 1 <= dt <= self.telemetry_gap:
                    rise = (temp - last_temp) * 60.0 / dt
                    old = active["max_temperature_rise_c_per_min"]
                    active["max_temperature_rise_c_per_min"] = rise if old is None else max(old, rise)
            if self.last_temperature is None or reported_at > self.last_temperature[0]:
                self.last_temperature = (reported_at, temp)

    def _summary(self, at: float, *, ended: bool) -> dict[str, Any]:
        active = self.active
        if active is None:
            raise RuntimeError("No active request cycle")
        counts = active["requesting_zones"]
        quality = tuple(sorted(active["quality_flags"]))
        fault_codes = tuple(sorted(active["fault_codes"]))
        eligible = (
            ended
            and not active["incomplete"]
            and not fault_codes
            and not active["service_seen"]
            and not active["master_off_seen"]
            and not active["dhw_seen"]
            and not quality
        )
        return {
            "cycle_id": active["cycle_id"],
            "site_revision": active["site_revision"],
            "started_at": active["started_at"],
            "ended_at": at if ended else None,
            "start_kind": active["start_kind"],
            "incomplete": bool(active["incomplete"]),
            "runtime_seconds": max(0.0, at - active["started_at"]) if ended else None,
            "burner_starts": active["burner_starts"],
            "start_boiler_temperature": active["start_boiler_temperature"],
            "max_boiler_temperature": active["max_boiler_temperature"],
            "max_temperature_rise_c_per_min": active["max_temperature_rise_c_per_min"],
            "min_requesting_zones": min(counts) if counts else None,
            "average_requesting_zones": mean(counts) if counts else None,
            "fault_codes": fault_codes,
            "service_seen": active["service_seen"],
            "master_off_seen": active["master_off_seen"],
            "dhw_seen": active["dhw_seen"],
            "quality_flags": quality,
            "eligible_for_baseline": eligible,
        }

    def feed(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        transitions: list[dict[str, Any]] = []
        current = deepcopy(sample)
        t = float(current["t"])
        previous = self.previous
        gap = previous is not None and t - float(previous["t"]) > self.telemetry_gap

        if self.active is not None and gap:
            self.active["incomplete"] = True
            self.active["quality_flags"].add("capture_gap")

        starting = current.get("relay") is True and (previous is None or previous.get("relay") is not True)
        if starting and self.active is None:
            incomplete = previous is None or gap or previous.get("relay") is None
            summary = self._start(current, incomplete=incomplete)
            self.active["quality_flags"].update(self._quality_flags(current))
            transitions.append({"kind": "cycle_started", "cycle": summary})
        elif self.active is not None:
            if current.get("gas") is True and (previous is None or previous.get("gas") is not True):
                self.active["burner_starts"] += 1
            self._update(current)

        if self.active is not None and current.get("relay") is False:
            summary = self._summary(t, ended=True)
            transitions.append({"kind": "cycle_completed", "cycle": summary})
            self.active = None
            self.last_temperature = None

        self.previous = current
        return transitions

    @property
    def active_cycle_id(self) -> str | None:
        return self.active["cycle_id"] if self.active else None
