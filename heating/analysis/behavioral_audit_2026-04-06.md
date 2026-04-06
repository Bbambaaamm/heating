# Behaviorální audit vytápění (Home Assistant)

Datum auditu: **2026-04-06**  
Scope: režimy Auto/Eco/Boost/Off, smart zone schedule blueprint, manuální override, startup chování, fail-safe mechaniky.

## 1) Kritická analýza spolehlivosti (bez příkras)

### 1.1 Co se stane při restartu během Boostu

**Aktuální stav (rizikový):**
- `boost_until` je perzistentní helper, takže po restartu se Boost často „obnoví“.  
- Ale aplikace boost teplot běží přes trigger `binary_sensor.kotel_boost_active -> on`; pokud po restartu senzor rovnou naběhne na `on` bez hrany, není jisté, že se zóny přenastaví okamžitě.  
- Startup sync dnes spouští `_bp` schedulery, které během aktivního Boostu záměrně nic nepřepisují.

**Důsledek:** systém je funkční „většinou“, ale po restartu během Boostu se můžeš dostat do přechodně nekonzistentního stavu (část zón zůstane na starém setpointu, část se nepřepočte hned).

---

### 1.2 Co se stane při výpadku helperů

**Aktuální stav (slabé místo):**
- Většina templatingu má fallbacky (`float(0)`, `int(60)`), ale to není fail-safe — je to jen „nějaká“ náhradní hodnota.  
- Když helper spadne do `unknown/unavailable`, logika může pokračovat s defaultem, který nebyl provozně zamýšlen (typicky příliš agresivní nebo naopak příliš konzervativní reakce).

**Důsledek:** systém se nezastaví tvrdě, ale může degradovat tiše a dlouho bez jasného alarmu.

---

### 1.3 Chybějící ochrany proti extrémním hodnotám

**Aktuální stav:**
- Boost logika správně clampuje cíle na `min_temp/max_temp` hlavice.  
- Scheduler blueprint ale používá `last_comfort` a `eco_temp` bez systémového clampu vůči fyzickým limitům konkrétní hlavice.

**Důsledek:** při chybné konfiguraci helperů nebo ručním zásahu mimo očekávané meze můžeš do hlavice posílat hodnoty, které nejsou bezpečně normalizované už v automation vrstvě.

---

### 1.4 Co se stane při selhání automation

**Aktuální stav:**
- Existují watchdogy na konektivitu hlavic a dlouhé manual override.  
- Chybí watchdog, který hlídá **zdraví klíčových automací** (disabled/nenaběhla/neloguje trigger). 

**Důsledek:** při „tichém úmrtí“ automation (vypnutá, rozbitá po refaktoru, nespouští se) nemusíš mít okamžitý signál. Zásah přijde až symptomaticky (zima nebo přetopení).


## 2) Návrh fail-safe strategie

Priorita bezpečnosti (doporučené pořadí rozhodnutí):
1. **Master bezpečnost:** když nejsou validní řídicí vstupy, systém přejde do **Eco** (nikoliv Boost, nikoliv „drž poslední“).  
2. **Lokální ochrana zón:** každé nastavení teploty clampnout na fyzické meze hlavice.  
3. **Detekce degradace:** při výpadku helperů / selhání automací okamžitě log + notifikace.  
4. **Samonáprava:** po restartu explicitně re-aplikovat Boost nebo explicitně ukončit neplatný Boost.


## 3) Konkrétní YAML řešení

> Níže je návrh připravený k vložení jako nový soubor, např. `heating/control/reliability_failsafe.yaml`.

