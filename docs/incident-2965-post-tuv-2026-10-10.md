# Incident 2026-10-10 – 2965 po TUV, čerpadlo OFF a hydraulická podpora jediné žádající zóny

## Rozlišení dvou problémů

1. **Počet vytápěných místností:** `input_number.kotel_min_active_zones=1` je už trvale nastaven, avšak `sensor.kotel_effective_min_active_zones=2` používá bezpečnostní `[configured,2]|max`. Není to samovolná změna nastavení. Jde o záměrný softwarový limit po dřívějších reálných chybách 2964 při jedné hlavici. Dvě softwarově započítané zóny **neprokazují fyzický průtok**.
2. **Vysoká teplota po TUV:** nový skutečný kód **2965** a 87,8 °C po vypnutí hořáku. Toto je samostatná provozní závada (čerpadlo, hydraulika, čidlo nebo přepínací ventil); samotná změna počtu zón ji nevyřeší.

## Časová osa podle živého HA recorderu (Europe/Prague)

| Čas | Událost |
|---|---|
| 05:27:54 | Jedna skutečná zóna požaduje teplo; automatická podpora zvolí `climate.1p_chodba`, nastaveno 29 °C |
| 05:29:03 | Podpůrná hlavice hlásí `Potřebné teplo=ON` |
| 05:30:03 | PI podpory 76 %, agregace eviduje dvě zóny; žádná ochrana se neuvolňuje bez potvrzení |
| 05:32:03 | Topné relé ON, 05:32:14 hořák ON |
| 05:32:40–05:35:03 | Přibyla třetí žádající zóna; podpora ukončena; následně stále dvě započítané zóny |
| **05:47:44** | Třícestný ventil a `wwcharging` hlásí TUV ON; topné relé OFF, hořák OFF, `heatingpump` OFF |
| 05:47:54–05:48:14 | EMS `heatingpump`/modulace krátce ON/100 %, následně OFF/0 % |
| 05:48:04 | Flow V4 přechází do `EMERGENCY_COOLING`, hlavní povolení vypnuto; otevírá únikové TRV |
| 05:48:54 | Kotlový blok **80,8 °C**, čerpadlo stále OFF |
| **05:49:24** | Špička **87,8 °C**, čerpadlo a hořák dle EMS OFF |
| **05:49:34** | EMS skutečně zapisuje **2965** |
| 05:50:44 | Teplota klesla na 74,8 °C, relé i hořák OFF |
| 05:52:51 | Teplota 55,2 °C, Flow V4 v `NORMAL`, fault-clear ON, relé OFF |

## Co bylo zjištěno

- **Hydraulická podpora jedné žádající zóny umí fungovat**: v 05:29–05:30 přijala 29°C nastavení a PI 76 %. Neplatí proto, že by vždy selhávala.
- Jiný pokus s `climate.prizemi_chodba_zachod` skončil při 29 °C jen PI 1 %, `Potřebné teplo=OFF`. Motorické kroky a TRV cílová teplota nedokládají fyzický průtok.
- Ochrana Flow V4 vypíná topný master/relé a nouzově otevírá hlavice, ale **nevlastní interní čerpadlo kotle**. Proto nedokáže zajistit oběh vody jen otevřením TRV.
- Původní HA watchdog upozorňoval na teplo >69 °C **pouze při hořáku ON** a v jeho vypnutém stavu mohl persistentní vysokoteplotní alarm smazat. Chybu 2965 však oznamoval až samostatný fault trigger.
- **Bezpečnostní doplněk:** nezávislé pasivní upozornění při heatblock >80 °C a pumpa OFF, i když je hořák OFF. Telefon se upozorní pouze při novém přechodu na vysokou teplotu či při zastavení pumpy; periodická kontrola jen obnoví persistentní zprávu, bez opakovaných push notifikací. Nemění relé, hlavice, nastavení EMS ani režim Flow V4.

## Fyzické ověření nutné před snížením tvrdého minima na jednu zónu

Kvalifikovaný servis Bosch musí změřit a ověřit:

1. Tlak soustavy v chladném a horkém stavu a správné naplnění/odvzdušnění.
2. **Skutečný hydraulický průtok** přes primární výměník při topení i během přepínání TUV, včetně tlakové diference a případného obtoku; samotné `boiler_pc0flow=0` je nepoužitelné jako měření.
3. Funkci **čerpací jednotky, dobu doběhu** a chování řídicí desky při TUV; EMS `heatingpump OFF` je telemetrie, nikoliv měření skutečného průtoku.
4. Položku třícestného ventilu, filtr/sítko, polohu uzavíracích ventilů a snímač výstupní teploty, včetně montáže a konektorů.
5. Doporučené řešení trvale dostupné hydraulické cesty (výrobcem/technikem navržený bypass či správně dimenzovaný vždy otevřený otopný okruh).

Teprve po **fyzickém** potvrzení průtoku může v další změně politika připustit jednu opravdu žádající zónu jako dostatečnou. **Neobcházet přirozené fault kódy 2964–2967.**

## Zdroj

Bosch Condens 2300i W – český instalační a servisní návod 6720889912, tabulka kódů 2964/2965: kontrola tlaku, čerpadla a polohy ventilů.

https://dokumenty.maro.cz/prilohy/Bosch_Condens_2300i_W_15_P_23_24_P_23_22_25_C_23_navod_k_instalaci_a_udrzbe.pdf

Původní fyzická diagnostika zůstává v GitHub issue #151. Stav no-pump vysokoteplotního alarmu je dokumentován samostatně, nikoliv jako oprava hydrauliky.
