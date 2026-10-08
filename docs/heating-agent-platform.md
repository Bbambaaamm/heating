# Heating Agent Platform — architektura a datový kontrakt

## Milestones

- M1 Observation Fabric: issues #81–#86.
- M2 Diagnostic + Knowledge Agents: issue #87.
- M3 Historical replay + protection evaluation: issue #88.
- M4 PR-only Code Agent + gated release: issue #89.
- M3 runtime replay/validation: #96.
- M4 Heating Intelligence: #97.
- M5 read-only Safety Sentinel: #98.
- M6 machine-enforced permissions: #99.
- M7 PR-only Code/Release/Deployment gates: #100.

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


## Runtime 0.3 — M3 až M7

### Replay / Validation

`replay-v1` znovu vyhodnocuje pevný katalog shadow hypotéz nad uloženými
`eligible` epizodami. Fault clustery se započítávají nejvýše jednou podle
`incident_id`. Fault i normal-control množiny se chronologicky rozdělí na
evidence a held-out validation část. Výstup pouze měří detection/miss, předstih
a warning v normálních oknech; nemění provozní ochranu.

### Heating Intelligence

`intelligence-v1` smí vytvořit pouze `CANDIDATE`. Dokud evidence neobsahuje
alespoň 3 fault clustery + 20 normal controls a held-out validation alespoň
1 fault + 10 normal controls, stav je `INSUFFICIENT_EVIDENCE`.
Ani po splnění tohoto gate není kandidát aktivní pravidlo: vždy
`active_policy_changed=false`, `deployment_allowed=false` a human review.

### Safety Sentinel

`safety-sentinel-v1` je read-only. Vyhodnocuje strojový katalog S01–S21
v `custom_components/heating_observer/safety_invariants.json`. V0.3 nemá
shutdown endpoint ani žádnou HA service-call capability.

S21 je high-severity read-only varování pro `sensor.boiler_heatblock > 72 °C`.
Je záměrně nezávislé na stavu relé i hořáku, aby zachytilo zbytkový tepelný
vrchol po jejich vypnutí (incident #140). Hodnota 72 °C je projektová
eskalační mez, nikoli tvrzení o certifikované bezpečnostní mezi kotle.

### Permission manifest

Runtime manifest je `custom_components/heating_observer/agent_policy.json`.
Je `default_deny`, runtime deployment je vypnutý a žádný agent nemá
`ha.control`, `git.write` ani `deployment.execute`.

CI kontrola `scripts/validate_agent_permissions.py` navíc odmítne:
- child capability mimo parent;
- zapnutý runtime deployment;
- nekompletní S01–S20;
- odstranění RED ochrany pro `heating/control/**`, `heating/safety/**`,
  `automations.yaml` nebo `scripts.yaml`.

### Code / Release / Deployment

Runtime Code Agent je pouze planner: klasifikuje cesty GREEN/YELLOW/RED, ale
neprovádí Git write. Release Gate pracuje pouze s dodanými důkazy CI/replay/safety.
Neznámé CI = `AWAITING_CI`, nikoli schválení. Deployment Agent pouze sestaví
plán; `execution_allowed=false`.

### Watchdog

`watchdog-v1` hlídá chyby observer/agent storage, permission audit, Safety
Sentinel, automatické FACT promotion a čerstvost evidence writeru.
Nemá control API.


## Runtime 0.4 — Autonomous Improvement Loop

0.4 rozšiřuje read-only agentní platformu o nepřetržité hledání zlepšení:

- Energy Efficiency Agent: kWh plynu, venkovní teplota, cykly, návrhy úspor;
- Comfort Agent: přetápění/nedotápění v comfort oknech;
- Schedule Agent: překryv zón a možnosti zkrácení/posunu oken;
- Hydraulics Agent: interní restarty, low-zone patterns a composite-rule vývoj;
- Maintenance Agent: faults, TRV health a opakované safety warningy;
- Data Quality Agent: chybějící kontext/senzory;
- Opportunity Orchestrator: deduplikovaný backlog návrhů.

Opportunity lifecycle je evidence-first. Každý návrh obsahuje category, confidence,
risk class, evidence, shadow experiment, případné estimated saving a stabilní fingerprint.

Autonomie:
- GREEN + bez fyzické změny → `AUTO_PR_ELIGIBLE`;
- YELLOW → `SHADOW_VALIDATE_THEN_REVIEW`;
- RED → `HUMAN_SAFETY_REVIEW`.

Ani 0.4 nemá `ha.control`, `git.write` ani `deployment.execute` v Home Assistant runtime.
Úsporné změny komfortu/rozvrhu se proto nejdřív validují v shadow režimu.


## Composite flow-risk shadow replay

GREEN experiment `composite-flow-risk-v1` extends replay analytics only. It does
not call Home Assistant services, change operating policy, change safety
thresholds, or claim that TRV PI confirms physical water flow.

For each eligible heating episode the observer stores only bounded, quantized
shadow features needed for the experiment: number of zones with PI >= 10 %,
block-temperature rise band, burner/request phase and request-age band. Fault
episodes freeze the feature intervals observed before the fault; normal episodes
store only unique feature signatures. Raw control actions are not generated.

Candidate conjunctions are ranked from the evidence split only. Held-out
validation is evaluated only after a candidate has been selected and therefore
cannot improve its rank. A candidate is not surfaced until feature-traced data
contains at least 3 evidence faults, 20 evidence normal controls, 1 validation
fault and 10 validation normal controls.

The output always keeps `active_protection_changed=false` and
`deployment_allowed=false`. Even a `PROMISING_SHADOW_CANDIDATE` remains an
offline hypothesis requiring separate safety review before any future RED-path
or physical-control proposal.
