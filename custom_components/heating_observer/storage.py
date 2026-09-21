"""Bounded local journal and atomic model checkpoint; invoke in an executor."""
from __future__ import annotations

import json
import os
from pathlib import Path


class Journal:
    def __init__(self, root: Path, revision: str, *, max_bytes: int = 16 * 1024 * 1024,
                 backups: int = 3):
        self.root = root
        self.revision = revision
        self.max_bytes = max_bytes
        self.backups = backups
        self.model_path = root / f"model-{revision}.json"

    def load(self) -> dict | None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.model_path.exists():
            return None
        with self.model_path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("Observer checkpoint is not an object")
        return data

    def _append(self, name: str, record: dict):
        path = self.root / name
        encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()
        if len(encoded) > self.max_bytes:
            raise ValueError("Observer record exceeds the journal size limit")
        if path.exists() and path.stat().st_size + len(encoded) > self.max_bytes:
            oldest = self.root / f"{name}.{self.backups}"
            oldest.unlink(missing_ok=True)
            for i in range(self.backups - 1, 0, -1):
                old = self.root / f"{name}.{i}"
                if old.exists():
                    old.replace(self.root / f"{name}.{i + 1}")
            path.replace(self.root / f"{name}.1")
        with path.open("ab") as stream:
            stream.write(encoded)

    def _atomic(self, path: Path, value: dict):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)

    def write(self, snapshot: dict | None, events: list[dict], model: dict, report: dict,
              checkpoint: bool):
        self.root.mkdir(parents=True, exist_ok=True)
        if snapshot is not None:
            self._append("samples.jsonl", snapshot)
        for event in events:
            self._append("episodes.jsonl", event)
        if checkpoint:
            self._atomic(self.model_path, model)
            self._atomic(self.root / "report.json", report)
