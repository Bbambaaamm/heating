#!/usr/bin/env python3
"""Kontroluje, že debug logika je řízená guard helpery."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "heating/control", ROOT / "heating/schedule", ROOT / "heating/ui"]


def main() -> int:
    errors: list[str] = []
    for base in TARGETS:
        for file_path in base.rglob("*.yaml"):
            text = file_path.read_text(encoding="utf-8")
            if "[DEBUG]" not in text:
                continue
            has_guard = "input_boolean.heating_debug_guard" in text
            has_time_guard = "input_datetime.heating_debug_until" in text
            rel = file_path.relative_to(ROOT)
            if not (has_guard and has_time_guard):
                errors.append(
                    f"{rel}: obsahuje [DEBUG] logiku bez povinné dvojice guardů "
                    "(input_boolean.heating_debug_guard + input_datetime.heating_debug_until)."
                )

    if errors:
        print("❌ Debug guard validace selhala:")
        print("\n".join(errors))
        return 1

    print("✅ Debug guard validace prošla.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
