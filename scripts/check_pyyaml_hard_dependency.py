#!/usr/bin/env python3
"""Důkaz, že YAML validace bez PyYAML failne (není warning-only)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [sys.executable, "-S", "scripts/validate_yaml_and_ha_style.py"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        print("❌ Kontrola selhala: validate_yaml_and_ha_style.py prošel bez PyYAML.")
        return 1
    if "PyYAML není dostupné" not in output:
        print("❌ Kontrola selhala: chybí očekávaná hláška o PyYAML hard dependency.")
        print(output.strip())
        return 1
    print("✅ PyYAML hard dependency je vynucena: bez PyYAML validace selže.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
