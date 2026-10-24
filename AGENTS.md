# AGENTS.md — závazná pravidla projektu heating

## Fyzická konfigurace instalace (potvrzeno uživatelem 2026-10-13)

- **Tento kotel NENÍ používán k přípravě teplé užitkové vody (TUV) a teplou vodu do koupelen nedodává.**
- **Teplou vodu v koupelnách zajišťují samostatné karmy.** Z kotle se provozuje vytápění prostoru, nikoli uživatelská dodávka TUV.
- Tato informace má přednost před dřívějšími hypotézami a názvy EMS entit v dokumentaci. Změnit ji lze pouze po výslovném potvrzení změny fyzické instalace uživatelem.

## Povinná interpretace EMS a nočního chodu

- Signály `binary_sensor.boiler_wwcharging`, `binary_sensor.boiler_tapwateractive`, `binary_sensor.boiler_ww3wayvalve` a podobné označují **hlášený vnitřní stav regulátoru kotle**, nikoli důkaz skutečného odběru či přípravy TUV v této instalaci.
- **NIKDY** nevysvětluj noční start hořáku bez požadavku na vytápění jako normální ohřev TUV. Formuluj ho jako **nevysvětlený start hořáku / nečekaný EMS TUV režim, který vyžaduje diagnostiku**.
- Při hořáku ON a relé vytápění OFF dokumentuj přesné časové návaznosti `burngas`, `tapwateractive`, `wwcharging`, `ww3wayvalve`, `wwactivated`, čerpadla, teploty, servisního kódu a stavu Flow V4. Rozlišuj hlášený stav, fyzicky doložený stav a hypotézu. Hoření bez požadavku se nesmí ignorovat jen proto, že EMS vyhlásí TUV příznak.
- Při fault kódech 2964–2967 vyhodnoť poruchu i v noci bez požadavku na vytápění. Zaměř se na interní požadavek regulátoru, mapování EMS-ESP, nastavení TUV, třícestný ventil, hydraulický průtok a čerpadlo. **Nepředpokládej**, že někdo pustil teplou vodu nebo že existuje funkční TUV větev.
- Incident 2026-10-13: relé prostorového vytápění i `boiler_wwactivated` OFF, přesto `wwcharging` a `ww3wayvalve` ON; hořák krátce ON okolo 03:59:35 a 04:02:25; fault 2964 v 03:59:55 a 04:02:45. Závěr je **nevysvětlený režim kotle / EMS**, nikoli legitimní ohřev TUV. Příčina není potvrzena.
- Starší texty označující tyto události jako „při TUV“, „po TUV“ nebo „TUV okruh“ popisují nejvýše **EMS indikaci**, nikoli ověřenou fyzickou přípravu teplé vody.

## Bezpečnost a změnové řízení

- **Trvalé zadání uživatele 2026-10-24: Git a HA mají být 1:1.** Každou schválenou změnu živé konfigurace topení uložit také do `Bbambaaamm/heating` a dokončit její začlenění do `main`; pouhý lokální commit ani nezkontrolovaná větev nestačí. Uživatel výslovně schválil odesílání změn do tohoto repozitáře jako součást synchronizace. Po nasazení znovu načíst změněné objekty z HA a porovnat je se zdrojem, včetně helperů a zapnutí automatizací. Nesoulad nebo blokované odeslání vždy uvést a netvrdit úplnou shodu bez kontroly. Synchronizují se konfigurace; průběžné provozní hodnoty nejsou zdrojovou konfigurací. Tento souhlas neopravňuje k zápisům do interních parametrů kotle ani k publikování přístupových údajů.

- **Výslovná změna uživatele 2026-10-24:** softwarový zámek trvá nejvýše 10 minut a potom se vždy automaticky zruší. Časovač se přechodem mezi stavy neprodlužuje. Zrušení historického zámku není povel k zapálení: běžný vlastník relé zachovává kontrolu aktuální poruchy, EMS, teploty a požadavků zón. Aktivní nouzové chlazení pokračuje do vychladnutí. Toto výslovné zadání nahrazuje dřívější zákaz automatického zrušení historického HARD_LOCKOUT; zákaz EMS zápisů a přímého nuceného sepnutí relé dál platí.

