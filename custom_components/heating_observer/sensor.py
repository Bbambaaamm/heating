"""Read-only diagnostic entities; no control platform is provided."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, SIGNAL, VERSION
from .engine import rule_description


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    runtime = hass.data[DOMAIN]
    async_add_entities([ObserverSensor(runtime, kind) for kind in ("status", "learning")])


class ObserverSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, runtime, kind):
        self.runtime, self.kind = runtime, kind
        self.entity_id = f"sensor.heating_observer_{kind}"
        self._attr_unique_id = f"heating_observer_{kind}"
        self._attr_name = "Topení – pozorovací režim" if kind == "status" else "Topení – vyhodnocování cyklů"

    @property
    def native_value(self):
        if self.kind == "status":
            status = "storage_error" if self.runtime.storage_error else self.runtime.engine.status
            return {"storage_error": "Chyba ukládání", "initializing": "Načítání dat",
                    "fault_observed": "Ohlášená porucha", "data_incomplete": "Neúplná data",
                    "service": "Servisní režim", "observing": "Pozorování"}[status]
        return self.runtime.engine.data["generation"]

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
        return {**{k: v for k, v in r.cached_report.items() if k != "metrics"},
                "top_hypotheses": r.cached_report["metrics"][:3]}

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()
