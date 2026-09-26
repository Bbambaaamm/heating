"""Read-only Safety Sentinel for the heating platform."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine import FAULTS, number
from .permissions import PermissionManifest


class SafetySentinel:
    name = "safety-sentinel-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions
        self.invariants = json.loads(
            Path(__file__).with_name("safety_invariants.json").read_text(encoding="utf-8")
        )
        self._fault_relay_streak = 0

    @staticmethod
    def _dhw(sample: dict[str, Any]) -> bool:
        return any(sample.get(key) is True for key in ("dhw", "dhw_recharging", "dhw_valve"))

    def evaluate(
        self,
        sample: dict[str, Any],
        *,
        runtime: dict[str, Any],
        permission_audit: dict[str, Any],
        knowledge_summary: dict[str, Any],
        intelligence_candidate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.permissions.require(self.name, "safety.evaluate")
        violations: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        notes: list[dict[str, str]] = []

        relay = sample.get("relay")
        gas = sample.get("gas")
        service = sample.get("service")
        master = sample.get("master")
        mode = sample.get("mode")
        code = number(sample.get("code"))
        active_fault = code is not None and int(code) in FAULTS

        def violation(invariant: str, message: str, severity: str = "critical"):
            violations.append({"invariant": invariant, "severity": severity, "message": message})

        def warning(invariant: str, message: str, severity: str = "high"):
            warnings.append({"invariant": invariant, "severity": severity, "message": message})

        if service is True and relay is True:
            violation("S01", "service mode is ON while boiler relay is ON")
        if master is False and relay is True:
            violation("S02", "master heating is OFF while boiler relay is ON")
        if mode == "Off" and relay is True:
            violation("S03", "heating mode is Off while boiler relay is ON")

        if active_fault and relay is True:
            self._fault_relay_streak += 1
            if self._fault_relay_streak >= 2:
                violation("S04", f"fault {int(code)} persisted with relay ON across multiple observations", "high")
            else:
                warning("S04", f"fault {int(code)} observed with relay ON; waiting for deterministic shutdown response")
        else:
            self._fault_relay_streak = 0

        active = relay is True or gas is True
        if active:
            missing = []
            for key in ("block", "flow", "relay", "master", "service"):
                if sample.get(key) is None:
                    missing.append(key)
            for key in ("block", "flow"):
                age = number(sample.get("ages", {}).get(key))
                if age is None or age < 0 or age > 45:
                    missing.append(f"stale:{key}")
            if missing:
                warning("S05", "critical telemetry incomplete during active heating: " + ", ".join(sorted(set(missing))))

        if gas is True and relay is False and not self._dhw(sample):
            warning("S06", "burner is ON without space-heating relay request and outside DHW context", "medium")

        if self._dhw(sample):
            notes.append({"invariant": "S07", "message": "DHW context present; space-heating hydraulic inference excluded"})

        if runtime.get("actuator_control") is not False:
            violation("S08", "agent actuator_control is not explicitly false")
        if runtime.get("service_call_api") is not False:
            violation("S09", "agent service_call_api is not explicitly false")
        if runtime.get("agent_storage_error"):
            warning("S10", f"agent evidence storage error: {runtime['agent_storage_error']}")

        notes.append({"invariant": "S12", "message": "TRV PI remains a demand proxy, not physical flow confirmation"})
        notes.append({"invariant": "S13", "message": "last_reported remains HA receipt time, not physical freshness proof"})

        if intelligence_candidate and intelligence_candidate.get("active_policy_changed"):
            violation("S15", "intelligence candidate claims active policy change")

        if self.permissions.deployment_runtime.get("enabled") is not False:
            violation("S17", "deployment runtime is enabled")

        if knowledge_summary.get("facts_promoted_from_hypotheses", 0):
            violation("S18", "knowledge contains automatically promoted hypotheses", "high")

        if runtime.get("event_log_append_only") is not True:
            violation("S19", "append-only event-log guarantee not confirmed", "high")

        if permission_audit.get("status") != "PASS":
            violation("S20", "permission manifest audit failed: " + "; ".join(permission_audit.get("violations", [])))

        status = "VIOLATION" if violations else "WARNING" if warnings else "OK"
        return {
            "agent": self.name,
            "status": status,
            "violations": violations,
            "warnings": warnings,
            "notes": notes,
            "active_fault": int(code) if active_fault else None,
            "relay": relay,
            "gas": gas,
            "actuator_control": False,
            "operating_policy_changed": False,
        }
