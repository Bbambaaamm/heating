"""Bound the HA software latch; never write Bosch parameters or force a relay ON."""
from copy import deepcopy

FLOW = "input_select.heating_flow_state_v4"
LOCK = "input_boolean.heating_flow_relief_lockout"
TIMER = "timer.heating_lockout_limit_10m"
EVENT = "heating_flow_v4_lockout_expired"
MASTER = "input_boolean.topny_system_enable"


def state(entity, value):
    return {"condition": "state", "entity_id": entity, "state": value}


def call(action, entity, **data):
    result = {"action": action, "target": {"entity_id": entity}}
    if data:
        result["data"] = data
    return result


def blocked():
    return {"condition": "or", "conditions": [
        state(LOCK, "on"), state(FLOW, ["EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"])
    ]}


def manager():
    release = [
        call("input_boolean.turn_off", LOCK),
        # Never cancel the in-progress two-batch emergency opening. The periodic
        # owner detects the expired incident after that opening has finished.
        {"if": [{"condition": "or", "conditions": [
            {"condition": "not", "conditions": [state(FLOW, "EMERGENCY_COOLING")]},
            {"condition": "numeric_state", "entity_id": "automation.topeni_flow_relief_pred_restartem_horaku", "attribute": "current", "below": 1},
        ]}], "then": [{"event": EVENT}]},
    ]
    return {
        "id": "heating_lockout_limit_10m_v1",
        "alias": "Topení – automatické zrušení zámku do 10 minut",
        "description": "Deset minut od prvního zablokování. Přechody stavů časovač neprodlužují. Obnovený aktivní časovač pokračuje; při startu/reloadu s blokací a neaktivním časovačem se zámek zruší hned. Vypršení nezávisí na fault-clear. Relé zapíná výhradně původní regulace se všemi svými kontrolami.",
        "mode": "queued", "max": 20, "initial_state": True,
        "trigger": [
            {"trigger": "state", "entity_id": LOCK, "to": "on", "id": "blocked"},
            {"trigger": "state", "entity_id": LOCK, "to": "off", "id": "clear"},
            *[{"trigger": "state", "entity_id": FLOW, "to": s, "id": "blocked"}
              for s in ["EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"]],
            {"trigger": "state", "entity_id": FLOW, "to": "NORMAL", "id": "clear"},
            {"trigger": "event", "event_type": "timer.finished", "event_data": {"entity_id": TIMER}, "id": "expired"},
            {"trigger": "homeassistant", "event": "start", "id": "startup"},
            {"trigger": "event", "event_type": "automation_reloaded", "id": "reload"},
        ],
        "condition": [],
        "action": [{"choose": [
            {"conditions": [{"condition": "trigger", "id": "expired"}, blocked()],
             "sequence": deepcopy(release)},
            {"conditions": [{"condition": "trigger", "id": ["startup", "reload"]}, blocked(),
                            {"condition": "not", "conditions": [state(TIMER, "active")]}],
             "sequence": deepcopy(release)},
            {"conditions": [{"condition": "trigger", "id": "blocked"}, blocked(), state(TIMER, "idle")],
             "sequence": [call("timer.start", TIMER, duration="00:10:00")]},
        ], "default": [{"if": [{"condition": "not", "conditions": [blocked()]}, state(TIMER, "active")],
                         "then": [call("timer.cancel", TIMER)]}]}],
    }


def expiry_handler():
    # Rechecking a cooled expired emergency uses the incident timestamp, not
    # last_changed, which is reset by HA restarts. The event is the exact timer path.
    due = "{{ is_state('timer.heating_lockout_limit_10m', 'idle') and (state_attr('input_datetime.heating_flow_relief_started_at', 'timestamp') | float(0)) > 0 and as_timestamp(now()) - (state_attr('input_datetime.heating_flow_relief_started_at', 'timestamp') | float(0)) >= 600 }}"
    return {
        "alias": "Zámek vždy končí nejpozději po 10 minutách",
        "if": [{"condition": "or", "conditions": [
            {"condition": "trigger", "id": "lockout_expired"},
            {"condition": "and", "conditions": [
                state(FLOW, ["EMERGENCY_COOLING", "RESTORING", "HARD_LOCKOUT"]),
                {"condition": "template", "value_template": due},
            ]},
        ]}],
        "then": [
            call("input_boolean.turn_off", LOCK),
            {"if": [state(FLOW, "EMERGENCY_COOLING"), {"condition": "not", "conditions": [
                {"condition": "and", "conditions": [
                    {"condition": "numeric_state", "entity_id": "sensor.boiler_heatblock", "below": 60},
                    state("binary_sensor.boiler_burngas", "off"),
                    state("sensor.system_bus_status", "connected"),
                ]}
            ]}], "then": [{"stop": "Časový zámek zrušen. Aktivní chlazení pokračuje do vychladnutí; časovač se neobnovuje."}]},
            call("input_boolean.turn_off", "input_boolean.heating_fault_recovery_pending"),
            call("input_boolean.turn_off", "input_boolean.heating_flow_relief_mode"),
            call("input_select.select_option", FLOW, option="NORMAL"),
            {"if": [{"condition": "not", "conditions": [state("input_boolean.heating_restore_verified", "on")]},
                    state("input_boolean.heating_service_mode", "off")],
             "then": [{"action": "script.heating_restore_schedule_after_service", "continue_on_error": True}]},
            {"if": [state("input_boolean.heating_flow_relief_resume_armed", "on"),
                    state("input_boolean.heating_service_mode", "off"),
                    state("input_boolean.heating_restore_verified", "on")],
             "then": [call("input_boolean.turn_on", MASTER)]},
            {"action": "logbook.log", "data": {"name": "Topení – konec časového zámku", "entity_id": LOCK,
                "message": "Softwarový zámek automaticky zrušen po nejvýše 10 minutách. Kotel nebyl resetován ani nuceně zapnut; relé dále řídí běžná regulace s kontrolou teploty, poruchy, EMS a požadavků zón."}, "continue_on_error": True},
            {"stop": "Časový zámek zrušen; pokračuje běžná regulace."},
        ],
    }


def patch_flow(original):
    result = deepcopy(original)
    triggers = "triggers" if "triggers" in result else "trigger"
    actions = "actions" if "actions" in result else "action"
    if any(t.get("id") == "lockout_expired" for t in result[triggers]):
        raise ValueError("Already patched")
    result[triggers].append({"trigger": "event", "event_type": EVENT, "id": "lockout_expired"})
    # Preserve the opening sequence's positions and all native hazard triggers.
    result[actions].insert(4, expiry_handler())
    result["description"] += " Oprava 2026-10-24: softwarový zámek vždy vyprší do 10 minut; aktivní přehřátí/porucha zůstávají nezávislou překážkou normálního startu."
    return result
