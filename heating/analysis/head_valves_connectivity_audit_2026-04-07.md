# Audit dostupnosti topných hlavic (2026-04-07)

## 1) Entity související s hlavicemi

### Climate entity (hlavice)
- `climate.sklep_michal`
- `climate.prizemi_michal`
- `climate.prizemi_chodba_zachod`
- `climate.1p_jidelna`
- `climate.1p_kuchyn`
- `climate.1p_koupelna`
- `climate.1p_chodba`
- `climate.2p_mama`

Definované skupinou `group.topne_zony`. 

### Související entity používané v logice dostupnosti
- `binary_sensor.heating_core_entities_available`
- `binary_sensor.heating_helpers_all_available`
- `sensor.zona_*_demand` (8×, jedna per zóna)
- UI templaty teplot z `climate.*` a jeden externí senzor `sensor.tz3000_jidelna_teplota`

### Co v projektu NENÍ (pro hlavice)
- Žádné explicitní `battery`/`linkquality`/`lqi`/`rssi` entity pro hlavice.
- Žádný explicitní error-code sensor z hlavic (např. `*_error`).

## 2) Existující kontrola dostupnosti / výpadků / neaktualizace

### A) Přímý watchdog konektivity hlavic
Soubor: `heating/control/watchdog_connectivity.yaml`

Mechanika:
- Trigger každých 30 minut.
- Prochází pevný seznam 8 hlavic (`for_each`).
- Vyhodnocuje dvě podmínky závady:
  1. `states(ent) in ['unavailable', 'unknown']`
  2. `now() - last_updated > 7200` (2 hodiny)
- Pokud je některá true:
  - push notifikace na `notify.mobile_app_sm_s938b`
  - záznam do logbooku s `state` a `last_updated`.

=> Tohle je explicitní kontrola **dostupnosti** i **neaktualizujících se dat**.

### B) Agregovaná dostupnost klíčových entit + fail-safe
Soubor: `heating/control/reliability_failsafe.yaml`

Mechanika:
- `binary_sensor.heating_core_entities_available` je ON jen pokud všechny klíčové entity nejsou `unknown/unavailable/''`.
- V seznamu jsou všechny hlavice + `switch.kotel_rele_spinac`.
- Automatizace `heating_failsafe_entities_unavailable`:
  - Trigger: když `binary_sensor.heating_core_entities_available` přejde do OFF na více než 5 minut.
  - Akce:
    - přepne režim na `Eco`
    - vypne `input_boolean.boost_now`
    - vypne kotel `switch.kotel_rele_spinac`
    - logbook + persistent notification.

=> Tohle je systémová reakce na **výpadek dostupnosti** (včetně hlavic).

### C) Ošetření „stará data“ přímo v zónových demand senzorech
Soubory: `heating/core/zone_*.yaml` (8 zón)

Mechanika:
- `availability`: klimatu nesmí být `unavailable`.
- `state`:
  - spočte `age_sec = now - climate.last_updated`
  - pokud `age_sec > 120*60` (2 hodiny), vrátí `0`
  - jinak čte `pi_heating_demand` z atributu climate.

=> Tohle není alerting, ale bezpečné degradační chování při **neaktualizovaných datech**.

### D) UI availability guard (vizualizační vrstva)
Soubor: `heating/ui/dashboards/heating_templates.yaml`

Mechanika:
- Teplotní template senzory mají `availability` kontrolu na `climate.* != unavailable`.
- U jídelny je zdroj externí Zigbee teplota `sensor.tz3000_jidelna_teplota` s vlastním availability guardem.

=> Pouze ochrana UI senzorů, ne aktivní watchdog.

### E) Ošetření nedostupného externího senzoru pro Danfoss
Soubor: `blueprints/automation/heating/danfoss_external_sensor.yaml`

Mechanika:
- Když `raw` teplota je `unavailable/unknown/none/NaN` nebo mimo rozsah, hodnota se do hlavice neposílá.
- Jen logbook záznam o nevalidní/nedostupné hodnotě.

=> Řeší kvalitu vstupu externího senzoru, ne přímo online stav climate entity.

## 3) Konkrétní automations/template senzory, které to řeší

1. `automation.heating_watchdog_connectivity` (periodický watchdog hlavic).
2. `binary_sensor.heating_core_entities_available` + `automation.heating_failsafe_entities_unavailable`.
3. 8× `sensor.zona_*_demand` (stale-data guard přes `last_updated`).
4. UI templaty teplot (`availability`) + Danfoss external sensor blueprint validation.

## 4) Shrnutí stavu

- Kontrola dostupnosti hlavic v projektu **existuje** a je realizována dvěma vrstvami:
  - periodický watchdog (detekce + notifikace),
  - fail-safe režim (Eco + vypnutí kotle při delším výpadku).
