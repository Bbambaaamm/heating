"""Health watchdog for the agent platform itself."""
from __future__ import annotations

from typing import Any

from .permissions import PermissionManifest


class AgentWatchdog:
    name = "watchdog-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(
        self,
        *,
        observer_storage_error: str | None,
        agent_storage_error: str | None,
        permission_audit: dict[str, Any],
        safety: dict[str, Any],
        knowledge_summary: dict[str, Any],
        last_agent_written_at: float | None,
        now: float,
    ) -> dict[str, Any]:
        self.permissions.require(self.name, "watchdog.evaluate")
        problems = []
        if observer_storage_error:
            problems.append(f"observer storage: {observer_storage_error}")
        if agent_storage_error:
            problems.append(f"agent storage: {agent_storage_error}")
        if permission_audit.get("status") != "PASS":
            problems.append("permission audit failed")
        if safety.get("status") == "VIOLATION":
            problems.append("safety sentinel violation")
        if knowledge_summary.get("facts_promoted_from_hypotheses", 0):
            problems.append("automatic FACT promotion detected")
        if last_agent_written_at is None or now - last_agent_written_at > 180:
            problems.append("agent evidence writer stale")

        return {
            "agent": self.name,
            "status": "CRITICAL" if safety.get("status") == "VIOLATION" else "DEGRADED" if problems else "HEALTHY",
            "problems": problems,
            "actuator_control": False,
            "service_call_api": False,
        }
