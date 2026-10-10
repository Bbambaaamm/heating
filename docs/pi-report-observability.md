# PI report time in passive heating diagnostics

Observer 0.4.2 keeps cached PI as a proxy and explicitly marks the time of its last actual Zigbee report as unknown. A change to a climate target or room temperature can update the Home Assistant climate state without a new PI report. The HA state timestamp cannot establish PI freshness. A repeated unchanged PI report may also be suppressed before the HA state is written.

Each captured zone includes `pi_source=cached_ha_climate_attribute`, `pi_reported_at=null`, `pi_report_age_sec=null` and `pi_report_time_quality=unknown`. `climate_state_reported_at` and `climate_state_updated_at` identify the existing HA state times. The older `reported_at` and `updated_at` fields remain compatible aliases for these climate times. They do not describe a PI attribute report. The snapshot and diagnostic set `pi_report_freshness_verified=false`.

Hydraulic hypotheses name stored PI proxies and retain the existing conservative confidence value 0.50 when they use a low zone count. Empty general quality flags no longer imply PI freshness. Historical snapshots without the new metadata receive the same qualification. Temperature-only hypotheses retain their scoring, and unknown PI report time does not suppress existing temperature warnings or shadow capture. These scores are diagnostic heuristics, not measured probabilities or operating limits.

This change records uncertainty; it does not collect raw PI reports. A future passive collector must observe incoming Zigbee attribute reports, including repeated unchanged values, and must start with unknown time after restart. Cache reads, setpoint changes, availability and a device's general last-seen time must not populate PI report time. A reporting interval or freshness limit needs separate validation.

No actuator calls, SQL migration, heating thresholds or hydraulic safeguards change. A current PI report would still not prove a physically open valve or adequate water flow.
