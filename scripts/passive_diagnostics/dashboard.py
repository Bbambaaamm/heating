"""Read-only cards appended to the existing heating-observation view."""
import json
from pathlib import Path

PAIR = r"""{% set beat=states('input_text.heating_pair_heartbeat')[3:]|float(0) %}
**Párování:** {{ 'běží' if as_timestamp(now())-beat < 60 else 'záznam není čerstvý' }}

| Zóna | Cíl | Hlášení cíle | Změna PI |
|:--|--:|--:|--:|
{% for z,name in [('sklep_michal','Sklep'),('prizemi_michal','Přízemí Michal'),('prizemi_chodba_zachod','Chodba / WC'),('1p_jidelna','Jídelna'),('1p_kuchyn','Kuchyň'),('1p_koupelna','Koupelna'),('1p_chodba','Chodba 1. patro'),('2p_mama','Máma')] -%}
{% set p=states('input_text.heating_pair_'~z)[3:]|from_json({}) -%}
| {{ name }} | {{ p.v if p else '—' }} | {{ (p.a|round(1)|string ~ ' s') if p and p.a is not none else '—' }} | {{ (p.p|round(1)|string ~ ' s') if p and p.p is not none else '—' }} |
{% endfor %}

Poslední párování se drží nejvýše 10 minut. Historie je ve společném deníku pozorování. Časy běží od prvního povelu; opakování do 30 s se slučují. Chybějící hlášení se nezapočítá jako úspěch.

Změna cíle a PI je pouze časová souvislost. **Nepotvrzuje otevření ventilu ani průtok.**"""

SHADOW = r"""{% set p=states('input_text.heating_restart_shadow_v1')[3:]|from_json([]) %}
{% set s=states('input_text.heating_restart_stats_v1')[3:]|from_json([1,0,0,0,[[0,0,0],[0,0,0],[0,0,0]]]) %}
{% set e=states('input_text.heating_restart_episode_v1')[3:]|from_json([]) %}
**Interní restarty:** {{ 'záznam běží' if p|length==9 and as_timestamp(now())-p[5]<45 else 'záznam není čerstvý' }}

Bez zachycené poruchy: **{{ s[1] }}** · S poruchou: **{{ s[2] }}** · Neúplné: **{{ s[3] }}**

{{ 'Právě sledujeme okno restartu.' if e else 'Čekáme na další interní restart.' }}

| Pravidlo | Varování bez poruchy | Předstih ≥60 s | Pozdě / bez varování |
|:--|--:|--:|--:|
{% for row in s[4] -%}
| R{{ loop.index }} | {{ row[0] }} | {{ row[1] }} | {{ row[2] }} |
{% endfor %}

**R1:** v pauze hořáku mají méně než 3 hlavice PI ≥10 %.

**R2:** v pauze mají méně než 2 hlavice PI ≥20 %.

**R3:** podmínka R1 trvá alespoň 30 s.

Pauza musí patřit do souvisle sledovaného požadavku kotle. Předstih počítáme k prvnímu hlášení poruchy, ne až k pozdějšímu servisnímu kódu. Výpadky dat a neúplná okna vyřazujeme z hodnocení.

Jde o novou statistiku **restart-shadow-v1**, oddělenou od původního pozorování. 60 s je porovnávací předpoklad, nikoli ověřená doba otevření. **Pravidla nic neovládají a nedokazují, že by zásah poruše zabránil.**"""

def section():
    return {'type':'grid','cards':[
        {'type':'heading','heading':'Povely a interní restarty','icon':'mdi:flask-outline'},
        {'type':'markdown','title':'Odezva hlavic','content':PAIR},
        {'type':'markdown','title':'Pravidla nanečisto','content':SHADOW},
    ]}

if __name__=='__main__':
    import sys
    Path(sys.argv[1]).write_text(json.dumps(section(),ensure_ascii=False,indent=2))
