# Paranoid production audit – topení (HA/Zigbee)

Datum: 2026-05-21

## A) Kritické chyby

### A1) Reálná možnost „quiet failure“ při zápisu setpointu do TRV (bez retry/backoff/ověření)
- **Důkaz:** Zápis `climate.set_temperature` je proveden jednorázově, bez navazující verifikace stavu a bez retry logiky. (`heating_apply_zone_target`, `mode_boost`).
- **Soubory / entity:**
  - `heating/control/refactor_mode_schedule_override.yaml` (`script.heating_apply_zone_target`, `climate.set_temperature`).
  - `heating/control/mode_boost.yaml` (`heating_boost_apply_comfort_on`, `climate.set_temperature`).
- **Scénář selhání:** TRV je krátce offline / sleepy / APS_NO_ACK, service call proběhne v HA, ale zařízení příkaz nepřevezme.
- **Dopad:** Dispečink i watchdog mohou reportovat „vše ok“, ale fyzický ventil zůstane na staré hodnotě → lokální přetápění/nedotápění.
- **Konzervativní oprava:** Po setpoint zápisu přidat krátké `wait_template` ověřující atribut `temperature` (tolerance), při failu 1–2 retry s jitterem a poté varování.

## B) Významná rizika

### B1) Startup race: dispatch může minout první konzistentní okamžik po bootu
- **Důkaz:** Dispatch je blokovaný guardem `input_boolean.heating_startup_reconcile_guard == off`; trigger je `homeassistant.start` + event + state změny s `for: 8s`.
- **Soubory / entity:**
  - `heating/control/refactor_mode_schedule_override.yaml` (automation `heating_dispatch_mode_schedule_override`).
  - `heating/control/reliability_failsafe.yaml`, `heating/schedule/automation/startup/*` (startup orchestrace přes guard a čekání).
- **Scénář selhání:** Při startu se guard vypne dříve/později než dorazí relevantní state změny; `for: 8s` může odfiltrovat krátký stabilní stav.
- **Dopad:** Po restartu může zůstat část zón dočasně se starým setpointem až do další změny triggeru.
- **Konzervativní oprava:** Po uvolnění guardu vždy explicitně emitovat `heating_reconcile_requested` (idempotentně) a logovat source.

### B2) Logbook spam v dispatch smyčce
- **Důkaz:** Každé spuštění dispatch zapisuje obecný log + per-zóna logy přes `script.heating_apply_zone_target`.
- **Soubory / entity:**
  - `heating/control/refactor_mode_schedule_override.yaml` (`logbook.log` před smyčkou, další v apply skriptu).
- **Scénář selhání:** Burst změn helperů (schedule/manual/timer) → časté restarty automace (`mode: restart`) → vysoká frekvence logů.
- **Dopad:** Zhoršená observability (signal-to-noise), pomalejší diagnostika skutečných chyb.
- **Konzervativní oprava:** Redukovat info logy na změny intentu nebo změny targetu >0.1 °C; ostatní jen při debug guard ON.

### B3) Duplicitní řídicí cesty pro Boost (historická + central dispatch)
- **Důkaz:** `mode_boost` obsahuje přímé nastavování klimat, ale je podmíněné `heating_central_dispatch_enable == off`; zároveň central dispatch řeší boost intent, když je ON.
- **Soubory / entity:**
  - `heating/control/mode_boost.yaml`
  - `heating/control/refactor_mode_schedule_override.yaml`
- **Scénář selhání:** Ruční přepínání `heating_central_dispatch_enable` během aktivního boostu.
- **Dopad:** Krátké okno dvojího zápisu / nejednoznačné vlastnictví logiky.
- **Konzervativní oprava:** Při změně dispatch enable vynutit jednorázový reconcile event + throttling 10–20 s.

### B4) Zigbee dostupnost je hlídána, ale bez diferenciace transient vs. dlouhý výpadek
- **Důkaz:** Watchdog eviduje unknown/unavailable a LQI/stáří update, ale řídicí zápisy nevyužívají watchdog stav pro degradovaný režim.
- **Soubory / entity:**
  - `heating/control/watchdog_connectivity.yaml`
  - `heating/control/refactor_mode_schedule_override.yaml`
