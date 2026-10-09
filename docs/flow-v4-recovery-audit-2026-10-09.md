# Audit a oprava Flow V4 – 9. 10. 2026 (live HA)

## Rozsah a zdroje

- Live Home Assistant **Core 2026.9.2**, HA OS 18.2, Bosch přes EMS-ESP a Danfoss Zigbee TRV.
- Konfigurace ověřená přes HA API: Flow V4, bezpečný start kotle, obnovovací skript, čtyři šablonové pomocníky a pasivní watchdog dlouhé obnovy.
- Historie EMS kódů, relay/hořáku, průběhu chlazení a potvrzení motorů hlavic; systémový log Zigbee.
- Přesný **read-only snapshot** těchto storage-managed objektů: [`live-storage-snapshot-2026-10-09-v4.json`](live-storage-snapshot-2026-10-09-v4.json). **Nikdy ho nenačítat jako další HA package** a nevytvářet duplicitní YAML řídicí automace.

## Co potvrzují data

| Datum, čas Europe/Prague | Událost | Závěr |
|---|---|---|
| 6. 10. 13:34 | EMS 2964 při TUV, topné relé již OFF | Nezpůsobil ji požadavek HA na radiátorové topení; možné interní hydraulické/TUV omezení |
| 7. 10. 13:38 | EMS 2965 | Překročená výstupní teplota; historie nezaručuje stejnou příčinu jako 2964 |
| 8. 10. 21:44–21:59 | Dvě cyklování EMERGENCY/RESTORING, druhé skončilo HARD_LOCKOUT | Nouzové otevření TRV bylo jednou potvrzeno, podruhé ne včas |
| 9. 10. 12:48:03 | EMS 2964 při topení, relé ON, heatblock 52,6 °C | Nízký průtok nelze spolehlivě poznat jen prahovou teplotou 72 °C |
| 9. 10. 12:48–12:51 | Restartované přechody RESTORING, opakované volání restore skriptu | **Závada obnovovací logiky:** `mode: restart` a minutový trigger ve stejné automatizaci |
| 9. 10. 12:51:49 | Úspěšný návrat NORMAL, master ON | Recovery je možné, pokud je ověřena obnova hlavic, EMS/fault-clear a nouzové průtokové cesty |

### Pozor na falešné důkazy průtoku

- `sensor.boiler_pc0flow` ukazoval **0 l/h**, ale poslední změnu/hlášení měl od 8. 10. 02:21. Pro řízení jej nepovažovat za spolehlivý průtokoměr.
- `heating_flow_relief_confirmed_paths` je odvozeno z dosažení cíle 29 °C a zvýšení **počtu kroků motoru**; prokazuje aktivitu hlavic, **nikoli skutečný průtok výměníkem**.
- `heating_flow_paths_verified_v4` je **historické potvrzení pro jednu emergency recovery session**, není platná indikace otevřeného průtoku v NORMAL.
- `sensor.kotel_effective_min_active_zones` je 2, i když konfigurační `input_number.kotel_min_active_zones` je 1. Dvě započítané PI zóny stále negarantují minimální hydraulický průtok.
- U 2964 při TUV nepomůže pouhé otevření radiátorových TRV: hydraulická cesta třícestného ventilu je odlišná.

## Provedeno v živém HA

1. Vytvořena storage automation `automation.topeni_v4_periodicka_kontrola_pouze_nouzoveho_chlazeni`, každou minutu pouze pro `EMERGENCY_COOLING` vyšle `heating_flow_v4_reconcile`. **Sama nemění relé ani teploty.**
2. Z Flow V4 odebrán jeho univerzální minutový trigger. Kritické EMS/heatblock triggery i explicitní recovery event zůstávají. Tím se minutový tick nedostane do rozpracovaného `RESTORING` a neukončí dlouhý restore skript.
3. Na úspěšném konci `RESTORING → NORMAL` se po publikaci stavu NORMAL vymaže starý pomocník `heating_flow_paths_verified_v4`. Když v době úpravy již bylo NORMAL, starý příznak byl jednorázově vymazán v HA.
4. V HA přidán čistě pasivní watchdog: pokud `RESTORING` trvá 10 minut, vytvoří stabilní upozornění a pošle jednorázový mobilní alarm. Při NORMAL/HARD_LOCKOUT oznámení smaže. Watchdog nikdy nesepíná kotel.
5. **Již dříve** bylo v HA opraveno spouštění `automation.kotel_v4_bezpecny_start_podle_politiky`, aby změny atributů senzoru `kotel_should_be_on` nerestartovaly 120s čekání. Tato konfigurace je součástí snapshotu.
6. V předchozím paralelním zásahu byla do Flow V4 zavedena podmínka: pokud je kotel už pod 60 °C, nepokračuje do RESTORING bez potvrzených cest ani před dokončením 120s timeoutu; lockout při nepotvrzených cestách se zachovává.

