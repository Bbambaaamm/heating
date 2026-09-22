# Pasivní párování a interní restarty — 22. 9. 2026

Tato vrstva rozšiřuje existující `heating_response_passive_log_v1`. Nemění
observer 0.1.0, řízení topení, bezpečnostní automatizace ani nastavení hlavic.
Povoleny jsou pouze zápisy do vlastních diagnostických input_text a deníku.

## Sestavení a instalace

`python3 scripts/passive_diagnostics/build.py /tmp/heating-diagnostics`
vytvoří `diagnostics.json`. Jde o podklady pro konfigurační API, nikoli automaticky
načítaný HA balíček. Merge do GitHubu tuto instalaci neopakuje.

1. Zálohovat aktuální zdrojovou automatizaci a pohled `heating-observation`.
2. Založit všech 12 input_text podle `helpers`, max 255, bez initial.
3. Vytvořit dvě automatizace z `pair` a `shadow`; při aktualizaci použít čerstvý
   config_hash. Hodnoty pomocníků mají prefix `v2:`, aby zůstaly řetězci.
4. Do zdrojové automatizace vložit `source_event` bezprostředně za proměnnou
   `record`, pouze pokud tam událost ještě není. Zachovat ostatní akce.
5. Připojit sekci z `scripts/passive_diagnostics/dashboard.py` do stávajícího
   pohledu; neopakovat ji při aktualizaci. Žádné přepsání celého automations.yaml.
6. Ověřit stopy obou automatizací, heartbeat a přenos pasivní události.

## Význam měření

Párování zpracovává skalární set_temperature. Slučuje stejný cíl do 30 s od
posledního povelu, ale zachovává první čas. Nový cíl předchozí záznam ukončí.
Zvlášť měří novou změnu hlášeného cíle a první změnu PI libovolným směrem.
Neprokazuje příčinnost, doručení Zigbee, pohyb ventilu ani fyzický průtok.
Po 600 s se neúplné párování uzavře; restart, nedostupnost a přeházené události
jsou výslovně označeny. Zpracování opožděné o více než 30 s se nepáruje.
Další typy povelů zůstávají v původním surovém deníku.

Pravidla restart-shadow-v1 platí pouze v pauze po zachyceném hoření uvnitř
souvislého požadavku relé: R1 méně než 3 hlavice PI≥10 %, R2 méně než 2 PI≥20 %,
R3 R1 souvisle 30 s. Čas začátku není oříznutý na 180 s. Hodnotí se interní
start, nikoli první start požadavku. Neznámá historie po spuštění se nedoplňuje.

První změna lastcode na novou událost 2964–2967 nebo aktuální servisní kód
určuje první čas poruchy. Pozdější hlášení v 10minutovém shluku čas neposouvá.
Pouhá změna koncového času stejného lastcode není novou poruchou.
Okno končí 300 s po vypnutí hořáku nebo při dalším startu, maximálně po 2 h.
Chybějící data, reset, mezera >45 s, TUV či zásah řízení před chybou vedou
k neúplnému oknu, nikoli k úspěšnému výsledku. Čerstvost last_reported je
čerstvostí hlášení v HA; nepotvrzuje nové fyzické měření či polohu hlavice.

Každé pravidlo má počet varování v oknech bez poruchy, poruch s předstihem
alespoň 60 s a poruch bez dostatečného předstihu. 60 s je experimentální
porovnávací rozpočet, nikoli bezpečnostní limit. Počty začínají od nuly a
nemíchají se s předchozími cykly observeru. Pozorování neprokáže, že otevření
hlavic skutečně zabrání poruše. Parametry se automaticky neučí ani neuvolňují.

Podrobné záznamy: `Topení – párování DATA` a `Topení – restart SHADOW DATA`.
Lidsky čitelné události jsou přiřazeny sensor.heating_observer_learning.
Retence se řídí stávajícím recorderem HA; dlouhodobý archiv tato vrstva negarantuje.

## Ověření a návrat

Testy: `python3 -m unittest discover -s tests -p test_passive_diagnostics_v2.py`
(vyžadují Jinja2). Pokrývají časové pořadí, duplicity, výpadky a oddělení prvního
hlášení poruchy od pozdějšího kódu; kontrolují absenci služeb ovládajících zařízení.
Šablony je navíc nutné ověřit v HA a zkontrolovat skutečné běhové stopy.

Návrat: vypnout pouze `heating_response_pair_v2` a `heating_restart_shadow_v1`,
ze zdroje odstranit pouze událost `heating_response_observed_v2` a odstranit
novou sekci přehledu. Původní logy, observer a ochrany ponechat. Pomocníky lze
uchovat jako diagnostickou historii. Neobnovovat celý starý soubor automatizací.
