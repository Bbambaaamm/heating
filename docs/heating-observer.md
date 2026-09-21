# Pozorovací režim topení a průběžné vyhodnocování

Tato změna přidává místní integraci `heating_observer`. Průběžně zaznamenává
provoz, vyhodnocuje cykly a aktualizuje porovnání varovných pravidel.
**Nemá žádnou službu ani kód pro ovládání relé, hlavic, rozvrhů nebo parametrů kotle.**

Verze 0.1.0 je první pozorovací část návrhu prevence nedostatečného odběru.
Aktivní příprava odběrné větve a řízené dochlazení nejsou touto změnou zapnuty.
Stávající regulace a poruchové ochrany dále řídí soustavu.

## Co se děje automaticky po instalaci

1. Každých 10 sekund se při provozu pořídí snímek teplot, hořáku, čerpadla,
   relé, servisního režimu, politiky HA a všech osmi hlavic.
2. Změny teplot a zásadních stavů vyvolají také okamžitý snímek. Periodické
   snímky v úplném klidu se omezí na jeden za minutu.
3. Každý zachycený start hořáku zahájí vyhodnocovaný cyklus. První start
   požadavku se odlišuje od dalšího zapálení při stále sepnutém relé.
4. Při kódu 2964–2967 se uloží incident včetně předchozího kontextu.
   Následující údaje zůstanou v průběhu a souhrnu cyklu.
5. Po skončení pozorovacího okna se aktualizuje porovnání 15 hypotéz:
   četnost varování před chybou, předstih a varování v cyklech bez chyby.
6. Přehled je dostupný ve dvou diagnostických senzorech a v souboru
   `report.json`. Nejpříznivější hypotéza může být označena jako návrh
   k dalšímu ověření. Nevytváří se z ní aktivní bezpečnostní nastavení.

Vyhodnocování běží v HA bez otevřeného chatu, bez internetové služby a bez
průběžných požadavků uživatele. Teprve instalace a načtení integrace tento
proces skutečně spustí.

## Co zde znamená „učení“

Verze 0.1.0 používá vysvětlitelné porovnávání předem zadaných hypotéz:

- počet hlavic s hlášeným PI požadavkem alespoň 10, 20, 30 nebo 50 %;
- varování při počtu menším než jedna, dvě nebo tři;
- růst teploty bloku alespoň 0,2 nebo 0,5 K/s;
- teplota bloku alespoň 75 °C.

To jsou **experimentální hypotézy v pozorovacím režimu**, nikoli bezpečnostní
meze tohoto kotle. Procenta stále neznamenají měřený průtok ani ověřenou
polohu ventilu. Hlavice ve stavu `off` se nezapočte ani se starým vysokým PI.

Čas `last_reported` znamená přijetí stavu v HA. Sám nepotvrzuje nové
fyzické měření; aktualizace jiného atributu hlavice nepotvrzuje čerstvost
jejího PI požadavku. Výsledky proto zůstávají porovnáním hlášených stavů.

Každý další úplný cyklus mění výsledky porovnání. Model drží souhrny posledních
500 cyklů příslušné revize soustavy a průběžné počítadlo zaznamenaných
přechodů do poruchy. Starší podrobnosti podléhají popsané rotaci souborů.
Nejde o neomezený archiv veškerých dat.

Pro každou hypotézu se uvádí:

| Hodnota | Význam |
|---|---|
| `fault_incidents` | Počet hodnocených skupin poruch |
| `timely` | Varování s předstihem alespoň podle porovnávacího času |
| `late_or_missed` | Varování pozdní nebo chybějící |
| `observed_no_fault` | Úplná pozorovací okna bez zaznamenané poruchy |
| `warned_no_fault` | Kolikrát hypotéza varovala také v takovém okně |
| `lead_median_s` | Medián dostupného předstihu, omezeného pohledem 180 s zpět |

Varování ze stejného snímku, který již obsahuje poruchu, se nezapočítá jako
předpověď. Nepoužívají se ani hodnoty z budoucnosti k doplnění staršího stavu.

Hypotézy se řadí podle počtu včas zachycených skupin poruch a potom podle
počtu varování bez následné chyby. Kandidát se vůbec nezobrazí před alespoň
třemi hodnocenými skupinami poruch a dvaceti úplnými okny bez chyby, ani pokud
žádná hypotéza neposkytla včasné varování. **Tato minima nejsou potvrzením
statistické spolehlivosti ani důvodem chyby záměrně vyvolávat.**

Výběr je popisný, ze stejných dat, na kterých byly hypotézy porovnány.
Před případným provozním použitím se musí vybraný návrh zmrazit a ověřit na
následujícím, dosud nepoužitém období. Odhad z minulosti neprokazuje,
že by fyzický zásah zabránil chybě.

### Co se nezapočítá jako úspěšný cyklus

