# Composite Flow-Risk dashboard activation plan

This branch is a **YELLOW, source-only** dashboard proposal. It does not modify
the live Home Assistant Lovelace storage.

Target discovered from a read-only live dashboard audit:

- dashboard: `heating-panel`;
- view: `agents` / Agenti;
- section: `views[1].sections[4]`;
- current combined Replay/Safety markdown card:
  `views[1].sections[4].cards[7]`.

The proposed native markdown card is
`dashboard/heating-panel-agents-composite-flow-risk-card.yaml`.

## Future activation gate

Activation is intentionally outside this PR. Before a future dashboard write:

1. Heating Agent Platform 0.4.1 must already be running read-only.
2. Safety Sentinel must be OK, Permissions PASS/default-deny and Watchdog HEALTHY.
3. Fetch the dashboard fresh and locate the existing Replay/Safety card again;
   do not rely only on the historical numeric index.
4. Preserve the six existing status tiles.
5. Add/replace only the diagnostic markdown content; no action button, service
   call or physical-control entity may be introduced.
6. Render the `agents` view and visually verify desktop and mobile layouts.
7. Roll back only the modified dashboard card if rendering or semantics are
   wrong; do not restore unrelated Home Assistant state.

The card intentionally shows “Sběr nových 0.4.1 feature-traced epizod” when the
new composite payload does not exist. It never substitutes legacy replay counts
for the new composite dataset.
