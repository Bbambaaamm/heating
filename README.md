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

Před nasazením porovnejte zdrojové YAML balíčky s načtenou konfigurací, zachovejte jejich
původní kopie a ověřte cíle všech zón. Chybějící rozvrh, význam vypnutého rozvrhu a chování
při výpadku musí mít určenou politiku. Oprava společného skriptu začne při příštím běhu
uplatňovat požadavky všech zón. Pro první test je nutná ověřená izolace jedné zóny.
Samotné sloučení PR nenahradí instalaci souborů do `/config`, kontrolu konfigurace a
provozní ověření. Balíčkové skripty nenahrazujte duplicitami vytvořenými přes UI API.
