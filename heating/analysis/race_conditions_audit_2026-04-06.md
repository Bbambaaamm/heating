# Audit race conditions a časových problémů (kritický)

Datum: **2026-04-06**  
Scope: `smart_zone_schedule` blueprint, `mode_auto`, `mode_boost`, central dispatch, override/timer startup automace.

---

## 1) Souběžné spouštění automations

### RC-1: Paralelní zápisy setpointu při přechodovém stavu (cutover / burst triggerů)

**Pozorování:**
- Centrální aktuační skript je `mode: parallel` (`script.heating_apply_zone_target`).
- Central dispatch je `mode: restart`, ale při burstu triggerů může několikrát rychle odstartovat skript pro stejné climate entity.
- V legacy režimu (`heating_central_dispatch_enable = off`) zároveň zapisují teplotu blueprinty + boost automace.

**Dopad:**
- „Last writer wins“: cílová teplota může krátce oscilovat podle pořadí dokončení paralelních běhů.
- Zbytečný zápisový šum do Zigbee zařízení + logbook spam.

**Důkazy v konfiguraci:**
- `script.heating_apply_zone_target` je paralelní a zapisuje `climate.set_temperature`.  
- `heating_dispatch_mode_schedule_override` reaguje na velké množství vstupů, včetně timerů a override helperů.  
- Blueprint má vlastní actuation větev, když je central dispatch OFF.

**Návrh opravy:**
1. Přepnout `script.heating_apply_zone_target` na `mode: queued` + `max: 1` (globální serializace zápisů) nebo rozdělit na per-zóna skripty (lepší škálování).
2. Do central dispatch přidat debounce (např. krátké `delay: 1-2s` + `mode: restart`), aby se burst triggerů sloučil do jednoho výpočtu.
3. V legacy režimu explicitně zakázat boost apply automation, pokud zóna právě prošla ručním zásahem v posledních X sekundách.

---

### RC-2: Současný trigger „reapply po Boost OFF“ + scheduler edge

**Pozorování:**
- Po přechodu `kotel_boost_active -> off` se hromadně triggerují `_bp` automace / central dispatch.
- Ve stejném čase může scheduler přepínat komfortní okno (`scheduler_entity on/off`) a spouštět stejné zónové automace.

**Dopad:**
- Dvojité spuštění stejné logiky v krátkém čase.
- Nejde o hard-fail, ale o race na timing + zbytečné přepisy.

**Návrh opravy:**
- Místo `automation.trigger` všech zón poslat jediný „reconcile event“ (`event.fire`) a nechat jednu orchestraci přepočítat cíle.
- U `_bp` scénáře přidat podmínku „pokud poslední trigger < 2s, skip“ i pro scheduler triggry (teď se cooldown na scheduler nevztahuje).

---

## 2) Přepisování teploty více zdroji

### RC-3: Multi-writer problém (Blueprint vs Boost vs Central dispatch)

**Pozorování:**
- Při `heating_central_dispatch_enable = off` píšou teplotu:
  - zónové blueprinty,
  - boost automation,
  - implicitně i uživatel přes UI/fyzickou hlavici.
- Při `on` se blueprint tváří jako ingest-only, ale pořád se spouští a manipuluje override lifecycle.

**Dopad:**
- Obtížná predikce výsledného setpointu v přechodových stavech.
- Riziko, že uživatel „nastaví“, ale systém hned přepíše (z pohledu uživatele „systém bojuje proti mně“).

**Návrh opravy:**
1. Zaveďte **single writer policy**: teplotu smí zapisovat jen central apply script.
2. Blueprint a boost automace převést na „intent-only“ (zapisují helpery/stavy, ne climate.set_temperature).
3. Přidat auditní atribut (např. helper `input_text.heating_last_writer`) a při každém zápisu ukládat zdroj + timestamp.

---

### RC-4: Auto režim při návratu ruší Boost, ale zároveň spouští re-apply

**Pozorování:**
- `mode_auto` při přepnutí na Auto vypne `boost_now`, nastaví `boost_until = now()`, čeká na `kotel_boost_active = off`, pak triggeruje rozvrhy/dispatch.
- Současně může běžet `heating_boost_reapply_schedule_off` (trigger na stejnou hranu `boost_active -> off`).

**Dopad:**
- Dvě orchestrace návratu po Boostu mohou běžet skoro zároveň.
- Duplicita zápisů a občasné „cuknutí“ cíle teploty.

