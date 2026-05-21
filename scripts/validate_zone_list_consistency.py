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

    print("✅ Seznamy zón jsou konzistentní.")
    print(f"Zóny ({len(baseline)}): {', '.join(sorted(baseline))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
