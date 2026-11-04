"""Passive ignition evidence; reported relay state never proves contact state."""
from __future__ import annotations

from copy import deepcopy
import math
from uuid import uuid4


COUNTERS = ("burn_starts", "heat_starts", "ww_starts")
CONTEXT = ("relay", "gas", "ion_current", "pump", "block", "flow", "code",
           "dhw", "dhw_recharging", "dhw_valve", "tapwater_active", "ww_activated",
           "flow_state_v4", *COUNTERS)


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class IgnitionEvidence:
    """Bounded corroboration ledger independent of learning eligibility.

    Correlation window (120s) is a diagnostic assumption, never a start time
    inferred from counter arrival. Startup/reconnect does not manufacture an
    edge. Counter resets establish a new baseline. No temperature-only ignition.
    """

    def __init__(self, saved=None, *, telemetry_gap=45):
        self.data = deepcopy(saved) if saved else {
            "sequence": 0, "observed_starts": 0, "relay_off_starts": 0,
            "counter_only_increments": 0, "recent": [],
        }
        self.previous = None
        self.telemetry_gap = telemetry_gap
        self.correlate_after = None
        self.pending_counters = []
        self.burn_ended_at = None

    def feed(self, sample):
        t = sample["t"]
        prev = self.previous
        self.previous = deepcopy(sample)
        if (prev is None or sample.get("gap") or not 0 < t - prev["t"] <= self.telemetry_gap):
            self.correlate_after = t
            self.pending_counters.clear()
            self.burn_ended_at = None
            return []
        events = []
        changed = {}
        edges = []
        if prev.get("gas") is False and sample.get("gas") is True:
            edges.append("gas")
        old_ion, ion = numeric(prev.get("ion_current")), numeric(sample.get("ion_current"))
        if sample.get("gas") is False and (ion == 0 or (prev.get("gas") is True and ion is None)):
            self.burn_ended_at = t
        if (old_ion == 0 and ion is not None and ion > 0
                and not (prev.get("gas") is True and sample.get("gas") is True)):
            edges.append("ion_current")

        for channel in edges:
            # Different channels can corroborate one ignition. A new edge of
            # the same channel is a separate observed start, even inside 120s.
            recent = self.data["recent"]
            record = recent[-1] if recent else None
            if (not record or record["kind"] != "ignition"
                    or record["t"] < self.correlate_after
                    or (self.burn_ended_at is not None and record["t"] <= self.burn_ended_at)
                    or not 0 <= t - record["t"] <= 120
                    or channel in record["signals"]):
                self.data["sequence"] += 1
                relay = sample.get("relay")
                # Unknown/interrupted relay history is not explicit OFF.
                off = relay is False and prev.get("relay") is False
                record = {
                    "id": f"ignition-{uuid4()}", "kind": "ignition", "t": t,
                    "relay_at_start": False if off else True if relay is True else None,
                    "classification": "unexplained_relay_off" if off else "relay_on" if relay is True else "relay_unknown",
                    "signals": [], "counter_deltas": {},
                    "at_start": {k: sample.get(k) for k in CONTEXT},
                    "at_start_reported_at": {k: sample.get("reported_at", {}).get(k) for k in CONTEXT},
                    "at_start_changed_at": {k: sample.get("changed_at", {}).get(k) for k in CONTEXT},
                    "physical_contact_verified": False, "root_cause": "UNKNOWN",
                }
                recent.append(record)
                self.data["observed_starts"] += 1
                self.data["relay_off_starts"] += int(off)
            record["signals"].append(channel)
            record["last_context"] = {k: sample.get(k) for k in CONTEXT}
            changed[record["id"]] = record

        # Positive current during an already reported burn corroborates its
        # evidence without counting current jitter as additional ignitions.
        if sample.get("gas") is True and ion is not None and ion > 0:
            record = self.data["recent"][-1] if self.data["recent"] else None
            if (record and self.correlate_after <= record["t"] <= t
                    and (self.burn_ended_at is None or record["t"] > self.burn_ended_at)
                    and t - record["t"] <= 120 and "ion_current" not in record["signals"]):
                record["signals"].append("ion_current")
                record["last_context"] = {k: sample.get(k) for k in CONTEXT}
                changed[record["id"]] = record

        # EMS entities may arrive in either order. Preserve a counter-first
        # observation as such, then append a correlation (never rewrite logs).
        for pending in self.pending_counters:
            if not 0 <= t - pending["t"] <= 120:
                continue
            for record in changed.values():
                key = pending["counter"]
                if not pending["remaining"] or key in record["counter_deltas"]:
                    continue
                record["counter_deltas"][key] = {
                    "delta": 1, "reported_at": pending["t"],
                    "observation_id": pending["id"], "arrived_before_edge": True,
                }
                pending["remaining"] -= 1
                if key == "burn_starts":
                    self.data["counter_only_increments"] -= 1

        for key in COUNTERS:
            old, new = numeric(prev.get(key)), numeric(sample.get(key))
            if old is None or new is None or old < 0 or new < 0 or not old.is_integer() or not new.is_integer() or new <= old:
                continue
            delta = int(new - old)
            # One increment can corroborate one preceding ignition per counter.
            matches = [r for r in self.data["recent"]
                       if r["kind"] == "ignition" and self.correlate_after <= r["t"] <= t
                       and t - r["t"] <= 120
                       and key not in r["counter_deltas"]]
            for record in matches[:delta]:
                record["counter_deltas"][key] = {"delta": 1, "reported_at": t}
                changed[record["id"]] = record
            remaining = delta - min(delta, len(matches))
            if remaining:
                self.data["counter_only_increments"] += remaining if key == "burn_starts" else 0
                observation_id = str(uuid4())
                self.pending_counters.append({"id": observation_id, "t": t, "counter": key,
                                              "remaining": remaining})
                events.append({
                    "kind": "ignition_counter_unattributed", "t": t, "counter": key,
                    "observation_id": observation_id,
                    "delta": remaining, "relay_at_start": None,
                    "arrival_context": {k: sample.get(k) for k in CONTEXT},
                    "meaning": "Counter arrival does not establish ignition time or relay contact state.",
                })
        self.data["recent"] = self.data["recent"][-50:]
        self.pending_counters = [p for p in self.pending_counters if p["remaining"] and t-p["t"] <= 120][-50:]
        for record in changed.values():
            events.append({"kind": "ignition_evidence", "t": t, "ignition": deepcopy(record)})
        return events

    def report(self):
        return {**deepcopy(self.data), "actuator_control": False,
                "physical_contact_verified": False, "correlation_window_seconds": 120,
                "coverage": "observed edges only; restart and telemetry gaps are unobserved",
                "counter_only_increments_meaning": "unmatched total burner counter; subcounters are not added"}
