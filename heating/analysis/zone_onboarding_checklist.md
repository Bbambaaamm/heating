# Checklist přidání nové topné zóny

Tento checklist je záměrně konzervativní: cílem je zabránit tichým chybám při přidání nové zóny do více seznamových sekcí.

## 1) Entita zóny a helpery
- [ ] `climate.<zona>` existuje a má očekávané `min_temp`/`max_temp`.
- [ ] Existuje `input_number.<zona>_last_comfort`.
- [ ] Existuje `input_boolean.<zona>_schedule_active`.
- [ ] Existuje `input_boolean.<zona>_manual_override`.
- [ ] Existuje `input_select.<zona>_manual_override_type`.
- [ ] Existuje `timer.<zona>_manual_override`.

## 2) Kontrolní seznam souborů
- [ ] `heating/control/refactor_mode_schedule_override.yaml`
  - [ ] zóna je v `trigger.entity_id` seznamech (`last_comfort`, `schedule_active`, `manual_override`, `manual_override_type`, `timer`).
  - [ ] zóna je ve `variables.zones` mapě.
- [ ] `heating/control/mode_boost.yaml`
  - [ ] zóna je ve `variables.zones` mapě pro Boost ON.
- [ ] `heating/control/watchdog_manual_override.yaml`
  - [ ] zóna je v obou seznamech `repeat.for_each` (12h i 24h watchdog).
- [ ] `heating/schedule/automation/startup/manual_override_startup_reconcile.yaml`
  - [ ] zóna je v seznamu helperů `input_boolean.<zona>_manual_override` pro startup reconcile.
- [ ] `automations.yaml`
  - [ ] existuje blueprint instance se `schedule_enable: input_boolean.schedule_enable_<zona>`.
  - [ ] v blueprint inputech jsou konzistentně i helpery `last_comfort`, `scheduler_entity`, `manual_override_boolean`, `manual_override_type`, `manual_override_timer` pro stejný slug zóny.
- [ ] `heating/core/groups.yaml`
  - [ ] `climate.<zona>` je v `group.heating_zones` (pro centrální přehled a navazující automace).
- [ ] `heating/schedule/preferences/helpers/scheduler_booleans.yaml`
  - [ ] existuje `input_boolean.<zona>_schedule_active` pro zónu (konzistence helperů plánování).
- [ ] `heating/core/zone_<zona>.yaml`
  - [ ] soubor obsahuje správnou entitu `climate.<zona>` (nejen že existuje).
- [ ] `heating/schedule/preferences/helpers/schedule_helpers_<zona>.yaml`
  - [ ] existuje helper soubor pro zónu se schedule preferencemi.
- [ ] `heating/schedule/preferences/prefs/zone_<zona>_prefs.yaml`
  - [ ] existuje prefs soubor zóny pro časové preference.

## 3) Rychlá validace konzistence
Spusť:

```bash
python3 scripts/validate_zone_list_consistency.py
```

Skript ověří, že slugy zón jsou konzistentní mezi klíčovými seznamy (dispatch/boost/watchdog/startup reconcile/blueprint schedule helpery + navázané blueprint helpery/group.heating_zones + scheduler_booleans schedule helpery), současně zkontroluje existenci navazujících souborů `heating/core/zone_<zona>.yaml`, `heating/schedule/preferences/helpers/schedule_helpers_<zona>.yaml`, `heating/schedule/preferences/prefs/zone_<zona>_prefs.yaml` a navíc ověří, že v `heating/core/zone_<zona>.yaml` je skutečně použita odpovídající entita `climate.<zona>`. Pokud vrátí nenulový exit code, je potřeba doplnit chybějící zóny/soubory nebo opravit nekonzistenci entity.

## 4) Minimální smoke test po změně
- [ ] Auto → Boost → Auto a ověřit návrat setpointů.
- [ ] Manuální override zóny + expirační logika.
- [ ] Ověřit, že se zóna zapisuje do logbooku bez chybových hlášek.
