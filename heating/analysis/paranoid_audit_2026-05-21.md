# Paranoid production audit – topení (HA/Zigbee)

Datum: 2026-05-21

## Stav při dokončení PR #71 (2026-09-18)

Tento dokument uchovává historický statický audit z 21. května. Původní nálezy,
produkční verdikt i číselný odhad jistoty níže popisují tehdejší stav; nejsou
aktuálním potvrzením ani zamítnutím provozní spolehlivosti.

Vyhodnocení níže porovnává audit s opravami v [PR #74](https://github.com/Bbambaaamm/heating/pull/74),
commit `932b8ebff045a95e5e585a0b0503f6a1482811e4`. Tento PR byl sloučen do `main`.
Historický audit se přijímá jako dokumentace; jeho přijetí neznamená, že všechna
doporučení byla implementována.

| Nález / doporučení | Stav po opravách #74 a zbývající práce |
| --- | --- |
| A1: nepotvrzený zápis cíle | Sdílený centrální skript ověřuje hlášený režim `heat` a cíl s tolerancí 0,1 °C, čeká nejvýše 30 s a při neúspěchu vyvolá oznámení a chybu. Změna požadavku ukončí staré ověřování. Automatické retry nebylo zavedeno. Přímá záložní cesta Boostu v `mode_boost.yaml` tuto potvrzovací smyčku nemá; sjednocení všech cest zůstává otevřené. Report integrace nedokazuje fyzický účinek. |
| B1: start a uvolnění guardu | Startup synchronizace i watchdog po uvolnění guardu vysílají `heating_reconcile_requested`; pořadí pokrývá regresní test. Centrální řízení reaguje také na reload a návrat hlavice. Konvergence skutečných zařízení po restartu ještě vyžaduje provozní ověření. |
| B2: množství logů | Obecný dispatch log a některé diagnostické větve jsou pod debug guardem. Potvrzení cíle se však stále zapisuje při každé úspěšné kontrole, i bez změny setpointu; úplné omezení logování na změny zůstává otevřené. |
| B3: přechod mezi centrálním a záložním Boostem | Před zápisy se znovu kontroluje aktuální řízení a požadavek; zapnutí centrálního řízení spouští dispatch. Úplné předání vlastnictví v obou směrech během Boostu ani navržený throttling nejsou tímto uzavřeny. |
| B4: krátké výpadky a obnova Zigbee | Současný watchdog má 5minutovou stabilní obnovu, eskalaci při více než jedné problémové hlavici po 30 minutách a stabilní identifikaci incidentu pro 60minutový cooldown stejné skupiny hlavic. Periodická kontrola po 10 minutách nevyžaduje vždy předchozí 10minutové trvání poruchy; úplná filtrace krátkých výpadků a degradované řízení zůstávají samostatnou otázkou. |
| C1–C2: metriky a strukturované logy | Důvod požadavku je součástí diagnostiky, ale metrika `write_success_rate` a jednotné schéma všech provozních logů nejsou dokončené. |
| C3: kontrola po restartu | Izolované testy nenahrazují kontrolu cílů všech zón, časování kotle a fyzických zařízení po aktivaci. Automatická kontrola celé instalace do 2–3 minut není tímto auditem doložena. |
| C4: deduplikace oznámení | Potvrzování cíle používá stabilní ID pro zónu, watchdog stabilní ID a cooldown. Nejde o plošný rate limit všech oznámení. |
| C5: drift blueprintů | Existují kontroly konzistence zón a integrační regresní testy; úplná kontrola schématu všech vstupů blueprintů proti všem instancím není zavedena. |
| D1: chybějící PyYAML | Aktuální ochranné kontroly při chybějícím PyYAML selžou i lokálně. Historický úspěch s přeskočenou YAML validací již není platným postupem. |

### Důkazy a provozní stav k 18. září

- Lokálně prošlo 72/72 testů na HA Core 2026.5.1 i 2026.9.2;
  [CI ověřeného commitu](https://github.com/Bbambaaamm/heating/actions/runs/35323731534)
  úspěšně dokončilo ochranné kontroly a runtime testy na obou verzích.
- Vlastník doložil instalaci souborů tohoto commitu do `/config` a úspěšný `ha core check`.
  Restart/reload aktivující nové balíčky a následné provozní ověření zatím doložené nejsou.
- PR #65 a #66 byly uzavřeny jako nahrazené současnými ochrannými kontrolami;
  jejich konfliktní staré větve nebyly sloučeny.
- Pro Auto je potvrzené pravidlo: mimo skutečné komfortní okno nebo bez rozvrhu
  použít ECO (v projektu 15 °C), při zachování platného manuálu a Boostu.
  Samostatně zůstává vyjasnění a ověření širších pravidel pro vypnutý zónový
  `schedule_enable`, master off a otevřené okno.

Následuje původní audit beze změn.

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
