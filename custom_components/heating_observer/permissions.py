"""Machine-enforced permissions for Heating Agent Platform."""
from __future__ import annotations

from fnmatch import fnmatch
import json
from pathlib import Path
from typing import Any


class PermissionErrorDenied(PermissionError):
    pass


class PermissionManifest:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.default_deny = bool(data.get("default_deny", True))
        self.agents = data.get("agents", {})
        self.path_policy = data.get("path_policy", {})
        self.deployment_runtime = data.get("deployment_runtime", {})

    @classmethod
    def load_default(cls) -> "PermissionManifest":
        path = Path(__file__).with_name("agent_policy.json")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def allowed(self, agent: str, capability: str) -> bool:
        spec = self.agents.get(agent)
        if not spec:
            return not self.default_deny
        for denied in spec.get("deny", []):
            if capability == denied or capability.startswith(denied + "."):
                return False
        return any(
            capability == allowed or capability.startswith(allowed + ".")
            for allowed in spec.get("allow", [])
        )

    def require(self, agent: str, capability: str) -> None:
        if not self.allowed(agent, capability):
            raise PermissionErrorDenied(f"{agent} is not allowed capability {capability}")

    def classify_path(self, path: str) -> str:
        normalized = path.lstrip("/")
        for level in ("red", "yellow", "green"):
            for pattern in self.path_policy.get(level, []):
                if fnmatch(normalized, pattern):
                    return level
        return "red"

    def audit(self) -> dict[str, Any]:
        violations: list[str] = []
        for agent, spec in self.agents.items():
            parent = spec.get("parent")
            if not parent:
                continue
            parent_spec = self.agents.get(parent)
            if parent_spec is None:
                violations.append(f"{agent}: missing parent {parent}")
                continue
            parent_allow = set(parent_spec.get("allow", []))
            for capability in spec.get("allow", []):
                if capability not in parent_allow:
                    violations.append(
                        f"{agent}: capability {capability} exceeds parent {parent}"
                    )

        if self.deployment_runtime.get("enabled") is not False:
            violations.append("deployment runtime must remain disabled")

        dangerous = []
        for agent in self.agents:
            for cap in ("ha.control", "deployment.execute", "git.write"):
                if self.allowed(agent, cap):
                    dangerous.append(f"{agent}:{cap}")
        if dangerous:
            violations.extend(f"dangerous capability enabled: {x}" for x in dangerous)

        return {
            "version": self.data.get("version"),
            "status": "PASS" if not violations else "FAIL",
            "violations": violations,
            "runtime_deployment_enabled": bool(self.deployment_runtime.get("enabled")),
            "agents": len(self.agents),
        }
