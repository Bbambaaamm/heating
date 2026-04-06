# Architektonické zhodnocení řízení vytápění (kritické)

Datum: 2026-04-06

## 1) Duplicitní logika

1. **Výpočet efektivního manuálního override je duplikovaný**
   - Ve blueprintu `smart_zone_schedule.yaml` (`override_should_apply`).
   - V `mode_boost.yaml` je stejná podmínka znovu pro každou zónu (`effective_manual`).
   - Riziko: drift pravidel (jedno místo opravíš, druhé zapomeneš).

2. **Nastavení teploty + clamp + "neměň pokud rozdíl < 0.1" se opakuje**
   - V blueprintu pro běžný schedule.
   - V boost automaci při startu boostu.
   - Udržovatelnost je slabá: stejný patch musíš dělat na více místech.

3. **Rozhodnutí o prioritě (Boost vs Schedule vs Override) je rozlezlé**
   - Část priority je v blueprintu (`stop: Boost aktivní` / `override priority`).
   - Část priority je v režimových automacích (`mode_auto`, `mode_boost`).
   - To je typický symptom „distributed policy“ bez jednoho rozhodovacího centra.

## 2) Zbytečná složitost

1. **Příliš mnoho triggerů v jednom blueprintu**
   - Blueprint řeší současně: schedule, ruční zásahy, režimy, antispam, override lifecycle.
   - Důsledek: těžké mentálně ověřit, jestli každá změna vede ke správné akci.

2. **Dynamické spouštění všech `_bp` automací regexem**
   - Praktické, ale křehké: naming konvence je implicitní contract.
   - Větší jistotu dává explicitní dispatch seznam.

3. **Smíchání orchestrace a exekuce**
   - Stejné soubory dělají „co chci“ i „jak přesně to nastavím na hlavici“.
   - Čistší je oddělit rozhodování cíle od jedné centrální execute vrstvy.

## 3) Kde centralizovat řízení

1. **Central Rule Engine (jedno místo pro prioritu)**
   - Priorita: `off > override > boost > eco > auto(schedule)`.
   - Výstup: `target_temp` + `reason` pro každou zónu.

2. **Central Apply Script (jedno místo pro clamp + set_temperature + log)**
   - `script.heating_apply_zone_target(climate_entity, requested_temp, reason)`.
   - Všechny automace volají tento skript, ne `climate.set_temperature` napřímo.

3. **Blueprint zjednodušit na "ingest layer"**
   - Blueprinty jen sbírají vstupy z UI/scheduleru do helperů.
   - Neřeší velkou část globální priority.

## 4) Doporučené rozdělení logiky

- **mode/**
  - Globální intent (`off/eco/auto/boost`), žádné per-zóna teplotní akce.
- **schedule/**
  - Pouze informace `in_window` pro zónu + případně sync po restartu.
- **override/**
  - Lifecycle manuálu (start, timer, clear on schedule edge).
- **dispatch/**
  - Vypočte pro každou zónu cílovou teplotu dle priority.
- **actuation/**
  - Jediný skript pro fyzické nastavení hlavice.

## 5) Konkrétní refactoring (sjednocený a zavedený)

Refaktor je zaveden v souboru `heating/control/refactor_mode_schedule_override.yaml` a obsahuje:

1. **Feature flag**
   - `input_boolean.heating_central_dispatch_enable` pro bezpečný cutover.

2. **Central Rule Engine**
   - `sensor.heating_global_intent` (`off/eco/auto/boost`).
   - Priorita: `off > override > boost > eco > auto(schedule)`.

3. **Central Apply**
   - `script.heating_apply_zone_target` (clamp + set + log).

4. **Fail-safe**
   - `binary_sensor.heating_dispatch_inputs_available` + fallback do Eco při nedostupných vstupech.

5. **Plný rozsah zón**
   - Dispatch pokrývá všechny topné zóny (ne jen pilotní subset).

## 6) Stav po opravách

Krátká odpověď: **ano, architektonické opravy jsou už propsané i do samotných YAML souborů**.

Konkrétně:
- `mode_auto` a `mode_boost` respektují feature flag a při ON triggerují central dispatch.
- Blueprint `smart_zone_schedule` je při ON v ingest režimu (bez vlastní actuation), takže nedochází k přetahování setpointů.
- Přidán fail-safe fallback do Eco při degradaci klíčových vstupů.

## 7) Co ještě hlídat v provozu (už ne architektonický dluh, ale provozní validace)

- Ověřit chování při restartu během aktivního Boostu.
- Ověřit edge-cases manuálního override (timer / do další změny rozvrhu).
- Ověřit dostupnost všech helperů po restartu HA.
