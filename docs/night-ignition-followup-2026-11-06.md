# Diagnostické pokračování – noc 5.–6. 11. 2026

Kontrola 6. 11. přibližně 08:23–08:25 Europe/Prague. Pouze čtení HA.
Žádný merge, deployment, reset, povel relé/TRV ani zápis EMS.
Doplnění draft PR #171; prototypy zůstávají mimo aktivní HA konfiguraci.

## 1. Spouští to pokles pod 15 °C?

První start 6. 11. 00:29:16 není vysvětlen poklesem pokojů pod 15 °C:
v kontrolované historii 00:20–00:29 všech osm climate entit hlásilo teplotu nad
15 °C (nejnižší Michal přízemí 15,9 °C), všechny měly cíl 15 °C,
počet aktivních zón byl 0 a relé OFF. Blok kotle hlásil 18,0 °C.
Hlavní enable byl ON do 00:29:36; samotný enable není požadavek relé.

V okně 06:20–06:30 byly pod 15 °C chodba (14,4 °C) a koupelna
(13,9 °C; následně 14,2 °C v 06:30:48). Aktivní zóny hlásily 2,
ale master i relé OFF. Michal přízemí měl již na začátku okna cíl 29 °C;
nejde automaticky o skutečný uživatelský požadavek. Čtení pokojové teploty
z hlavice není nezávislé měření pokoje ani záruka fyzické čerstvosti.

| První ionizační signál | Blok / výstup při hraně | Relé |
|---|---|---|
| 00:29:16 | 18,0 / 18,0 °C | OFF |
| 00:32:06 | 18,3 / 18,3 °C | OFF |
| 06:30:16 | 15,9 / 15,8 °C | OFF |
| 06:33:06 | 15,9 / 16,2 °C | OFF |

V obou krátkých oknech number.boiler_nofrosttemp hlásí 5 a
switch.boiler_nofrostmode OFF. To není fyzická kontrola regulátoru ani
vyloučení všech jeho vnitřních ochranných funkcí. Nedokládáme žádný
interní zapínací práh 15 °C. Obvyklá regulace místnosti s cílem 15 °C
a nevysvětlená zapálení při hlášeném relé OFF jsou rozdílné jevy.

## 2. Pravidelnost EMS

Za 5. 11. 08:25 až 6. 11. 08:25 má ww3wayvalve dvanáct ON hran.
Jedenáct rozestupů je 7209,987–7220,079 s: přibližně 2 h + 10–20 s.
Zaznamenané poslední časy ON jsou 00:29:06, 02:29:26, 04:29:36,
06:29:56. Při prvním a posledním z těchto čtyř cyklů následovala
dvojice zapálení s rozestupem přibližně 170 s.

Pravidelnost je důvod prověřit vnitřní periodickou sekvenci regulátoru
a mapování EMS; její konkrétní funkce ani příčina nejsou určené.
WW čítač přidal čtyři starty; wwactivated zůstalo OFF. Kotel nedodává
TUV, kterou zajišťují samostatné karmy. Nejde o potvrzenou legitimní
přípravu TUV.

## 3. Prokázaný pád vstupu do nouzové sekvence

V 06:30:36,721 loguje Flow V4 ValueError při převodu unavailable přes
int bez defaultu v seznamu osmi motorových čítačů. Sklepní čítač byl
v 06:25 unavailable a vrátil se až 06:30:47,515; climate až 06:30:44,447.
Ze stavové historie: při poruše 2964 v 06:30:36 nepřišel přechod do
EMERGENCY_COOLING. Ten nastal až při další poruše v 06:33:26.

Stejná nechráněná baseline je ve vzdáleném main automations.yaml
(blob 829f35084cf0f9e5e289e05a42ff870c7ebf0c05). Root zdroj ji počítá
před přechodem do EMERGENCY_COOLING. Přesný úplný live readback nebyl
dostupný: config_get_automation vrací INVALID_ARGUMENT; trace config
vrací jen alias a mode. Shodu celé konfigurace proto netvrdíme.
Živý log však obsahuje přímo problematickou šablonu.

Následně čítač sklepa hlásil 954438 → 0 → 954438 v 06:30:47,
06:33:33, 06:34:03. Příčina nulové hodnoty není doložena; skok se nesmí
automaticky považovat za otevření ventilu.

### Zadání cílené opravy pro samostatné testy a review

- Chybějící motorová baseline nesmí zablokovat vstup do nouzového režimu
  a pokusy o vypnutí relé / otevření ostatních způsobilých hlavic.
- Neplatná baseline zůstane neznámá; prosté int(0) bez validity příznaku
  může po obnovení čítače vyrobit falešný velký přírůstek.
- Reset, regresi a návrat starého kumulativního čítače odlišit od nové
  motorové odezvy. Nezaměňovat ji za skutečný průtok.
- Testovat všechny pozice neplatného čítače, unavailable→číslo,
  číslo→0→staré číslo, chybu povelu jedné zóny a souběh se změnou epizody.
- Zachovat pravidlo jedné legitimně žádající zóny, zákaz EMS zápisů,
  stávající normálního vlastníka relé a limit historického zámku 10 min.
- Jde o dosud nepřipravenou opravu aktivní sekvence; 18 prototypových
  testů z PR #171 neprokazuje její správnost.

## 4. HARD_LOCKOUT a Zigbee

