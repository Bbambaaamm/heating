# Composite Flow-Risk — dashboard panel design

The panel is a diagnostic view of a shadow experiment. It must never look like
a boiler controller and must never expose an action button for relay/TRV/safety
control.

## Placement in the current Home Assistant dashboard

Current target is the existing storage dashboard `heating-panel`, view
`agents` / **Agenti**, section index 4. That section already contains the
Replay, Intelligence, Safety, Permissions, Watchdog and Release Gate tiles plus
one combined markdown evidence card.

For a future YELLOW dashboard-only change, keep those six status tiles and
replace/extend only the existing full-width evidence card below them. Do not
create another top-level agent view and do not add any control card. The
current card path is `views[1].sections[4].cards[7]`.

## Visual hierarchy

```text
┌────────────────────────────────────────────────────────────────────┐
│ COMPOSITE FLOW-RISK                 SHADOW ONLY · NO CONTROL        │
│ INSUFFICIENT FEATURE EVIDENCE                                      │
│ “PI/TRV demand is a proxy; physical flow is not confirmed.”        │
├────────────────────────────────────────────────────────────────────┤
│ Evidence gate                                                     │
│  Faults       0 / 3   █░░░      Normal controls   0 / 20  ░░░░    │
│  Val. faults  0 / 1   ░          Val. controls    0 / 10  ░░░░    │
├───────────────────────────────┬────────────────────────────────────┤
│ Selected candidate            │ Quality                            │
│ PI10 ≤ —                      │ Evidence false positive      —     │
│ Block rise ≥ —                │ Validation false positive    —     │
│ Phase —                       │ Timely detections             —     │
│ Request age ≥ —               │ Misses                        —     │
│                               │ Median lead                   — s   │
├───────────────────────────────┴────────────────────────────────────┤
│ Candidate comparison: false-positive rate vs median lead           │
│ [compact scatter / ordered bars; evidence candidates only]         │
├────────────────────────────────────────────────────────────────────┤
│ Status trail                                                       │
│ Evidence collection → Evidence-only selection → Held-out validation│
│ → Human safety review (required before any physical proposal)       │
└────────────────────────────────────────────────────────────────────┘
```

## Status treatment

Use restrained diagnostic semantics:

- **grey/neutral** — waiting for feature-traced data;
- **amber** — insufficient evidence or candidate needs refinement;
- **green** — platform/validation process healthy, not “safe to control”;
- **red** — only actual Safety Sentinel violation, permission violation,
  storage failure or broken guard invariant.

Do not color `PROMISING_SHADOW_CANDIDATE` as a safety approval. It remains a
hypothesis. Pair it with a permanent `SHADOW ONLY · NO CONTROL` badge.

## Primary data

Source: `sensor.heating_agent_replay` attributes after 0.4.1 materializes a
new replay generation.

Panel fields from `composite_flow_risk`:

- `status`;
- `dataset.evidence_faults` / minimum 3;
- `dataset.evidence_normal_controls` / minimum 20;
- `dataset.validation_faults` / minimum 1;
- `dataset.validation_normal_controls` / minimum 10;
- `candidate_rule`;
- `candidate.definition.pi10_max`;
- `candidate.definition.block_rise_min`;
- `candidate.definition.phase`;
- `candidate.definition.request_age_min`;
- evidence and validation `timely`, `missed`, `warned_normal_rate`,
  `lead_median_s`;
- `validation_used_for_ranking`;
- `active_protection_changed`;
- `deployment_allowed`.

The top banner should also consume:

- `sensor.heating_agent_safety`;
- `sensor.heating_agent_permissions`;
- `sensor.heating_agent_watchdog`.

## Interaction

Default view shows only the gate, current candidate and quality metrics.
A details disclosure opens the top evidence-ranked rules and their metrics.

No panel interaction may:

- turn relay/TRVs on or off;
- modify schedules or temperatures;
- change safety thresholds;
- promote a candidate to active protection;
- perform deployment.

The only meaningful navigation action is “Open evidence details”, which remains
read-only.

## First 0.4.1 deployment state

Immediately after deployment it is expected that legacy replay counts can exist
while Composite Flow-Risk shows no feature-traced evidence. Display:

**Collecting new 0.4.1 feature-traced episodes**

rather than copying legacy 1/33/1/11 counts into the composite gate. This avoids
presenting historical data as if the new composite features had been observed.
