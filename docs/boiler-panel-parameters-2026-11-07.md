# Parametry Bosch z displeje bez přímého odečtu v EMS-ESP

Ruční odečet 7. 11. 2026 v 11:32 (Europe/Prague). Kotel Bosch Condens 2300i W, GC2300iW 24 P 23. Porovnáno s entitami Home Assistantu, záznamem sběrnice a dekodérem EMS-ESP 3.8.4. Tabulky zachycují stav při tomto odečtu.

## Odečtené hodnoty a dostupnost online

| Kód | Parametr | Odečet z kotle | Co máme přes EMS/HA |
|---|---|---|---|
| Manometr | Tlak otopné soustavy | 1,6 bar | Pole tlaku v `0xE4` na offsetu 21 mělo `FF` ve všech 202 vzorcích. Bez platného digitálního odečtu. |
| `1-A2` | Aktuální kód poruchy na panelu | `0` | HA má aktuální provozní kód a poslední uloženou poruchu. `0xC2` v exportu obsahuje uložený kód `2964`. Samostatný ekvivalent panelového `1-A2` nebyl ověřen. |
| `1-A3` | Horní mez výkonu vytápění | 100 % | Samostatný údaj nedostupný. Online `burnmaxpower` odpovídá nastavenému limitu `3-b1`. |
| `1-A4` | Horní mez výkonu ohřevu teplé vody | 100 % | Samostatný údaj nedostupný. |
| `1-E1 / 1-E2` | Verze softwaru ovládacího panelu | 5 / 6 | Přímý odečet panelu nedostupný. EMS eviduje verzi elektroniky kotle `05.06`, která odpovídá `1-EA / 1-Eb`. |
| `1-E3 / 1-E4` | Číslo a verze kódovacího konektoru | `25078` / `3` | Mapování nenalezeno. |
| `2-A1` | Hydraulická konfigurace | `0` | Mapování nenalezeno. EMS `headertemp` je teplota. |
| `3-C1` | Nastavený limit výkonu ohřevu teplé vody | 100 % | `0xEA`, offset 21 → `64` (100). Shoda čísla, význam pole nepotvrzený. |
| `3-C7` | Ruční spuštění termické dezinfekce | OFF | EMS hlásí provozní příznak dezinfekce. Přímá vazba na položku panelu nebyla ověřena. |
| `3-d6` | Nastavený doběh čerpadla vytápění | 3 min | `0xE6`, offset 12 → `03` ve všech 33 odpovědích. Dekodér uvádí tento offset jako kandidáta a hodnotu nepublikuje. |
| `4-A1 / 4-A2` | Odvzdušnění / plnění sifonu | `1` / `1` | Mapování nenalezeno. |
| `4-F1 / 4-F2` | Obnovení základního nastavení / reset chybových hlášení | `NO` / `NO` | Přímý odečet voleb nedostupný. |
| `5-A1` | Servisní strop výstupní teploty | 82 °C | `0xE6`, offset 3 → `52` (82). Shoda čísla, význam pole nepotvrzený. Provozní požadavek `1-A6` byl 65 °C. |
| `5-A3` | Minimální jmenovitý tepelný výkon | 12 % | Dříve používaný offset 5 v `0xE6` vrací `0D` (13). EMS-ESP toto mapování odstranil. |
| `6-t1 / 6-t2 / 6-t3` | Test zapalování / ventilátoru / čerpadla | OFF / OFF / OFF | Přímý odečet servisních testů nedostupný. |
| `6-t5 / 6-tA / 6-tb` | Test třícestného ventilu / ionizačního oscilátoru / hořáku | `0` / OFF / `0` | Přímý odečet servisních testů nedostupný. Běžné provozní stavy ventilu a hořáku lze sledovat samostatně. |
| `0-A1 / 0-A2` | Ruční režim / jeho požadovaná teplota | OFF / 60 °C | `0xE6`, offsety 18 a 19 → `00 3C`. EMS je publikuje jako nouzový provoz. Hodnoty se shodují, přímé mapování na položky panelu zůstává nepotvrzené. |

## Měřicí položky bez platné hodnoty

| Kód | Parametr | Displej | Surový EMS záznam |
|---|---|---|---|
| `1-b3 / 1-b5` | Skutečná teplota teplé vody / zásobníku | Položky chyběly | `0xE9`, teplotní pole na offsetech 1 a 3 → `80 00` ve všech 202 vzorcích. |
| `1-C4` | Venkovní teplota | `---` | `0xD1` → `7F FF` nebo `80 00`. |
| `1-C6` | Digitální tlak otopné soustavy | Položka chyběla | `0xE4`, offset 21 → `FF`. Hodnota 1,6 bar pochází z manometru. |

Offsety se počítají od nuly v datech telegramu a respektují offset fragmentu. Počet vzorků udává opakování hodnoty ve stejném exportu. Kandidátní mapování zůstávají diagnostickými poznámkami. Konfiguraci kotle přes EMS lze podle [pravidel projektu](../AGENTS.md) pouze číst. Kotel v této instalaci vytápí prostory, teplou vodu zajišťují samostatné karmy. Příznaky teplé vody v EMS popisují hlášený vnitřní stav kotle.

## Zdroje

- [Bosch Condens 2300i W, servisní návod 6720889912](https://junkers-cz-cs-b.boschhc-documents.com/download/pdf/file/6720889912.pdf?token=1uncspjqa55d7nsijsjm5effa0)
- [Bosch Condens 2300i W, starší vydání 6720889912 s popisem 1-A4 a 3-C1](https://dokumenty.maro.cz/prilohy/Bosch_Condens_2300i_W_15_P_23_24_P_23_22_25_C_23_navod_k_instalaci_a_udrzbe.pdf)
- [Dekodér kotle EMS-ESP 3.8.4](https://github.com/emsesp/EMS-ESP32/blob/v3.8.4/src/devices/boiler.cpp)
- [EMS-ESP #2918, odstranění mapování minimálního výkonu](https://github.com/emsesp/EMS-ESP32/issues/2918)
