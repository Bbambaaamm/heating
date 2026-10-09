# Audit konfigurace HA / Git — 2026-10-09

## Ověřené zdroje

- Skutečný HA pracovní strom: `/config`, větev `nasazeni/topeni-20260918`, HEAD `fbd3143bf3d6f40af2a39257c8cb9b39bbd8e47d`.
- Stažený GitHub `main` v HA při auditu: `1fb9b869db44e530f645103adcc021a2fe298129`. Proveden jen `git fetch origin main`, žádný `git pull`, `checkout`, `reset` ani HA Core restart.
- Načteno **59 sledovaných YAML** v HA. Žádné chyby v syntaxi během kontroly s podporou HA custom YAML tagů; po opravě žádné duplicitní názvy skriptů ani duplicitní `automation.id` v analyzovaných souborech.
- `ha core check` před i po opravě hlásil úspěch; systémový log před opravou zaznamenal 21 výskytů `script has duplicate key alias`. Nekomplikovat validaci tím, že návratový kód `ha core check` sám o sobě vysvětlí všechny runtime warningy.

## Root cause chyby `duplicate key alias`

Skript `heating_apply_zone_target` byl v živém HA definovaný **dvakrát**:
- `/config/scripts.yaml`, s důležitou podmínkou pro hydraulickou podporu v `target_raw`;
- `/config/heating/control/refactor_mode_schedule_override.yaml`, která tuto podmínku neobsahovala.

Kód na Gitu navíc neuchovával root `heating_restore_schedule_after_service`, který je potřeba pro Flow V4 recovery. Pouhé `git pull` mohlo odstranit ochranu i obnovovací skript.

### Provedená živá oprava

1. Význam obou verzí `heating_apply_zone_target` byl před změnou porovnán jako YAML slovníky. Lišily se pouze popisem a `target_raw` s hydraulickou podporou.
2. Package script získal identickou funkci `target_raw` a popis z fungující root verze.
3. Z `scripts.yaml` byla odstraněna pouze duplicitní definice; `heating_restore_schedule_after_service` zůstal beze změny.
4. Původní soubory byly zazálohovány pod `/config/analysis/yaml_audit_backups/audit-20261009-133026-356/`.
5. Atomické souborové změny prošly syntaktickou kontrolou a `ha core check` (exit 0). `script.reload` proběhl úspěšně bez restartu HA Core, za podmínky že probíhající skripty měly `current=0`, Flow V4 byl `NORMAL` a bez lockoutu.
6. HA služba `script.heating_apply_zone_target` zůstala dostupná s popisem hydraulického guardu; systémový log po reloadu nezvýšil původní čítač duplicitního `alias`.

## Co se lišilo od GitHub main

| Soubor | Live vs main | Postup |
|---|---|---|
| `heating/control/refactor_mode_schedule_override.yaml` | Pouze `description` a `target_raw` scriptu (plus kosmetické odsazení komentářů) | **Tento PR** verzoval guard do package scriptu |
| `scripts.yaml` | Live má jediné `heating_restore_schedule_after_service`, main původně prázdný | **Tento PR** verzoval root recovery skript dle ověřeného live snapshotu |
| `automations.yaml` | Live 39 automatizací vs 15 v main; dalších 24 byly primárně storage-managed incident/Flow V4/watcher objekty | Nepřepisovat automatizace plošně; snapshots a regresní testy už jsou v `docs/live-storage-snapshot-2026-10-09-v4.json`, zbytek vyžaduje výběrovou config-as-code migraci |
| `blueprints/automation/heating/smart_zone_schedule.yaml` | 35 sémantických rozdílů: z větší části normalizace selectorů; také `mode: queued` live vs `restart` main | **Nenasazovat naslepo**, změna `mode` může změnit zacházení s ručními zásahy a Zigbee požadavky. Ověřit runtime testy a cílové chování |
| `heating/control/kotel_control.yaml` | Live 2 automace, main 3 včetně `kotel_tuv_relay_interlock` | V živém HA již existuje samostatný TUV interlock. Potenciální dva vlastníci stejného relé se musí migrovat atomicky, ne paralelně |
| `.herdr/consumer.yaml` | Git-only konfigurace platformy, netýká se přímo aktivních regulátorů HA | Chybí lokálně; lze doplnit samostatně bez měnění řízení |

Dále lokální soubory `custom_components/heating_observer/*.py` byly proti staršímu lokálnímu HEAD modifikované, ale jejich obsah při diff proti staženému `main` odpovídal novému verzovanému kódu.

## Nepřepsat neověřené odchylky

Obsah lokální `/config` větve je stále provozní pravda pro domov. Není dovoleno použít `git reset --hard`, plošné `git checkout`, `git clean`, nevýběrové `git pull` ani zapnout dvě automace pro tutéž bezpečnostní funkcionalitu. Doporučený další krok pro zbývající migrovatelné položky je oddělená reprodukovatelná migrace s filtrem `automation.id`, snapshotem a kontrolou zónových rozvrhů. Při vysokém riziku držet změny jako audit, nikoli násilně sjednotit text souborů.

## Verifikace po merge

```sh
python -m unittest tests.test_yaml_script_dedup -v
python -m unittest discover -s tests -v
python scripts/run_protective_checks.py
```

Tyto testy pokrývají strukturu, nikoli fyzický průtok kotlem; hardwarová 2964 může vzniknout i během TUV při vypnutém topném relé.
