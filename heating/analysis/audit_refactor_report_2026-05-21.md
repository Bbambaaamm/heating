# Audit a konzervativní refactoring review (2026-05-21)

## Rozsah a metoda
- Prošel jsem celý repozitář se zaměřením na architekturu balíčků Home Assistant, orchestrace režimů, startup sync, watchdog, fail-safe a vazby mezi helpery/zónami.
- Cíl byl **nezměnit funkční chování**, pouze potvrdit rizika, duplicity a místa vhodná pro malé bezpečné kroky.
- V tomto kroku jsem neprováděl zásahy do runtime logiky.

## Přehled hlavních částí projektu
1. **Root konfigurace HA**
   - `configuration.yaml` načítá `automations.yaml`, `scripts.yaml`, `scenes.yaml` a celé `heating/*` jako package strom.
2. **Zone scheduling + preference helpery**
   - `heating/schedule/preferences/*` drží helpery a per-zóna preference.
   - `automations.yaml` instancuje blueprints pro rozvrhy zón a externí čidla.
3. **Centrální řízení topení**
   - `heating/control/*` řeší režimy (`Auto/Eco/Boost/Off`), fail-safe, watchdog, řízení kotle a central dispatch.
4. **UI a dashboard část**
   - `heating/ui/*` drží package helpery, dashboard šablony a UI controls.
5. **Analytika / audit artefakty**
   - `heating/analysis/*` obsahuje historický audit a snapshoty entit.

## Datový tok (zjednodušeně)
- Uživatel / automatika změní `input_select.topny_rezim` nebo override helpery.
- Boost stav je odvozen z `input_boolean.boost_now` + `input_datetime.boost_until` v `binary_sensor.kotel_boost_active`.
- Při zapnutém central dispatch (`input_boolean.heating_central_dispatch_enable`) se má uplatnit centrální orchestrace v `refactor_mode_schedule_override.yaml`.
- Při vypnutém central dispatch se vrací orchestrace do blueprint automací (fallback větev v `mode_auto.yaml` a `mode_boost.yaml`).

## Nálezy podle rizika

### A) Bezpečné opravit hned (nízké riziko)
1. **Nekonzistentní pojmenování/diakritika v názvech zón (textové labely)**
   - Např. `Chodba zachod` vs `Chodba záchod` (jen text, ne entity).
   - Dopad: diagnostika/logbook je méně konzistentní.
   - Riziko změny: nízké (UI/log text), ale i tak ověřit dashboard filtry.

2. **Prázdné „globální“ soubory `scripts.yaml` a minimální `scenes.yaml`/`automations.yaml` sekce mimo balíčky**
   - Nejde o chybu, ale je vhodné explicitně označit v komentáři, že jsou záměrně prázdné a vše je v packages.
   - Riziko: nízké.

### B) Opravit opatrně po ověření (střední riziko)
1. **Duplicitní orchestrace zón mezi central dispatch a staršími větvemi**
   - V `mode_auto.yaml` i `mode_boost.yaml` jsou fallback větve pro stav `heating_central_dispatch_enable = off`, zatímco `refactor_mode_schedule_override.yaml` drží central orchestraci.
   - Riziko: drift logiky (jedna větev bude opravena, druhá ne), race conditions při přechodech režimů.
   - Doporučení: sjednotit postupně do jedné „source of truth“, ale po etapách a s replay test scénáři.

2. **Dlouhé statické seznamy zón/helperů ve více souborech**
   - Opakují se v `mode_boost.yaml`, startup reconcile a watchdog souborech.
   - Riziko: při přidání nové zóny je vysoká šance na vynechání v některé části.
   - Doporučení: opatrně centralizovat seznamy přes script/templating helper nebo generátor, ale jen pokud je ověřená kompatibilita.

3. **Vysoká četnost logbook zápisů**
   - Velké množství `logbook.log` akcí v kontrolních tocích může zvyšovat šum a ztěžovat diagnostiku incidentů.
   - Riziko: provozní (noise), nikoliv funkční.
   - Doporučení: zavést úrovně „audit vs debug“ (např. guard boolean) až po potvrzení požadavků na observabilitu.

### C) Zatím pouze označit, neměnit (vyšší riziko / nejasná kauzalita)
1. **Časová logika override watchdogu založená na `last_changed`**
   - Potenciálně citlivé na restart nebo obnovu stavu entity.
   - Bez incidentních dat nelze potvrdit, že to v produkci selhává.
   - Změna by mohla měnit chování expirace override.

2. **Fail-safe notifikační strategie místo tvrdého zásahu**
   - Aktuální návrh v části fail-safe je konzervativní (notifikace + log), což může být záměr kvůli bezpečnosti provozu.
   - Bez provozního rozhodnutí není bezpečné přejít na agresivnější automatické zásahy.

