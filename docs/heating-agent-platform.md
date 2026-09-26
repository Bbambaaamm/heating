# Heating Agent Platform — architektura a datový kontrakt

## Milestones

- M1 Observation Fabric: issues #81–#86.
- M2 Diagnostic + Knowledge Agents: issue #87.
- M3 Historical replay + protection evaluation: issue #88.
- M4 PR-only Code Agent + gated release: issue #89.

## Q2: databázový model

Primární zdroj pravdy je append-only event_log. State samples, cycles,
incidents, diagnostics a replays jsou normalizované projekce.

### Vztahy

~~~text
event_log
   |
   +-- state_samples --< zone_samples
   |
   +-- heating_cycles
   |       |
   |       +--< incidents
   |               |
   |               +--< diagnostic_reports --< diagnostic_hypotheses
   |               |
   |               +--< protection_replays
   |
   +-- agent_runs
~~~

Cycle ID a incident ID jsou korelační klíče. causation_id ukazuje na
bezprostřední event, který vznik dalšího eventu vyvolal.

## Event semantics

telemetry.snapshot.v1
: Normalizovaný read-only snímek HA. Nikdy neimplikuje fyzický průtok.

heating.cycle.started.v1
: Začátek souvislého request okna relé. Start při neznámé historii je incomplete.

heating.cycle.completed.v1
: Uzavřený request cyklus s metrikami. eligible_for_baseline je true jen pokud
  byl cyklus úplný, bez faultu, servisního zásahu, DHW kontextu a quality flagů.

heating.incident.created.v1
: Objektivní detekce s timeline. diagnosis musí být null.

diagnostic.completed.v1
: Budoucí M2 výstup. Obsahuje fakta a více konkurenčních hypotéz.

protection.replay.completed.v1
: Budoucí M3 výstup. Obsahuje would_trip, lead_seconds a dataset_role.
  Replay sám není povolení k nasazení.

agent.run.completed.v1
: Audit trail běhu specializovaného agenta.

Přesná strojová definice je v agent_platform/schemas/events.schema.json.
