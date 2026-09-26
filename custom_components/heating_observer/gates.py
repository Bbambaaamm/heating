"""Planning-only Code, Release and Deployment gates."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from .permissions import PermissionManifest


class CodeAgentPlanner:
    name = "code-agent-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def plan(self, changed_paths: list[str]) -> dict[str, Any]:
        self.permissions.require(self.name, "artifact.plan")
        self.permissions.require(self.name, "git.pr.plan")
        rows = [{"path": path, "class": self.permissions.classify_path(path)} for path in changed_paths]
        classes = {row["class"] for row in rows}
        return {
            "plan_id": str(uuid4()),
            "agent": self.name,
            "paths": rows,
            "highest_class": "red" if "red" in classes else "yellow" if "yellow" in classes else "green",
            "requires_safety_review": "red" in classes,
            "requires_human_review": bool(classes & {"red", "yellow"}),
            "git_write_performed": False,
            "ha_write_performed": False,
        }


class ReleaseGate:
    name = "release-gate-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def evaluate(
        self,
        *,
        code_plan: dict[str, Any],
        ci_green: bool,
        safety_status: str,
        replay: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.permissions.require(self.name, "release.evaluate")
        reasons = []
        decision = "MERGE_ELIGIBLE_DEPLOY_DISABLED"
        if not ci_green:
            reasons.append("CI is not green")
            decision = "BLOCKED"
        if safety_status == "VIOLATION":
            reasons.append("Safety Sentinel reports violation")
            decision = "BLOCKED"
        if code_plan.get("highest_class") == "red":
            reasons.append("RED-path change requires human safety review")
            if decision != "BLOCKED":
                decision = "HUMAN_REVIEW_REQUIRED"
        elif code_plan.get("highest_class") == "yellow":
            reasons.append("YELLOW-path change requires human review")
            if decision != "BLOCKED":
                decision = "HUMAN_REVIEW_REQUIRED"

        if replay and code_plan.get("highest_class") == "red" and not replay.get("enough_for_candidate_review"):
            reasons.append("safety-affecting change lacks sufficient held-out replay evidence")
            decision = "BLOCKED"

        return {
            "gate_id": str(uuid4()),
            "agent": self.name,
            "decision": decision,
            "reasons": reasons,
            "runtime_deployment_enabled": False,
            "human_approval_required": decision in {"HUMAN_REVIEW_REQUIRED", "BLOCKED"} or code_plan.get("highest_class") == "red",
            "active_deployment_performed": False,
        }


class DeploymentPlanner:
    name = "deployment-agent-v1"

    def __init__(self, permissions: PermissionManifest):
        self.permissions = permissions

    def plan(self, approved_sha: str | None = None) -> dict[str, Any]:
        self.permissions.require(self.name, "deployment.plan")
        return {
            "agent": self.name,
            "approved_sha": approved_sha,
            "execution_allowed": False,
            "runtime_deployment_enabled": False,
            "human_approval_required": True,
            "required_steps": ["backup", "config_check", "install_approved_artifact", "restart_if_required", "post_deploy_verify"],
            "note": "runtime can describe deployment only; it has no deployment.execute capability",
        }
