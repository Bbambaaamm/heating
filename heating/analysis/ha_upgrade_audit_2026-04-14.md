# Home Assistant audit – profesionální upgrade tipy (2026-04-14)

## A) Stručné shrnutí architektury systému

- Projekt je postavený jako **package-based HA architektura** (`homeassistant.packages: !include_dir_named heating`) s oddělením na vrstvy `core`, `policy`, `control`, `schedule`, `ui` a `analysis`. To je velmi dobrý základ pro produkční provoz.  
- Řízení topení je hybridní: 
  - per-zónové blueprint automace (`smart_zone_schedule`) v `automations.yaml`,
  - plus centrální orchestrátor `heating_dispatch_mode_schedule_override` v `heating/control/refactor_mode_schedule_override.yaml`.
- V projektu už existují watchdog/fail-safe mechanismy (helpery/automatizace/konktivita), ale část je čistě diagnostická a část má aktivní zásah (přepnutí do Eco), což vytváří prostor pro lepší vrstvení fail-safe politik.  
- V konfiguraci je patrná silná orientace na topení, ale také **vyšší počet ručně udržovaných seznamů zón** napříč více soubory (dispatch, watchdog, override, UI), což zvyšuje riziko driftu při přidání/odebrání zóny.

---

## B) Tabulka 10 doporučených upgrade tipů

| # | Název upgradu | Kategorie | Proč důležité právě zde | Náročnost | Riziko zásahu | Priorita |
|---|---|---|---|---|---|---|
| 1 | Konsolidace orchestrace do 1 „source of truth“ (central dispatch) | spolehlivost / údržba / škálovatelnost | Máte paralelní logiku v blueprintu i centrálním dispatchi; hrozí drift a race condition při změnách režimu/boost/override. | střední | střední | 10 |
| 2 | Trigger hygiene: rozdělit „heavy“ dispatch trigger set + debounce | výkon / spolehlivost | Centrální dispatch poslouchá desítky entit, běží `mode: restart`, obsahuje delay a loop přes všechny zóny. | střední | střední | 9 |
| 3 | Zrušit `git push` z HA runtime a oddělit snapshot pipeline | bezpečnost / spolehlivost | Automatizace každých 30 min spouští shell skript, který commituje i pushuje z HA. Produkčně rizikové. | nízká | nízké-střední | 9 |
| 4 | Zavést zónový registr (single YAML map) pro odstranění duplicit seznamů | údržba / škálovatelnost | Seznamy 8 zón jsou ručně opakované v dispatchi, watchdogu, UI i startup reconcile. | střední | nízké-střední | 8 |
| 5 | Převést minutu-based Boost expiry na přesný event trigger | výkon / spolehlivost / energetická efektivita | Aktuálně běží periodický check každou minutu. Lze nahradit eventem/timerem bez polling smyčky. | nízká | nízké | 8 |
| 6 | Zesílit fail-safe vrstvu pro výpadek ventilů (degradace místo „jen notify“) | spolehlivost / bezpečnost provozu | U výpadku hlavic je dnes eskalace hlavně notifikační; při delší degradaci chybí automatická ochranná strategie. | střední | střední-vysoké | 8 |
| 7 | Optimalizace template výpočtů závislých na `now()` | výkon | Více templatingu používá `now()` (demand age, boost, connectivity), což vyvolává periodické přepočty. | střední | nízké | 7 |
| 8 | Normalizace naming convention (CZ/EN, diakritika, aliasy) | přehlednost / údržba | Mix jazyků a stylů komplikuje troubleshooting, team review i grep diagnostiku. | nízká | nízké | 6 |
| 9 | UI/UX: sjednotit stav „globální manuál“ a selekce zón obousměrně | UX / spolehlivost | Máte sync override→UI select, ale chybí jasná lifecycle logika resetu selekcí po hromadné akci. | nízká | nízké | 6 |
|10| Přidat architekturní guardrails (lint + CI + check_config) | údržba / bezpečnost změn | Repo je rozsáhlé, produkční; bez automatických kontrol roste riziko regressí v YAML/Jinja. | střední | nízké | 7 |

---

## C) Detailní rozpad 10 tipů

### 1) Konsolidace orchestrace do 1 „source of truth“ (central dispatch)
- **Kategorie:** spolehlivost / údržba / škálovatelnost  
- **Proč důležité zde:** aktuálně máte vedle sebe dvě orchestrace teplot: 
  1) blueprint `smart_zone_schedule` (legacy/fallback), 
  2) centrální `heating_dispatch_mode_schedule_override`.  
  To je funkční, ale při rozšiřování systému zvyšuje riziko, že se logika začne rozcházet.
