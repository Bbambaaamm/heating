#!/usr/bin/env python3
"""Konzervativní statická validace konzistence zón napříč topnými seznamy."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASELINE_ZONES = [
    "sklep_michal",
    "prizemi_michal",
    "prizemi_chodba_zachod",
    "1p_jidelna",
    "1p_kuchyn",
    "1p_koupelna",
    "1p_chodba",
    "2p_mama",
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def extract(pattern: str, text: str) -> set[str]:
    return set(re.findall(pattern, text, flags=re.MULTILINE))


def validate_set(name: str, actual: set[str], expected: set[str], errors: list[str]) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        errors.append(f"{name}:")
        if missing:
            errors.append(f"  chybí: {', '.join(missing)}")
        if extra:
            errors.append(f"  navíc: {', '.join(extra)}")


def main() -> int:
    baseline = set(BASELINE_ZONES)
    errors: list[str] = []

    dispatch = read("heating/control/refactor_mode_schedule_override.yaml")
    boost = read("heating/control/mode_boost.yaml")
    watchdog = read("heating/control/watchdog_manual_override.yaml")
    startup = read("heating/schedule/automation/startup/manual_override_startup_reconcile.yaml")
    automations = read("automations.yaml")
    groups = read("heating/core/groups.yaml")
    scheduler_bools = read("heating/schedule/preferences/helpers/scheduler_booleans.yaml")
    ui_sync = read("heating/schedule/automation/startup/heating_ui_sync_selection.yaml")
    ui_global_manual = read("heating/ui/packages/heating_global_manual.yaml")
    manual_override_helpers = read("heating/schedule/preferences/helpers/manual_override_helpers.yaml")

    ui_timer_logic = read("heating/ui/controls/heating_timer_logic.yaml")

    validate_set("dispatch last_comfort", extract(r"input_number\.([\w]+)_last_comfort", dispatch), baseline, errors)
    validate_set("dispatch schedule_active", extract(r"input_boolean\.([\w]+)_schedule_active", dispatch), baseline, errors)
    validate_set("dispatch manual_override", extract(r"input_boolean\.([\w]+)_manual_override", dispatch), baseline, errors)
    validate_set("dispatch manual_override_type", extract(r"input_select\.([\w]+)_manual_override_type", dispatch), baseline, errors)
    validate_set("dispatch timers", extract(r"timer\.([\w]+)_manual_override", dispatch), baseline, errors)

    validate_set("boost zones (climate)", extract(r"climate\.([\w]+)'", boost), baseline, errors)
    validate_set("watchdog manual_override", extract(r"input_boolean\.([\w]+)_manual_override", watchdog), baseline, errors)
    validate_set("startup reconcile manual_override", extract(r"input_boolean\.([\w]+)_manual_override", startup), baseline, errors)

    validate_set("automations blueprint climate_entity", extract(r"climate_entity:\s*climate\.([\w]+)", automations), baseline, errors)
    validate_set("automations blueprint schedule_enable", extract(r"schedule_enable:\s*input_boolean\.schedule_enable_([\w]+)", automations), baseline, errors)
    validate_set("automations blueprint last_comfort", extract(r"last_comfort_helper:\s*input_number\.([\w]+)_last_comfort", automations), baseline, errors)
    validate_set("automations blueprint scheduler_entity", extract(r"scheduler_entity:\s*input_boolean\.([\w]+)_schedule_active", automations), baseline, errors)
    validate_set("automations blueprint manual_override", extract(r"manual_override_boolean:\s*input_boolean\.([\w]+)_manual_override", automations), baseline, errors)
    validate_set("automations blueprint manual_override_type", extract(r"manual_override_type:\s*input_select\.([\w]+)_manual_override_type", automations), baseline, errors)
    validate_set("automations blueprint manual_override_timer", extract(r"manual_override_timer:\s*timer\.([\w]+)_manual_override", automations), baseline, errors)

    validate_set("group.heating_zones", extract(r"climate\.([\w]+)", groups), baseline, errors)
    validate_set("scheduler_booleans", extract(r"^\s*([0-9A-Za-z_]+)_schedule_active:\s*$", scheduler_bools), baseline, errors)
    validate_set("ui sync manual_override", extract(r"input_boolean\.([\w]+)_manual_override", ui_sync), baseline, errors)
    validate_set("ui sync ui_select", extract(r"input_boolean\.ui_select_([\w]+)", ui_sync), baseline, errors)

    validate_set("manual_override_helpers manual", extract(r"^\s*([0-9A-Za-z_]+)_manual_override:\s*$", manual_override_helpers), baseline, errors)
    validate_set("manual_override_helpers ui_select", extract(r"^\s*ui_select_([0-9A-Za-z_]+):\s*$", manual_override_helpers), baseline, errors)
    validate_set("manual_override_helpers timer", extract(r"^\s*([0-9A-Za-z_]+)_manual_override:\s*$", manual_override_helpers), baseline, errors)
    validate_set("manual_override_helpers type", extract(r"^\s*([0-9A-Za-z_]+)_manual_override_type:\s*$", manual_override_helpers), baseline, errors)

    validate_set("ui timer logic timers", extract(r"timer\.([\w]+)_manual_override", ui_timer_logic), baseline, errors)

    for zone in BASELINE_ZONES:
        if f"manual: input_boolean.{zone}_manual_override" not in ui_global_manual:
            errors.append(f"ui global manual map: chybí manual pro {zone}")
        if f"timer: timer.{zone}_manual_override" not in ui_global_manual:
            errors.append(f"ui global manual map: chybí timer pro {zone}")
        if f"type_select: input_select.{zone}_manual_override_type" not in ui_global_manual:
            errors.append(f"ui global manual map: chybí type_select pro {zone}")

        core_file = ROOT / f"heating/core/zone_{zone}.yaml"
        sched_file = ROOT / f"heating/schedule/preferences/helpers/schedule_helpers_{zone}.yaml"
        pref_file = ROOT / f"heating/schedule/preferences/prefs/zone_{zone}_prefs.yaml"
        for p in (core_file, sched_file, pref_file):
            if not p.exists():
                errors.append(f"chybí soubor: {p.relative_to(ROOT)}")

        if core_file.exists() and f"climate.{zone}" not in core_file.read_text(encoding="utf-8"):
            errors.append(f"core soubor neobsahuje climate.{zone}: {core_file.relative_to(ROOT)}")

        if sched_file.exists():
            s = sched_file.read_text(encoding="utf-8")
            for needle in (f"schedule_enable_{zone}", f"{zone}_monday_start", f"{zone}_sunday_end"):
                if needle not in s:
                    errors.append(f"schedule helper {sched_file.relative_to(ROOT)} neobsahuje {needle}")

    if errors:
        print("❌ Konzistence zón: NÁLEZ PROBLÉMŮ")
        print("\n".join(errors))
        return 1

    print("✅ Konzistence zón: vše odpovídá baseline seznamu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