**Návrh opravy:**
- Vybrat jednoho „ownera“ návratu po Boostu:
  - buď jen `mode_auto`,
  - nebo jen `heating_boost_reapply_schedule_off`.
- Druhý tok nechat jen logovat (bez triggeru zón).

---

## 3) Smyčky a rychlé přepínání

### RC-5: Trigger na `climate.temperature` může generovat pseudo-smyčky

**Pozorování:**
- Blueprint se triggeruje změnou atributu `temperature` u climate entity.
- Automatizace sama tu samou hodnotu nastavuje, což vytváří re-trigger chain.
- Ochrana přes `abs > 0.1` loop většinou zastaví, ale přesto vzniká vysoká frekvence triggerů při šumu zařízení.

**Dopad:**
- Zbytečné běhy automace, vyšší latence ostatních akcí.

**Návrh opravy:**
- Do triggeru na `attribute: temperature` přidat `for: "00:00:02"` (odfiltrovat krátký jitter).
- Doplnit guard: pokud je `trigger.to_state.context.parent_id` z vlastní automation/script, skipnout celý běh (nejen část větví).

---

### RC-6: Rychlé přepínání režimů Auto/Boost/Eco

**Pozorování:**
- `heating_boost_start` zapisuje `boost_until` při `Boost`/`boost_now on`.
- `mode_auto` při Auto resetuje `boost_until` na `now()`.
- Při rychlém klikání režimů (sekundy) rozhoduje pořadí dokončení samostatných automací.

**Dopad:**
- Dočasně nekonzistentní `kotel_boost_active` (krátký ON/OFF jitter), který spouští další automace.

**Návrh opravy:**
1. Zaveďte transakční helper `input_datetime.mode_change_guard_until` (cooldown 3-5s po změně režimu).
2. Dokud běží guard, ignorovat další módové triggery (kromě Off = hard stop).
3. Přidat explicitní prioritu: `Off` má možnost přerušit vše okamžitě, ostatní režimy čekají na uvolnění guardu.

---

## 4) Prioritizovaný plán oprav

### P0 (hned)
1. **Single writer**: serializovat/zcentralizovat zápis teploty.  
2. **Odstranit dvojí „reapply po Boost OFF“ orchestrace.**  
3. **Debounce trigger burstů** (dispatch + climate attribute).

### P1 (krátkodobě)
1. Režimový guard proti rychlému přepínání Auto/Boost/Eco.
2. Lepší observabilita: měřit počet zápisů/minutu na zónu a alarm při anomálii.

### P2 (střednědobě)
1. Přechod blueprintů na čistý ingest layer.
2. Event-driven orchestrace místo hromadných `automation.trigger`.

---

## 5) Měřitelné akceptační podmínky (po opravách)

1. **Max 1 zápis/5 s na jednu zónu** při stabilním stavu (bez ručního zásahu).  
2. Po `Boost -> Off` proběhne **právě jedna** orchestrace návratu.  
3. Při 10 rychlých změnách režimu během 15 s nevznikne více než 1 finální přenastavení setpointu na zónu.  
4. Logbook bude mít jasný „writer source“ pro každý zápis setpointu.

---

## 6) Kritický závěr

Současná konfigurace je funkční, ale z pohledu concurrency není deterministická ve všech přechodových stavech. Největší slabina je **více zapisovačů teploty** a **duplicitní orchestrace při změnách Boost/Auto**. Dokud nezavedete single-writer model a debounce režimových přechodů, bude systém občas „cuknout“ setpointem i bez skutečné potřeby.

---

## 7) Implementační patchset (doporučeno aplikovat jako první)

1. **Central apply script serializovat**
   - `script.heating_apply_zone_target`: přepnout z `mode: parallel` na `mode: queued`.
   - Přidat krátký debounce (`delay: 1s`) do `heating_dispatch_mode_schedule_override`.

2. **Odstranit duplicitní návrat po Boost OFF**
   - V `mode_auto` spouštět hromadný re-apply jen když Boost před vstupem do Auto **nebyl aktivní**.
   - Pokud Boost aktivní byl, re-apply nechávat pouze na `heating_boost_reapply_schedule_off`.

3. **Anti-loop ochrana v blueprintu**
   - Trigger na `climate.temperature` doplnit o `for: 2s` (odfiltrování jitteru).
   - Přidat guard, který interní změny z automation/script (`parent_id != null`) ukončí hned na začátku běhu.
