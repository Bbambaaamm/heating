#!/usr/bin/env python3
"""Re-evaluate local observation journals; never connects to Home Assistant."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="samples.jsonl files in chronological order")
    parser.add_argument("--revision", required=True, help="Only this physical/configuration revision may be combined")
    parser.add_argument("--lead-seconds", type=int, default=60, help="Shadow comparison budget, not a safety setting")
    args = parser.parse_args()
    if not 10 <= args.lead_seconds <= 180:
        parser.error("lead-seconds must be between 10 and 180")
    path = Path(__file__).resolve().parents[1] / "custom_components/heating_observer/engine.py"
    spec = importlib.util.spec_from_file_location("observer_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observer = module.Observer(args.revision, lead_budget=args.lead_seconds)
    samples = 0
    for path in args.files:
        with path.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                except ValueError as error:
                    raise SystemExit(f"Invalid JSON: {path}:{index}; do not silently omit evidence") from error
                if record.get("revision") != args.revision:
                    raise SystemExit(f"Revision mismatch at {path}:{index}; use separate runs")
                observer.feed(record)
                samples += 1
    observer.stop()  # The final unfinished cycle is censored, never called successful.
    print(json.dumps({"input_samples": samples, **observer.report()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