- **Scénář selhání:** Krátké flapping unavailable stavy při reconnectu ConBee/ZHA.
- **Dopad:** Nadbytečné notifikace a případné „thrash“ mezi recover/fail notifikacemi.
- **Konzervativní oprava:** Přidat hysteresi (např. 2–5 min) i pro recovery a odlišit soft warning vs hard incident.

## C) Hardening doporučení

1. **Runtime verifikace climate write-path:** po každém setpointu ověřit atribut teploty a zapisovat metriky „write_success_rate“.  
2. **Jednotný „source-of-truth“ pro orchestrace logy:** strukturovaný log (`source`, `reason`, `zone`, `old_target`, `new_target`).  
3. **Canary kontrola po HA restartu:** do 2–3 min ověřit, že všechny zóny mají target odpovídající intentu.  
4. **Rate-limit notifikací:** persistent_notification deduplikovat a časově omezit.  
5. **Audit blueprint driftu v CI:** diff očekávaných inputů vs instancí v `automations.yaml`.

## D) False positives / bezpečné warningy

1. **`PyYAML není dostupné`** při lokálním běhu validátoru není chyba konfigurace samotná, ale omezení prostředí.  
2. **Smíšený styl trigger/action (`platform` vs `trigger`)** v `automations.yaml` je backward-compatible (nejde o runtime bug).  
3. **Mnoho výskytů `unavailable/unknown`** je zde většinou záměrné defensivní ošetření, ne smell samo o sobě.

## E) Co je už dobře navržené

1. **Protective systém existuje a je automatizovatelný:** `scripts/run_protective_checks.py` + guard skripty.  
2. **Fail-safe při nedostupných dispatch vstupech:** notifikace + bez agresivního zásahu do režimu.  
3. **Oddělení policy/effective vrstvy:** snižuje riziko ad-hoc zásahů do kotle.  
4. **Central dispatch s explicitní zónovou mapou:** předvídatelné chování a jednodušší auditovatelnost.  
5. **Startup reconcile guard:** explicitní ochrana proti předčasným zápisům při bootu.

## Produkční verdikt

Systém je **blízko production-grade**, ale **ne ještě plně robustní pro Zigbee failure režimy**, protože write-path na TRV nemá potvrzovací smyčku (verify+retry+escalation). Bez toho hrozí tiché selhání při přenosových problémech.

## Top 10 remaining technical risks

1. Tichý drop `climate.set_temperature` bez retry.  
2. Startup timing mezery mezi guard release a trigger stabilizací.  
3. Logbook spam při burstech změn helperů.  
4. Přepínání dispatch enable za běhu boostu.  
5. Flapping unavailable při ZHA reconnect.  
6. Chybějící metrika úspěšnosti write operací.  
7. Nedostatek runtime trace pro „proč se zóna nepřepsala“.  
8. Potenciální backlog v queued skriptu při delších výpadcích.  
9. Závislost na správné obnově helper state po restartu.  
10. Omezená statická YAML validace bez PyYAML v CI/runtime prostředí.

## Confidence level

**Střední až vyšší (0.77)** – orchestrace je čitelná a obranná, ale bez runtime dat z produkce nelze definitivně potvrdit frekvenci výpadků write-pathu.

## Co sledovat následujících 14 dní v provozu

1. Počet dispatch triggerů/den a jejich burst profile.  
2. Počet write pokusů vs. potvrzených změn targetu na TRV.  
3. Watchdog incidenty unavailable/LQI a délky trvání.  
4. Po restartu HA: čas do plné konvergence všech zón.  
5. Počet manuálních zásahů uživatele po automatickém řízení (proxy nespokojenosti).  
6. Počet persistent_notification dedupe kolizí.  
7. Korelace mezi boostem a následnými reconcile eventy.  
8. Výkyvy kotle (short cycling) při změnách politiky delay.
