# Opravy Q1 a Q3 — příprava k review, bez živého nasazení

## Rozsah a zjištěné chyby

Zdroj predikce byl načten 4. 11. 2026 přes konfigurační API, identifikátor
`predictive_heating_shadow_recalc`, hash `d87ddfd4b30c6174`. Export je v
`candidates/predictive-shadow-live-2026-11-04.json`; jde o konfiguraci bez
provozní telemetrie a přístupových údajů. `bias_min` v tomto zdroji již existuje
a tuto dřívější chybu tato změna znovu neopravuje.

1. Neúspěch `weather.get_forecasts` dosud přerušil celou sekvenci. Kandidát
   inicializuje odpověď a pokračuje jen přes tuto očekávanou externí chybu.
   Nejbližší hodinový záznam musí být nejvýše hodinu od požadovaného času a mít
   platné hodnoty. Náhrada používá skutečné aktuální počasí nejvýše hodinu staré,
   výslovně označené v každé zóně i souhrnu jako `DEGRADED`. Bez platného počasí
   se nevymýšlí venkovní teplota a stav uvádí nedostupnou predikci.
2. Každá zóna má vlastní ohraničenou sekvenci. Chyba šablony či zápisu jedné
   zóny nezastaví zbylé zóny; selhání zůstane v HA trace. Úspěšný zápis vyžaduje
   shodu hodnoty a `last_reported` z aktuálního pokusu. Tím starý shodný text
   nemůže potvrdit nový zápis. Souhrn i událost `heating_prediction_recalculated`
   obsahují počty/seznamy dokončených, datově platných a předpovědí pokrytých zón.
3. `input_datetime.predictive_heating_last_attempt` odděluje pokus od dosavadního
   `input_datetime.predictive_heating_heartbeat`. Heartbeat znamená všech osm
   potvrzených zápisů s platnými vstupy; může být `DEGRADED`, pokud používá
   výslovně označené aktuální počasí. Chybějící data či zápis heartbeat neposunou.
   `input_text.predictive_heating_run_status` rozlišuje `OK`, `DEGRADED`,
   `INCOMPLETE` a probíhající pokus. Zrušený/přerušený běh nedostane dokončovací
   heartbeat. Stavové texty mají maximálně 255 znaků. Výpočet naučeného modelu,
   bias a mapování osmi zón zůstávají zachovány.
4. Intelligence dříve povolila `PROPOSED_FOR_HUMAN_REVIEW`, pokud byl každý
   incident zachycen byť pozdě. Composite měl stejný problém s opožděním.
   Nyní vyžadují včasné zachycení všech validačních poruch a nejvýše 10 %
   varovaných normálních kontrol; nejméně 1 validační poruchu a 10 kontrol.
   Composite totéž kontroluje i na evidence splitu. Počítá se z konzistentních
   celočíselných četností, nikoli uloženého procenta. Mez 10 % je konzervativní
   kritérium **pro předání k review**, ne automaticky naučená nebo bezpečnostní
   provozní mez. Malý holdout není důkaz statistické spolehlivosti. Při startu
   runtime proběhne nový replay, i když se generace učení nezměnila.
5. Safety Sentinel měl výjimku pro EMS WW příznaky a mohl při nich vynechat
   S06 pro hořák ON s relé OFF. Výjimka je odstraněna a synchronizovány jsou
   obě kopie invariantů S01–S20. WW není dokladem legitimního odběru TUV.

## Diagnostika zapálení

Observer 0.4.5 čte navíc `sensor.boiler_flamecurr` (pouze validní µA),
`sensor.boiler_burnstarts`, `sensor.boiler_heatstarts` a `sensor.boiler_wwstarts`.
Změny těchto entit zachytává existující listener i při vypnutém topení. Samostatná
diagnostická větev nezávisí na způsobilosti cyklu pro učení ani na master ON.
Hrany proudu a změny dostupnosti/jednotek se zaznamenávají okamžitě; běžné
kolísání mezi kladnými hodnotami používá existující periodický odběr vzorků,
aby každá změna proudu nevytvářela další úplný snímek všech zón.