```yaml
# YAML 2024.10
# =====================================================================
# Soubor   : config/heating/control/reliability_failsafe.yaml
# Modul    : Topení – reliability fail-safe + watchdog
# Účel     : Reakce na výpadek helperů, restart během Boostu, health-check automací
# =====================================================================

template:
  - binary_sensor:
      - name: "heating_helpers_all_available"
        unique_id: heating_helpers_all_available
        device_class: connectivity
        state: >-
          {% set required = [
            'input_select.topny_rezim',
            'input_boolean.topny_system_enable',
            'input_number.eco_temp_default',
            'input_number.boost_minutes',
            'input_datetime.boost_until'
          ] %}
          {{ required
             | map('states')
             | select('in', ['unknown', 'unavailable', ''])
             | list
             | count == 0 }}

      - name: "heating_core_automations_healthy"
        unique_id: heating_core_automations_healthy
        device_class: connectivity
        state: >-
          {% set list = [
            'automation.heating_boost_start',
            'automation.heating_boost_apply_comfort_on',
            'automation.heating_boost_reapply_schedule_off',
            'automation.kotel_turn_on_by_policy',
            'automation.kotel_turn_off_by_policy',
            'automation.heating_startup_schedule_sync'
          ] %}
          {{ list | select('is_state', 'on') | list | count == (list|count) }}

automation:
  # 1) FAIL-SAFE: výpadek helperů => přepnout režim do Eco + zapsat alarm
  - id: heating_failsafe_helpers_unavailable
    alias: "Topení Fail-safe – helpery nedostupné => Eco"
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.heating_helpers_all_available
        to: "off"
        for: "00:02:00"
    actions:
      - action: input_select.select_option
        target:
          entity_id: input_select.topny_rezim
        data:
          option: "Eco"
      - action: logbook.log
        data:
          name: "Topení Fail-safe"
          message: "Detekován výpadek klíčových helperů >2 min. Systém přepnut do Eco."
          entity_id: input_select.topny_rezim
      - action: notify.mobile_app_sm_s938b
        data:
          message: "⚠️ Topení fail-safe: klíčové helpery nedostupné, přepínám na Eco."

  # 2) RESTART během Boostu: po startu explicitně dořeš stav
  - id: heating_startup_reconcile_boost
    alias: "Topení – po startu srovnat Boost"
    mode: single
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      - delay: "00:00:20"
      - variables:
          boost_until_ts: "{{ as_timestamp(states('input_datetime.boost_until'), default=0) }}"
          boost_should_be_active: "{{ now().timestamp() < boost_until_ts }}"
      - choose:
          # Boost měl být aktivní => explicitně re-aplikuj boost teploty
          - conditions:
              - condition: template
                value_template: "{{ boost_should_be_active }}"
            sequence:
              - action: input_boolean.turn_on
                target:
                  entity_id: input_boolean.boost_now
              - action: automation.trigger
                target:
                  entity_id: automation.heating_boost_apply_comfort_on

          # Boost už expiroval => uklidit stav
          - conditions:
              - condition: template
                value_template: "{{ not boost_should_be_active }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.boost_now

  # 3) WATCHDOG automací: disabled / dead automace
  - id: heating_watchdog_core_automations
    alias: "Heating Watchdog – zdraví klíčových automací"
    mode: single
    triggers:
      - trigger: time_pattern
        minutes: "/15"
      - trigger: state
        entity_id: binary_sensor.heating_core_automations_healthy
        to: "off"
        for: "00:05:00"
    actions:
      - choose:
          - conditions:
              - condition: state
                entity_id: binary_sensor.heating_core_automations_healthy
                state: "off"
            sequence:
              - action: logbook.log
                data:
                  name: "Heating Watchdog"
                  message: "Některé klíčové automace jsou vypnuté nebo nefunkční."
                  entity_id: input_select.topny_rezim
              - action: notify.mobile_app_sm_s938b
                data:
                  message: "⚠️ Heating Watchdog: klíčové automace nejsou healthy. Zkontrolujte automation.*"
```


## 4) Doplnění ochrany proti extrémům v blueprintu (konkrétní patch koncept)

V `blueprints/automation/heating/smart_zone_schedule.yaml` doporučuji přidat výpočet `safe_eco` a `safe_comfort` a používat je místo syrových `eco_temp` / `last_comfort`:

```yaml
variables:
  min_temp: "{{ state_attr(climate_entity, 'min_temp') | float(5) }}"
  max_temp: "{{ state_attr(climate_entity, 'max_temp') | float(30) }}"

  safe_eco: >-
    {% set x = eco_temp | float(15) %}
    {% if x < min_temp %}{{ min_temp }}
    {% elif x > max_temp %}{{ max_temp }}
    {% else %}{{ x }}{% endif %}

  safe_comfort: >-
    {% set x = last_comfort | float(22) %}
    {% if x < min_temp %}{{ min_temp }}
    {% elif x > max_temp %}{{ max_temp }}
    {% else %}{{ x }}{% endif %}
```

Pak v akcích nahradit:
- `temperature: "{{ eco_temp }}"` → `temperature: "{{ safe_eco }}"`
- `temperature: "{{ last_comfort }}"` → `temperature: "{{ safe_comfort }}"`


## 5) Bezpečné výchozí stavy (doporučení)

- Globální režim po restartu držet **Auto**, ale fail-safe fallback při chybě helperů přepnout na **Eco**.
- Pokud je `topny_system_enable = off`, vždy preferovat tvrdé vypnutí kotle (už implementováno správně).
- Pokud watchdog hlásí nefunkční klíčové automace > 5 minut, poslat notifikaci + přepnout do Eco.
- Nikdy neeskalovat do Boostu automaticky z fail-safe větve.


## 6) Shrnutí

Systém je slušně navržený, ale stále má „měkká místa“ typická pro HA:
- tiché degradace při výpadku helperů,
- slabé health-checky automací,
- ne zcela deterministické chování po restartu během Boostu.

Výše uvedený YAML návrh je konzervativní a provozně bezpečnější: raději krátkodobě topit méně (Eco) než riskovat nekontrolované přetápění nebo dlouhou nekonzistenci stavu.
