# Behaviorální audit vytápění (Home Assistant)

Datum auditu: **2026-04-06**  
Scope: režimy Auto/Eco/Boost/Off, smart zone schedule blueprint, manuální override, startup chování.

## 1) Kritické nálezy (reálné failure scénáře)

### A. Race condition při přechodu Boost → Auto
- `mode_auto.yaml` zruší Boost a **okamžitě** triggeruje všechny `_bp` automace.
- `smart_zone_schedule.yaml` má ochranu `Boost aktivní – rozvrh nepřepisuje setpoint`.
- Pokud se `binary_sensor.kotel_boost_active` ještě nepřepočítá na `off`, scheduler krok přeskočí.

**Reálný dopad:** zóny zůstanou dočasně na boostových teplotách i po přepnutí do Auto (dokud nepřijde další trigger).

---

### B. „Visící“ timed manual override po restartu HA
- Override je aktivní přes `input_boolean.*_manual_override`.
- Typ `Časovač` se opírá o stav `timer.*_manual_override`.
- Po restartu může být boolean `on`, ale timer už `idle` (nebo se neobnoví jako `active`).

**Reálný dopad:**  
- logika mezi moduly je nekonzistentní (scheduler, boost, watchdog vyhodnocují override různě),
- zóna může být omylem blokovaná pro boost a/nebo se chová nečekaně.

---

### C. Boost přepisuje „neúčinný“ manuál (nebo naopak manuál blokuje Boost navždy)
- V `mode_boost.yaml` byl dosud check jen `manual == on`.
- Scheduler blueprint ale používá jemnější logiku: override je účinný jen když:
  - typ = `Do další změny rozvrhu`, nebo
  - typ = `Časovač` a timer je `active`.

**Reálný dopad:** zóna může být **nesprávně přeskočena** při Boost, i když timed override už fakticky neběží.

---

### D. Zbytečné duplicity zápisu setpointu v Boost
- Boost nastavoval cílovou teplotu bez kontroly rozdílu proti aktuální hodnotě.

**Reálný dopad:** vyšší počet servisních volání `climate.set_temperature`, zbytečný spam logů a potenciálně vyšší provoz Zigbee sítě.

## 2) Provedené opravy v YAML

### Oprava 1 — synchronizace při Auto návratu
Soubor: `heating/control/mode_auto.yaml`

- Přidáno `wait_template` na `binary_sensor.kotel_boost_active == off` (timeout 5 s),
- logbook zpráva explicitně hlásí timeout.

Tím se snižuje závod mezi výpočtem boost stavu a re-aplikací scheduleru.

---

### Oprava 2 — sjednocení vyhodnocení manuálu v Boost logice
Soubor: `heating/control/mode_boost.yaml`

- Každá zóna nově obsahuje:
  - `timer.*_manual_override`
  - `input_select.*_manual_override_type`
- Nová proměnná `effective_manual` kopíruje sémantiku scheduleru:
  - `Do další změny rozvrhu` => účinný override
  - `Časovač` => účinný jen při `timer == active`
- Boost teploty se aplikují jen při `not effective_manual`.

---

### Oprava 3 — startup reconcile timed override
Soubor: `heating/schedule/automation/startup/manual_override_startup_reconcile.yaml`

- Nová startup automatizace:
  - po 15 s od startu projde všechny zóny,
  - pokud je override `on` + typ `Časovač` + timer není `active`, override vypne,
  - zapíše nápravnou událost do logbooku.

Tím se odstraní „visící“ stavy po restartu.

---

### Oprava 4 — omezení duplicitních setpoint zápisů v Boost
Soubor: `heating/control/mode_boost.yaml`

- před `climate.set_temperature` přidána kontrola rozdílu `abs(current-target) > 0.1`,
- před zápisem je explicitně nastaven `hvac_mode: heat`.

## 3) Doporučení (další krok, zatím neimplementováno)

1. **Centralizovat seznam zón** (jeden `template`/`group` + mapa helperů), aby se snížilo riziko nekonzistence mezi soubory (`mode_boost`, watchdog, startup reconcile, UI sync).
2. Přidat **meta-senzor diagnostiky** (počet konfliktů zápisu setpointu za 5 min; počet timeoutů při čekání na boost-off).
3. Zavést **jednotné priority** v komentáři i kódu:
   1) Off blokace  
   2) účinný manual override  
   3) Boost  
   4) Eco/Auto + scheduler.

