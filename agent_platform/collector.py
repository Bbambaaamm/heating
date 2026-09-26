"""Read-only normalization of Home Assistant state snapshots.

This module intentionally has no HTTP/WebSocket client and no service-call
method. A transport may inject states obtained through get_states/subscription.
The command policy below rejects actuator-capable WebSocket message types.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .model import HeatingSnapshot, ZoneState

ZONES = (
    "sklep_michal",
    "prizemi_michal",
    "prizemi_chodba_zachod",
    "1p_jidelna",
    "1p_kuchyn",
    "1p_koupelna",
    "1p_chodba",
    "2p_mama",
)


@dataclass(frozen=True)
class EntityMap:
    block: str = "sensor.boiler_heatblock"
    flow: str = "sensor.boiler_curflowtemp"
    power: str = "sensor.boiler_curburnpow"
    code: str = "sensor.boiler_servicecodenumber"
    gas: str = "binary_sensor.boiler_burngas"
    pump: str = "binary_sensor.boiler_heatingpump"
    dhw: str = "binary_sensor.boiler_wwcharging"
    dhw_recharging: str = "binary_sensor.boiler_wwrecharging"
    dhw_valve: str = "binary_sensor.boiler_ww3wayvalve"
    relay: str = "switch.kotel_rele_spinac"
    master: str = "input_boolean.topny_system_enable"
    service: str = "input_boolean.heating_service_mode"
    mode: str = "input_select.topny_rezim"
    zones: tuple[str, ...] = ZONES


class ReadOnlyHaCommandPolicy:
    """Fail closed when a future transport attempts a write-capable message."""

    ALLOWED_MESSAGE_TYPES = frozenset({
        "auth",
        "get_states",
        "subscribe_events",
        "unsubscribe_events",
        "ping",
    })

    @classmethod
    def assert_allowed(cls, message: Mapping[str, Any]) -> None:
        message_type = message.get("type")
        if message_type not in cls.ALLOWED_MESSAGE_TYPES:
            raise PermissionError(f"Home Assistant command type is not read-only: {message_type!r}")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _bool_state(value: Any) -> bool | None:
    if value == "on":
        return True
    if value == "off":
        return False
    return None


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class ReadOnlyCollector:
    def __init__(
        self,
        site_revision: str,
        *,
        entities: EntityMap | None = None,
        stale_seconds: float = 45.0,
    ):
        if not site_revision:
            raise ValueError("site_revision is required")
        self.site_revision = site_revision
        self.entities = entities or EntityMap()
        self.stale_seconds = stale_seconds

    @staticmethod
    def _item(states: Mapping[str, Mapping[str, Any]], entity_id: str) -> Mapping[str, Any] | None:
        item = states.get(entity_id)
        return item if isinstance(item, Mapping) else None

    def _number_state(
        self,
        states: Mapping[str, Mapping[str, Any]],
        entity_id: str,
        captured_at: float,
        quality: list[str],
        *,
        stale_check: bool = False,
    ) -> float | None:
        item = self._item(states, entity_id)
        if item is None:
            quality.append(f"missing:{entity_id}")
            return None
        value = _number(item.get("state"))
        if value is None:
            quality.append(f"invalid:{entity_id}")
        if stale_check:
            reported = _timestamp(item.get("last_reported") or item.get("last_updated"))
            if reported is None:
                quality.append(f"unknown_age:{entity_id}")
            elif captured_at - reported < 0 or captured_at - reported > self.stale_seconds:
                quality.append(f"stale:{entity_id}")
        return value

    def _bool_entity(
        self,
        states: Mapping[str, Mapping[str, Any]],
        entity_id: str,
        quality: list[str],
    ) -> bool | None:
        item = self._item(states, entity_id)
        if item is None:
            quality.append(f"missing:{entity_id}")
            return None
        value = _bool_state(item.get("state"))
        if value is None:
            quality.append(f"unknown:{entity_id}")
        return value

    def collect(
        self,
        states: Mapping[str, Mapping[str, Any]],
        *,
        captured_at: float,
    ) -> HeatingSnapshot:
        quality: list[str] = []
        e = self.entities

        block = self._number_state(states, e.block, captured_at, quality, stale_check=True)
        flow = self._number_state(states, e.flow, captured_at, quality, stale_check=True)
        power = self._number_state(states, e.power, captured_at, quality)
        raw_code = self._number_state(states, e.code, captured_at, quality)
        code = int(raw_code) if raw_code is not None and raw_code.is_integer() else None
        if raw_code is not None and code is None:
            quality.append(f"invalid_integer:{e.code}")

        gas = self._bool_entity(states, e.gas, quality)
        pump = self._bool_entity(states, e.pump, quality)
        relay = self._bool_entity(states, e.relay, quality)
        master = self._bool_entity(states, e.master, quality)
        service = self._bool_entity(states, e.service, quality)
        dhw = self._bool_entity(states, e.dhw, quality)
        dhw_recharging = self._bool_entity(states, e.dhw_recharging, quality)
        dhw_valve = self._bool_entity(states, e.dhw_valve, quality)

        mode_item = self._item(states, e.mode)
        mode = str(mode_item.get("state")) if mode_item and mode_item.get("state") not in (None, "unknown", "unavailable") else None
        if mode is None:
            quality.append(f"unknown:{e.mode}")

        zones: dict[str, ZoneState] = {}
        for zone_name in e.zones:
            entity_id = f"climate.{zone_name}"
            item = self._item(states, entity_id)
            if item is None:
                quality.append(f"missing:{entity_id}")
                zones[zone_name] = ZoneState(entity_id, None, None, None, None)
                continue
            attributes = item.get("attributes") if isinstance(item.get("attributes"), Mapping) else {}
            hvac_state = item.get("state")
            if hvac_state not in ("heat", "off"):
                quality.append(f"unknown:{entity_id}")
                hvac_state = None
            pi = _number(attributes.get("pi_heating_demand"))
            if pi is None or not 0 <= pi <= 100:
                quality.append(f"invalid_pi:{entity_id}")
                pi = None
            zones[zone_name] = ZoneState(
                entity_id=entity_id,
                hvac_state=hvac_state,
                current_temperature=_number(attributes.get("current_temperature")),
                target_temperature=_number(attributes.get("temperature")),
                pi_demand=pi,
            )

        if any(value is True for value in (dhw, dhw_recharging, dhw_valve)):
            quality.append("dhw_context")

        return HeatingSnapshot(
            timestamp=captured_at,
            site_revision=self.site_revision,
            relay=relay,
            gas=gas,
            pump=pump,
            master=master,
            service=service,
            mode=mode,
            dhw=dhw,
            dhw_recharging=dhw_recharging,
            dhw_valve=dhw_valve,
            boiler_block_temperature=block,
            flow_temperature=flow,
            burner_power=power,
            service_code=code,
            zones=zones,
            quality=tuple(sorted(set(quality))),
        )
