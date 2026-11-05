# Návrh koordinace podpory a ověření hlavic; diagnostika doručení relé

Stav k 5. 11. 2026, časy **Europe/Prague (UTC+01:00)**. Návrh k review,
nikoli nasazená oprava. Výchozí main: `94e5f4685830ef13050578790bd94958430ff1d1`.
Uživatel schválil přípravu návrhu s testy, read-only diagnostiku a podmínky
pozdějšího ověření. V tomto úkolu nebyly provedeny zápisy do HA, reload,
restart, deployment, změny ochran ani fyzické zkoušky.

## Co je doložené

- V 21:13 jsou `sensor.heating_observer_status` i
  `sensor.heating_agent_platform` verze **0.4.5**. Platforma Běží,
  `agent_storage_error=null`, `actuator_control=false`, `service_call_api=false`.
  Existuje `sensor.heating_agent_ignition`; jeho aktuální stav 2 není počet
  incidentů za den. Safety OK bez violations/warnings, Permissions PASS,
  default_deny=true, runtime_deployment_enabled=false, Watchdog HEALTHY.
- Zdrojový základ obsahuje release z [PR #168](https://github.com/Bbambaaamm/heating/pull/168).
  Nový návrh nemění Observer ani predikci.
- Kotel zde **nepřipravuje TUV**. EMS WW indikace v této zprávě nejsou
  výjimkou z detekce ani vysvětlením legitimního ohřevu vody.

### Ranní událost: podpůrná cesta zmizela před zhasnutím

| Čas 5. 11. | Pozorování |
|---|---|
| 08:20:50.893 | Podpora přešla z `climate.1p_chodba` na none; log uvedl nula skutečně silně žádajících zón. |
| 08:20:59.587 | Chodba změnila hlášený cíl 29 → 15 °C; plyn zůstal hlášen ON. |
| 08:26:46.291 | Plyn OFF, čerpadlo OFF / modulace 0, servisní kód 305. |
| 08:26:47.435 | Relé nahlásilo OFF po EMS WW interlocku; to nepotvrzuje fyzickou polohu kontaktu. |
| 08:26:56 | Blok 76,2 °C, čerpadlo ON / modulace 100 %. |
| 08:27:06.297 | Flow V4 EMERGENCY_COOLING, blok přibližně 76,5 °C. |
| 08:27:11.730–08:27:31.903 | Sedm hlavic nahlásilo 29 °C. Koupelna v tomto okně cíl 29 nenahlásila. |
| 08:27:16 | Čerpadlo znovu OFF / modulace 0; ionizace 0, bez nového pozorovaného gas ON. |
| 08:27:51.334 | Helper potvrdil dvě cesty podle cíle a přírůstku motorových kroků. |
| 08:28:06.291 | Servisní kód 2965. |
| 08:28:26.29 | Maximum bloku i výstupu 93,8 °C. Jde o růst po zhasnutí, nikoli doložené nové zapálení. |
| 08:30:26–08:31:26 | Kód 203, blok 67,4 → 59,5 °C, RESTORING a následně NORMAL. |

V kritickém ranním okně byla hlášena sběrnice connected a teplotní záznamy
přibližně po 10 s bez unavailable. To nedokládá nezávislou fyzickou čerstvost
měření. PI ani motorové kroky nejsou měřením průtoku. Návrat podpory při
stále hořícím kotli je doložená časová souvislost, nikoli prokázaná příčina
poruchy. Výpadek čerpadla / průtok vyžadují samostatné odborné posouzení.

Koupelna zůstala na hlášeném cíli 15 °C. Motorový čítač měl přechodný reset
na 0 a následný přírůstek; nelze jej prostě odečíst přes reset. V sedmi jiných
epizodách dne koupelna 29 °C nahlásila (00:26:35, 06:18:15, 12:28:50,
14:31:05, 16:29:49, 18:30:45, 20:30:19). Historická příčina jediné chybějící
změny není určena: detailní ranní trace se již nedochovala. Přijetí povelu,
zápis cíle, pohyb motoru a otevření ventilu jsou různé důkazy.

### Večerní chyby Zigbee relé

| Čas | Důkaz | Co z něj plyne |
|---|---|---|
| 20:28:26.521 / 20:28:27.395 | Gas OFF / relé hlásí OFF. | Recorder zachytil oba hlášené stavy. |
| 20:28:32.621 | OFF interlock skončil `APS_NO_ACK`. | Není potvrzeno doručení; současně již existuje hlášené OFF. |
| 20:32:00.132–20:32:05.149 | Flow V4 poslal OFF a zaznamenal stejnou chybu. | Trace `7e3ead1da72ce8729af2e24e40360715`, `action/6/then/1`. |
| 20:33:01.544 / 20:33:06.640 / 20:33:14.668 | Další chyby OFF v ochranných cestách. | Duplicitní tracebacky nejsou nezávislé povely. |
| 20:38:24.883–20:38:29.927 | Běžný vlastník poslal ON, opět `APS_NO_ACK`. | Trace `91cb21412bdf7222c588c0725390ee9d`, `action/35`; nejde jen o opakování OFF. |
| 21:13 | Relé i plyn stále hlásí OFF, Flow NORMAL. | Bez nezávislé zpětné vazby kontaktu není doložena fyzická poloha relé. |

Chyby doručení se v dostupných večerních podkladech objevují také u dalších
Zigbee zařízení a předávání externí teploty. Relé hlásilo napájení přibližně
223 V a zařízení mělo jednorázově LQI 165 / RSSI −91 dBm. Jediný rádiový
snapshot neurčuje příčinu. Nebyla ověřena trasa, rodič, historie rušení ani
fyzický kontakt; nelze prohlásit vadné relé nebo konkrétní router.

Další diagnostika: bez přepínání relé zachovat trace/logy přirozených povelů,
porovnat jejich čas s recorderem a více zařízeními; při odborné návštěvě
ověřit kontakt/vedení termostatu a skutečnou cirkulaci i čerpadlo. Žádné
přemostění, rozpojování vodičů, reset poruch ani vynucený start v tomto úkolu.

## Obsah návrhu a hranice použitelnosti

1. `docs/candidates/hydraulic-coast-decision.jinja` je čisté rozhodnutí bez
   akčních služeb. Jedna nezávislá žádající zóna zachovává podporu. Při nule
   požadavků se žádá vypnutí výhradně u stávajícího normálního vlastníka relé;
   podpůrná zóna se nesmí započíst jako nový požadavek. Uvolnění navrhuje jen
   při explicitním relé OFF, plynu OFF a obou teplotách pod 60 °C. Jinak
   HOLD_COAST. Hranice 60 °C i 45 s pro přijetí dat jsou **návrhy k review**,
   nejsou nasazené ani ověřené pro tuto hydrauliku. Čerstvý příjem HA není
   záruka nového fyzického měření. Neznámá data vracejí UNVERIFIED, nikoli
   povolení podpory či startu. Limit místnosti 24 °C nebo ztráta způsobilosti
   vrací HANDOFF_REQUIRED; volající musí vyřešit náhradní cestu/bezpečný stav,
   nesmí bezmyšlenkovitě dál ohřívat místnost. Flow V4 má vždy přednost.
2. `docs/candidates/emergency-zone-open.yaml` je izolovaný worker pro jednu
   z osmi hlavic a konkrétní uloženou epizodu v3. Nejvýše dva pokusy o cíl
   29 °C, dvě čekání na hlášení po 5 s a mezi nimi 2 s. Změna epizody nebo
   opuštění EMERGENCY_COOLING ruší další pokus. Neprovádí zápisy do relé,
   EMS, master enable ani helperů. Výsledek target_reported / unconfirmed /
   cancelled neznamená fyzické otevření nebo průtok. Optimistická aktualizace
   integrace může také změnit `last_reported`; fyzický ACK z něj nelze vyvodit.
   Čas samotného servisního volání není těmito čekáními omezen. Již odeslaný
   příkaz nelze touto kontrolou vzít zpět.
3. Nativní HA testy simulují zařízení včetně nedoručení, tichého nepřijetí,
   starého cíle 29 °C bez nového hlášení, přechodu vlastníka a selhání jedné
   hlavice při úspěchu ostatních sedmi. Nejde o zkoušku fyzické instalace.

Soubory jsou mimo aktivní package include a nemají produkčního volajícího.
Tento PR je review prototyp, **není kompletní zapojitelná úprava Flow V4**.

### Co je nutné vyřešit před integračním PR

- Rozdíl root/live podpory: načtené live hashe guardu `ee2fd3ae18e1f1c9`,
  startu `2d39426dc2b95dd6`, Flow V4 `4c14ac71c6aa4fd1`. Root podpora počítá
  starší PI politiku, live skutečné požadavky zón. Hash je otisk v době čtení,
  nikoli trvalá záruka. Úplný readback centrálního dispatch skriptu konektor
  neposkytl. Bez nového přesného readbacku a sjednocení zdrojů nepřenášet
  kořenovou automatizaci do HA.
- Jeden koordinátor vlastní aktuální epizodu, deduplikuje `(episode, zone)`,
  sbírá výsledky všech osmi zón a chybějící výsledek výslovně označí. Musí
  omezit i celkovou dobu služby a počet paralelních povelů podle ZHA. Limit
  `max: 8` sám nezajišťuje vzájemné vyloučení stejné hlavice.
- Normální dispatch nesmí přepsat podrženou podpůrnou cestu; Flow V4 musí
  převzít autoritu bez soupeřícího zápisu. Obnova smí vracet pouze uložené
  cíle platné epizody. Nepřevzít kandidáta jako dalšího vlastníka relé.
- Spojené testy startu a nezávislého OFF guardu musí vycházet z přesných
  společných root zdrojů a počítat stejný nezávislý požadavek. Samostatná
  historická fixture nestačí. Jedna žádající zóna zůstává legitimní.
- Zachovat fault/EMS/teplotní kontroly, opakovatelnou RESTORING obnovu a
  nejvýše desetiminutový softwarový zámek bez prodlužování přechody.
- Nepřevádět target_reported ani motorový pohyb na fyzicky potvrzený průtok.
  Odborně prověřit příčinu růstu teploty při čerpadle hlášeném OFF.

## Měřitelné podmínky pozdějšího ověření

Nasazení vyžaduje samostatné schválení konkrétního integračního diffu,
úspěšné testy, přesný readback a běžný bezpečný postup konfigurace/zálohy.
Tento úkol je neprovádí. Následující rozsah je návrh, ne příslib výsledku.

| Oblast | Podmínka přijetí |
|---|---|
| Offline | Nativní testy na HA 2026.5.1 i 2026.9.2 a všech šest projektových kontrol PASS; test nulového a jednoho skutečného požadavku společně se startem i OFF guardem. |
| Vlastnictví | Žádné souběžné protichůdné zápisy; žádný opakovaný povel staré epizody; 8/8 zaznamenaných výsledků pro každé nouzové otevření. Ohlášené zrušení není úspěch. |
| Doručení hlavic | Každá hlavice vlastní výsledek, max. 2 pokusy; žádné celkové „otevřeno“ při nepotvrzené hlavici. Selhání jedné nesmí zrušit ostatní. Potvrzení 8/8 výsledků není požadavek osmi zón pro start. |
| Podpora | Ve 100 % zachycených přirozených doběhů žádné uvolnění podpory před schválenými release podmínkami; nula započtení pomocné zóny jako samostatného požadavku. Limit místnosti má definované bezpečné předání. |
| Telemetrie | Všechna povinná data explicitní a v přijatém stáří; mezery, unavailable, restart a reset čítače výslovně označit. Mezery vyřadit z kauzálního porovnání. |
| Relé | Nula nevysvětlených selhání doručení ON/OFF v ověřovaném vzorku. Stav OFF v HA nezaměnit za měření kontaktu. Opakovaný APS_NO_ACK znamená nesplněné kritérium a samostatnou diagnostiku. |
| Ochrany | Žádné nové Safety/Permissions/Watchdog/storage chyby; žádný EMS zápis, vynucený start nebo prodloužení softwarového zámku. |
| Provoz | První kontrola po ≥72 h a ≥20 přirozených ukončeních topení, potom celé 7denní okno. Bez tohoto vzorku NEDOSTATEK DAT; malé počty nejsou statistický důkaz spolehlivosti. |
| Poruchy | Každý nový přechod 2964–2967 individuálně analyzovat. Srovnání před/po pouze při podobné zátěži, počasí, pokrytí a konfiguraci. Poruchy na 100 startů pouze s platným rozdílem hardwarového čítače bez resetu; jinak poměr neuvádět. |
| Fyzický výsledek | Otevření/cirkulaci a stav kontaktu ověřit odpovídající nezávislou zpětnou vazbou nebo odborným měřením; software je nemůže doplnit odhadem. |

Plná denní/týdenní historie nebyla znovu rekonstruována v tomto dílčím úkolu.
Podkladem jsou konkrétní recorder okna, dostupné trace a omezené logy.
Ranní trace již chybí, logový výřez není úplná historie a atribut recent
není denní/týdenní součet. Z těchto dat nelze vyčíslit celkovou chybovost
sítě ani prokázat příčinu poruchy nebo účinnost dosud nenasazené úpravy.

## Validace návrhu

Výsledky úplného lokálního běhu a přesný commit doplní PR. Simulovaná chyba
doručení v testu je očekávaný vstup, nikoli chyba živého zařízení.
