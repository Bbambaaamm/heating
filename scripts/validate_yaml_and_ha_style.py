#!/usr/bin/env python3
"""Fail-fast kontrola YAML syntaxe a základní HA styl guardrails."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def is_ci_environment() -> bool:
    """Vrátí True, pokud skript běží v CI prostředí."""
    return os.getenv("CI", "").lower() == "true"


def load_yaml_module():
    """Bezpečně načte PyYAML a vrátí modul nebo None."""
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return None
    return yaml


def yaml_files() -> list[Path]:
    files = [p for p in ROOT.rglob("*.yaml") if ".git" not in p.parts]
    return sorted(files)


def main() -> int:
    yaml = load_yaml_module()
    if yaml is None:
        if is_ci_environment():
            print("❌ PyYAML není dostupné v CI; YAML/HA style validace musí být povinně spuštěna.")
            return 1
        print("⚠️ PyYAML není dostupné, syntax YAML nelze ověřit.")
        print("Nainstaluj balíček pyyaml pro lokální běh této kontroly.")
        return 0

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
