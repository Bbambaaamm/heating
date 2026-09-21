"""Passive local recorder for this heating installation. No actuator services."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CRITICAL, DOMAIN, INPUTS, SIGNAL, VERSION, ZONES
from .engine import Observer, number
from .storage import Journal

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = vol.Schema({
    vol.Optional(DOMAIN): vol.Schema({
        vol.Optional("site_revision", default="hydraulika-20260921-neoverena"): vol.All(cv.string, vol.Match(r"^[a-zA-Z0-9_-]{1,64}$")),
        vol.Optional("sample_seconds", default=10): vol.All(vol.Coerce(int), vol.Range(min=5, max=30)),
        vol.Optional("telemetry_gap_seconds", default=45): vol.All(vol.Coerce(int), vol.Range(min=30, max=300)),
        vol.Optional("comparison_lead_seconds", default=60): vol.All(vol.Coerce(int), vol.Range(min=10, max=180)),
        vol.Optional("journal_mb", default=16): vol.All(vol.Coerce(int), vol.Range(min=2, max=64)),
    }),
}, extra=vol.ALLOW_EXTRA)


class Runtime:
    def __init__(self, hass: HomeAssistant, config: dict, engine: Observer, journal: Journal):
        self.hass, self.config, self.engine, self.journal = hass, config, engine, journal
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.worker = None
        self.unsubs = []
        self.closing = False
        self.capture_gap = False
        self.dropped = 0
        self.storage_error = None
        self.last_saved_at = 0.0
        self.last_idle_at = 0.0
        self.last_captured_at = None
        self.last_written_at = None
        self.cached_report = engine.report()

    def _read(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable") or state.attributes.get("restored"):
            return None, state
        return state.state, state

    @callback
    def snapshot(self, reason: str) -> dict:
        now = dt_util.utcnow().timestamp()
        sample = {"t": now, "schema": 1, "version": VERSION, "reason": reason,
                  "revision": self.config["site_revision"], "ages": {}, "zones": {},
                  "reported_at": {}, "gap": self.capture_gap}
        self.capture_gap = False
        for key, entity_id in INPUTS.items():
            raw, state = self._read(entity_id)
            if key in ("gas", "pump", "relay", "master", "service", "policy", "boost", "dhw", "dhw_recharging", "dhw_valve"):
                value = True if raw == "on" else False if raw == "off" else None
            elif key == "mode":
                value = raw
            else:
                value = number(raw)
            sample[key] = value
            reported = state.last_reported.timestamp() if state else None
            sample["reported_at"][key] = reported
            if key in ("block", "flow"):
                # last_reported is receipt by HA, not a manufacturer's freshness guarantee.
                sample["ages"][key] = now - reported if raw is not None and reported else None
                if state and state.attributes.get("unit_of_measurement") not in ("°C", "C"):
                    sample[key] = None
            if key == "block":
                sample["block_reported_at"] = reported
        windows = self.hass.states.get("sensor.heating_schedule_windows")
        active_helpers = windows.attributes.get("active_helpers", []) if windows and windows.state == "ready" else None
        for zone in ZONES:
            raw, state = self._read(f"climate.{zone}")
            attrs = state.attributes if state else {}
            row = {"state": raw, "pi": number(attrs.get("pi_heating_demand")),
                   "target": number(attrs.get("temperature")),
                   "room": number(attrs.get("current_temperature")),
                   "action": attrs.get("hvac_action"),
                   "reported_at": state.last_reported.timestamp() if state else None,
                   "updated_at": state.last_updated.timestamp() if state else None,
                   "in_window": f"input_boolean.{zone}_schedule_active" in active_helpers if active_helpers is not None else None}
            for key, entity_id in {
                "comfort": f"input_number.{zone}_last_comfort",
                "calendar": f"input_boolean.schedule_enable_{zone}",
                "manual": f"input_boolean.{zone}_manual_override",
                "manual_type": f"input_select.{zone}_manual_override_type",
                "timer": f"timer.{zone}_manual_override",
            }.items():
                row[key] = self._read(entity_id)[0]
            sample["zones"][zone] = row
        return sample

    @callback
    def enqueue(self, reason="interval"):
        if self.closing:
            return
        sample = self.snapshot(reason)
        # Persist idle health less often; critical changes are always captured.
        if reason == "interval" and not (sample.get("gas") or sample.get("relay") or sample.get("pump") or self.engine.data["active"]):
            if sample["t"] - self.last_idle_at < 60:
                self.capture_gap |= sample["gap"]
                return
            self.last_idle_at = sample["t"]
        try:
            self.queue.put_nowait(sample)
            self.last_captured_at = sample["t"]
        except asyncio.QueueFull:
            self.dropped += 1
            self.capture_gap = True

    @callback
    def _changed(self, event):
        self.enqueue(event.data["entity_id"])

    @callback
    def _interval(self, now):
        self.enqueue()

    async def start(self):
        self.worker = self.hass.async_create_background_task(self._consume(), DOMAIN)
        self.unsubs.append(async_track_state_change_event(self.hass, CRITICAL, self._changed))
        self.unsubs.append(async_track_time_interval(self.hass, self._interval, timedelta(seconds=self.config["sample_seconds"])))
        self.unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.stop))
        self.enqueue("startup")

    async def _consume(self):
        while True:
            sample = await self.queue.get()
            events = []
            try:
                if sample is None:
                    return
                events = self.engine.feed(sample)
                checkpoint = bool(events) or sample["t"] - self.last_saved_at >= 60
                if checkpoint:
                    self.cached_report = self.engine.report()
                await self.hass.async_add_executor_job(
                    self.journal.write, sample, events, deepcopy(self.engine.data),
                    deepcopy(self.cached_report), checkpoint,
                )
                self.last_written_at = sample["t"]
                if checkpoint:
                    self.last_saved_at = sample["t"]
                self.storage_error = None
            except Exception as error:  # Diagnostic failure must not take down heating.
                self.storage_error = type(error).__name__
                self.capture_gap = True
                if self.engine.data["active"]:
                    self.engine.data["active"]["bad_before_fault"] = True
                if events:
                    for episode in self.engine.data["episodes"]:
                        if any(e.get("id") == episode["id"] for e in events):
                            episode["eligible"] = False
                            episode["outcome"] = "censored_storage"
                    self.cached_report = self.engine.report()
                _LOGGER.exception("Heating observer could not record an observation")
            finally:
                self.queue.task_done()
                async_dispatcher_send(self.hass, SIGNAL)

    async def stop(self, event=None):
        if self.closing:
            return
        self.closing = True
        for unsub in self.unsubs:
            unsub()
        self.unsubs.clear()
        await self.queue.join()
        events = self.engine.stop()
        try:
            await self.hass.async_add_executor_job(
                self.journal.write, None, events, deepcopy(self.engine.data), self.engine.report(), True,
            )
        except Exception:
            _LOGGER.exception("Heating observer checkpoint at shutdown failed")
        await self.queue.put(None)
        if self.worker:
            await self.worker


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if DOMAIN not in config:
        return True
    cfg = CONFIG_SCHEMA(config)[DOMAIN]
    journal = Journal(Path(hass.config.path("heating_observer_data")), cfg["site_revision"],
                      max_bytes=cfg["journal_mb"] * 1024 * 1024)
    try:
        saved = await hass.async_add_executor_job(journal.load)
    except (OSError, ValueError):
        # Preserve corrupt evidence; do not silently replace it with a fresh model.
        _LOGGER.exception("Heating observer checkpoint cannot be loaded; observer disabled")
        return False
    try:
        engine = Observer(cfg["site_revision"], saved, telemetry_gap=cfg["telemetry_gap_seconds"],
                          lead_budget=cfg["comparison_lead_seconds"])
    except (ValueError, KeyError, TypeError):
        _LOGGER.exception("Heating observer model is incompatible; keep it and select a new site_revision")
        return False
    runtime = Runtime(hass, cfg, engine, journal)
    hass.data[DOMAIN] = runtime
    await runtime.start()
    await discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    return True
