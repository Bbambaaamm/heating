"""Deterministic, device-independent observer. No HA services or actuator API.

Candidate rules are *hypotheses*, never operating limits. Outcomes are observed
faults / observed fault-free windows / censored windows, not physical safety.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import math
import statistics
from typing import Any

FAULTS = {2964, 2965, 2966, 2967}
MODEL_SCHEMA = 1
CATALOG = "proxy-grid-v1"
RULES = tuple(f"pi{p}_count_lt{n}" for p in (10, 20, 30, 50) for n in (1, 2, 3)) + (
    "block_rise_0_2", "block_rise_0_5", "block_above_75",
)


def rule_description(rule: str) -> str:
    if rule.startswith("pi"):
        threshold, count = rule.removeprefix("pi").split("_count_lt")
        return f"Požadavek alespoň {threshold} % hlásí méně než {count} hlavic"
    return {"block_rise_0_2": "Růst teploty bloku alespoň 0,2 K/s",
            "block_rise_0_5": "Růst teploty bloku alespoň 0,5 K/s",
            "block_above_75": "Teplota bloku alespoň 75 °C"}[rule]


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


class Observer:
    """Incrementally score a fixed set of shadow hypotheses against real episodes."""

    def __init__(self, revision: str, saved: dict | None = None, *,
                 telemetry_gap: float = 45, lead_budget: float = 60,
                 postrun: float = 300):
        self.revision = revision
        self.telemetry_gap = telemetry_gap
        self.lead_budget = lead_budget  # Evaluation budget, NOT a validated opening time.
        self.postrun = postrun
        compatible = (saved and saved.get("schema") == MODEL_SCHEMA
                      and saved.get("revision") == revision
                      and saved.get("catalog") == CATALOG
                      and saved.get("lead_budget") == lead_budget
                      and saved.get("telemetry_gap") == telemetry_gap
                      and saved.get("postrun") == postrun)
        if saved and not compatible:
            raise ValueError("Model settings changed: preserve evidence and use a new site_revision")
        self.data = deepcopy(saved) if compatible else {
            "schema": MODEL_SCHEMA, "revision": revision, "catalog": CATALOG,
            "lead_budget": lead_budget, "telemetry_gap": telemetry_gap, "postrun": postrun,
            "generation": 0, "sequence": 0, "fault_transitions": 0,
            "incident_sequence": 0, "last_fault_at": None, "incident_id": None,
            "episodes": [], "active": None,
        }
        self.previous: dict | None = None
        self.request_burns = 0
        self.request_known = False
        self.request_started_at = None
        self.ring: deque[dict] = deque(maxlen=180)
        self.status = "initializing"
        self.current_warnings: list[str] = []
        self.current_quality: list[str] = []
        self.slope: float | None = None
        self.last_temperature: tuple[float, float] | None = None
        self.pending: list[dict] = []
        self.last_finished: dict | None = None
        if self.data["active"]:
            # A persisted in-progress episode is NEVER silently learned as success.
            self._finish("restart_gap")

    def _quality(self, s: dict) -> list[str]:
        problems = []
        for key in ("block", "flow"):
            n = number(s.get(key))
            age = number(s.get("ages", {}).get(key))
            if n is None or not -20 <= n <= 150:
                problems.append(f"invalid_{key}")
            if age is None or age < 0 or age > self.telemetry_gap:
                problems.append(f"stale_{key}")
        for key in ("gas", "pump", "relay", "master", "service"):
            if not isinstance(s.get(key), bool):
                problems.append(f"unknown_{key}")
        if number(s.get("code")) is None:
            problems.append("unknown_code")
        if any(not isinstance(s.get(key), bool) for key in ("dhw", "dhw_recharging", "dhw_valve")):
            problems.append("unknown_dhw_mode")
        elif any(s.get(key) for key in ("dhw", "dhw_recharging", "dhw_valve")):
            problems.append("dhw_context_excluded")
        if s.get("mode") not in ("Auto", "Eco", "Boost", "Off"):
            problems.append("unknown_mode")
        zones = s.get("zones", {})
        if len(zones) != 8 or any(
            number(z.get("pi")) is None or not 0 <= number(z.get("pi")) <= 100
            or z.get("state") not in ("heat", "off") for z in zones.values()
        ):
            problems.append("unknown_zone_proxy")
        if s.get("gap"):
            problems.append("capture_gap")
        return problems

    def _warnings(self, s: dict) -> list[str]:
        # Never infer adequate flow from these proxies or from an empty warning list.
        if self.current_quality or s.get("service") or s.get("master") is not True:
            return []
        if not (s.get("relay") or s.get("gas")):
            return []
        demands = [number(z.get("pi")) if z.get("state") == "heat" else 0 for z in s["zones"].values()]
        result = []
        for p in (10, 20, 30, 50):
            count = sum(v >= p for v in demands)
            result.extend(f"pi{p}_count_lt{n}" for n in (1, 2, 3) if count < n)
        if self.slope is not None:
            if self.slope >= 0.2:
                result.append("block_rise_0_2")
            if self.slope >= 0.5:
                result.append("block_rise_0_5")
        if number(s["block"]) >= 75:
            result.append("block_above_75")
        return result

    def _start(self, s: dict, incomplete: bool):
        self.data["sequence"] += 1
        self.data["active"] = {
            "id": f"{self.revision}-{self.data['sequence']}",
            "start": s["t"], "end": s["t"], "incomplete": incomplete,
            "start_kind": ("unattributed" if s.get("relay") is not True else
                           "internal_restart" if self.request_burns else
                           "request_start" if self.request_known else "unknown_request_history"),
            "heating_request_observed": s.get("relay") is True,
            "start_demands": {z: number(v.get("pi")) for z, v in s.get("zones", {}).items()},
            "warnings": {r: [] for r in RULES}, "warned": [],
            "fault_at": None, "fault_codes": [], "incident_id": None,
            "fault_leads": {}, "bad_before_fault": bool(self.current_quality),
            "intervention_before_fault": bool(s.get("service") or not s.get("master")),
            "quality": list(self.current_quality), "gas_off_at": None,
            "block_at_gas_off": None, "off_baseline_reported_at": None,
            "peak_block": number(s.get("block")),
            "postburn_peak": None, "fault_trace": [],
        }

    def _finish(self, reason: str):
        episode = self.data["active"]
        if not episode:
            return
        episode["finish_reason"] = reason
        eligible = not (episode["incomplete"] or not episode["heating_request_observed"] or episode["bad_before_fault"]
                        or episode["intervention_before_fault"] or reason in ("restart_gap", "duration_cap", "stop"))
        episode["outcome"] = "fault" if episode["fault_at"] is not None else "observed_no_fault"
        episode["eligible"] = eligible
        if not eligible:
            episode["outcome"] = "censored_fault" if episode["fault_at"] is not None else "censored"
        off, peak = episode["block_at_gas_off"], episode["postburn_peak"]
        episode["observed_overshoot_k"] = max(0, peak - off) if off is not None and peak is not None else None
        episode["postrun_complete"] = reason == "postrun_window"
        episode.pop("warnings", None)
        self.pending.append({"kind": "episode", **deepcopy(episode)})
        summary = {k: v for k, v in episode.items() if k != "fault_trace"}
        self.data["episodes"] = (self.data["episodes"] + [summary])[-500:]
        self.data["generation"] += 1
        self.last_finished = summary
        self.data["active"] = None

    def feed(self, snapshot: dict) -> list[dict]:
        s = deepcopy(snapshot)
        t = number(s.get("t"))
        if t is None:
            raise ValueError("A finite UTC timestamp is required")
        s["t"] = t
        previous = self.previous
        if previous and t < previous["t"]:
            s["gap"] = True
            self._finish("restart_gap")
            previous = self.previous = None
            self.last_temperature = None
            self.ring.clear()
            self.request_known = False
            self.request_burns = 0
            self.request_started_at = None
        if s.get("relay") is False or (previous and previous.get("relay") is False and s.get("relay") is True):
            self.request_burns = 0
            self.request_known = True
            self.request_started_at = t if s.get("relay") else None
        if previous and t - previous["t"] > self.telemetry_gap and (previous.get("gas") or previous.get("relay") or self.data["active"]):
            s["gap"] = True
        self.current_quality = self._quality(s)
        self.slope = None
        measured_at = number(s.get("block_reported_at"))
        temperature = number(s.get("block"))
        if measured_at is not None and temperature is not None and "stale_block" not in self.current_quality:
            if self.last_temperature:
                dt = measured_at - self.last_temperature[0]
                if 1 <= dt <= self.telemetry_gap:
                    self.slope = (temperature - self.last_temperature[1]) / dt
            if self.last_temperature is None or measured_at > self.last_temperature[0]:
                self.last_temperature = (measured_at, temperature)
        code = number(s.get("code"))
        fault = code in FAULTS
        # The fault-bearing snapshot is not allowed to supply its own warning.
        self.current_warnings = [] if fault else self._warnings(s)
        is_start = s.get("gas") is True and (not previous or previous.get("gas") is not True)
        if is_start:
            self._finish("next_burner_start")
            self._start(s, incomplete=not previous or previous.get("gas") is None or
                        (s.get("relay") is True and not self.request_known))
            if s.get("relay") is True:
                self.request_burns += 1
            # Include pre-start exposure during an already enabled heat request.
            for old in self.ring:
                if max(t - 180, self.request_started_at or t - 180) <= old["t"] < t:
                    for rule in old.get("warnings", []):
                        self.data["active"]["warnings"][rule].append(old["t"])
                        if rule not in self.data["active"]["warned"]:
                            self.data["active"]["warned"].append(rule)
        if fault and self.data["active"] is None and (not previous or number(previous.get("code")) != code):
            self._start(s, incomplete=True)
        active = self.data["active"]
        if active:
            active["end"] = t
            if active["fault_at"] is None:
                active["bad_before_fault"] |= bool(self.current_quality)
                active["intervention_before_fault"] |= bool(s.get("service") or s.get("master") is not True)
            active["quality"] = sorted(set(active["quality"]) | set(self.current_quality))
            if temperature is not None:
                active["peak_block"] = max(active["peak_block"] or temperature, temperature)
            if s.get("gas") is False and previous and previous.get("gas") is True:
                active["gas_off_at"] = t
                active["block_at_gas_off"] = None
                active["postburn_peak"] = None
            if (active["gas_off_at"] is not None and active["block_at_gas_off"] is None
                    and temperature is not None and measured_at is not None
                    and 0 <= measured_at - active["gas_off_at"] <= self.telemetry_gap):
                # Never use a pre-shutdown temperature as a simultaneous measurement.
                active["block_at_gas_off"] = temperature
                active["off_baseline_reported_at"] = measured_at
                active["postburn_peak"] = temperature
            if active["block_at_gas_off"] is not None and temperature is not None:
                active["postburn_peak"] = max(active["postburn_peak"] or temperature, temperature)
            if not fault and active["fault_at"] is None:
                for rule in self.current_warnings:
                    active["warnings"][rule].append(t)
                    if rule not in active["warned"]:
                        active["warned"].append(rule)
                for rule in RULES:
                    active["warnings"][rule] = [x for x in active["warnings"][rule] if x >= t - 180][-200:]
            new_fault = fault and (not previous or number(previous.get("code")) != code)
            if new_fault:
                self.data["fault_transitions"] += 1
                last_fault = self.data["last_fault_at"]
                if last_fault is None or t - last_fault > 600:
                    self.data["incident_sequence"] += 1
                    self.data["incident_id"] = f"{self.revision}-incident-{self.data['incident_sequence']}"
                self.data["last_fault_at"] = t
                if int(code) not in active["fault_codes"]:
                    active["fault_codes"].append(int(code))
                if active["fault_at"] is None:
                    active["fault_at"] = t
                    active["incident_id"] = self.data["incident_id"]
                    active["fault_leads"] = {}
                    for rule, times in active["warnings"].items():
                        recent = [x for x in times if t - 180 <= x < t]
                        if recent:
                            active["fault_leads"][rule] = t - min(recent)
                    active["fault_trace"] = [deepcopy(x) for x in self.ring if x["t"] >= t - 600]
                    self.pending.append({"kind": "incident_open", "episode_id": active["id"],
                                         "incident_id": active["incident_id"], "t": t,
                                         "code": int(code), "prelude": deepcopy(active["fault_trace"])})
            if active["fault_at"] is not None and len(active["fault_trace"]) < 240:
                active["fault_trace"].append(s)
            if active["gas_off_at"] is not None and t - active["gas_off_at"] >= self.postrun and s.get("gas") is False:
                self._finish("postrun_window")
            elif t - active["start"] > 7200:
                self._finish("duration_cap")
        self.status = ("fault_observed" if fault else "data_incomplete" if self.current_quality
                       else "service" if s.get("service") else "observing")
        if not self.ring or t - self.ring[-1]["t"] >= 5:
            self.ring.append({**s, "warnings": self.current_warnings.copy()})
        self.previous = s
        result, self.pending = self.pending, []
        return result

    def stop(self) -> list[dict]:
        self._finish("stop")
        result, self.pending = self.pending, []
        return result

    def report(self) -> dict:
        episodes = self.data["episodes"]
        # One independent weight per heuristic incident cluster, not per retry.
        seen = set()
        faults, clean = [], []
        for e in episodes:
            if not e["eligible"]:
                continue
            if e["outcome"] == "fault" and e["incident_id"] not in seen:
                seen.add(e["incident_id"])
                faults.append(e)
            elif e["outcome"] == "observed_no_fault":
                clean.append(e)
        metrics = []
        for rule in RULES:
            leads = [e["fault_leads"][rule] for e in faults if rule in e["fault_leads"]]
            timely = sum(x >= self.lead_budget for x in leads)
            warned_clean = sum(rule in e["warned"] for e in clean)
            metrics.append({"rule": rule, "description": rule_description(rule),
                            "fault_incidents": len(faults), "timely": timely,
                            "late_or_missed": len(faults) - timely,
                            "observed_no_fault": len(clean), "warned_no_fault": warned_clean,
                            "lead_median_s": statistics.median(leads) if leads else None})
        ranked = sorted(metrics, key=lambda x: (-x["timely"], x["warned_no_fault"], x["rule"]))
        # Explicitly a candidate for further validation, never a promoted policy.
        candidate = ranked[0]["rule"] if len(faults) >= 3 and len(clean) >= 20 and ranked[0]["timely"] else None
        overshoots = [e["observed_overshoot_k"] for e in episodes
                      if e["observed_overshoot_k"] is not None]
        return {"mode": "shadow_only", "catalog": CATALOG, "revision": self.revision,
                "generation": self.data["generation"], "episodes_retained": len(episodes),
                "fault_transitions_lifetime": self.data["fault_transitions"],
                "fault_clusters_scored": len(faults), "observed_no_fault_scored": len(clean),
                "censored": sum(not e["eligible"] for e in episodes),
                "by_start_kind": {kind: {
                    "faults": sum(e["start_kind"] == kind for e in faults),
                    "observed_no_fault": sum(e["start_kind"] == kind for e in clean),
                } for kind in ("request_start", "internal_restart", "unattributed")},
                "comparison_lead_budget_s": self.lead_budget,
                "candidate_for_validation": candidate, "operating_policy_changed": False,
                "candidate_description": rule_description(candidate) if candidate else "Zatím nedostatek podkladů",
                "observed_overshoot_max_k": max(overshoots) if overshoots else None,
                "metrics": ranked}