- Zahájení pozorování u již běžícího hořáku nebo neznámého začátku požadavku.
- Restart HA nebo konec záznamu před dokončením okna.
- Chybějící, neplatné nebo nedostatečně čerstvé potřebné údaje.
- Výpadek zachytávání za provozu nebo během sledovaného doběhu.
- Servisní režim nebo vypnutí hlavního řízení před případnou poruchou.
- Hoření, které nelze přiřadit k požadavku relé na vytápění.
- Aktivní nebo neznámý ohřev TUV podle hlášení nabíjení, dobíjení a přepnutí ventilu.
- Umělé ukončení mimořádně dlouhého, dvouhodinového záznamu.

Taková okna mají označení `censored`; při zaznamenané chybě
`censored_fault`. Zůstanou k rozboru, ale netrénují běžné hodnocení.

Servis zapnutý až po zachycení chyby nesmaže již pozorovanou chybu.
Následné ochlazování je ovlivněno existující ochranou; z poklesu teploty
nelze usuzovat na chování bez zásahu.

Opakované poruchové přechody s odstupem nejvýše 600 s se seskupují. Každá
skupina má při hodnocení nejvýše jednu váhu. Je to transparentní heuristika,
nikoli důkaz stejné fyzické příčiny či statistické nezávislosti skupin.

### Režimy a revize soustavy

Souhrn rozlišuje počty prvních startů a vnitřních restartů. Skóre hypotéz je
ve verzi 0.1.0 společné; jemnější porovnávání podle režimu nebo konkrétní
kombinace radiátorů vyžaduje dostatek dalších dat.

Při změně čerpadla, vyvážení, hlavic, hydrauliky či významné konfigurace
změňte `site_revision`. Vznikne nový model a předchozí soubor zůstane
uchovaný. Neslučujte zkušenosti z rozdílných fyzických soustav bez označení.

Změna porovnávacího času nebo meze čerstvosti při stejné revizi odmítne
načíst starý model. Tím se zabrání jeho tichému přepsání novým významem
výsledků. Nové nastavení použijte s novou revizí.

## Co a kam se ukládá

Adresář `/config/heating_observer_data/`:

| Soubor | Obsah |
|---|---|
| `samples.jsonl` | Časově řazené snímky; jeden JSON na řádek |
| `episodes.jsonl` | Otevření incidentů a ukončené cykly včetně poruchového kontextu |
| `model-<site_revision>.json` | Obnovitelné souhrny, čítače a rozpracovaný cyklus |
| `report.json` | Aktuální přehled všech hypotéz |

Každý z obou deníků má výchozí limit 16 MiB a tři rotované soubory.
Celkový strop těchto deníků je tedy přibližně 128 MiB; model a přehled jsou
navíc. Retence se řídí objemem, ne pevným počtem dní. Model je omezen na
500 souhrnů. Nové revize vytvářejí další samostatné modely.

Předporuchový kontext obsahuje vybrané snímky nejvýše deset minut zpět;
mezera mezi ukládanými kontextovými snímky je alespoň pět sekund.
Počet snímků má pevný limit. Začátek sledování či výpadek sběru mohou
dostupné okno zkrátit. Následné okno končí obvykle pět minut po zhasnutí,
nebo je přerušeno dalším zapálením.

**Pět minut je délka pozorovacího okna, nikoli příkaz ani potvrzení
bezpečného dochlazení.** Stejně tak `postrun_complete` označuje dokončené
okno sběru, nikoli bezpečnou teplotu kotle.

Teplotní růst po zhasnutí se počítá od prvního dostupného teplotního reportu
po hlášeném vypnutí hořáku. Uchovává se jeho čas. Při nesoučasném přenosu
mohla část růstu proběhnout již před tímto reportem. Chybějící měření se
nenahrazuje starou teplotou vydávanou za současnou.

Zápisy na disk probíhají mimo hlavní smyčku HA. Model se ukládá atomicky
nejméně při důležitých událostech a průběžně přibližně každou minutu.
Při náhlém výpadku může chybět poslední část od posledního zápisu.
Rozpracovaný cyklus po restartu nedostane automaticky nálepku úspěchu.
Při poškozeném modelu se modul nespustí a soubor nepřepíše.

Průběhy nepatří do Gitu; projektový seznam povolených souborů je nezahrnuje.
Pro dlouhodobý rozbor před rotací exportujte celý adresář prostřednictvím
běžné zálohy HA. Modul sám data nikam neposílá.

## Instalace pozorovací verze

Připojení použité pro tuto přípravu poskytovalo pouze čtení. Tato změna
nebyla instalována do běžícího HA a nebyl proveden restart ani změna řízení.

1. Vytvořte běžnou zálohu konfigurace HA.
2. Přeneste celý adresář `custom_components/heating_observer/` z ověřeného
   commitu do `/config/custom_components/heating_observer/`.
3. Přeneste `heating/observer/heating_observer.yaml` do
   `/config/heating/observer/heating_observer.yaml`.
   Stávající `configuration.yaml` už načítá balíčky ze stromu `heating`.
   Nenahrazujte hlavní konfiguraci ani existující řídicí YAML soubory.