- **Důkaz z repa:**
  - `automations.yaml` instancuje 8× `smart_zone_schedule` blueprint.  
  - `refactor_mode_schedule_override.yaml` zavádí central dispatch a ještě podporuje fallback při `heating_central_dispatch_enable = off`.  
- **Konkrétně dotčené části:** `automations.yaml`, `blueprints/automation/heating/smart_zone_schedule.yaml`, `heating/control/refactor_mode_schedule_override.yaml`, startup/boost reconcile automace.
- **Dnešní problém/riziko:** race condition při souběžných triggerech mode/boost/override + údržbový drift (feature se opraví v dispatchi, ale ne v blueprint větvi).
- **Cílový stav:** central dispatch jako primární engine; blueprinty ponechat jen jako nouzový fallback za feature flagem + explicitně označit „deprecated path“.
- **Očekávaný přínos:** menší komplexita, méně regressí, rychlejší debug.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** střední  
- **Priorita:** 10

### 2) Trigger hygiene: rozdělit „heavy“ dispatch trigger set + debounce
- **Kategorie:** výkon / spolehlivost  
- **Proč důležité zde:** `heating_dispatch_mode_schedule_override` má velmi široký trigger set (desítky helperů) + `mode: restart` + `delay 2s` + loop přes všechny zóny. To je robustní, ale při burstu změn může vyvolat „restart storm“.  
- **Důkaz z repa:** automation `heating_dispatch_mode_schedule_override` má velký seznam trigger entit (mode, schedule, manual override, timer, last comfort), následně full-zone loop a volání skriptu pro každou zónu.
- **Konkrétně dotčené části:** `heating/control/refactor_mode_schedule_override.yaml`.
- **Dnešní problém/riziko:** opakované přerušování běhů (`mode: restart`) může oddalovat stabilizaci setpointů a zvyšovat latenci během startupu či boost přechodů.
- **Cílový stav:**
  - rozdělit trigger domény (kritické vs. méně kritické),
  - přidat debounce/batch event (`heating_reconcile_requested`) jako hlavní vstup,
  - u vybraných triggerů spouštět jen „delta apply“ na konkrétní zónu.
- **Očekávaný přínos:** stabilnější chování při burstech, nižší počet zbytečných write operací do climate entit.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** střední  
- **Priorita:** 9

### 3) Zrušit `git push` z HA runtime a oddělit snapshot pipeline
- **Kategorie:** bezpečnost / spolehlivost  
- **Proč důležité zde:** automatizace spouští shell command každých 30 minut a při změně dat skript provádí `git commit` + `git push`. To v produkční HA instanci otevírá bezpečnostní i provozní riziko (credentials, výpadky sítě, blokace procesu).  
- **Důkaz z repa:**
  - `automations.yaml` obsahuje automatizaci „Export entit do Git snapshotu“ na start + `/30 min`.
  - `scripts/export_entities_to_git.sh` explicitně dělá `git commit` a `git push`.
- **Konkrétně dotčené části:** `automations.yaml`, `configuration.yaml`, `scripts/export_entities_to_git.sh`.
- **Dnešní problém/riziko:** nežádoucí side effects v runtime HA a potenciální zneužití při kompromitaci shell command path.
- **Cílový stav:** v HA nechat pouze export souboru; commit/push přes externí CI (GitHub Actions, cron mimo HA host).
- **Očekávaný přínos:** tvrdší bezpečnostní profil, menší coupling HA↔Git infrastruktura.
- **Náročnost implementace:** nízká  
- **Riziko zásahu:** nízké-střední  
- **Priorita:** 9

### 4) Zavést zónový registr (single YAML map) pro odstranění duplicit seznamů
- **Kategorie:** údržba / škálovatelnost  
- **Proč důležité zde:** seznam stejných 8 zón je ručně opisovaný v několika souborech (dispatch, watchdog, UI sync, manual override startup, global manual script).  
- **Důkaz z repa:** opakované entity listy např. v dispatch `zones`, v watchdog manual override `repeat.for_each`, v UI sync mapě, v global manual skriptu.
- **Konkrétně dotčené části:** `heating/control/refactor_mode_schedule_override.yaml`, `heating/control/watchdog_manual_override.yaml`, `heating/ui/packages/heating_global_manual.yaml`, `heating/schedule/automation/startup/manual_override_startup_reconcile.yaml`, `heating/schedule/automation/startup/heating_ui_sync_selection.yaml`.
- **Dnešní problém/riziko:** při přidání 9. zóny je vysoká šance, že se zapomene některý seznam.
- **Cílový stav:** centrální registr zón (např. `!include` map) a od něj generované šablony/listy v automatizacích.
- **Očekávaný přínos:** výrazně nižší maintenance cost a menší drift mezi vrstvami.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** nízké-střední  
- **Priorita:** 8