- Kontrola neaktualizujících se dat také **existuje**:
  - watchdog (`last_updated > 2h`) + zónové demand senzory (fallback na 0).
- Explicitní kontrola diagnostik typu `battery`, `linkquality`, `error_code` pro hlavice v YAML konfiguraci projektu **nenalezena**.


## 5) Upřesnění: co znamená „2 hodiny beze změny“

Watchdog v projektu nekontroluje změnu **hodnoty teploty**, ale stáří `last_updated` celé `climate.*` entity.

Prakticky:
- Pokud je teplota 2 hodiny stejná, ale zařízení/integrace průběžně publikuje update (state/attributes), `last_updated` se obnovuje a watchdog chybu nehlásí.
- Pokud 2+ hodiny nepřijde žádný update entity (`last_updated` je starší než 7200 s), watchdog chybu nahlásí, i kdyby poslední naměřená teplota byla „validní“.

Tj. rozhoduje komunikační čerstvost entity, ne to, zda se numerická teplota změnila.

## 6) Je to nejlepší řešení?

Ne. Je to funkční minimum, ale ne „nejlepší možné“ pro provoz.

### Co je dnes dobré
- Máte 2 vrstvy ochrany: detekce (`watchdog_connectivity`) + reakce (`failsafe_entities_unavailable`).
- Máte stale guard v `zona_*_demand`, takže při výpadku se poptávka přirozeně stáhne na 0.

### Slabiny současného stavu
1. Watchdog běží jen po 30 minutách (detekce může být pomalá).
2. Hlídá jen `climate.*` stav + `last_updated`; nehlídá přímo Zigbee kvalitu (LQI/RSSI), battery low, případné error atributy.
3. `last_updated` může být ovlivněné i změnou jiného atributu; není to čistě „teplotní heartbeat“.

### Konkrétní lepší varianta (doplněk)
- Přidat **per-zónový binary_sensor „alive“** s timeoutem 90 minut.
- Přidat **agregovaný sensor počtu nealive hlavic**.
- Přidat automatizaci s kratším cyklem (např. 10 minut) + eskalací (notifikace po 10 min, fail-safe po 30 min).
- Pokud máte z integrace battery/LQI entity, přidat je do stejného watchdogu.

```yaml
template:
  - binary_sensor:
      - name: "heating_valve_sklep_michal_alive"
        unique_id: heating_valve_sklep_michal_alive
        device_class: connectivity
        state: >-
          {% set e = states['climate.sklep_michal'] %}
          {% set ts = as_timestamp(e.last_updated) if e is not none else 0 %}
          {{ states('climate.sklep_michal') not in ['unknown','unavailable','']
             and (as_timestamp(now()) - ts) < 5400 }}

      - name: "heating_valve_prizemi_michal_alive"
        unique_id: heating_valve_prizemi_michal_alive
        device_class: connectivity
        state: >-
          {% set e = states['climate.prizemi_michal'] %}
          {% set ts = as_timestamp(e.last_updated) if e is not none else 0 %}
          {{ states('climate.prizemi_michal') not in ['unknown','unavailable','']
             and (as_timestamp(now()) - ts) < 5400 }}

  - sensor:
      - name: "heating_valves_unhealthy_count"
        unique_id: heating_valves_unhealthy_count
        state: >-
          {% set lst = [
            'binary_sensor.heating_valve_sklep_michal_alive',
            'binary_sensor.heating_valve_prizemi_michal_alive'
          ] %}
          {{ lst | map('states') | select('eq','off') | list | count }}

automation:
  - id: heating_watchdog_valves_unhealthy_escalation
    alias: "Heating Watchdog – unhealthy hlavice (eskalace)"
    mode: single
    triggers:
      - trigger: state
        entity_id: sensor.heating_valves_unhealthy_count
        to: ~
      - trigger: time_pattern
        minutes: "/10"
    conditions:
      - condition: template
        value_template: "{{ states('sensor.heating_valves_unhealthy_count')|int(0) > 0 }}"
    actions:
      - action: persistent_notification.create
        data:
          notification_id: heating_valves_unhealthy
          title: "Heating Watchdog"
          message: >-
            ⚠️ Nedostupné/neživé hlavice: {{ states('sensor.heating_valves_unhealthy_count') }}
      - choose:
          - conditions:
              - condition: template
                value_template: >-
                  {{ states('sensor.heating_valves_unhealthy_count')|int(0) >= 2 }}
            sequence:
              - action: input_select.select_option
                target:
                  entity_id: input_select.topny_rezim
                data:
                  option: "Eco"
```

Pozn.: výše je minimální ukázka (2 zóny). V produkci to rozšiřte na všech 8 hlavic.
