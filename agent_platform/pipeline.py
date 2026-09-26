"""Phase 1 wiring: Collector -> Cycle Builder -> Observer."""
from __future__ import annotations

from .collector import ReadOnlyCollector
from .cycle_builder import CycleBuilder
from .event_schema import EventEnvelope, new_event
from .observer import Observer


class Phase1Pipeline:
    def __init__(self, site_revision: str):
        self.site_revision = site_revision
        self.collector = ReadOnlyCollector(site_revision)
        self.cycles = CycleBuilder()
        self.observer = Observer()

    def process_state_map(self, states, *, captured_at: float) -> list[EventEnvelope]:
        snapshot = self.collector.collect(states, captured_at=captured_at)
        snapshot_event = new_event(
            "telemetry.snapshot.v1",
            site_revision=self.site_revision,
            source="collector",
            occurred_at=snapshot.timestamp,
            data=snapshot.to_dict(),
        )

        prior_cycle_id = self.cycles.active_cycle_id
        transitions = self.cycles.feed(snapshot)
        started = next((x for x in transitions if x.kind == "started"), None)
        snapshot_cycle_id = prior_cycle_id or (started.summary.cycle_id if started else None)

        incidents = self.observer.feed(snapshot, cycle_id=snapshot_cycle_id)
        result = [snapshot_event]

        for transition in transitions:
            event_type = (
                "heating.cycle.started.v1"
                if transition.kind == "started"
                else "heating.cycle.completed.v1"
            )
            result.append(new_event(
                event_type,
                site_revision=self.site_revision,
                source="cycle_builder",
                occurred_at=snapshot.timestamp,
                correlation_id=transition.summary.cycle_id,
                causation_id=snapshot_event.event_id,
                data=transition.summary.to_dict(),
            ))

        for incident in incidents:
            result.append(new_event(
                "heating.incident.created.v1",
                site_revision=self.site_revision,
                source="observer",
                occurred_at=incident.occurred_at,
                correlation_id=incident.cycle_id,
                causation_id=snapshot_event.event_id,
                data=incident.to_dict(),
            ))

        for transition in transitions:
            if transition.kind == "completed":
                self.observer.observe_completed_cycle(transition.summary)

        return result
