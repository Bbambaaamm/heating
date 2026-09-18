# Heating Home Assistant config

## Automatic protective and debug checks

Projekt obsahuje automatické ochranné a auditní kontroly, aby nebylo nutné je spouštět ručně.

### Kdy se kontroly spouští automaticky
- **Primárně v CI (GitHub Actions)** přes workflow `Heating audit and validation` při každém push a pull requestu; bez filtrů, které dříve vynechávaly blueprinty.
- **Volitelně lokálně** přes `pre-commit` hook (`heating-protective-checks`) jako vývojářská pomůcka.

### Co se kontroluje
1. Konzistence zón napříč orchestrace/listy/helpery (`scripts/validate_zone_list_consistency.py`).
2. YAML syntaxe a HA styl guard (`trigger/condition/action`, projektový jednotný styl; `triggers/actions` jsou rovněž platná syntaxe HA) (`scripts/validate_yaml_and_ha_style.py`).
3. Debug guardrail: jakýkoliv nový `[DEBUG]` blok musí obsahovat oba guardy:
   - `input_boolean.heating_debug_guard`
   - `input_datetime.heating_debug_until`
   (`scripts/validate_debug_guards.py`)
4. Smoke/checklist coverage guard (existence a minimální obsah smoke matice + checklistu) (`scripts/validate_smoke_coverage.py`).

### PASS/FAIL pravidla
- **PASS**: všechny kontroly vrátí exit code 0.
- **FAIL**: alespoň jedna kontrola vrátí exit code 1 → commit/CI se zastaví.

### Lokální spuštění (volitelné, ne primární ochrana)
```bash
python3 scripts/run_protective_checks.py
```

### Poznámka k Home Assistant kompatibilitě
Kontrola konfigurace (`ha core check`/`check_config`) je pouze jedna vrstva. Runtime kompatibilitu a chování je nutné potvrdit integračními scénáři v cílové verzi HA; přijetí služby není důkaz fyzické reakce zařízení.


## Regresní audit 2026-09-16

Podrobný audit, mapa, pokrytí a provozní ověřovací postup jsou předány vlastníkovi samostatně.
Tato větev obsahuje opravy a reprodukovatelné testy se simulovanými daty.

Izolované testy používají skutečné šablony, skripty a události HA Core **2026.9.2**, Python **3.14**,
s testovacími entitami a simulovanými službami zařízení. Tato referenční verze není potvrzením
verze nasazené v domácnosti. Testy nekomunikují s kotlem ani s živým HA.

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python scripts/run_protective_checks.py
```

`HEATING_CONFIG_ROOT=/cesta/k/původnímu/checkoutu` umožňuje stejnou testovací sadu spustit proti
původní konfiguraci. Kontrola `hass --script check_config -c /cesta/ke/config` je další vrstva;
čtěte také její výstup, protože chybějící externí device trigger může být pouze zalogován.

Režim a master přepínač po restartu obnovují předchozí hodnotu. V nové instalaci bez uloženého
stavu začíná master vypnutý. Manuální časovače mají `restore: true`. Nové časové značky
manuálního override se ukládají při jeho příští aktivaci; stáří override aktivního již před
aktualizací nelze zpětně rekonstruovat. Prahy kotle, ECO teplota a Boost offset jsou zachovány.

Boost ukládá jednoznačný konec v `input_text.boost_until_utc`; `input_datetime.boost_until` zůstává
pro místní zobrazení a časový trigger. Starý termín při migraci má fallback na timestamp atribut
původního helperu. Nový UTC termín zachovává délku i přes změnu letního času a restart.

### Potvrzení cíle hlavice

Centrální skript po příkazu ověřuje režim `heat` a hlášenou cílovou teplotu s tolerancí
0,1 °C. Kontrola přijme i report doručený před začátkem čekání. Čeká nejvýše 30 sekund
na zónu; tento výchozí limit je nutné při provozní zkoušce porovnat s odezvou zařízení.
Při změně rozhodovacích vstupů nebo vypnutí masteru ukončí kontrolu starého požadavku.
Příkaz automaticky neopakuje. Fronta může být při chybě zdržena nejvýše o tento interval
na každou zónu; ostatní zóny pokračují díky existujícímu `continue_on_error` v dispatchi.

Nepotvrzený cíl vyvolá chybu ve stopě a oznámení v HA se stabilním ID pro danou zónu.
Oznámení se smaže až při další úspěšné kontrole, i pokud už není třeba nový zápis.
Odmítnutý neplatný požadavek nebo nedostupná hlavice se zapíše i při vypnutém debug režimu
a běh skončí chybou. Úspěch potvrzuje stav hlášený integrací; fyzické otevření ventilu
ani dodávku tepla tím test neprokazuje.

### Skutečné rozvrhové okno a chybějící rozvrh

V režimu Auto bez manuálního override patří komfort pouze do aktuálního komfortního
úseku Scheduleru. Mimo úsek, bez rozvrhu nebo při vypnutém/nedostupném rozvrhu se použije
`eco_temp_default` (v projektu 15 °C). Uložený `last_comfort` ani obnovený příznak
`*_schedule_active=on` samy o sobě komfortní okno nevytvářejí. Boost a platný manuální
override zachovávají své priority; po jejich skončení se znovu použije skutečné okno.

`sensor.heating_schedule_windows` čte `current_slot` a jeho akci z atributů Scheduleru.
Stav rozvrhového přepínače `on` znamená jen povolený rozvrh; při vykonání akce může být
krátce `triggered`. Kalendářní dny, přechod přes půlnoc a DST vyhodnocuje Scheduler.
Chybějící nebo neplatný index úseku nezakládá požadavek na komfort. Při více rozvrzích
zóny stačí jeden skutečně aktivní komfortní úsek. Stejný výsledek používá centrální řízení
i záložní blueprint; změna okna zneplatní také starý požadavek čekající na hlavici.

Adaptér je určen pro zde používané časové rozvrhy: jedna cílová zónová boolean entita,
jedna akce `input_boolean.turn_on/turn_off` na úsek, bez dalších podmínek. Scheduler
ve stavových atributech nezveřejňuje podmínky ani všechny akce. Podmíněné nebo vícecílové
rozvrhy proto vyžadují samostatné rozšíření adaptéru. Při kontrole 18. 9. 2026 všech
19 existujících rozvrhů odpovídalo podporovanému formátu, sklep neměl žádný.

Pomocné příznaky se srovnají po startu, reloadu, změně oken a kontrolně každou minutu.
Synchronizace nepřepisuje příznak zóny během manuálního override, aby oprava starého
stavu nezrušila manuál. Skutečná změna okna dané zóny nadále ukončuje manuál typu
„Do další změny rozvrhu“. Změna okna jiné zóny jej neukončí.

Před nasazením porovnejte zdrojové YAML balíčky s načtenou konfigurací, zachovejte jejich
původní kopie a ověřte cíle všech zón. Význam vypnutého zónového přepínače `schedule_enable`
a ostatní pravidla při výpadku jsou samostatné otázky. Oprava společného skriptu začne při příštím běhu
uplatňovat požadavky všech zón. Pro první test je nutná ověřená izolace jedné zóny.
Samotné sloučení PR nenahradí instalaci souborů do `/config`, kontrolu konfigurace a
provozní ověření. Balíčkové skripty nenahrazujte duplicitami vytvořenými přes UI API.
