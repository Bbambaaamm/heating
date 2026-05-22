#!/usr/bin/env python3
"""Spouští ochranné a debug kontroly nad repozitářem."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_step(name: str, cmd: list[str]) -> int:
    print(f"\n==> {name}")
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode


def main() -> int:
    checks = [
        ("Validace konzistence zón", [sys.executable, "scripts/validate_zone_list_consistency.py"]),
        ("YAML syntax + HA styl guard", [sys.executable, "scripts/validate_yaml_and_ha_style.py"]),
        ("PyYAML hard dependency guard", [sys.executable, "scripts/check_pyyaml_hard_dependency.py"]),
        ("Debug guard kontroly", [sys.executable, "scripts/validate_debug_guards.py"]),
        ("Orchestrace smoke coverage guard", [sys.executable, "scripts/validate_smoke_coverage.py"]),
    ]

    failed = 0
    for name, cmd in checks:
        if run_step(name, cmd) != 0:
            failed += 1

    if failed:
        print(f"\n❌ Ochranné kontroly selhaly ({failed} kroků).")
        return 1

    print("\n✅ Všechny ochranné kontroly prošly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
