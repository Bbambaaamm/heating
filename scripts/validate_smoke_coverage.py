#!/usr/bin/env python3
"""Kontroluje, že změny v orchestrace vrstvách mají oporu ve smoke/checklist dokumentaci."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "heating/analysis/heating_smoke_test_matrix.md"
CHECKLIST = ROOT / "heating/analysis/zone_onboarding_checklist.md"

REQUIRED_SMOKE = [
    "Off -> Auto -> Eco -> Boost -> Auto",
    "Dispatch ON vs OFF",
    "Manual override lifecycle",
]


def main() -> int:
    errors: list[str] = []
    smoke_text = SMOKE.read_text(encoding="utf-8") if SMOKE.exists() else ""
    checklist_text = CHECKLIST.read_text(encoding="utf-8") if CHECKLIST.exists() else ""

    if not SMOKE.exists():
        errors.append("chybí heating/analysis/heating_smoke_test_matrix.md")
    if not CHECKLIST.exists():
        errors.append("chybí heating/analysis/zone_onboarding_checklist.md")

    for needle in REQUIRED_SMOKE:
        if needle not in smoke_text:
            errors.append(f"smoke matice neobsahuje povinný scénář: {needle}")

    if "validate_zone_list_consistency.py" not in checklist_text:
        errors.append("checklist neobsahuje povinný validační krok validate_zone_list_consistency.py")

    if errors:
        print("❌ Smoke coverage guard selhal:")
        print("\n".join(errors))
        return 1

    print("✅ Smoke coverage guard prošel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
