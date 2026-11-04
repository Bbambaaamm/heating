# Nezávislé ověření kontaktu topného relé

Stav k 4. 11. 2026: protokol připraven; fyzické měření nebylo provedeno.
HA sám nezávislou zpětnou vazbu skutečné polohy kontaktu nemá.

## Ověřená identita a čtené stavy

- Zařízení v HA: Aqara `lumi.switch.acn047`, dva kanály.
- Řízený kanál: `switch.kotel_rele_spinac`; druhý: `switch.kotel_rele_spinac_2`.
- Při kontrole první kanál ON, druhý OFF, přepínací režim `Power`, oba vstupy
  `ControlRelay`. Tyto hodnoty nebyly měněny.
- Fyzické přiřazení kanálu ke kabelu kotle musí potvrdit technik. Softwarový
  název entity ani režim Power sám neurčuje fyzické zapojení kontaktů.

## Zadání pro technika

1. Podle přesného označení modulu a instalační dokumentace kotle identifikovat
   skutečný spínaný výstup a termostatický vstup; zkontrolovat, zda požadavek
   na kotel nemůže přivést druhý kanál nebo paralelní propojení.
2. Ověřit fyzické provedení kontaktového rozhraní podle dokumentace Aqara.
   Modul T2 rozlišuje suchý a napájený kontakt zapojením propojky; název režimu
   v HA není nezávislým měřením tohoto zapojení. Zapojení ani parametry se v
   tomto protokolu automaticky nemění.
3. Nezávisle zaznamenat skutečný stav výstupu relé a požadavek na termostatickém
   vstupu při běžném zapnutí a vypnutí regulací. Zvolit přístroj a postup podle
   skutečného obvodu. Kontinuita se neměří na živém obvodu a paralelní cesty se
   musí odlišit od samotného kontaktu. Měření provádí kvalifikovaný technik.
4. K měření přiřadit přesný čas Europe/Prague. Z HA uložit oba kanály relé,
   `burngas`, ionizační proud, čítače startů, čerpadlo, teploty vody/bloku,
   servisní kód, WW příznaky včetně `tapwateractive` a `wwactivated` a Flow V4.
   Zapsat počáteční stav, přechod i následný průběh.

| Hlášení HA a nezávislé měření | Co lze uzavřít | Co zůstává neověřeno |
|---|---|---|
| HA OFF, ověřený kontakt příslušného kanálu sepnutý | Nesoulad hlášení a skutečného výstupu | Konkrétní příčina v modulu, režimu nebo mapování |
| Kontakt rozpojený, termostatický vstup stále hlásí požadavek | Požadavek přichází jinou cestou nebo je chybně interpretován | Konkrétní větev zapojení / interpretace vstupu |
| Kontakt i externí požadavek vypnuté, nový start podpořený gas/ion/čítačem | Start nevysvětluje tento externí termostatický požadavek | Interní požadavek kotle, porucha nebo mapování EMS |
| Gas OFF, proud nula, po vypnutí roste teplota | Růst teploty bez těchto signálů hoření | Tepelný doběh a skutečný průtok |

Příznaky WW nejsou v této instalaci důkazem legitimní přípravy TUV. Kotel TUV
nedodává. Cvaknutí, LED a přijetí služby HA samy nepotvrzují polohu kontaktu.
Žádný z výše uvedených výsledků není bez měření potvrzenou příčinou poruchy.

## Referenční dokumentace výrobce

- [Aqara Dual Relay Module T2 – FAQ a kontaktové režimy](https://www.aqara.com/eu/dual-relay-module-t2/dual-relay-module-t2-faq/)
- [Aqara – oficiální návod T2](https://cdn.aqara.com/cdn/opencloud-product/mainland/product-manual/material/prd/1100007700920942592/en-user-manual-20230608094029.pdf)

Tento dokument nepovoluje změny interních parametrů Bosch, zkratování vstupů
ani vynucené zkušební zapálení asistentem.
