# Flow V4 incident audit — 2026-10-08

Status: diagnosis only; no production safety bypass. Do not merge or deploy until HA/Git YAML comparison, backup, validation and review.

## Confirmed from Home Assistant
- Emergency cooling at 11:43, 15:43, 21:44, 21:56 Europe/Prague.
- Final event: boiler relay ON 21:55:04, burner ON 21:55:23, relay OFF 21:55:50, heatblock 73 C at 21:56:13; HARD_LOCKOUT 21:59:15.
- On final event, flow paths verification was reset OFF at 21:56:13 and never confirmed ON. Restoration verification ON, fault clear ON, EMS bus connected, heatblock 29.5 C, but lockout ON and boiler OFF.
- ZHA APS_NO_ACK failures observed; script heating_apply_zone_target has repeated errors. Do not equate Zigbee acknowledgement with physical valve position.
- Live script heating_apply_zone_target has a hydraulic-support target >=29 C condition not found in main branch heating/control/refactor_mode_schedule_override.yaml.
- Recorder warns heating_agent_opportunities attributes exceed 16384 bytes.
- System log reports duplicate alias in package refactor_mode_schedule_override.yaml; validate the current actual on-disk file and config before restart.

## Required next checks before a code change
1. Snapshot on-disk /config and compare against Git main (including untracked and local changes); inspect template helper heating_flow_relief_confirmed and all TRV motor steps/availability.
2. Inspect pre-restart flow, demand, boiler burner, valve and circulation pump histories; establish why 73 C was reached.
3. Verify recovery event sequencing and why paths_confirmed did not fire during final event. Preserve HARD_LOCKOUT until safe physical flow is verified.
4. Add regression tests for failed Zigbee writes, stale decisions, restart after emergency, two-path confirmation and manual/schedule restoration.
5. Validate HA configuration and observe real post-deploy behavior before claiming synchronization.
