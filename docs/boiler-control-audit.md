# Audit řízení kotle a nasazení opravy

Tato oprava navazuje na PR #75 (commit
`da7cf88415fed77184c0b2eb1d0ccb33f9d4ad9e`). Zachovává jeho chování:
vypnutý kalendář zóny vynutí ECO i při manuálu nebo Boostu.

## Nalezené a opravené chyby

- Čekající zapnutí/vypnutí relé se při opačném požadavku okamžitě zruší.
  Podmínky jsou uvnitř akcí, aby `mode: restart` mohl zrušit předchozí běh
  i při nesplněných podmínkách nového běhu. Nový požadavek čeká celý interval.
- Zapnutí kontroluje přímo master, režim a blokaci Off před čekáním i po něm.
  Opožděná aktualizace odvozeného požadavku proto nemůže obejít přímou blokaci.
- Politika kotle, všech osm přepínačů kalendářů, ECO teplota, délka a navýšení
  Boostu, ignorování oken a volba centrálního řízení obnovují hodnotu po restartu.
  Pevné `initial` dosud přepisovalo nastavení obsluhy. Záměrná startovací
  pojistka centrálního vyhodnocení zůstává zapnutá.
- Zóna s vypnutým HVAC režimem nepřispívá do požadavku na kotel, ani když
  zařízení stále hlásí starou nenulovou hodnotu PI demand.
- Analytika odděluje hoření a sepnutí relé. Nové senzory
  `sensor.kotel_relay_on_periods_1h`, `sensor.kotel_relay_on_periods_24h`
  a `sensor.kotel_relay_on_time_24h` doplňují původní entity bez změny jejich ID.

## Co zpoždění znamená

Zpoždění zapnutí a vypnutí filtruje krátké změny požadavku na relé. Původní
referenční hodnoty jsou 120 a 300 sekund; stávající nastavení se nemění.
Dosavadní výjimka aktivního Boostu s nulovým zpožděním zapnutí zůstává zachována.
Tato prodleva není minimální dobou hoření ani minimální odstávkou hořáku.
Hořák se může vypínat vlastní regulací i při trvale sepnutém relé.

`history_stats` s `type: count` počítá úseky ON zasahující do sledovaného okna.
Zahrnuje tedy i úsek začínající před oknem; mezery v datech mohou přidat další
úseky. Počet úseků není přesný počet hran OFF→ON. Pro přesné hodnocení je
potřeba současně sledovat historii relé, plamene a hardwarové čítače kotle.

Odstranění `initial` na nové instalaci bez uložené historie znamená, že
číselné pomocníky je nutné nastavit před zapnutím hlavního systému. Referenční
politika: průměr 15 %, zóna 5 %, alespoň 1 zóna, prodlevy 120/300 s. Na novém
systému nastavte také ECO, Boost a povolené kalendáře. Stávající instalace
obnoví uložené hodnoty.

## Ověření

- Home Assistant 2026.5.1, Python 3.14.7: 93 testů prošlo (88 runtime,
  5 nasazovacího skriptu).
- Osm regresních scénářů reprodukováno na původním PR #75; oprava je řeší.
- Kontroly `scripts/run_protective_checks.py` a `git diff --check` prošly.
- Ověřeno zachování kalendářů, manuálu, časovačů a příslušných ID.

Runtime testy ani kontrola YAML samy nepotvrzují odstranění fyzického
cyklování hořáku. Nastavení spalování, výkonu a hydrauliky se touto opravou
nemění.

## Nasazení

Na HA hostu nejdříve stáhněte větev opravy a zvolte celý ověřený commit SHA.
Skript lze vyjmout příkazem `git show COMMIT:scripts/deploy_boiler_audit.py`
do samostatného souboru mimo adresář balíčků. Spouští se standardním Pythonem:

```sh
python3 /cesta/deploy_boiler_audit.py --config /config --source COMMIT --check
python3 /cesta/deploy_boiler_audit.py --config /config --source COMMIT --apply --restart
```

`--check` nic nezapisuje. `--apply` ověří 21 konkrétních YAML souborů proti
PR #75 nebo cílovému commitu, vytvoří zálohu, zapíše opravu a provede
`ha core check`. Při neúspěšné kontrole obnoví zapsané soubory. Neznámá místní
změna nasazení zastaví. Restart proběhne pouze s `--restart` a po úspěšné kontrole.
Skript nevytváří commit v HA a nepřepisuje Git index, `automations.yaml`,
dashboard ani OIG opravy.

Skript vypíše konkrétní adresář zálohy. Návrat:

```sh
python3 /cesta/deploy_boiler_audit.py --config /config --rollback /config/boiler_audit_backups/audit-ADRESAR --restart
```

Návrat odmítne soubory změněné po nasazení. Při selhání restartu zůstávají
ověřené soubory a záloha na disku; zkontrolujte stav HA před dalším zásahem.

## Kontrola v provozu

Po restartu ověřte zachované hodnoty politiky, kalendářů, ECO a Boostu. Sledujte
současně relé a plamen alespoň jeden topný cyklus: čekání na zapnutí musí
odpovídat účinné prodlevě, protichůdný požadavek musí čekání zrušit.
Pokud plamen opakovaně zhasíná během nepřetržitého sepnutí relé, vyhodnocujte
teplotu topné vody, výkon hořáku a dostupný odběr tepla. Samotné prodloužení
čekání na relé nemění vnitřní regulaci již běžícího kotle.

## Dokumentace

- [Home Assistant: history_stats](https://www.home-assistant.io/integrations/history_stats/)
- [Home Assistant: obnova input_number](https://www.home-assistant.io/integrations/input_number/)
- [EMS-ESP: regulace kotle a cyklování](https://emsesp.org/FAQ/)
