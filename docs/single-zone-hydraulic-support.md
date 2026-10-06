# Single-zone hydraulic support

## Goal

Allow one genuinely heat-requesting zone to obtain boiler heat without removing the
existing hydraulic safety invariant that the boiler policy requires at least two
counted zones.

The historical single-zone test that produced service code 2964 remains the reason
for keeping `sensor.kotel_effective_min_active_zones` at 2. This change does **not**
replace that floor with 1.

## Runtime strategy

When exactly one real zone satisfies the normal boiler zone-demand threshold:

1. Select an eligible auxiliary TRV. Current order:
   - `climate.1p_chodba`
   - `climate.prizemi_chodba_zachod`
2. The candidate must be available, healthy, have its window closed, have schedule
   control enabled and have no manual override.
3. Request 29 °C through the existing central
   `script.heating_apply_zone_target` path.
4. Treat that setpoint report as an internal hydraulic-support report in
   `smart_zone_schedule.yaml`; it must not create manual override or overwrite
   `*_last_comfort`.
5. Require Danfoss device feedback before relaxing any aggregate threshold:
   - `binary_sensor.<zone>_potrebne_teplo = on`
   - `sensor.<zone>_pozadavek_na_vytapeni_pi >= 5`
   - target remains 29 °C
6. Only when needed, temporarily lower
   `input_number.kotel_min_zone_demand_pct` to the confirmed support PI value.
   The original value is saved and restored automatically.
7. The original aggregate must then report at least two counted zones.
   The normal `binary_sensor.kotel_should_be_on` chain and the existing 120 s
   boiler ON delay remain authoritative.
8. If support feedback disappears, the original threshold is restored immediately.
   If support cannot be confirmed within five minutes, the attempt is cancelled and
   a 15-minute cooldown prevents repeated valve forcing.

## Live Home Assistant objects

Storage-managed runtime objects created during the controlled 2026-10-02 test:

- `automation.topeni_hydraulicka_podpora_jedine_zadajici_zony`
- `automation.topeni_hlidani_a_navrat_hydraulicke_podpory`
- `input_select.topeni_hydraulicka_podpurna_zona`
- `input_number.topeni_hydraulicka_podpora_puvodni_min_demand_zony`
- `input_boolean.topeni_hydraulicka_podpora_docasny_pi_prah`
- `timer.topeni_hydraulicka_podpora_cooldown`

These storage-managed objects must not be duplicated by YAML deployment. A follow-up
config-as-code migration should replace them atomically rather than creating a second
controller.

## Fail-closed evidence from 2026-10-02

### Loss-of-support test

A support window temporarily lowered the zone-demand threshold from 70 % to 17 %.
When `Potřebné teplo` fell to OFF:

- the threshold returned 17 -> 70 % in about two seconds,
- `kotel_should_be_on` returned ON -> OFF,
- the relay never had time to switch on.

### Successful supported start

Later, `1p_chodba` confirmed:

- target 29 °C,
- `Potřebné teplo = ON`,
- PI demand 76 %.

At the original 70 % zone-demand threshold the normal aggregate saw two zones, so
no threshold relaxation was needed.

Runtime sequence:

- `kotel_should_be_on = ON`: 10:19:02
- boiler relay ON through the existing control path: 10:22:06
- burner ON: 10:22:20
- service code: 200
- after more than three minutes of burning:
  - flow temperature: about 32.9 °C
  - heat block: about 33.2 °C
  - flow-relief mode: OFF
  - flow-relief lockout: OFF
  - fault recovery pending: OFF

No new 2964 event was observed in this controlled test window.

## Manual-mode regression

Hydraulic support reports at 29 °C are classified as internal reports only while the
same climate entity is recorded as the active hydraulic-support zone. The regression
test verifies that a parentless device report at that target:

- does not turn on `*_manual_override`, and
- does not replace the user's stored comfort temperature.

Normal physical/manual changes remain handled by the existing blueprint logic.
