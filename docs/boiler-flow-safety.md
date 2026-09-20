# Ochrana průtoku kotlem a falešných ručních změn

Oprava navazuje na nasazený commit `a04f9fe` a na provozní test kotle
Bosch Condens 2300i W GC2300iW 24 P 23. Při jediné otevřené chytré zóně
se opakoval kód 2964 a kotel cykloval v řádu desítek sekund. Se všemi
18 radiátory otevřenými proběhl více než patnáctiminutový test stabilně
s jediným startem.

## Příčiny

1. Boost nuloval prahové hodnoty a prodlevu zapnutí. Relé proto mohlo sepnout
   ihned i pro jedinou zónu, dříve než se ventil fyzicky otevřel.
2. Některé Zigbee hlavice potvrzují automatický setpoint událostí bez
   `parent_id`. Blueprint takové potvrzení považoval za fyzické otočení
   hlavice a vytvořil falešný manuální override.
3. Chyběl trvalý zdrojový zámek pro kódy 2964–2967. Dočasná UI automatizace
   chránila živý systém, ale ochrana nebyla součástí verzované konfigurace.

## Změny

- Boost už nikdy nesnižuje bezpečnostní minima kotle.
- Efektivní politika má tvrdé dolní meze 15 % průměrné poptávky,
  2 aktivní zóny a 120 sekund před sepnutím relé.
- Vypnutí relé má tvrdou horní mez 30 sekund; provozní hodnota je 10 sekund.
- Samotné řízení relé znovu aplikuje 120/30sekundové meze, i kdyby byl
  odvozený senzor vadný.
- Potvrzení Zigbee bez rodičovského kontextu se ignoruje jen tehdy, když
  přesně odpovídá aktuálnímu cíli politiky. Jiný setpoint zůstává skutečným
  ručním zásahem.
- Kódy 2964, 2965, 2966 a 2967 nejdříve vypnou relé, hlavní řízení a Boost,
  potom zapnou servisní režim a otevřou všech osm chytrých hlavic.
- Samostatná rychlá pojistka blokuje relé i hlavní řízení po celou dobu
  aktivního servisního režimu; nečeká na Zigbee komunikaci.

Minimum dvou zón je ochranná výchozí hodnota, nikoli hydraulické potvrzení
konkrétní soustavy. Po nasazení se musí ověřit kontrolovaným testem. Trvalé
řešení může vyžadovat nastavení čerpadla, hydraulické vyvážení nebo diferenční
obtok; software nezajistí průtok přes fyzicky uzavřené ventily.

## Bezpečné nasazení

Po celou dobu ponechte zapnutý `input_boolean.heating_service_mode` a všech
10 manuálních ventilů plně otevřených. Ve zdrojovém stromu `/config` načtěte
větev a použijte celý SHA ověřeného commitu:

```sh
git fetch origin fix/boiler-flow-safety
FIX_SHA="$(git rev-parse origin/fix/boiler-flow-safety)"
git show "$FIX_SHA:scripts/deploy_boiler_flow_safety.py" > /config/deploy_boiler_flow_safety.py
python3 /config/deploy_boiler_flow_safety.py --config /config --source "$FIX_SHA" --check
```

`--check` musí vypsat pět ověřených souborů a nic nezmění. Teprve potom:

```sh
python3 /config/deploy_boiler_flow_safety.py --config /config --source "$FIX_SHA" --apply
ha core restart
```

Skript přijímá pouze přesný nasazený základ `a04f9fe` nebo již nasazený
cílový obsah. Neznámou místní změnu odmítne před prvním zápisem. Vytvoří
zálohu v `/config/boiler_flow_safety_backups`, zapisuje atomicky a při
neúspěšném `ha core check` vrátí všechny zapsané soubory.

Po restartu nejdříve ověřte, že servisní režim, hlavní řízení a relé jsou
ve stavech `on`, `off`, `off`. Dočasnou UI ochranu 2964 ponechte aktivní,
dokud se nepotvrdí načtení balíčkové automatizace
`heating_boiler_low_flow_package_guard`.

## Kontrolovaný test

### Servisní automatizace z nasazené konfigurace (PR #78)

Servisní režim je v `automations.yaml`. Popisy jednotlivých akcí používají
`alias`, které podporuje také HA 2026.5.1; klíč `note` tato verze odmítá.
Původní stav hlavního povolení se ukládá jen při skutečném přechodu
servisního přepínače z `off` na `on`, pokud je hlavní povolení dostupné.
Obnova z `unknown`, `unavailable` nebo chybějící entity zachová již uložený
stav, ale znovu vypne relé a otevře hlavice. Obnova vypnutého servisního
přepínače sama nezapíná hlavní řízení. Při chybě průtoku se hlavní povolení
vypne před zapnutím servisu, takže ukončení servisu kotel automaticky neuvolní.

Konfigurace používá existující UI helpery `input_boolean.heating_service_mode`
a `input_boolean.heating_service_restore_main_enable`; při obnově instalace
musí být obnoveny také tyto helpery. Není zde přidána druhá YAML definice
těchto entit. Rychlé pojistky z UI a z balíčku zůstávají aktivní.

Testy načítají nové instanční automatizace skutečným HA enginem a ověřují,
že nejsou `unavailable`, vypnutí relé před povely hlavicím, zachování stavu
při obnově, souběh s pomalým Zigbee povelem a servisní zámek po chybě průtoku.
Starší pětisouborový instalátor z PR #77 soubor `automations.yaml` nenasazuje;
změna na GitHubu tedy sama neaktualizuje běžící Home Assistant.

### Postup provozního ověření

1. Ověřte tlak studené soustavy a ponechte všech 18 radiátorů otevřených.
2. Vypněte servisní režim a zapněte Boost. Efektivní prodleva musí zůstat
   120 sekund; relé nesmí sepnout dříve.
3. Ověřte, že žádná zóna sama nepřešla do manuálního override.
4. Sledujte servisní kód, teplotu výstupu, relé, plamen, počet startů a tlak.
5. Manuální ventily zavírejte po jednom, mezi kroky čekejte nejméně tři
   minuty. Při kódu 2964–2967, rychlém růstu teploty, hluku nebo cyklování
   test okamžitě ukončete servisním režimem.
6. Teprve po stabilním testu manuálních ventilů zkoušejte počet chytrých zón
   8 → 6 → 4 → 3 → 2. Jednu zónu znovu netestujte.

## Návrat

Použijte přesnou cestu vypsanou při nasazení:

```sh
python3 /config/deploy_boiler_flow_safety.py \
  --config /config \
  --rollback /config/boiler_flow_safety_backups/flow-ADRESAR
ha core restart
```

Návrat odmítne přepsat soubor, který byl po nasazení znovu ručně změněn.

## Odkaz výrobce

Bosch v instalačním a servisním návodu 6720889912 uvádí:

- 2964: příliš malý průtok v tepelném výměníku,
- 2965: příliš vysoká teplota na výstupu,
- 2966: příliš rychlé zvýšení teploty na výstupu,
- 2967: příliš velký teplotní spád mezi výstupním čidlem a omezovačem
  teploty výměníku.

Pro všechny čtyři stavy výrobce směřuje kontrolu na tlak vody, čerpadlo
a polohu ventilů; u 2964/2967 také na montáž čidla.