## Co bylo v tomto kroku bezpečně opraveno
- V tomto kroku **nebyla provedena žádná změna runtime logiky** (záměrně).
- Přidán pouze tento auditní report jako podklad pro řízené malé kroky v dalších iteracích.

## Návrh minimální bezpečné testovací sady (pokud dnes není automatizovaná)
1. **Smoke scénář režimů**: Off → Auto → Eco → Boost → Auto, kontrola že nevznikají konfliktní zásahy do stejných climate entit.
2. **Boost lifecycle**: start Boost, kontrola `boost_until`, automatické ukončení, návrat rozvrhů.
3. **Manual override lifecycle**: ruční override + časovač, restart HA, kontrola startup reconcile.
4. **Dispatch fallback**: stejný scénář 1x s central dispatch ON a 1x OFF; porovnat cílové setpointy.
5. **Fail-safe simulace**: dočasně označit vstup jako unavailable a ověřit notifikaci + recovery.

## Doporučený další krok (konzervativní)
1. ✅ Provedeno: sjednocena textová nekonzistence `Chodba zachod` -> `Chodba záchod` v `heating/control/mode_boost.yaml` (pouze display text, bez změny entit/ID).
2. ✅ Provedeno: doplněn interní checklist `heating/analysis/zone_onboarding_checklist.md` + validační skript `scripts/validate_zone_list_consistency.py` pro kontrolu konzistence zón napříč seznamy.
3. ✅ Provedeno: doplněna smoke test matice `heating/analysis/heating_smoke_test_matrix.md` jako vstupní brána před centralizací seznamů zón.
4. Teprve následně řešit centralizaci seznamů zón (nejrizikovější část) s oporou o tuto testovací matici.

## Jak ověřit, že systém funguje správně po budoucích změnách
- Validace konfigurace Home Assistant (`check_config`) v cílovém runtime prostředí.
- Ruční replay výše uvedených 5 scénářů.
- Kontrola: nevznikají duplicitní konfliktní akce na `climate.set_temperature` ve stejném časovém okně.
- Kontrola, že notifikační kanály watchdog/fail-safe neprodukují falešně pozitivní alarmy.

## Další krok provedený v této iteraci (2026-05-21)
1. ✅ Rozšířena statická validace konzistence zón ve skriptu `scripts/validate_zone_list_consistency.py` o další kontrolní zdroje:
   - `heating/schedule/automation/startup/manual_override_startup_reconcile.yaml` (konzistence `manual_override` seznamu),
   - `automations.yaml` (konzistence `schedule_enable_<zona>` u blueprint instancí).
2. ✅ Zachována beze změny runtime logika topení (změna je pouze v auditním/validačním tooling).
3. ✅ Přínos: menší riziko tiché divergence seznamů při přidání nové zóny, dřívější zachycení chyby před nasazením.


## Další krok provedený v této iteraci (2026-05-21, navazující)
1. ✅ Rozšířena statická validace `scripts/validate_zone_list_consistency.py` o kontrolu `heating/core/groups.yaml`:
   - ověřuje se, že každá baseline zóna má `climate.<zona>` i v `group.heating_zones`.
2. ✅ Aktualizován onboarding checklist `heating/analysis/zone_onboarding_checklist.md` o povinnou kontrolu zápisu zóny do `heating/core/groups.yaml`.
3. ✅ Zachována runtime logika bez změny; úpravy jsou pouze v auditním tooling procesu a dokumentaci.
4. ✅ Přínos: nižší riziko, že nově přidaná zóna bude v orchestrace seznamech, ale nebude zahrnutá v centrální skupině zón.

## Další krok provedený v této iteraci (2026-05-21, dokumentační sjednocení)
1. ✅ Aktualizován `heating/analysis/zone_onboarding_checklist.md`, aby odpovídal aktuálním kontrolám ve validačním skriptu:
   - doplněna povinná kontrola `heating/schedule/automation/startup/manual_override_startup_reconcile.yaml`,
   - doplněna povinná kontrola `automations.yaml` pro `schedule_enable_<zona>` u blueprint instancí.
2. ✅ Upřesněn popis validačního kroku v checklistu, že zahrnuje i startup reconcile, blueprint schedule helpery a `group.heating_zones`.
3. ✅ Runtime logika topení zůstala beze změny; úprava je pouze procesní/dokumentační pro snížení rizika tichého vynechání zóny při onboardingu.

## Další krok provedený v této iteraci (2026-05-21, posílení statické validace)
1. ✅ Rozšířen skript `scripts/validate_zone_list_consistency.py` o další konzervativní kontroly bez zásahu do runtime:
   - kontrola konzistence `climate.<zona>` seznamu i v `automations.yaml` (vedle již hlídaného `schedule_enable_<zona>`),
   - kontrola existence `heating/core/zone_<zona>.yaml` pro každou baseline zónu.
