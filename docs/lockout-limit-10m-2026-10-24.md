Uživatel 24. 10. 2026 výslovně požaduje nejvýše desetiminutový softwarový
zámek a jeho automatické zrušení po každém vypršení.

První zablokování spustí `timer.heating_lockout_limit_10m` na 600 sekund.
Přechod EMERGENCY_COOLING → RESTORING → HARD_LOCKOUT časovač neprodlužuje.
`restore: true` zachová aktivní odpočet při restartu. Pokud HA naběhne
s blokací a časovač už není aktivní (včetně vypršení během výpadku), zámek
se zruší při startu; nových deset minut se nepřidává. Za vypnutého HA
nemůže automatizace běžet.

Vypršení vždy smaže `heating_flow_relief_lockout`, nezávisle na aktuálním
servisním kódu. HARD_LOCKOUT a RESTORING přejdou zpět do NORMAL. Při skutečně
aktivním nouzovém chlazení software drží odvod tepla do ochlazení pod 60 °C,
explicitního burner OFF a připojených EMS, ale historický zámek už neplatí.
Běžící otevírání hlavic ve dvou dávkách časovač nepřeruší. Po vychladnutí
obnovu dokončí existující periodický reconcile bez nového zamčení.

Návrat k automatice respektuje původní povolení topení, servisní režim
a potvrzené obnovení cílů hlavic. Při neúspěšném obnovení hlavic zámek
stejně skončí, hlavní povolení se však nevynutí.

Časovač ani nová větev neobsahují `switch.turn_on` a nezapisují do Bosch
parametrů. Jediným vlastníkem sepnutí zůstává původní automatizace bezpečného
startu se všemi kontrolami poruchy, EMS, teploty a požadavků zón. Zrušení
časového zámku proto není příslib zapálení při trvající skutečné překážce.

Zdroj timeru a automatizace je `heating/control/lockout_limit_10m.yaml`.
V živém HA se timer vytváří jako UI helper a automatizace ukládá přes API;
stejný timer se současně nesmí znovu přidávat jako YAML helper. Změna vlastníka
Flow V4 se ukládá přes API s kontrolou původního konfiguračního hashe.

Ověření: skutečný HA Core 2026.5.1 s izolovanými simulovanými zařízeními;
vypršení při poruše, běžný zpožděný start, zachování blokace aktuální poruchou
a teplotou, restart/reload, chladnutí, ochrana rozpracovaného otevírání,
neprodlužování odpočtu a zachování ručního vypnutí. Živým kotlem nebyla
vyvolána žádná zkušební porucha ani zkušební blokace.

Návrat: vrátit předchozí konfiguraci Flow V4 z rodičovského Git commitu,
vypnout novou automatizaci a zrušit její časovač. Běžný start a nezávislá
vypínací ochrana touto změnou nebyly upraveny.
