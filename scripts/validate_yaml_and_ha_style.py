#!/usr/bin/env python3
"""Fail-fast kontrola YAML syntaxe a základní HA styl guardrails."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    import yaml
except ModuleNotFoundError:
    print("⚠️ PyYAML není dostupné, syntax YAML nelze ověřit.")
    print("Nainstaluj balíček pyyaml pro lokální běh této kontroly.")
    raise SystemExit(0)


def yaml_files() -> list[Path]:
    files = [p for p in ROOT.rglob("*.yaml") if ".git" not in p.parts]
    return sorted(files)


def main() -> int:
    errors: list[str] = []
    for file_path in yaml_files():
        rel = file_path.relative_to(ROOT)
        text = file_path.read_text(encoding="utf-8")
        try:
            yaml.safe_load(text)
        except Exception as exc:
            errors.append(f"{rel}: YAML parse error: {exc}")

        if "automation" in file_path.parts or "automations.yaml" == file_path.name:
            if "triggers:" in text or "actions:" in text:
                errors.append(f"{rel}: obsahuje legacy klíče triggers/actions, použij trigger/action.")

    if errors:
        print("❌ YAML/HA guard: nalezeny problémy")
        print("\n".join(errors))
        return 1

    print("✅ YAML syntaxe + HA styl guard jsou v pořádku.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