4. Spusťte kontrolu konfigurace `ha core check`. Pokud neprojde, opravte
   pouze instalaci pozorovacího modulu před restartem.
5. Pro načtení nového Python modulu je potřebný restart HA Core.
6. Ověřte nové entity `sensor.heating_observer_status` a
   `sensor.heating_observer_learning` a vznik výše uvedených souborů.
   Při dostupných údajích a zapnutém servisním režimu je očekávaný text
   „Servisní režim“; při chybějících údajích „Neúplná data“.
7. Volitelně přidejte jednu novou ruční kartu podle
   `docs/heating-observer-card.yaml`. Stávající dashboard se nenahrazuje.

Instalace pozorovatele není pokynem k vypnutí servisního režimu ani
k uvolnění kotle po poruše. Nevyžaduje zápis do existujících helperů.
Běh při odstaveném kotli ověří sběr a dostupnost dat; nezískává tím
zkušenosti z vytápění.

Při prvním spuštění musí být `actuator_control: false` a
`mode: shadow_only`. Ověřte, že `last_written_at` postupuje a
`storage_error` je prázdné. Do aktivní logiky kotle žádný ze senzorů
pozorovatele zatím nepřipojujte.

Pro odebrání odstraňte pouze přidaný balíček z načítané konfigurace a
restartujte HA. Zdrojový adresář integrace lze poté odstranit.
Adresář se záznamy uchovejte. Stávající ochrany a regulace zůstávají stejné.

## Opakované vyhodnocení dat bez připojení ke kotli

Skript používá pouze standardní Python, nevyžaduje HA ani přístupový token:

```sh
python3 scripts/replay_heating_observer.py \
  --revision hydraulika-20260921-neoverena \
  samples.jsonl.3 samples.jsonl.2 samples.jsonl.1 samples.jsonl
```

Uveďte jen existující soubory, od nejstaršího po nejnovější. Skript odmítne
neplatný JSON i záměnu revizí. Poškozený poslední řádek nejprve samostatně
prozkoumejte; nemažte ho tiše a neoznačujte vzniklou mezeru jako úplná data.

Parametr `--lead-seconds` dovoluje porovnat jiný požadovaný předstih.
Výchozích 60 sekund je jen porovnávací rozpočet, **ne změřená doba otevření
hlavic**. Skript vypíše nový JSON přehled na standardní výstup; nepřepisuje
živý model ani konfiguraci.

## Postup dalšího zlepšování

Po každém dalším výpadku modul automaticky uchová podklady a po uzavření
cyklu aktualizuje výsledky. Při následném odborném rozboru:

1. Ověřit úplnost dat, skutečný režim a čas prvního příznaku.
2. Oddělit stav před poruchou od zásahů současných ochran po ní.
3. Zjistit, zda některá hypotéza poskytla potřebný předstih.
4. Posoudit, jak často stejná hypotéza varovala v ostatních cyklech.
5. Zapsat vysvětlení příčiny jako potvrzené, pravděpodobné nebo neznámé.
6. Pokud stávající hypotézy nestačí, připravit novou verzi katalogu
   a vyhodnotit ji nad uchovanými daty.
7. Vybraný návrh ověřit na novém období, teprve potom připravovat
   samostatnou změnu aktivní ochrany s možností návratu.

Modul sám nedokáže potvrdit, že příčinou byl filtr, čerpadlo nebo ventil.
Nesnižuje bezpečnostní rezervy po několika cyklech bez chyby, nenastavuje
doběh čerpadla a netestuje soustavu zavíráním radiátorů.

## Ověření a zdroje

Testy ověřují skutečný HA loader a diagnostické senzory, absenci volání
ovládacích služeb, restart, ztrátu dat, poruchy ukládání, seskupení opakování,
časový předstih, oddělení servisních stavů a pořadí teplotních reportů.

Celá sada 141 testů prošla v HA 2026.5.1 i 2026.9.2. Z toho 25 testů
ověřuje nový pozorovatel; prošly také všechny projektové ochranné kontroly.

Offline přehrání tří dostupných historických úseků zachytilo zaznamenané
poruchy. Úseky byly správně vyřazeny z trénovacího skóre: nebyl znám celý
začátek požadavku a část historie nedokládá čerstvost měření. Přehrání
ověřuje zpracování záznamů, nikoli účinnost budoucí aktivní ochrany.
Soukromé provozní záznamy ani takto vytvořený model nejsou součástí změny.

```sh
python -m unittest discover -s tests -v
python scripts/run_protective_checks.py
```

Události se sledují pomocí podporovaných helperů HA a diskové operace
probíhají v executor vlákně. [Události HA](https://developers.home-assistant.io/docs/integration_listen_events/),
[neblokující práce v HA](https://developers.home-assistant.io/docs/asyncio_blocking_operations/).

Samostatný deník uchovává vybrané důkazy nezávisle na běžném promazávání
Recorderu. [Retence Recorderu](https://www.home-assistant.io/integrations/recorder/).