2. ✅ Přínos: nižší riziko tichého rozjezdu nekonzistence při onboardingu nové zóny (např. helpery existují, ale chybí core zóna soubor).
3. ✅ Runtime logika topení zůstala beze změny; úprava je pouze v auditním validačním tooling procesu.

## Další krok provedený v této iteraci (2026-05-21, rozšíření onboarding guardrailů)
1. ✅ Rozšířen validační skript `scripts/validate_zone_list_consistency.py` o kontrolu existence souborů navázaných na každou baseline zónu:
   - `heating/schedule/preferences/helpers/schedule_helpers_<zona>.yaml`,
   - `heating/schedule/preferences/prefs/zone_<zona>_prefs.yaml`.
2. ✅ Aktualizován checklist `heating/analysis/zone_onboarding_checklist.md` o povinné ověření výše uvedených souborů pro každou novou zónu.
3. ✅ Upřesněn popis validačního kroku v checklistu, že skript nekontroluje jen seznamy helperů, ale i přítomnost klíčových zónových souborů.
4. ✅ Runtime logika topení zůstala beze změny; úprava je pouze v auditním validačním tooling procesu a dokumentaci.

## Další krok provedený v této iteraci (2026-05-21, zpřesnění blueprint guardrailů)
1. ✅ Rozšířen validační skript `scripts/validate_zone_list_consistency.py` o kontrolu konzistence zón i pro další blueprint helpery v `automations.yaml`:
   - `input_number.<zona>_last_comfort`,
   - `input_boolean.<zona>_schedule_active`,
   - `input_boolean.<zona>_manual_override`,
   - `input_select.<zona>_manual_override_type`,
   - `timer.<zona>_manual_override`.
2. ✅ Aktualizován `heating/analysis/zone_onboarding_checklist.md`, aby explicitně požadoval kontrolu výše uvedených blueprint input helperů pro stejný slug zóny.
3. ✅ Runtime logika topení zůstala beze změny; úpravy jsou pouze v auditním validačním tooling procesu a dokumentaci.
4. ✅ Přínos: nižší riziko „polovičního“ onboardingu zóny, kdy existuje `schedule_enable_<zona>`, ale chybí některý navázaný override/schedule helper.

## Další krok provedený v této iteraci (2026-05-21, kontrola konzistence core entity)
1. ✅ Rozšířen validační skript `scripts/validate_zone_list_consistency.py` o kontrolu obsahu `heating/core/zone_<zona>.yaml`:
   - pro každou baseline zónu se nyní ověřuje, že soubor obsahuje odpovídající entitu `climate.<zona>` (nejen existence souboru).
2. ✅ Aktualizován checklist `heating/analysis/zone_onboarding_checklist.md` o explicitní krok kontroly, že `heating/core/zone_<zona>.yaml` používá správnou `climate` entitu.
3. ✅ Runtime logika topení zůstala beze změny; úprava je pouze v auditním validačním tooling procesu a dokumentaci.
4. ✅ Přínos: nižší riziko tiché chyby při onboardingu, kdy soubor zóny existuje, ale omylem odkazuje na jinou `climate` entitu.


## Další krok provedený v této iteraci (2026-05-21, doplnění kontroly scheduler helperů)
1. ✅ Rozšířen validační skript `scripts/validate_zone_list_consistency.py` o kontrolu `heating/schedule/preferences/helpers/scheduler_booleans.yaml`:
   - ověřuje se, že každá baseline zóna má i `input_boolean.<zona>_schedule_active` v centrálním seznamu scheduler helperů.
2. ✅ Aktualizován `heating/analysis/zone_onboarding_checklist.md` o explicitní krok kontroly tohoto helperu.
3. ✅ Runtime logika topení zůstala beze změny; úpravy jsou pouze v auditním validačním tooling procesu a dokumentaci.
4. ✅ Přínos: nižší riziko tiché nekonzistence mezi orchestrace seznamy a UI/helper vrstvou plánování.

## Další krok provedený v této iteraci (2026-05-21, UI konzistence zónových map)
1. ✅ Rozšířen validační skript `scripts/validate_zone_list_consistency.py` o konzervativní kontroly UI vrstvy:
   - `heating/schedule/automation/startup/heating_ui_sync_selection.yaml` (`input_boolean.<zona>_manual_override` + `input_boolean.ui_select_<zona>`),
   - `heating/ui/packages/heating_global_manual.yaml` (`manual`, `timer`, `type_select` v `zone_map`).
2. ✅ Aktualizován checklist `heating/analysis/zone_onboarding_checklist.md` o povinné ověření výše uvedených UI seznamů.
3. ✅ Runtime logika topení zůstala beze změny; úpravy jsou pouze v auditním validačním tooling procesu a dokumentaci.
4. ✅ Přínos: nižší riziko tiché divergence mezi backend override helpery a UI výběrem/masovým manuálním ovládáním zón.
