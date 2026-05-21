#!/usr/bin/env python3
"""Konzervativní kontrola konzistence zón napříč klíčovými seznamy.

Skript je záměrně jednoduchý a bez externích závislostí.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "dispatch": ROOT / "heating/control/refactor_mode_schedule_override.yaml",
    "boost": ROOT / "heating/control/mode_boost.yaml",
    "watchdog": ROOT / "heating/control/watchdog_manual_override.yaml",
    "startup_reconcile": ROOT / "heating/schedule/automation/startup/manual_override_startup_reconcile.yaml",
    "automations": ROOT / "automations.yaml",
    "core_groups": ROOT / "heating/core/groups.yaml",
    "scheduler_booleans": ROOT / "heating/schedule/preferences/helpers/scheduler_booleans.yaml",
}


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Chybí soubor: {path}")
    return path.read_text(encoding="utf-8")


def extract_set(pattern: str, text: str) -> set[str]:
    return set(re.findall(pattern, text))


def main() -> int:
    dispatch = read_text(FILES["dispatch"])
    boost = read_text(FILES["boost"])
    watchdog = read_text(FILES["watchdog"])
    startup_reconcile = read_text(FILES["startup_reconcile"])
    automations = read_text(FILES["automations"])
    core_groups = read_text(FILES["core_groups"])
    scheduler_booleans = read_text(FILES["scheduler_booleans"])

    dispatch_last = extract_set(r"input_number\.([a-z0-9_]+)_last_comfort", dispatch)
    dispatch_schedule = extract_set(r"input_boolean\.([a-z0-9_]+)_schedule_active", dispatch)
    dispatch_manual = extract_set(r"input_boolean\.([a-z0-9_]+)_manual_override", dispatch)
    dispatch_manual_type = extract_set(r"input_select\.([a-z0-9_]+)_manual_override_type", dispatch)
    dispatch_timer = extract_set(r"timer\.([a-z0-9_]+)_manual_override", dispatch)

    boost_last = extract_set(r"input_number\.([a-z0-9_]+)_last_comfort", boost)
    boost_manual = extract_set(r"input_boolean\.([a-z0-9_]+)_manual_override", boost)
    boost_manual_type = extract_set(r"input_select\.([a-z0-9_]+)_manual_override_type", boost)
    boost_timer = extract_set(r"timer\.([a-z0-9_]+)_manual_override", boost)

    watchdog_manual = extract_set(r"input_boolean\.([a-z0-9_]+)_manual_override", watchdog)
    startup_manual = extract_set(r"input_boolean\.([a-z0-9_]+)_manual_override", startup_reconcile)
    automation_schedule = extract_set(r"input_boolean\.schedule_enable_([a-z0-9_]+)", automations)
    automation_last_comfort = extract_set(r"input_number\.([a-z0-9_]+)_last_comfort", automations)
    automation_schedule_active = extract_set(r"input_boolean\.([a-z0-9_]+)_schedule_active", automations)
    automation_manual = extract_set(r"input_boolean\.([a-z0-9_]+)_manual_override", automations)
    automation_manual_type = extract_set(r"input_select\.([a-z0-9_]+)_manual_override_type", automations)
    automation_timer = extract_set(r"timer\.([a-z0-9_]+)_manual_override", automations)
    core_group_climate = extract_set(r"climate\.([a-z0-9_]+)", core_groups)
    automation_climate = extract_set(r"climate\.([a-z0-9_]+)", automations)
    scheduler_booleans_schedule_active = extract_set(r"([a-z0-9_]+)_schedule_active", scheduler_booleans)

    groups = {
        "dispatch_last": dispatch_last,
        "dispatch_schedule": dispatch_schedule,
        "dispatch_manual": dispatch_manual,
        "dispatch_manual_type": dispatch_manual_type,
        "dispatch_timer": dispatch_timer,
        "boost_last": boost_last,
        "boost_manual": boost_manual,
        "boost_manual_type": boost_manual_type,
        "boost_timer": boost_timer,
        "watchdog_manual": watchdog_manual,
        "startup_manual": startup_manual,
        "automation_schedule": automation_schedule,
        "automation_last_comfort": automation_last_comfort,
        "automation_schedule_active": automation_schedule_active,
        "automation_manual": automation_manual,
        "automation_manual_type": automation_manual_type,
        "automation_timer": automation_timer,
        "automation_climate": automation_climate,
        "core_group_climate": core_group_climate,
        "scheduler_booleans_schedule_active": scheduler_booleans_schedule_active,
    }

    baseline = dispatch_last
    failures: list[str] = []

    for name, values in groups.items():
        if values != baseline:
            missing = sorted(baseline - values)
            extra = sorted(values - baseline)
            failures.append(
                f"{name}: missing={missing or '-'} extra={extra or '-'}"
            )

    if failures:
        print("❌ Nekonzistentní seznamy zón:")
        for item in failures:
            print(f"- {item}")
        return 1

    missing_zone_files = sorted(
        zone for zone in baseline if not (ROOT / "heating/core" / f"zone_{zone}.yaml").exists()
    )
    if missing_zone_files:
        print("❌ Chybí core definice zón (heating/core/zone_<zona>.yaml):")
        for zone in missing_zone_files:
            print(f"- zone_{zone}.yaml")
        return 1

    invalid_zone_file_entity: list[str] = []
    for zone in sorted(baseline):
        zone_file = ROOT / "heating/core" / f"zone_{zone}.yaml"
        zone_text = read_text(zone_file)
        if f"climate.{zone}" not in zone_text:
            invalid_zone_file_entity.append(zone)
    if invalid_zone_file_entity:
        print("❌ Nekonzistentní climate entity v core definici zóny:")
        for zone in invalid_zone_file_entity:
            print(f"- zone_{zone}.yaml neobsahuje climate.{zone}")
        return 1

    missing_schedule_helper_files = sorted(
        zone
        for zone in baseline
        if not (ROOT / "heating/schedule/preferences/helpers" / f"schedule_helpers_{zone}.yaml").exists()
    )
    if missing_schedule_helper_files:
        print("❌ Chybí schedule helper definice zón (heating/schedule/preferences/helpers/schedule_helpers_<zona>.yaml):")
        for zone in missing_schedule_helper_files:
            print(f"- schedule_helpers_{zone}.yaml")
        return 1

    missing_zone_pref_files = sorted(
        zone
        for zone in baseline
        if not (ROOT / "heating/schedule/preferences/prefs" / f"zone_{zone}_prefs.yaml").exists()
    )
    if missing_zone_pref_files:
        print("❌ Chybí preference zón (heating/schedule/preferences/prefs/zone_<zona>_prefs.yaml):")
        for zone in missing_zone_pref_files:
            print(f"- zone_{zone}_prefs.yaml")
        return 1

    print("✅ Seznamy zón jsou konzistentní.")
    print(f"Zóny ({len(baseline)}): {', '.join(sorted(baseline))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
