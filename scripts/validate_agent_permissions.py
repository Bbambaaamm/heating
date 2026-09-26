#!/usr/bin/env python3
"""Fail CI if Heating Agent permissions or safety invariants drift unsafe."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_POLICY = ROOT / "custom_components/heating_observer/agent_policy.json"
MIRROR_POLICY = ROOT / "agent_platform/policies/agent-policy.json"
RUNTIME_INVARIANTS = ROOT / "custom_components/heating_observer/safety_invariants.json"
MIRROR_INVARIANTS = ROOT / "agent_platform/policies/safety-invariants.json"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> int:
    policy = json.loads(RUNTIME_POLICY.read_text(encoding="utf-8"))
    mirror = json.loads(MIRROR_POLICY.read_text(encoding="utf-8"))
    if policy != mirror:
        fail("runtime and architecture permission manifests differ")
    if policy.get("default_deny") is not True:
        fail("agent permission manifest must be default-deny")
    if policy.get("deployment_runtime", {}).get("enabled") is not False:
        fail("runtime deployment must remain disabled")

    agents = policy.get("agents", {})
    for agent, spec in agents.items():
        for forbidden in ("ha.control", "deployment.execute", "git.write"):
            for allowed in spec.get("allow", []):
                if allowed == forbidden or allowed.startswith(forbidden + "."):
                    fail(f"{agent} grants forbidden capability {allowed}")
        parent = spec.get("parent")
        if parent:
            if parent not in agents:
                fail(f"{agent} references missing parent {parent}")
            parent_allow = set(agents[parent].get("allow", []))
            extra = sorted(set(spec.get("allow", [])) - parent_allow)
            if extra:
                fail(f"{agent} exceeds parent {parent}: {extra}")

    invariants = json.loads(RUNTIME_INVARIANTS.read_text(encoding="utf-8"))
    mirror_invariants = json.loads(MIRROR_INVARIANTS.read_text(encoding="utf-8"))
    if invariants != mirror_invariants:
        fail("runtime and architecture safety invariant sets differ")
    ids = [row.get("id") for row in invariants.get("invariants", [])]
    expected = [f"S{i:02d}" for i in range(1, 21)]
    if ids != expected:
        fail(f"safety invariant IDs must be exactly S01-S20 in order; got {ids}")

    red = set(policy.get("path_policy", {}).get("red", []))
    required_red = {"heating/control/**", "heating/safety/**", "automations.yaml", "scripts.yaml"}
    missing = sorted(required_red - red)
    if missing:
        fail(f"RED path policy missing protected paths: {missing}")

    print("PASS: Heating Agent permission manifest and S01-S20 safety invariants are fail-closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