- Pozorovaná hrana gas OFF→ON nebo proudu 0→kladný vytvoří podklad zapálení.
  Jde o hlášený signál; kladný proud sám není měřením fyzického kontaktu relé.
  Opakované kolísání proudu během hlášeného hoření nepřidává starty.
- Rozdílné signály a jednotlivé přírůstky čítačů se přiřazují v okně 120 s.
  Čítač může přijít před hranou i po ní; podklad si ponechá časy a původní stav
  relé u hrany. Nová hrana stejného signálu vytváří nový start. Okno 120 s je
  pracovní předpoklad časové korelace, nikoli důkaz společné fyzické příčiny.
- Čítač bez přiřaditelné hrany zaznamená neatributovaný přírůstek s neznámým
  relé v okamžiku zapálení. Příchod zprávy při relé OFF nedokazuje, že při OFF
  také vznikl start. Celkový čítač a podčítače heat/WW se nesčítají.
- Restart, explicitní capture gap nebo mezera nad nastavený telemetry gap
  přeruší korelaci. První dostupný vzorek není nová hrana. Reset/pokles,
  `unknown`/`unavailable`, nečíselný a neceločíselný čítač nezvýší počet startů.
  Neatributované přírůstky zůstávají po restartu neatributované; diagnostika
  nedoplňuje domnělé starty v době bez pozorování.
- `relay_off_starts` vyžaduje explicitní relé OFF na obou stranách hrany.
  Současný přechod relé ON→OFF nebo neznámé relé znamená neznámý stav u startu.
  WW kontext, čerpadlo, teploty, proud a čítače zůstávají součástí podkladů.
  Samotný růst teploty po zhasnutí se nepočítá jako zapálení.
- Nový senzor `sensor.heating_agent_ignition` ukazuje kumulativní počet
  pozorovaných hran při hlášeném relé OFF od instalace. Journal/model uchovává
  souhrn i posledních 50 záznamů, DB eviduje vytvoření a následná doplnění jako
  append-only události s týmž correlation ID. Počet událostí není počet startů.
  Atribut `recent` je vyloučen z HA recorderu, aby se detail zbytečně nekopíroval.

## Předání a návrat

V tomto kroku se neposílají žádné příkazy do HA, nemění se živé automatizace
ani řízení kotle. Kandidát predikce je **mimo** adresář `heating/`, který načítá
`configuration.yaml`; navíc má `initial_state: false`. Neslouží jako druhá
automatizace vedle původní. Připravené změny jsou určeny do samostatného PR.

Před pozdějším nasazením provést review, znovu načíst/porovnat živý zdroj,
zálohovat původní konfiguraci a helpery, vytvořit dva nové stavové helpery a
**nahradit** existující automatizaci přes konfigurační API. Zachovat ověřené
mapování entit a jednotky počasí °C a km/h. Při změně jednotek musí být doplněna
konverze a test. Po schváleném nasazení přesunout výslednou konfiguraci do
kanonického zdroje, začlenit do `main` a provést zpětné porovnání HA/Git včetně
helperů a zapnutí automatizace. Tento PR sám takovou shodu netvrdí.

Při návratu predikce nahradit její konfiguraci uloženým původním exportem a
obnovit původní stav zapnutí; nové dva helpery lze ponechat nevyužité. Observer
vrátit na předchozí zdrojovou verzi a znovu načíst integraci/restartovat dle
schváleného postupu; nemažou se DB, journal ani model. Nové pole modelu je
aditivní, nedochází ke změně `site_revision` nebo zahození existujících epizod.

## Ověření

Testy spouštějí skutečný HA Core se simulovanými službami a zařízeními; nejde
o fyzický test relé. Pokrývají výpadek a neplatnou předpověď, zastaralé počasí,
úplnost osmi zón, chybějící teplotu, selhání i tiché ignorování zápisu, zachování
bias, staré hodnocení v DB, včasnost/falešné poplachy v obou typech kandidátů,
jednotky proudu, korelace/pořadí čítačů, krátké starty, restarty, výpadky a
residuální růst teploty. Stávající AST kontrola dál zakazuje aktuátorové služby
ve všech modulech observeru. Výsledky celé sady a ochranných kontrol uvádí PR.