- **Obnova po přechodné překážce nesmí zůstat trvale zamčená pouze historickým stavem.** V `RESTORING` se čeká na explicitní hořák OFF, platnou teplotu pod mezí obnovy, fault-clear a připojené EMS. Timeout těchto přechodných podmínek zachová relé OFF a opakovatelnou obnovu; sám nesmí vytvořit nový `HARD_LOCKOUT`. Nečinnou obnovu znovu vyhodnotí minutový impuls, který nesmí přerušit běžící sekvenci ani znovu přepisovat již potvrzené cíle hlavic. Neověřené cesty, neúspěšná obnova hlavic a existující hardlock tím nejsou automaticky odblokovány.

- Žádné obcházení HARD_LOCKOUT, reset poruch nebo přepínání relé proti ochranám. **Hořák nespouštět bez ověřené hydraulické cesty.**
- Údaj PI demand nebo otevření hlavice nepotvrzuje skutečný průtok; zastaralý/nepodporovaný senzor `boiler_pc0flow = 0` sám průtok ani nepotvrzuje, ani nevylučuje.
- Zápis tohoto pravidla do Gitu **neznamená jeho nasazení do Home Assistantu**. Změny aktivního bezpečnostního řízení vyžadují samostatnou kontrolu, testy a bezpečnostní schválení.
- Analytická část / Safety Sentinel nesmí vyjímat hořák bez topného relé z upozornění pouze podle TUV příznaků. Jakoukoli změnu jeho implementace nejdříve prověřit testy a odborným review.

## Rozhraní termostatu a zákaz zápisů do parametrů kotle (upřesnění 2026-10-13)

- **Home Assistant nahrazuje běžný pokojový termostat.** Jediný úmyslně ovládaný akční vstup **samotného kotle Bosch** je `switch.kotel_rele_spinac` (externí topné relé). Normální deterministická regulace Home Assistantu **SMÍ** relé zapínat a vypínat podle požadavků zón a bezpečnostních ochran. Není to zásah do interní servisní konfigurace Bosch.
- Regulace může samostatně nastavovat radiátorové hlavice/TRV, rozvrhy a bezpečnostní stav Home Assistantu; to **není** oprávnění měnit parametry Bosch přes EMS.
- **Zakázat veškeré aktivní zápisy do interní konfigurace a ovládání kotle přes EMS-ESP/MQTT**, včetně `number.boiler_*`, `switch.boiler_*`, `select.boiler_*`, `text.boiler_*`, raw `ems-esp/boiler/*` příkazů a resetů. Výjimkou není ani `boiler/flowtemp`, `boiler/selflowtemp`, `boiler/heatingactivated`, `boiler/dhw.activated` či `boiler/forceheatingoff`. Tato rozhraní jsou pouze pro pasivní monitorování, pokud jde o parametry kotle.
- AI asistent a autonomní agenti mohou **číst** live EMS/HA telemetry a navrhovat změny k testům/review, ale nesmí samovolně posílat žádné aktivní příkazy kotli či přepisovat jeho servisní parametry. Také nesmí ručně sepínat relé proti ochranám nebo provádět neověřené zkušební starty.
- Stávající deterministické bezpečnostní automatizace Home Assistantu mají dál fungovat, včetně vypnutí a bezpečného sepnutí topného relé za ověřených podmínek. **Nezakazovat ani nevypínat legitimní termostatické ovládání relé** jen proto, že AI používá read-only přístup.
- Žádné obejití `HARD_LOCKOUT`, žádné obejití Flow V4, žádné vynucení zapálení bez ověřené hydraulické cesty; bezpečnostní incident nejdřív analyzovat.
- GitHub commit či návrh změny není nasazení do živého HA. Změny aktivní regulace/ochran vyžadují testy a lidskou bezpečnostní kontrolu; žádný automatický deployment.
- Historická kontrola 2026-10-13: všech **43** dostupných konfiguračních entit Bosch v HA; **38** mělo neměnnou dostupnou hodnotu od prvního pozorování 2026-10-08, **2** hlásí dynamické provozní požadované hodnoty (`number.boiler_selflowtemp`, `number.boiler_selburnpow`), **3** nedávají validní hodnoty. Tato kontrola **nedokládá** všechny historické zápisy ani neměnnost konfigurace před vznikem záznamu.
- Model z dřívější dokumentace: Bosch Condens 2300i W, GC2300iW 24 P 23; komunikace EMS-ESP. Kotel nezajišťuje TUV, koupelny používají samostatné karmy.
