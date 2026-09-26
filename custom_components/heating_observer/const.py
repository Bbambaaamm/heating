"""Project-specific input mapping. None of these entities is written to."""

DOMAIN = "heating_observer"
VERSION = "0.2.0"
SIGNAL = "heating_observer_updated"
ZONES = (
    "sklep_michal", "prizemi_michal", "prizemi_chodba_zachod", "1p_jidelna",
    "1p_kuchyn", "1p_koupelna", "1p_chodba", "2p_mama",
)
INPUTS = {
    "block": "sensor.boiler_heatblock",
    "flow": "sensor.boiler_curflowtemp",
    "power": "sensor.boiler_curburnpow",
    "code": "sensor.boiler_servicecodenumber",
    "gas": "binary_sensor.boiler_burngas",
    "pump": "binary_sensor.boiler_heatingpump",
    "dhw": "binary_sensor.boiler_wwcharging",
    "dhw_recharging": "binary_sensor.boiler_wwrecharging",
    "dhw_valve": "binary_sensor.boiler_ww3wayvalve",
    "relay": "switch.kotel_rele_spinac",
    "master": "input_boolean.topny_system_enable",
    "service": "input_boolean.heating_service_mode",
    "mode": "input_select.topny_rezim",
    "policy": "binary_sensor.kotel_should_be_on",
    "active_zones": "sensor.kotel_aktivni_zony_pocet",
    "average_demand": "sensor.kotel_poptavka_prumer",
    "minimum_zones": "sensor.kotel_effective_min_active_zones",
    "minimum_demand": "sensor.kotel_effective_min_avg_demand_pct",
    "eco": "input_number.eco_temp_default",
    "boost": "binary_sensor.kotel_boost_active",
}
CRITICAL = tuple(INPUTS[key] for key in ("block", "flow", "code", "gas", "pump", "relay", "master", "service", "mode", "dhw", "dhw_recharging", "dhw_valve"))
FAULTS = {2964, 2965, 2966, 2967}
