# Heating Home Assistant config

## Automatic protective and debug checks

Projekt obsahuje automatické ochranné a auditní kontroly, aby nebylo nutné je spouštět ručně.

### Kdy se kontroly spouští automaticky
- **Primárně v CI (GitHub Actions)** přes workflow `Heating audit and validation` při změnách v `heating/**`, `automations.yaml`, `configuration.yaml` a `scripts/**`.
- **Volitelně lokálně** přes `pre-commit` hook (`heating-protective-checks`) jako vývojářská pomůcka.

### Co se kontroluje
1. Konzistence zón napříč orchestrace/listy/helpery (`scripts/validate_zone_list_consistency.py`).
2. YAML syntaxe a HA styl guard (`trigger/condition/action`, zákaz legacy `triggers/actions`) (`scripts/validate_yaml_and_ha_style.py`).
3. Debug guardrail: jakýkoliv nový `[DEBUG]` blok musí obsahovat oba guardy:
   - `input_boolean.heating_debug_guard`
   - `input_datetime.heating_debug_until`
   (`scripts/validate_debug_guards.py`)
4. Smoke/checklist coverage guard (existence a minimální obsah smoke matice + checklistu) (`scripts/validate_smoke_coverage.py`).

### PASS/FAIL pravidla
- **PASS**: všechny kontroly vrátí exit code 0.
- **FAIL**: alespoň jedna kontrola vrátí exit code 1 → commit/CI se zastaví.

### Lokální spuštění (volitelné, ne primární ochrana)
```bash
python3 scripts/run_protective_checks.py
```

### Poznámka k Home Assistant kompatibilitě
Plná runtime kompatibilita se vždy potvrzuje až v cílovém HA prostředí (`ha core check`/`check_config`). V repozitáři je nyní zaveden fail-fast guard pro YAML syntax + styl a konzistenci orchestrace.
