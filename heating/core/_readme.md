# Core senzory vytápění

**Jak přidat novou zónu:**
1. Duplikuj jeden ze souborů `zone_*.yaml`, přejmenuj (např. `zone_2p_loznice.yaml`).
2. Uprav entity `climate.*` a odpovídající `sensor.*_detekovano_otevrene_okno`.
3. Do `aggregate_kotel.yaml` přidej novou zónu do seznamů (aktivní/demand).
4. Kontrola YAML → Rychlé nové načtení → ověř nové entity `zona_*` a `kotel_*`.
