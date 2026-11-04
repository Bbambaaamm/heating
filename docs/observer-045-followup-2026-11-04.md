# Vyhodnocování po nasazení observeru 0.4.5

Uživatel 4. 11. 2026 schválil nasazení samotného pasivního observeru 0.4.5,
přípravu nezávislého ověření kontaktu relé a pravidelné vyhodnocování.
Predikční automatizace se v tomto kroku neaktivuje ani nenahrazuje.

## Potvrzená příprava

- PR #168 začleněn do `main`, release commit
  `35e9e961ffe5a7d5a561a75c4a43c1e93b18587d`.
- Přesný merged commit má úspěšné CI
  https://github.com/Bbambaaamm/heating/actions/runs/41894434618 .
- HACS eviduje Heating Observer, doména `heating_observer`, cílová cesta
  `/config/custom_components/heating_observer`. Aktualizace se provádí pouze
  pro tuto integraci z přesného release commitu, nikoli plošným git pull v HA.
- Běžící HA při přípravě: Core 2026.9.2, Python 3.14.6, aarch64. Observer
  před aktualizací 0.4.4; HACS installed commit
  `49ac7d8a55f3eb76b6f567a2ee3b9df03d97d790`. Jeho adresář observeru je v Gitu
  obsahově shodný s výchozí verzí PR, takže jde o připravený rollback zdroje.
- Kontrola konfigurace před aktualizací platná. Povolení, watchdog a ukládání
  byly v pořádku. Tyto skutečnosti nejsou potvrzením dokončeného nasazení.

## Skutečně provedená instalace souborů a naplánovaná aktivace

HACS potvrdil stažení přesného release SHA a následné čtení potvrdilo
`installed_version=35e9e961ffe5a7d5a561a75c4a43c1e93b18587d`. Kontrola HA
konfigurace po instalaci je validní. Nová plná záloha `64aada53` z 20:07
Europe/Prague je dokončená v lokálním i cloudovém úložišti; obsahuje HA,
databázi a aplikace. Původní nástrojové volání vytvoření skončilo timeoutem,
proto bylo dokončení ověřeno čtením správce záloh a operace nebyla opakována.

Běžící proces po nahrání souborů stále hlásí **0.4.4**. Restart zatím neproběhl.
Topení je v normálním provozu s požadavkem osmi zón; rozvrhy mají běžná
ukončení od 21:30 do 22:00. Aktivace proto není prohlášena za dokončenou.

Jednorázová úloha **Aktivovat observer 0.4.5** je skutečně zapnutá na dnešek
kolem 22:15 Europe/Prague (flexibilní čas). Ověří přesný release, zálohu,
konfiguraci a dvě přirozené klidové kontroly 120–600 s od sebe. Při neověřeném
klidu nebo chybějících oprávněních/důkazech oznámí BLOCKED a nic nevypíná.
Po jednom schváleném restartu Core ověří novou verzi, senzor zapálení, zachování
evidence a zdraví agentů. Timeout restartu nepovede k druhému restartu naslepo.
Tato konkrétní aktivace není oprávněním k dalším změnám nebo k autonomnímu
nasazování budoucích verzí.

HACS commit a stav runtime jsou dvě různá ověření. Přímé čtení hashů všech
souborů z HA filesystemu v tomto kroku dostupné nebylo. Úplná shoda veškeré
konfigurace HA s Gitem se tímto auditem netvrdí.

## Skutečně vytvořené pravidelné vyhodnocování

Úloha **Vyhodnocení topení po nasazení** je zapnutá od 5. 11. 2026, každé ráno
kolem 08:00 Europe/Prague (flexibilní čas). Vyhodnocuje posledních 24 hodin a
průběžné sedmidenní okno. Není určena k řízení topení nebo k deploymentu.

Před každým reportem ověří skutečnou verzi observeru a nový senzor zapálení.
Pokud nová verze neběží, uvede NENASAZENO. Predikci posuzuje odděleně podle
skutečně existujících helperů a živé konfigurace; nenasazený kandidát se do
provozních výsledků nezapočítává.

| Oblast | Sledované podklady | Hodnocení |
|---|---|---|
| Zapálení | Hrany gas/ion, hlášené relé, čítače, WW a Flow V4 | Úplnost časové osy, chybějící podklady a neatributované přírůstky |
| Poruchy | Přechody 2964–2967 a platné hardwarové starty | Počet a poruchy na 100 startů při srovnatelném pokrytí |
| Kandidáti | Evidence/validation, včasnost a varované normální kontroly | Nedostatek dat je výslovný; nic se automaticky neaktivuje |
| Predikce | Aktuální zdroj, zóny, heartbeat, počasí | 8/8 a OK/DEGRADED/INCOMPLETE až po skutečném nasazení této opravy |
| Provoz agenta | Storage, Safety, Permissions, Watchdog, DB | Chyby zápisu, mezery, restart/reset a růst dat |

Posledních 50 položek `recent` není úplná historie dne nebo týdne. Report musí
uvést dostupné časové pokrytí, používat dostupnou historii a nic nedopočítávat
z neúplného seznamu. Vyšší citlivost nové diagnostiky se musí zohlednit při
srovnání s obdobím před nasazením. Samotná pasivní diagnostika neprokazuje
odstranění fyzické příčiny poruch.

Fyzické měření má vlastní protokol
`docs/relay-contact-verification-2026-11-04.md`; zatím nebylo provedeno.
