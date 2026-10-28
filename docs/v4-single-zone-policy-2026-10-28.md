# Jednotná politika počtu zón pro start a vypnutí relé

## Problém a výsledné chování

Živý bezpečný start `1791376426962` používá efektivní minimum zón,
nejméně jednu. Nezávislý OFF guard `heating_v4_relay_lockout_guard`
stejný vstup přebíjel pevným minimem dvou zón. Jedna platná žádající
zóna tak mohla projít startem a být okamžitě odmítnuta guardem.

Oprava mění pouze dolní mez potvrzeného počtu zón v živém guardu:

```diff
- ns.demands | count >= [min_z | int(99), 2] | max
+ ns.demands | count >= [min_z | int(99), 1] | max
```

Efektivní helper je nadále závazný: hodnota 2 nebo 3 neumožní start
s jedinou zónou. Nula potvrzených zón nikdy nestačí. Průměrná poptávka,
validace vstupů, aktuální potřeba tepla a aktivita zón zůstávají zachované.
Potřeba tepla ani PI nepotvrzují fyzický průtok.

Start ani guard nepřidávají žádný příkaz přes EMS. Jedinými akcemi
této dvojice zůstávají normální ON a ochranné OFF externího relé.
Kontroly Flow, zámku, aktuální poruchy, EMS spojení a teploty i stávající
prodlevy startu zůstávají zachované. Limit zámku 10 minut se nemění.

## Synchronizace zdrojů

Root `automations.yaml` před touto změnou obsahoval starší varianty obou
automatizací, bez již živých kontrol potvrzených zón. Změna dorovnává
právě tyto dva objekty podle čerstvého čtení z HA a výše uvedené opravy.
Ostatní automatizace zůstávají objektově stejné. Přesná shoda po nasazení
se ověřuje pro změněnou dvojici, nikoli jako nepodložený výrok o celém HA.
Historické kandidátní
fixtures se dvěma zónami zůstávají zachované a nejsou aktuálním zdrojem
pro nasazení.

Nové testy načítají skutečnou dvojici z root konfigurace a kontrolují
shodu všech čtyř výrazů startu s výrazem guardu. Tím zachytí opakovaný
rozchod podmínek i tehdy, když by samostatné kandidátní fixtures prošly.

## Ověření před nasazením

- `python3 scripts/run_protective_checks.py`.
- Celá sada `python -m unittest discover -s tests -v` v HA 2026.5.1
  a podle projektového CI také v HA 2026.9.2.
- Testy skutečné dvojice: jedna zóna bez krátkého vypínacího pulzu,
  odvolání posledního požadavku, opětovný start až po prodlevě,
  přísnější helper, neplatné vstupy, teplota a blokované Flow stavy.
- Porovnání ostatních objektů root konfigurace s výchozím commitem.

## Rozsah nasazení a návratu

Do HA se zapisuje jen proměnná `confirmed_zone_policy_ok` a popis guardu,
s čerstvým `config_hash`. Start se v HA nemění. Následuje nové čtení
obou objektů a porovnání s Gitem včetně zapnutí automatizací.

Při potřebě návratu se obnoví pouze původní výraz a popis téhož guardu
přes konfigurační API s novým hashem a zaznamená se odpovídající změna
v Gitu. Obnova celé zálohy ani reset kotle nejsou součástí tohoto kroku.

Tento dokument sám není důkaz nasazení. Dokončení vyžaduje skutečný
úspěšný zápis a následnou kontrolu HA proti zdrojům.

## Provedené nasazení a zbývající nesoulad

Guard byl změněn 28. 10. 2026 ve 12:39:31 Europe/Prague. Nové čtení
potvrdilo hash `a768084afb759037` a přesnou shodu s připraveným zdrojem.
Start zůstal beze změny, hash `a2ba1090b6ef13a8`; obě automatizace jsou ON.
Ochranné kontroly a všech 437 testů prošly v HA 2026.5.1 i 2026.9.2.
Podrobnosti jsou ve vedlejším deployment JSON.

Při širší kontrole se objevil další nesoulad: verzovaný
`heating/policy/policy_effective.yaml` stále používá `[configured, 2] | max`,
zatímco HA v režimu Auto při helperu 1 hlásí efektivní minimum 1.
Konfigurační API dostupné pro tento krok neposkytlo zdroj YAML tohoto
senzoru. Nelze tvrdit celkovou shodu Git/HA ani tento rozdíl odstranit
odhadem podle jedné provozní hodnoty. Před uzavřením kroku 1 je třeba
načíst skutečný živý soubor politiky a dorovnat zdroje s ověřením.