### 5) Převést minutu-based Boost expiry na přesný event trigger
- **Kategorie:** výkon / spolehlivost / energetická efektivita  
- **Proč důležité zde:** Boost timeout kontrolujete pollingem každou minutu (`time_pattern: /1`).
- **Důkaz z repa:** `heating_boost_auto_clear_button` je čistě periodický check na `boost_until`.
- **Konkrétně dotčené části:** `heating/control/mode_boost.yaml`.
- **Dnešní problém/riziko:** zbytečné periodické vyhodnocování + potenciální delay do 59 s.
- **Cílový stav:** timer-based/on-time trigger (např. pomocný timer pro boost lifecycle) nebo trigger na změnu `input_datetime.boost_until` + one-shot čekání.
- **Očekávaný přínos:** méně pollingu, přesnější konec Boostu, čistší logika.
- **Náročnost implementace:** nízká  
- **Riziko zásahu:** nízké  
- **Priorita:** 8

### 6) Zesílit fail-safe vrstvu pro výpadek ventilů (degradace místo „jen notify“)
- **Kategorie:** spolehlivost / bezpečnost provozu  
- **Proč důležité zde:** při výpadku hlavic je velká část reakce notifikační/diagnostická; není jasná automatická degradace pro delší incident.
- **Důkaz z repa:** connectivity watchdog vytvoří notification + log; escalace je po 30 min nad 2 unhealthy, ale bez tvrdšího zásahu do řízení.
- **Konkrétně dotčené části:** `heating/control/watchdog_connectivity.yaml`, `heating/control/reliability_failsafe.yaml`.
- **Dnešní problém/riziko:** dlouhotrvající výpadek může držet systém v suboptimálním režimu bez prediktabilního fallbacku.
- **Cílový stav:** definovat staged degradaci (např. soft eco clamp, disable boost, limit max setpoint, případně manual ack gate).
- **Očekávaný přínos:** bezpečnější chování při poruše infrastruktury Zigbee/ventilů.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** střední-vysoké  
- **Priorita:** 8

### 7) Optimalizace template výpočtů závislých na `now()`
- **Kategorie:** výkon  
- **Proč důležité zde:** více template senzorů používá `now()` (`demand age`, `boost active`, `remaining`, watchdog „alive“) => pravidelné periodické přepočty napříč systémem.
- **Důkaz z repa:**
  - zónové demand templaty porovnávají `last_updated` proti `now()`,
  - boost binary sensor používá `now().timestamp()`,
  - connectivity watchdog počítá stáří entit vůči `now()`.
- **Konkrétně dotčené části:** `heating/core/zone_*.yaml`, `heating/control/mode_boost.yaml`, `heating/control/watchdog_connectivity.yaml`.
- **Dnešní problém/riziko:** vyšší template churn a méně predikovatelný load při větším počtu entit.
- **Cílový stav:** kde jde, přejít na trigger-based template (`trigger:` template sensors) nebo omezit výpočty na event-driven změny.
- **Očekávaný přínos:** snížení zbytečných přepočtů, lepší runtime efektivita.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** nízké  
- **Priorita:** 7

### 8) Normalizace naming convention (CZ/EN, diakritika, aliasy)
- **Kategorie:** přehlednost / údržba  
- **Proč důležité zde:** konfigurace kombinuje češtinu i angličtinu v aliasech, názvech a komentářích; to je použitelné pro solo provoz, ale horší pro týmové review a incident response.
- **Důkaz z repa:** mix názvů typu `Heating Watchdog – ...`, `Topení – ...`, `Apply global manual override`, `boost_comfort_offset_c` vedle českých helperů a aliasů.
- **Konkrétně dotčené části:** např. `heating/ui/packages/heating_global_manual.yaml`, `heating/control/reliability_failsafe.yaml`, `heating/ui/controls/mode_controls.yaml`.
- **Dnešní problém/riziko:** pomalejší orientace, nejednotné logbook eventy, obtížnější fulltext diagnostika.
- **Cílový stav:** naming standard dokument (entity_id EN snake_case, friendly_name CZ/EN dle preference, alias pattern `[Heating][Layer] ...`).
- **Očekávaný přínos:** rychlejší debug, konzistentní dashboard/logbook UX.
- **Náročnost implementace:** nízká  
- **Riziko zásahu:** nízké  
- **Priorita:** 6

