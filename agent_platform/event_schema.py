"""Versioned append-only event envelope.

The JSON Schema in schemas/events.schema.json is the external contract. This
module creates envelopes without depending on a broker or database driver.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"

EVENT_TYPES = frozenset({
    "telemetry.snapshot.v1",
    "heating.cycle.started.v1",
    "heating.cycle.completed.v1",
    "heating.incident.created.v1",
    "diagnostic.completed.v1",
    "protection.replay.completed.v1",
    "agent.run.completed.v1",
})


def utc_iso_from_timestamp(value: float | None = None) -> str:
    dt = datetime.now(timezone.utc) if value is None else datetime.fromtimestamp(value, timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class EventEnvelope:
    schema_version: str
    event_id: str
    event_type: str
    occurred_at: str
    recorded_at: str
    site_revision: str
    source: str
    data: dict[str, Any]
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "site_revision": self.site_revision,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "data": self.data,
        }


def new_event(
    event_type: str,
    *,
    site_revision: str,
    source: str,
    data: dict[str, Any],
    occurred_at: float | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    event_id: str | None = None,
    recorded_at: float | None = None,
) -> EventEnvelope:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    if not site_revision:
        raise ValueError("site_revision is required")
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=event_id or str(uuid4()),
        event_type=event_type,
        occurred_at=utc_iso_from_timestamp(occurred_at),
        recorded_at=utc_iso_from_timestamp(recorded_at),
        site_revision=site_revision,
        source=source,
        data=data,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