## Zachované bezpečnostní invarianty

- 2964, 2965, 2966, 2967 a kritická teplota nad 72 °C stále vyvolávají emergency, okamžitě vypínají topný master a relé.
- Emergency otevírá TRV pouze **kvůli odvodu tepla** a poté vrací cíle podle rozvrhů/ručních zásahů.
- Kotel v `RESTORING` ani `HARD_LOCKOUT` nesmí sepnout. Povolí se jedině po potvrzení obnovy všech zón, stavu bez faultu, spojení EMS, dostatečném ochlazení, potvrzených cestách, a jen pokud byl start před poruchou povolen.
- Zůstává 120s minimální softwarová prodleva pro zapnutí topného relé; nejde o minimální interval výrobce mezi dvěma zapáleními hořáku.
- Nikde nebyla deaktivována výrobcem zajištěná tepelná ani hydraulická ochrana, upravován výkon hořáku, čerpadlo ani ručně resetován fyzický kotel.

## Audit Zigbee a konfigurace

- Log HA opakovaně zaznamenal `TXStatus.APS_NO_ACK` / `device did not respond` u hlavic. To může zdržet nastavení 29 °C i následnou obnovu. Samotné LQI 180–219 u dostupných TRV nevylučuje občasnou ztrátu ACK.
- V logu je chyba načítání package `heating/control/refactor_mode_schedule_override.yaml`: **duplicate key `alias` in `script`**. Zdrojový soubor na GitHubu `main` při kontrole takovou duplicitu na první pohled neměl. Skutečný živý `/config` nelze z použitého HA konfiguračního API přečíst a binární porovnání proto **zatím není potvrzeno**. Neprovádět naslepo přepis.
- Neaktivovat historické `topeni_flow_relief_*` automace paralelně s V4. Bezpečnostní state machine musí zůstat jediným vlastníkem nouzové posloupnosti.

## Testování a podmínky pro další nasazení

- CI statické regrese: `python -m unittest tests.test_flow_v4_live_snapshot -v` nebo `python -m unittest discover -s tests -v`.
- Živá konfigurace musí odpovídat verzi snapshotu dle `config_hash`; při změně jiným agentem se audit musí znovu provést.
- Ověřit trace: běh V4 v `RESTORING` již není každou minutu rušen; samostatný minutový poll je zablokován mimo EMERGENCY.
- Z historie bez zásahu do kotle vyhodnocovat reálný další topný cyklus: relé, hořák, výstupní teplota, pumpa, EMS kód 2964–2967, aktivační počty zón, požadavky PI a změny rozvrhů.
- V případě nové 2964 při TUV **se nemá obcházet ochrana kotle**. Prověřit tlak, hydrauliku třícestného ventilu, čerpadlo, primární výměník a vhodné skutečné měření průtoku.
- Pro skutečnou **prevenci 2964** je potřeba spolehlivá informace o fyzickém průtoku či výrobcem podporovaný hydraulický test. Kód z pouhých PI procent a kroků TRV není dostatečným důkazem. Proto nová úprava řeší obnovovací regresi, ale **negarantuje odstranění všech mechanických poruch**.

## Verzování a synchronizace

GitHub `main` a větev lokálně nasazená v HA mohou být různé: při auditu byla starší větev `nasazeni/topeni-20260918` za `main` o 23 commitů. Úpravy storage-managed automatizací v HA se **automaticky nepropisují** do `/config` ani Git indexu. Tento PR uchovává přesné testovatelné snapshoty živé konfigurace, neprovádí plošné přepsání `/config` a zachovává stávající řídicí objekty. Kompletní obousměrné srovnání lokálního Git working tree vyžaduje autorizovaný přístup k HA `/config` (nebo jeho read-only export) a bezpečné porovnání rozdílů.
