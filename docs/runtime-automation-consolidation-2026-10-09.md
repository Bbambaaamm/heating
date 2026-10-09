# Konsolidace topení HA / Git — 9. října 2026

## Výchozí ověřený stav

Zdroj: živý Home Assistant OS 18.2 / Core 2026.9.2 na `/config`, uživatelsky spravované automatizace + GitHub `Bbambaaamm/heating`.

- `automations.yaml` v HA obsahuje 39 objektů, předchozí GitHub `main` pouze 15.
- **24 nových vůči Gitu:** 17 běží, 7 je záměrně vypnutých (legacy Flow V2/fault reconciler, timeout guard, testování a pozorování).
- **4 sdílené objekty** se od `main` obsahově lišily. Dva z nich jsou rovněž záměrně vypnuté.
- Celkově **9 výslovně vypnutých** objektů má `initial_state: false`. Zbývající nově verzované objekty mají `initial_state: true`.
- Zdrojové konfigurace včetně hashů a stavů jsou zaznamenány ve čtyřech `docs/runtime-automations-20261009-part*.json` a chráněny regresními testy.

## Blueprint: queued versus restart

**Zvolený režim: `queued`, `max: 20`, `max_exceeded: warning`.**

Důvody:
- To je skutečně nasazená varianta v HA. Živý diagnostický záznam u jídelny, kuchyně, koupelny a přízemí ukázal krátké a dokončené invokace bez zahlcené fronty.
- Blueprint během aktivního centrálního dispatchingu funguje hlavně jako **ingest** manuální změny teploty a typu override. Opožděné události nepovažuje automaticky za fyzické otočení hlavice.
- `restart` může zrušit rozpracované ukládání uživatelsky zadaného komfortu, když dorazí další stavový trigger.
- Ve fallback režimu blueprint před povelem hlavice ověřuje čerstvé vstupy `fallback_inputs` (kalendář, režim, manuál, časovač, ECO/comfort, Boost). Starý požadavek tedy nemá bez nové kontroly přepsat aktuální cíl.
- Fronta zůstává **omezena na 20** a při překročení limity upozorní. V případě výrazného nárůstu latencí Zigbee je potřeba nejdřív vyhodnotit frontu a skutečné doručení.

Rozdíly selectorů `domain: climate` vs `domain: [climate]`, `multiple: false`, `reorder: false`, `mode: slider` jsou převážně normalizace editorem HA. Ostatní výkonná logika blueprintu byla při diff auditu totožná; záměrně se nemění.

## Jediný vlastník TUV interlocku

**Aktivní:** `automation.topeni_tuv_interlock_rele_live` (ID `1791310763182`) v `automations.yaml`.

- Jakmile sepne TUV třícestný ventil, nabíjení TUV nebo aktivní odběr teplé vody, guard vypne topné relé.
- Při pokusu o opakované sepnutí relé během TUV jej vypne.
- V4 start `automation.kotel_v4_bezpecny_start_podle_politiky` zároveň vyžaduje všechny TUV interlocky OFF před i po 120s prodlevě. Po skončení TUV se startuje plná prodleva.
- Z `heating/control/kotel_control.yaml` byla odstraněna druhá, ekvivalentní automatizace `kotel_tuv_relay_interlock`, která by při nasazení vytvořila dvě paralelní instance.
- Historická `kotel_turn_on_by_policy` zůstává v balíčku jen jako deaktivovaná záložní definice (`initial_state: false`). Aktivní start vlastní V4.

## Návrat po ručním servisním režimu

Izolované testy odhalily další rozdíl: servisní obnovovací skript maže uložené `heating_service_restore_main_enable`. Starý servisní závěr jej mazal ještě před zavoláním restore a neměl spolehlivé opětovné povolení masteru.

Zpřesněná logika:
1. Při `service_off` uložit do lokální proměnné, zda byl master před ručním servisem ON.
2. Vypnout master/relé a počkat na dokončení skutečného obnovovacího skriptu.
3. Master znovu povolit pouze když před servisem byl ON, všechny hlavice se obnovily a `heating_restore_verified=on`, Flow V4 je `NORMAL`, EMS fault-clear je ON, sběrnice EMS connected, není lockout, servis OFF, plamen OFF a heatblock pod 72 °C.
4. Pokud kterákoli podmínka selže, master zůstává vypnutý; žádný automatický bypass.
5. **Relé se nikdy nezapíná přímo tímto skriptem.** Stále musí projít V4 120s policy s TUV a průtokovým guardem.

## Kontrolní testy

- `python -m unittest tests.test_runtime_automation_inventory -v`
- `python -m unittest discover -s tests -v` pro Home Assistant 2026.5.1 a 2026.9.2
- `python scripts/run_protective_checks.py`
- `ha core check` na reálném hostiteli po selektivní změně souborů; nikdy ne během přepisování.

**Povinné pojistky:** nesepnout kotel s aktivními kódy 2964–2967, při `HARD_LOCKOUT`, v nouzovém chlazení či při TUV. Nepřepisovat pracovní strom lokální větve `nasazeni/topeni-20260918` nevýběrovým `git pull`; soubory jsou zachovávány v provozu na základě skutečného stavu, ne podle data commitu.

## Nasazení

Tento PR aktualizuje GitHub a obsahuje testovatelný obraz požadované konfigurace. Dočasné aktivace a vypnutí některých legacy objektů v HA jsou skutečné provozní stavy, nikoli důkaz, že `git checkout main` zachová jejich stav. Před případným nasazením je nutná **záloha místních souborů**, porovnání sekcí podle ID a jejich stavů, `ha core check`, a oddělené bezpečné reloady. Nepřepínat fyzické relé kvůli regresnímu testu.
