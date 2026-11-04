# Nasazení stínové predikce, 4. listopadu 2026

Schválené Q3: opravená automatizace `predictive_heating_shadow_recalc` byla nasazena do existujícího objektu `automation.predictive_heating_shadow_prepocet`. Běží pouze stínový výpočet. Zapisuje osm textových výsledků, souhrn, čas pokusu a heartbeat; neovládá hlavice, relé ani EMS parametry kotle.

Zdroj živé automatizace je v kořenovém `automations.yaml`, se zapnutím `initial_state: true`. Testovaný kandidát zůstává vypnutý mimo načítané balíčky. Dva nové helpery byly vytvořeny přes UI storage API; jejich konfigurace je exportována v `heating/analysis/predictive_shadow_storage_helpers.json`. JSON není YAML balíček a nevytváří duplicitní helpery při restartu.

## Ověření živého běhu

- Ruční spuštění pouze stínové automatizace: 20:50:38 Europe/Prague, trace `033ffabe5304686d9257e53af5b9a4bc`, dokončeno bez chyby.
- Následný automatický běh: 20:55:00, zápisy 8/8, platná data 8/8, posunutý heartbeat.
- Stav `DEGRADED`, předpověď 0/8, neznamená v tomto případě výpadek poskytovatele: služba vrátila 48 hodinových položek, ale žádná zóna neměla ze Scheduleru dostupný příští komfortní start (`next_comfort_ts: none`). Výpočet výslovně označil použití aktuálního počasí. Budoucí komfortní start tímto živým během ověřen nebyl; scénáře předpovědi a jejích selhání pokrývají runtime testy.
- Souhrn, časy, původní/nový hash, přesný readback konfigurace a název předchozí zálohy jsou v sousedním JSON záznamu.
- Automatizace byla po zápisu znovu načtena a porovnána s kořenovým zdrojem po normalizaci klíčů trigger/condition/action. Shoda se týká těchto změněných objektů, nikoli celé instalace HA.

## Oddělené úkoly

Observer 0.4.5 má soubory již nainstalované, ale při tomto záznamu běží 0.4.4. Aktivace kolem 22:15 je samostatná naplánovaná úloha s kontrolou podmínek. Nový detektor zapálení zatím nedodal první záznam; chybějící senzor není důkaz nulového počtu startů.

Nezávislá fyzická zpětná vazba kontaktu není instalovaná. Návrh je v `relay-contact-feedback-proposal-2026-11-04.md`. Tento krok nemění bezpečnostní řízení ani desetiminutový limit softwarového zámku.