| Událost | Čas |
|---|---|
| První timer ON | 00:29:36,634 |
| První HARD_LOCKOUT | 00:39:12,292 |
| Automatický návrat NORMAL | 00:39:36,015 |
| Druhý timer ON | 06:33:26,740 |
| Druhý HARD_LOCKOUT | 06:42:39,792 |
| Automatický návrat NORMAL | 06:43:26,010 |

Oba timery doběhly přibližně za 10 min od začátku emergency, bez nového
desetiminutového prodloužení při přechodu HARD_LOCKOUT.

Trace Flow V4 d00c670184e159386e77558900f9b054 volá v 06:35 obnovu.
Její child trace 7fb3850b1ad6aace3c6648530618a8e3 dokládá APS_NO_ACK
u set_temperature na sklep a Michal přízemí v 06:38:46, 06:38:52,
06:38:59 a u OFF relé v 06:39:29. Obnova ponechala restore_verified OFF.
Nadřazená sekvence po dalším čekání přešla do HARD_LOCKOUT;
také OFF relé v 06:42:34 a 06:42:39 selhalo doručením.
Důvod nepotvrzené obnovy je doložen, fyzická poloha ventilů či relé nikoli.

Oba kanály relé unavailable od 02:43:49, návrat prvního 04:55:54,
druhého 04:56:01. Při kontrole ZHA: relé RSSI −87 dBm / LQI 169,
sklep −88 / 168, Michal přízemí −90 / 166; tři zásuvky −68 až −71 dBm.
Je to okamžitý pohled, nikoli záznam konkrétní trasy, sousedů nebo příčina
nočního výpadku. Konkrétní parent relé nebyl zjištěn.

## 5. Databáze a čerstvost watchdogu

Dva snímky platformy mají skutečné časy writeru 5. 11. 08:24:56,292 a
6. 11. 08:25:07,249; první vrací recorder jako stav na začátku okna.

| Ukazatel | Starší | Novější | Přírůstek |
|---|---:|---:|---:|
| SQLite soubor B | 5864394752 | 6076850176 | 212455424 |
| state_samples | 637319 | 657075 | 19756 |
| optimization_samples | 635407 | 655163 | 19756 |
| event_log | 841323 | 866611 | 25288 |
| watchdog_evaluations | 57744 | 59236 | 1492 |

Nárůst hlavního souboru přibližně 202,61 MiB / 24 h, 3,62 %.
database_bytes je stat hlavního souboru, nezahrnuje WAL/SHM.
Jde o SQLite agenta, ne o HA recorder. Recorder samostatně uvádí odhad
3944,27 MiB. Supervisor uvádí celkem 56,3 GB a použito 26,4 GB.
Sken main database.py (blob 0fb1c338dd12527bf5b8242ed7545ee96b0f4de9)
nenašel retenční DELETE/VACUUM. Raw event_log chrání append-only triggery.
Vzorky a analýzy se ukládají i do oddělených tabulek a část payloadů do
event_log. Bez měření velikostí tabulek nelze určit hlavního původce růstu.

Další návrh: nejprve read-only inventura velikostí DB/WAL/SHM a tabulek,
potom review archivace/rotace s uchováním incidentů a auditní návaznosti.
Nic nemažeme ani nepouštíme VACUUM. Přírůstek za jeden den není přesná
dlouhodobá předpověď kapacity.

Watchdog entity hlásí HEALTHY se starým last_reported z 5. 11. 21:05:40.
Čítač uložených watchdog vyhodnocení přitom roste: činnost vyhodnocování
je doložená i novými zápisy. Staré datum entity samo nedokazuje zastavení
agenta; obsah atributů nemá samostatný evaluated_at/heartbeat.
Pro jednoznačné prokázání čerstvosti navrhnout read-only timestamp a
sequence posledního vyhodnocení. Bez této instrumentace netvrdit
nezávisle prokázanou čerstvost konkrétního zobrazeného reportu.

## 6. Fyzické ověření a pořadí dalších kroků

1. Prioritně připravit samostatnou opravu pádu nouzové sekvence a testy.
2. Diagnostikovat spolehlivost komunikace relé i sklepních hlavic; zlepšení
   doručení neprokazuje fyzický kontakt ani průtok.
3. Technik nezávisle časově zaznamená kontakt správného kanálu i požadavek
   na vstupu kotle při přirozené regulaci; identifikuje druhý kanál a případné
   paralelní cesty. Rozhraní snímání zvolí až podle skutečného obvodu a
   dokumentace zařízení. Teprve potom lze navrhnout konkrétní HA čidlo.
4. Servis porovná dvouhodinové EMS události s displejem kotle, čerpadlem,
   třícestným ventilem a skutečnou cirkulací. Žádné vynucené zkušební starty.
5. Uživatel může bez manipulace se zapojením zaznamenat čas, video displeje
   kotle a LED relé a fotografii tlaku. LED/cvaknutí nejsou měření kontaktu.
6. Uchovat stínový režim predikce i kandidátů Intelligence/Composite.

Podrobnější existující protokol:
[nezávislé ověření kontaktu relé](relay-contact-verification-2026-11-04.md).

Závěr: příčina zapálení zůstává UNKNOWN. Nově je doložena konkrétní
softwarová chyba vstupu do nouzové sekvence a chyby doručení během obnovy.
Nápravu těchto chyb nelze vydávat za opravu vnitřního chování nebo hydrauliky
kotle. Živá konfigurace v této kontrole nebyla změněna.
