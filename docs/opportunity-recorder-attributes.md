# Opportunity sensor recorder attributes

Heating Observer 0.4.3 marks only the `items` attribute of
`sensor.heating_agent_opportunities` as unrecorded using Home Assistant's
native entity metadata. Large proposal/evidence lists can otherwise exceed
Core's 16,384-byte state-attribute limit, causing all attributes for that
state to be discarded.

The live sensor still exposes the full list. Agent database persistence and
opportunity lifecycle rules are unchanged. Recorder retains the count,
status/category summaries, eligibility counters, autonomy policy and
`actuator_control`. Other sensors retain their existing recorder attributes,
including temperature warnings, data quality, storage errors and watchdog
details. No control action, threshold or capture schedule is changed.

Existing discarded attributes cannot be recovered by this change. It does
not establish a cause for history-query gaps or thermal receipt staleness.

Regression tests load the real HA sensor platform and use Core's recorder
serializer with synthetic details above the size limit. The same data
without exclusion metadata reproduces the original empty-attribute result.
A second test checks temperature warnings, quality, storage errors and an
`items` attribute belonging to a different diagnostic sensor.

Install the component files through authorized filesystem access and verify
the running version, recorder summary attributes and preserved live
`items` after restart. A source merge alone does not verify installation.

Reference: [Home Assistant entity recorder metadata](https://developers.home-assistant.io/blog/2023/09/20/excluding-state-attributes-from-recording/).
