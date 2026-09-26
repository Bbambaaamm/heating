"""SQLite evidence store for the Heating Agent Platform.

The store is local to Home Assistant, append-only for raw events, and contains
no network or actuator code. PostgreSQL remains the scale-out target; this
backend mirrors the logical schema with SQLite types available in HA Core.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AgentDatabase:
    def __init__(self, path: Path, revision: str):
        self.path = path
        self.revision = revision

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_log (
                    event_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    site_revision TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT,
                    causation_id TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_log_type_time_idx
                    ON event_log(event_type, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS event_log_correlation_idx
                    ON event_log(correlation_id);

                CREATE TRIGGER IF NOT EXISTS event_log_no_update
                BEFORE UPDATE ON event_log
                BEGIN
                    SELECT RAISE(ABORT, 'event_log is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS event_log_no_delete
                BEFORE DELETE ON event_log
                BEGIN
                    SELECT RAISE(ABORT, 'event_log is append-only');
                END;

                CREATE TABLE IF NOT EXISTS state_samples (
                    event_id TEXT PRIMARY KEY REFERENCES event_log(event_id),
                    captured_at REAL NOT NULL,
                    relay INTEGER,
                    gas INTEGER,
                    pump INTEGER,
                    master INTEGER,
                    service INTEGER,
                    mode TEXT,
                    dhw INTEGER,
                    dhw_recharging INTEGER,
                    dhw_valve INTEGER,
                    boiler_block_temperature REAL,
                    flow_temperature REAL,
                    burner_power REAL,
                    service_code INTEGER,
                    quality_flags TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS state_samples_time_idx
                    ON state_samples(captured_at DESC);

                CREATE TABLE IF NOT EXISTS zone_samples (
                    sample_event_id TEXT NOT NULL REFERENCES state_samples(event_id),
                    zone_id TEXT NOT NULL,
                    hvac_state TEXT,
                    current_temperature REAL,
                    target_temperature REAL,
                    pi_demand REAL,
                    in_window INTEGER,
                    PRIMARY KEY (sample_event_id, zone_id)
                );

                CREATE TABLE IF NOT EXISTS heating_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    site_revision TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL,
                    start_kind TEXT NOT NULL,
                    incomplete INTEGER NOT NULL,
                    runtime_seconds REAL,
                    burner_starts INTEGER NOT NULL,
                    start_boiler_temperature REAL,
                    max_boiler_temperature REAL,
                    max_temperature_rise_c_per_min REAL,
                    min_requesting_zones INTEGER,
                    average_requesting_zones REAL,
                    fault_codes TEXT NOT NULL,
                    service_seen INTEGER NOT NULL,
                    master_off_seen INTEGER NOT NULL,
                    dhw_seen INTEGER NOT NULL,
                    quality_flags TEXT NOT NULL,
                    eligible_for_baseline INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS heating_cycles_baseline_idx
                    ON heating_cycles(site_revision, eligible_for_baseline, started_at DESC);

                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    cycle_id TEXT,
                    episode_id TEXT,
                    site_revision TEXT NOT NULL,
                    incident_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    source_event_id TEXT NOT NULL REFERENCES event_log(event_id),
                    observation TEXT NOT NULL,
                    timeline TEXT NOT NULL,
                    diagnosis_state TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE INDEX IF NOT EXISTS incidents_time_idx
                    ON incidents(occurred_at DESC);

                CREATE TABLE IF NOT EXISTS diagnostic_reports (
                    diagnostic_id TEXT PRIMARY KEY,
                    incident_id TEXT REFERENCES incidents(incident_id),
                    episode_id TEXT,
                    agent TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    facts TEXT NOT NULL,
                    next_measurement TEXT,
                    safety_implication TEXT,
                    root_cause TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS diagnostic_hypotheses (
                    diagnostic_id TEXT NOT NULL REFERENCES diagnostic_reports(diagnostic_id),
                    hypothesis_index INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                    evidence_for TEXT NOT NULL,
                    evidence_against TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (diagnostic_id, hypothesis_index)
                );

                CREATE TABLE IF NOT EXISTS knowledge_entries (
                    knowledge_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('FACT','OBSERVATION','HYPOTHESIS','DECISION','DEPRECATED')),
                    statement TEXT NOT NULL,
                    source_incident_id TEXT,
                    created_at REAL NOT NULL,
                    confidence REAL,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS knowledge_kind_time_idx
                    ON knowledge_entries(kind, created_at DESC);

                CREATE TABLE IF NOT EXISTS agent_runs (
                    agent_run_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    input_refs TEXT NOT NULL,
                    output_refs TEXT NOT NULL
                );
                """
            )
            db.commit()

    def _event(
        self,
        db: sqlite3.Connection,
        event_type: str,
        occurred_at: float,
        source: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> str:
        event_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        db.execute(
            """
            INSERT INTO event_log
            (event_id, schema_version, event_type, occurred_at, recorded_at,
             site_revision, source, correlation_id, causation_id, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, SCHEMA_VERSION, event_type, _iso(occurred_at), now,
                self.revision, source, correlation_id, causation_id, _json(payload),
            ),
        )
        return event_id

    @staticmethod
    def _bool(value: Any) -> int | None:
        return None if value is None else int(bool(value))

    @staticmethod
    def _quality(sample: dict[str, Any]) -> list[str]:
        result = []
        if sample.get("gap"):
            result.append("capture_gap")
        for key in ("block", "flow"):
            if sample.get(key) is None:
                result.append(f"invalid_{key}")
            age = sample.get("ages", {}).get(key)
            if age is None:
                result.append(f"unknown_age_{key}")
        return sorted(set(result))

    def write_batch(
        self,
        sample: dict[str, Any] | None,
        cycles: list[dict[str, Any]],
        observer_events: list[dict[str, Any]],
        diagnostics: list[dict[str, Any]],
        knowledge_entries: list[dict[str, Any]],
    ) -> None:
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            snapshot_event_id = None
            if sample is not None:
                t = float(sample["t"])
                payload = {
                    "timestamp": t,
                    "site_revision": self.revision,
                    "relay": sample.get("relay"),
                    "gas": sample.get("gas"),
                    "pump": sample.get("pump"),
                    "master": sample.get("master"),
                    "service": sample.get("service"),
                    "mode": sample.get("mode"),
                    "dhw": sample.get("dhw"),
                    "dhw_recharging": sample.get("dhw_recharging"),
                    "dhw_valve": sample.get("dhw_valve"),
                    "boiler_block_temperature": sample.get("block"),
                    "flow_temperature": sample.get("flow"),
                    "burner_power": sample.get("power"),
                    "service_code": sample.get("code"),
                    "zones": sample.get("zones", {}),
                    "quality": self._quality(sample),
                }
                snapshot_event_id = self._event(db, "telemetry.snapshot.v1", t, "heating_observer", payload)
                db.execute(
                    """
                    INSERT INTO state_samples
                    (event_id, captured_at, relay, gas, pump, master, service, mode,
                     dhw, dhw_recharging, dhw_valve, boiler_block_temperature,
                     flow_temperature, burner_power, service_code, quality_flags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_event_id, t,
                        self._bool(sample.get("relay")), self._bool(sample.get("gas")),
                        self._bool(sample.get("pump")), self._bool(sample.get("master")),
                        self._bool(sample.get("service")), sample.get("mode"),
                        self._bool(sample.get("dhw")), self._bool(sample.get("dhw_recharging")),
                        self._bool(sample.get("dhw_valve")), sample.get("block"),
                        sample.get("flow"), sample.get("power"), sample.get("code"),
                        _json(self._quality(sample)),
                    ),
                )
                for zone_id, zone in sample.get("zones", {}).items():
                    db.execute(
                        """
                        INSERT INTO zone_samples
                        (sample_event_id, zone_id, hvac_state, current_temperature,
                         target_temperature, pi_demand, in_window)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_event_id, zone_id, zone.get("state"), zone.get("room"),
                            zone.get("target"), zone.get("pi"), self._bool(zone.get("in_window")),
                        ),
                    )

            for transition in cycles:
                cycle = transition["cycle"]
                event_type = (
                    "heating.cycle.started.v1"
                    if transition["kind"] == "cycle_started"
                    else "heating.cycle.completed.v1"
                )
                self._event(
                    db, event_type, float(cycle["started_at"] if transition["kind"] == "cycle_started" else cycle["ended_at"]),
                    "request_cycle_builder", cycle,
                    correlation_id=cycle["cycle_id"], causation_id=snapshot_event_id,
                )
                if transition["kind"] == "cycle_completed":
                    db.execute(
                        """
                        INSERT OR IGNORE INTO heating_cycles
                        (cycle_id, site_revision, started_at, ended_at, start_kind, incomplete,
                         runtime_seconds, burner_starts, start_boiler_temperature,
                         max_boiler_temperature, max_temperature_rise_c_per_min,
                         min_requesting_zones, average_requesting_zones, fault_codes,
                         service_seen, master_off_seen, dhw_seen, quality_flags,
                         eligible_for_baseline)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cycle["cycle_id"], cycle["site_revision"], cycle["started_at"],
                            cycle["ended_at"], cycle["start_kind"], int(cycle["incomplete"]),
                            cycle["runtime_seconds"], cycle["burner_starts"],
                            cycle["start_boiler_temperature"], cycle["max_boiler_temperature"],
                            cycle["max_temperature_rise_c_per_min"], cycle["min_requesting_zones"],
                            cycle["average_requesting_zones"], _json(list(cycle["fault_codes"])),
                            int(cycle["service_seen"]), int(cycle["master_off_seen"]),
                            int(cycle["dhw_seen"]), _json(list(cycle["quality_flags"])),
                            int(cycle["eligible_for_baseline"]),
                        ),
                    )

            incident_ids: dict[str, str] = {}
            for event in observer_events:
                if event.get("kind") != "incident_open":
                    continue
                incident_id = event.get("incident_id") or str(uuid4())
                incident_ids[event.get("episode_id") or incident_id] = incident_id
                t = float(event.get("t") or (sample or {}).get("t") or 0)
                payload = {
                    "incident_id": incident_id,
                    "episode_id": event.get("episode_id"),
                    "incident_type": "boiler_fault_code",
                    "severity": "high",
                    "occurred_at": t,
                    "observation": {
                        "service_code": event.get("code"),
                        "statement": "Known boiler fault-code transition observed.",
                        "root_cause": "UNKNOWN",
                        "physical_flow_confirmed": False,
                    },
                    "timeline": event.get("prelude") or [],
                    "diagnosis": None,
                }
                event_id = self._event(
                    db, "heating.incident.created.v1", t, "heating_observer",
                    payload, correlation_id=incident_id, causation_id=snapshot_event_id,
                )
                db.execute(
                    """
                    INSERT OR IGNORE INTO incidents
                    (incident_id, cycle_id, episode_id, site_revision, incident_type,
                     severity, occurred_at, source_event_id, observation, timeline, diagnosis_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        incident_id, event.get("request_cycle_id"), event.get("episode_id"), self.revision,
                        "boiler_fault_code", "high", t, event_id,
                        _json(payload["observation"]), _json(payload["timeline"]),
                    ),
                )

            for diagnostic in diagnostics:
                created_at = float((sample or {}).get("t") or 0)
                incident_id = diagnostic.get("incident_id")
                diagnostic_event_id = self._event(
                    db, "diagnostic.completed.v1", created_at, diagnostic.get("agent", "diagnostic"),
                    diagnostic, correlation_id=incident_id, causation_id=snapshot_event_id,
                )
                diagnostic_run_id = str(uuid4())
                db.execute(
                    """
                    INSERT INTO agent_runs
                    (agent_run_id, agent, task_type, started_at, finished_at, status, input_refs, output_refs)
                    VALUES (?, ?, 'diagnose_incident', ?, ?, 'completed', ?, ?)
                    """,
                    (
                        diagnostic_run_id, diagnostic.get("agent", "diagnostic"), created_at, created_at,
                        _json([incident_id] if incident_id else []),
                        _json([diagnostic["diagnostic_id"]]),
                    ),
                )
                self._event(
                    db, "agent.run.completed.v1", created_at, diagnostic.get("agent", "diagnostic"),
                    {"agent_run_id": diagnostic_run_id, "agent": diagnostic.get("agent", "diagnostic"),
                     "status": "completed", "output_refs": [diagnostic["diagnostic_id"]]},
                    correlation_id=incident_id, causation_id=diagnostic_event_id,
                )
                db.execute(
                    """
                    INSERT OR IGNORE INTO diagnostic_reports
                    (diagnostic_id, incident_id, episode_id, agent, created_at, facts,
                     next_measurement, safety_implication, root_cause)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        diagnostic["diagnostic_id"], incident_id, diagnostic.get("episode_id"),
                        diagnostic.get("agent", "diagnostic"), created_at,
                        _json(diagnostic.get("facts", [])), diagnostic.get("next_measurement"),
                        diagnostic.get("safety_implication"), diagnostic.get("root_cause", "UNKNOWN"),
                    ),
                )
                for index, hypothesis in enumerate(diagnostic.get("hypotheses", [])):
                    db.execute(
                        """
                        INSERT INTO diagnostic_hypotheses
                        (diagnostic_id, hypothesis_index, name, confidence,
                         evidence_for, evidence_against, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            diagnostic["diagnostic_id"], index, hypothesis["name"],
                            float(hypothesis["confidence"]), _json(hypothesis.get("evidence_for", [])),
                            _json(hypothesis.get("evidence_against", [])), hypothesis.get("status", "HYPOTHESIS"),
                        ),
                    )
                if incident_id:
                    db.execute(
                        "UPDATE incidents SET diagnosis_state='completed' WHERE incident_id=?",
                        (incident_id,),
                    )

            knowledge_ids = []
            for entry in knowledge_entries:
                knowledge_ids.append(entry["knowledge_id"])
                db.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_entries
                    (knowledge_id, kind, statement, source_incident_id, created_at,
                     confidence, promoted, detail)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["knowledge_id"], entry["kind"], entry["statement"],
                        entry.get("source_incident_id"), entry["created_at"],
                        entry.get("confidence"), int(bool(entry.get("promoted", False))), _json(entry),
                    ),
                )
            if knowledge_ids:
                created_at = float((sample or {}).get("t") or 0)
                knowledge_run_id = str(uuid4())
                incident_refs = sorted({
                    entry.get("source_incident_id") for entry in knowledge_entries
                    if entry.get("source_incident_id")
                })
                db.execute(
                    """
                    INSERT INTO agent_runs
                    (agent_run_id, agent, task_type, started_at, finished_at, status, input_refs, output_refs)
                    VALUES (?, 'knowledge-v1', 'update_knowledge', ?, ?, 'completed', ?, ?)
                    """,
                    (knowledge_run_id, created_at, created_at, _json(incident_refs), _json(knowledge_ids)),
                )
                self._event(
                    db, "agent.run.completed.v1", created_at, "knowledge-v1",
                    {"agent_run_id": knowledge_run_id, "agent": "knowledge-v1",
                     "status": "completed", "output_refs": knowledge_ids},
                    correlation_id=incident_refs[0] if len(incident_refs) == 1 else None,
                    causation_id=snapshot_event_id,
                )
            db.commit()

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            def count(table: str, where: str = "", params: tuple = ()) -> int:
                return int(db.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()[0])

            return {
                "backend": "sqlite",
                "schema_version": SCHEMA_VERSION,
                "database_bytes": self.path.stat().st_size if self.path.exists() else 0,
                "events": count("event_log"),
                "samples": count("state_samples"),
                "cycles": count("heating_cycles"),
                "baseline_cycles": count("heating_cycles", "WHERE eligible_for_baseline=1"),
                "incidents": count("incidents"),
                "diagnostics": count("diagnostic_reports"),
                "knowledge_entries": count("knowledge_entries"),
                "agent_runs": count("agent_runs"),
            }

    def latest_diagnostic(self) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT diagnostic_id, incident_id, episode_id, agent, created_at, facts,
                       next_measurement, safety_implication, root_cause
                FROM diagnostic_reports ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            hypotheses = db.execute(
                """
                SELECT name, confidence, evidence_for, evidence_against, status
                FROM diagnostic_hypotheses
                WHERE diagnostic_id=? ORDER BY hypothesis_index
                """,
                (row["diagnostic_id"],),
            ).fetchall()
            return {
                **dict(row),
                "facts": json.loads(row["facts"]),
                "hypotheses": [
                    {
                        "name": h["name"],
                        "confidence": h["confidence"],
                        "evidence_for": json.loads(h["evidence_for"]),
                        "evidence_against": json.loads(h["evidence_against"]),
                        "status": h["status"],
                    }
                    for h in hypotheses
                ],
            }

    def knowledge_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT kind, statement, source_incident_id, created_at, confidence, promoted
                FROM knowledge_entries ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
            counts = Counter(row["kind"] for row in rows)
            return {
                "entries": len(rows),
                "by_kind": dict(counts),
                "latest": [dict(row) for row in rows[:5]],
                "facts_promoted_from_hypotheses": sum(
                    1 for row in rows if row["kind"] == "FACT" and row["promoted"]
                ),
            }

    def recent_incidents(self, limit: int = 5) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT incident_id, episode_id, incident_type, severity, occurred_at,
                       observation, diagnosis_state
                FROM incidents ORDER BY occurred_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    **{k: row[k] for k in row.keys() if k != "observation"},
                    "observation": json.loads(row["observation"]),
                }
                for row in rows
            ]

    def baseline_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT max_temperature_rise_c_per_min, average_requesting_zones
                FROM heating_cycles
                WHERE site_revision=? AND eligible_for_baseline=1
                ORDER BY started_at DESC LIMIT 200
                """,
                (self.revision,),
            ).fetchall()
            rises = [row["max_temperature_rise_c_per_min"] for row in rows if row["max_temperature_rise_c_per_min"] is not None]
            zones = [row["average_requesting_zones"] for row in rows if row["average_requesting_zones"] is not None]
            return {
                "cycles": len(rows),
                "max_rise_mean_c_per_min": (sum(rises) / len(rises)) if rises else None,
                "average_requesting_zones_mean": (sum(zones) / len(zones)) if zones else None,
                "meaning": "observed baseline only; not an operating or safety limit",
            }
