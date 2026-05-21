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


def build_ha_loader(yaml_module):
    """Vytvoří YAML loader tolerantní k Home Assistant custom tagům."""

    class HaLoader(yaml_module.SafeLoader):
        """SafeLoader rozšířený o HA tagy."""

    def construct_tagged(loader, tag_suffix, node):
        """Bezpečně načte tagged node bez ztráty syntax kontroly."""
        if isinstance(node, yaml_module.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml_module.SequenceNode):
            value = loader.construct_sequence(node)
        elif isinstance(node, yaml_module.MappingNode):
            value = loader.construct_mapping(node)
        else:
            value = None
        return {"__ha_tag__": f"!{tag_suffix}", "value": value}

    supported_tags = [
        "!input",
        "!include",
        "!secret",
        "!include_dir_list",
        "!include_dir_named",
        "!include_dir_merge_list",
        "!include_dir_merge_named",
        "!env_var",
    ]

    for tag in supported_tags:
        HaLoader.add_constructor(tag, lambda loader, node, tag=tag: construct_tagged(loader, tag.lstrip("!"), node))

    # Fallback pro další neznámé tagy: chceme validovat syntaxi, ne selhat na neznámé značce.
    HaLoader.add_multi_constructor("!", construct_tagged)
    return HaLoader


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

    ha_loader = build_ha_loader(yaml)

    errors: list[str] = []
    for file_path in yaml_files():
        rel = file_path.relative_to(ROOT)
        text = file_path.read_text(encoding="utf-8")
        try:
            yaml.load(text, Loader=ha_loader)
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