### 9) UI/UX: sjednotit stav „globální manuál“ a selekce zón obousměrně
- **Kategorie:** UX / spolehlivost  
- **Proč důležité zde:** máte jednosměrnou synchronizaci `manual_override -> ui_select`, ale po hromadné operaci může UI selekce zůstat „sticky“ bez explicitního reset patternu.
- **Důkaz z repa:**
  - `heating_ui_sync_selection` přepíná UI checkboxy dle override state,
  - `apply_global_manual_override` aplikuje změny do více zón, ale neobsahuje krok pro reset `ui_select_*` po úspěchu.
- **Konkrétně dotčené části:** `heating/schedule/automation/startup/heating_ui_sync_selection.yaml`, `heating/ui/packages/heating_global_manual.yaml`.
- **Dnešní problém/riziko:** uživatel může omylem opakovat bulk zásah, protože UI výběr zón zůstane aktivní.
- **Cílový stav:** po aplikaci nabídnout volitelný auto-reset selekcí + vizuální potvrzení „N zón změněno“.
- **Očekávaný přínos:** nižší chybovost obsluhy, lepší použitelnost dashboardu.
- **Náročnost implementace:** nízká  
- **Riziko zásahu:** nízké  
- **Priorita:** 6

### 10) Přidat architekturní guardrails (lint + CI + check_config)
- **Kategorie:** údržba / bezpečnost změn  
- **Proč důležité zde:** projekt je rozsáhlý, hodně Jinja logiky a mnoho package souborů. Bez CI guardrails je vyšší riziko regressí při refactoru.
- **Důkaz z repa:**
  - velký počet YAML balíčků a šablon,
  - globální `scripts.yaml`/`scenes.yaml` jsou prakticky prázdné (logika běží primárně v packages), což je správně, ale o to více je potřeba automatizovaná validace package stromu.
- **Konkrétně dotčené části:** celý repo strom (zejména `heating/**`, `configuration.yaml`, `automations.yaml`).
- **Dnešní problém/riziko:** syntaktické/semantické chyby se mohou projevit až v runtime po restartu.
- **Cílový stav:** pre-commit + HA config check + yamllint + smoke test workflow při každém PR.
- **Očekávaný přínos:** nižší change-failure-rate, bezpečnější produkční release.
- **Náročnost implementace:** střední  
- **Riziko zásahu:** nízké  
- **Priorita:** 7

---

## TOP výběry

### TOP 3 upgrady s největším dopadem
1. **#1 Konsolidace orchestrace do central dispatch**  
2. **#2 Trigger hygiene + debounce dispatch**  
3. **#3 Oddělení git push pipeline od HA runtime**

### TOP 3 nejrychlejší výhry (quick wins)
1. **#5 Boost expiry bez minutu pollingu**  
2. **#8 Naming convention standard + sjednocení aliasů**  
3. **#9 UI auto-reset selekcí po bulk manuálu**

### TOP 3 nejrizikovější slabiny systému
1. **Paralelní logické cesty (dispatch vs. legacy blueprint fallback) při režimových přechodech.**  
2. **Git commit/push přímo z HA runtime shell skriptu.**  
3. **Vysoká míra ruční duplicity seznamů zón napříč soubory (drift při změně topologie).**

---

## D) Akční plán implementace po krocích

### Fáze 1 (nejdřív – stabilizační, nízké riziko)
1. **Vypnout `git push` z HA runtime** (ponechat jen export souboru).  
2. **Boost expiry refactor**: nahradit `/1` polling event/timer řešením.  
3. **UI quick fix**: po `apply_global_manual_override` volitelný reset `ui_select_*`.

### Fáze 2 (poté – architekturní konsolidace)
4. **Vyhlásit central dispatch jako jediný primární orchestrátor.**  
5. **Rozdělit trigger set dispatch automace** (kritické vs. nekritické), přidat debounce/event batch.  
6. **Zavést centrální registr zón** a migrovat na něj watchdog/UI/startup skripty.

### Fáze 3 (nakonec – hardening a dlouhodobá údržba)
7. **Fail-safe degradace pro výpadky ventilů** (staged policy + override rules).  
8. **Trigger-based optimalizace template výpočtů závislých na `now()`.**  
9. **Naming convention policy + postupná rename/normalizace.**  
10. **CI guardrails** (`ha core check`, yamllint, validační workflow, případně kontrola dead-entity odkazů).

---

## Poznámka k validitě zjištění

- Všechny závěry výše vycházejí pouze z obsahu tohoto repozitáře.  
- **Nelze z repa doložit runtime telemetrii** (reálnou frekvenci triggerů, CPU load, latence Zigbee, četnost incidentů). Tyto body jsou tedy návrhy architekturního hardeningu a je vhodné je potvrdit provozními statistikami v HA Recorder/Logbook.
