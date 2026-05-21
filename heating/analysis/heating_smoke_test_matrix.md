# Smoke test matice pro topení

Tento dokument převádí auditní doporučení na opakovatelný postup.
Cíl je konzervativní: ověřit stabilitu orchestrace před změnami seznamů zón.

## Předpoklady
- Home Assistant konfigurace je načtena bez chyb (`check_config`).
- Integrace, které dodávají teplotní data, jsou dostupné.
- V testu je dostupná entita `input_boolean.heating_central_dispatch_enable`.

## Scénář 1: Přepínání režimů bez konfliktů
1. Nastav `input_select.topny_rezim` postupně: `Off -> Auto -> Eco -> Boost -> Auto`.
2. Po každém kroku zkontroluj v trace automací, že se nespouští konfliktní zápisy na stejnou `climate.*` entitu ve stejném čase.
3. Ověř, že `binary_sensor.kotel_boost_active` odpovídá režimu Boost.

## Scénář 2: Boost lifecycle
1. Zapni `input_boolean.boost_now`.
2. Ověř vyplnění `input_datetime.boost_until` a aktivaci `binary_sensor.kotel_boost_active`.
3. Po vypršení nebo ručním ukončení Boost ověř návrat na plánované hodnoty.

## Scénář 3: Manual override lifecycle
1. U vybrané zóny zapni `input_boolean.<zona>_manual_override`.
2. Nastav odpovídající `input_select.<zona>_manual_override_type`.
3. Ověř, že běží `timer.<zona>_manual_override`.
4. Proveď restart Home Assistant a ověř startup reconcile (override zůstane konzistentní).

## Scénář 4: Dispatch ON vs OFF
1. Spusť scénář režimů s `input_boolean.heating_central_dispatch_enable = on`.
2. Zopakuj stejný scénář s `input_boolean.heating_central_dispatch_enable = off`.
3. Porovnej výsledné setpointy a ověř, že fallback větev je funkčně konzistentní.

## Scénář 5: Fail-safe simulace
1. Simuluj `unavailable` na jednom relevantním vstupu (např. testovací čidlo).
2. Ověř vznik očekávané notifikace a logbook události.
3. Po návratu vstupu do normálu ověř recovery bez ručního zásahu.

## Záznam výsledků
- Datum testu:
- Prostředí:
- Výsledek scénáře 1 až 5 (PASS/FAIL):
- Poznámky k odchylkám:
