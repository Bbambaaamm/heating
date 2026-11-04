# Návrh nezávislé zpětné vazby kontaktu

Stav `switch.kotel_rele_spinac` u Aqara T2 je hlášení zařízení, nikoli nezávislé měření rozepnutí jeho kontaktu. Režim `Power` v HA sám nepotvrzuje fyzickou polohu můstku ani zapojení svorek. Nic zde nebylo přepnuto a fyzické svorky nebyly ověřeny.

## Doporučené řešení k posouzení skutečného zapojení

Použít vhodné rozhraní s nuceně vedenými kontakty: kontakt NO pro požadavek kotle a příslušný mechanicky svázaný NC pro nezávislou indikaci. Výrobce musí tento konkrétní pár deklarovat jako nuceně vedený podle EN 61810-3; libovolné dva kontakty běžného relé tuto vlastnost nemají. Výběr závisí na dosud neověřeném napětí, proudu a požadavcích termostatického vstupu Bosch, včetně minimální spínané zátěže.

Zpětný kontakt může číst digitální vstup zařízení napájeného z odděleného malého napětí, například Shelly Plus Uni. Oddělení od obvodu Bosch musí zajistit správně navržený kontakt/rozhraní; samotný digitální vstup modulu nelze automaticky označit za galvanicky oddělený. Výstupy čtecího modulu by se nepoužívaly k ovládání kotle.

Pokud Aqara ovládá cívku vloženého relé, jde o změnu fyzické akční cesty: skutečný kotlový kontakt je potom na novém relé a jeho zpětná vazba sleduje tento kontakt. Nepotvrzuje stav původního kontaktu Aqara. Pouhé paralelní snímání cívky nebo další obyčejné relé nedokáže vyloučit přivaření sledovaného kontaktu.

## Vyhodnocení v HA až po fyzickém zapojení

Pasivně porovnávat povel, skutečný zpětný kontakt a čas zapálení. Při rozporu zaznamenat přesný čas a upozornit; nedostupný vstup vést jako neznámý, nikoli jako potvrzené rozepnutí. Dobu ustálení stanovit měřením při uvedení do provozu. První verze pouze diagnostická, bez nového automatického zámku.

Nová entita se nevytváří před zapojením a ověřením čidla. Návrh není hotový elektroprojekt, svorkový plán ani potvrzení vhodnosti konkrétního výrobku pro daný kotel. Aktuálně nebyl instalován žádný nový hardware a přímé parametry Bosch se nemění.

## Primární zdroje

- Finder: [Safety relays with forcibly guided contacts](https://www.findernet.com/en/uk/news/safety-relays-with-forcibly-guided-contacts-finder/).
- Finder: [Series 50 datasheet](https://cdn.findernet.com/app/uploads/S50EN.pdf), deklarované páry, EN 61810-3 a minimální zátěže.
- Shelly: [Plus Uni knowledge base](https://kb.shelly.cloud/knowledge-base/shelly-plus-uni), vstupy a napájení.
- Aqara: [T2 FAQ](https://www.aqara.com/eu/dual-relay-module-t2/dual-relay-module-t2-faq/), fyzická konfigurace suchého/mokrého kontaktu.
