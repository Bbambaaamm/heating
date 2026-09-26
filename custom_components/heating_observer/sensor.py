"""Read-only diagnostic entities; no control platform is provided."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, SIGNAL, VERSION
from .engine import rule_description


KINDS = ("status", "learning", "agent_platform", "agent_diagnostic", "agent_knowledge", "agent_baseline")


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    runtime = hass.data[DOMAIN]
    async_add_entities([ObserverSensor(runtime, kind) for kind in KINDS])


class ObserverSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, runtime, kind):
        self.runtime, self.kind = runtime, kind
        self.entity_id = f"sensor.heating_observer_{kind}" if kind in ("status", "learning") else f"sensor.heating_{kind}"
        self._attr_unique_id = f"heating_observer_{kind}"
        self._attr_name = {
            "status": "Topení – pozorovací režim",
            "learning": "Topení – vyhodnocování cyklů",
            "agent_platform": "Topení – Agent Platform",
            "agent_diagnostic": "Topení – diagnostický agent",
            "agent_knowledge": "Topení – knowledge agent",
            "agent_baseline": "Topení – request baseline",
        }[kind]
        self._attr_icon = {
            "status": "mdi:chart-timeline-variant",
            "learning": "mdi:chart-timeline-variant",
            "agent_platform": "mdi:database-eye",
            "agent_diagnostic": "mdi:stethoscope",
            "agent_knowledge": "mdi:book-open-page-variant",
            "agent_baseline": "mdi:chart-bell-curve-cumulative",
        }[kind]

    @property
    def native_value(self):
        r = self.runtime
        if self.kind == "status":
            status = "storage_error" if r.storage_error else r.engine.status
            return {"storage_error": "Chyba ukládání", "initializing": "Načítání dat",
                    "fault_observed": "Ohlášená porucha", "data_incomplete": "Neúplná data",
                    "service": "Servisní režim", "observing": "Pozorování"}[status]
        if self.kind == "learning":
            return r.engine.data["generation"]
        if self.kind == "agent_platform":
            return "Chyba DB" if r.agent_storage_error else "Běží"
        if self.kind == "agent_diagnostic":
            return "Analyzováno" if r.last_diagnostic else "Čeká na incident"
        if self.kind == "agent_knowledge":
            return r.cached_knowledge.get("entries", 0)
        if self.kind == "agent_baseline":
            return r.cached_baseline.get("cycles", 0)
        return None

    @property
    def extra_state_attributes(self):
        r = self.runtime
        if self.kind == "status":
            return {"mode": "shadow_only", "version": VERSION, "revision": r.engine.revision,
                    "warning_hypotheses": r.engine.current_warnings,
                    "warning_descriptions": [rule_description(x) for x in r.engine.current_warnings],
                    "data_quality": r.engine.current_quality, "dropped_observations": r.dropped,
                    "last_captured_at": r.last_captured_at, "last_written_at": r.last_written_at,
                    "storage_error": r.storage_error, "actuator_control": False}
        if self.kind == "learning":
            return {**{k: v for k, v in r.cached_report.items() if k != "metrics"},
                    "top_hypotheses": r.cached_report["metrics"][:3]}
        if self.kind == "agent_platform":
            return {
                "mode": "read_only",
                "version": VERSION,
                "revision": r.engine.revision,
                "database": r.cached_agent_stats,
                "last_agent_written_at": r.last_agent_written_at,
                "agent_storage_error": r.agent_storage_error,
                "recent_incidents": r.cached_incidents,
                "diagnostic_agent": r.diagnostic_agent.name,
                "knowledge_agent": r.knowledge_agent.name,
                "actuator_control": False,
                "service_call_api": False,
            }
        if self.kind == "agent_diagnostic":
            if not r.last_diagnostic:
                return {
                    "root_cause": "UNKNOWN",
                    "message": "Čeká na nový incident; agent nic neřídí.",
                    "actuator_control": False,
                }
            return {
                "diagnostic_id": r.last_diagnostic.get("diagnostic_id"),
                "incident_id": r.last_diagnostic.get("incident_id"),
                "episode_id": r.last_diagnostic.get("episode_id"),
                "root_cause": r.last_diagnostic.get("root_cause", "UNKNOWN"),
                "facts": r.last_diagnostic.get("facts", []),
                "hypotheses": r.last_diagnostic.get("hypotheses", []),
                "next_measurement": r.last_diagnostic.get("next_measurement"),
                "safety_implication": r.last_diagnostic.get("safety_implication"),
                "actuator_control": False,
            }
        if self.kind == "agent_knowledge":
            return {
                **r.cached_knowledge,
                "promotion_policy": "Hypothesis is never promoted to FACT automatically.",
                "actuator_control": False,
            }
        if self.kind == "agent_baseline":
            return {
                **r.cached_baseline,
                "safety_limit": False,
                "actuator_control": False,
            }
        return {}

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()
