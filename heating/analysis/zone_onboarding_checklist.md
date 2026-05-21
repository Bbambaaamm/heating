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

## 3) Rychlá validace konzistence
Spusť:

```bash
python3 scripts/validate_zone_list_consistency.py
```

Skript ověří, že slugy zón jsou konzistentní mezi klíčovými seznamy. Pokud vrátí nenulový exit code, je potřeba doplnit chybějící zóny.

## 4) Minimální smoke test po změně
- [ ] Auto → Boost → Auto a ověřit návrat setpointů.
- [ ] Manuální override zóny + expirační logika.
- [ ] Ověřit, že se zóna zapisuje do logbooku bez chybových hlášek.
