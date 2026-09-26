# Heating Agent Platform — Phase 1

Cíl této vrstvy je převést existující pasivní pozorování topení na auditovatelný
tok událostí pro budoucí agenty. Home Assistant zůstává jediná deterministická
řídicí vrstva.

## Tvrdé hranice Phase 1

- žádný obecný Home Assistant service-call endpoint;
- žádné ovládání relé, TRV, rozvrhů nebo kotle;
- žádná změna existujících safety automatizací;
- chybějící data jsou UNKNOWN a nesmí se doplňovat odhadem;
- PI hlavice je proxy požadavku, nikoli potvrzený fyzický průtok;
- statistická baseline je popisná, nikoli bezpečnostní limit.

ReadOnlyHaCommandPolicy explicitně odmítá write-capable WebSocket message types,
například call_service.

## Tok

~~~text
HA get_states / state_changed
        |
        v
ReadOnlyCollector
        |
        +--> telemetry.snapshot.v1
        |
        v
CycleBuilder
        |
        +--> heating.cycle.started.v1
        +--> heating.cycle.completed.v1
        |
        v
Observer
        |
        +--> heating.incident.created.v1
~~~

Cycle Builder používá jako hlavní jednotku jeden souvislý požadavek relé.
Interní starty hořáku zůstávají pod tímto request cyklem. Tím se tato vrstva
nepere s existujícím heating_observer 0.1.0 ani s pasivní diagnostikou z PR #80.

## Event contract

Externí smlouva je v schemas/events.schema.json. Všechny eventy mají:

- schema_version;
- event_id;
- event_type;
- occurred_at a recorded_at;
- site_revision;
- source;
- correlation_id;
- causation_id;
- data.

Raw event_log v databázi je append-only. Normalizované tabulky jsou projekce,
které lze z eventů znovu sestavit.

## Databáze

První migrace je v db/001_init.sql a obsahuje:

- event_log;
- state_samples;
- zone_samples;
- heating_cycles;
- incidents;
- diagnostic_reports + diagnostic_hypotheses;
- protection_replays;
- agent_runs.

Schéma funguje na PostgreSQL. TimescaleDB je volitelná pozdější optimalizace
pro časové vzorky; není podmínkou korektnosti.

## Observer

První verze vytváří incident při:

1. přechodu do známého service code 2964–2967;
2. až po minimálně 20 validních fault-free cyklech také při kombinovaném
   statistickém outlieru: výrazně rychlejší růst teploty a nízký počet
   requesting zones proti vlastní baseline.

Druhý bod je pouze kandidát k diagnostice. Neříká, že příčinou je průtok,
ventil nebo hlavice.

## Vztah k existujícímu observeru

custom_components/heating_observer zůstává nedotčený. Nová platforma může
později přijímat jeho journal jako další evidence source. Draft PR #80 lze
sloučit nezávisle, protože Phase 1 nevkládá změny do jeho souborů.

## Ověření

~~~sh
python -m unittest discover -s tests -v
python scripts/run_protective_checks.py
~~~

Nasazení transportu a PostgreSQL služby není součástí tohoto prvního kroku.
Phase 1 zde zavádí kontrakt a deterministické jádro, které lze bezpečně
replayovat bez připojení ke kotli.
