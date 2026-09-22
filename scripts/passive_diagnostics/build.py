"""Build API-deployable passive diagnostics. Never calls a device service.

The generated exports are deployment inputs, NOT an auto-loaded HA package.
Live config edits use guarded HA config APIs; this script has no network I/O.
"""
from pathlib import Path
import json

HERE=Path(__file__).parent
ZONES=['sklep_michal','prizemi_michal','prizemi_chodba_zachod','1p_jidelna','1p_kuchyn','1p_koupelna','1p_chodba','2p_mama']
CLIMATES=['climate.'+z for z in ZONES]
PAIR_HELPERS=['input_text.heating_pair_'+z for z in ZONES]
PHASE='input_text.heating_restart_shadow_v1'
EPISODE='input_text.heating_restart_episode_v1'
STATS='input_text.heating_restart_stats_v1'
PAIR_BEAT='input_text.heating_pair_heartbeat'
HELPERS=PAIR_HELPERS+[PHASE,EPISODE,STATS,PAIR_BEAT]
EVENT='heating_response_observed_v2'
pair_logic=(HERE/'pair.jinja').read_text()
shadow_logic=(HERE/'shadow.jinja').read_text()

def condition(v):return {'condition':'template','value_template':v}
def set_text(e,v):return {'action':'input_text.set_value','target':{'entity_id':e},'data':{'value':'v2:'+v}}
def log(name,message,entity=None):
 d={'name':name,'message':message}
 if entity:d['entity_id']=entity
 return {'action':'logbook.log','data':d}

pair_actions=[]
for z,helper in zip(CLIMATES,PAIR_HELPERS):
 pair_actions.extend([
  {'variables':{'z':z,'p':"{{ states('"+helper+"')[3:]|from_json({}) }}",'t':'{{ as_timestamp(now()) }}'}},
  {'variables':{'result':pair_logic}},
  {'if':[condition('{{ result.next != p }}')],'then':[set_text(helper,'{{ result.next|to_json }}')]},
  {'repeat':{'for_each':'{{ result.events }}','sequence':[
   log('Topení – párování DATA',"{{ dict(schema='heating_pair_v2',entity=z,captured_at=t,physical_valve_position_confirmed=false,causal_match_confirmed=false,event=repeat.item)|to_json }}"),
   log('Topení – párování',"{% set e=repeat.item %}{% set names={'pair_started':'Povel zařazen','pair_duplicate':'Opakovaný povel','pair_target_reported':'Změna cíle hlášena','pair_pi_changed':'Změna PI hlášena','pair_complete':'Obě hlášení zachycena','pair_timeout':'Párování neúplné po 10 min','pair_superseded':'Nahrazeno novým povelem','pair_diverged':'Hlášen jiný cíl','pair_interrupted':'Párování přerušeno','pair_out_of_order':'Opožděná nebo přeházená událost','pair_unsupported':'Nepodporovaný povel'} %}{{ state_attr(z,'friendly_name') or z }}: {{ names.get(e.kind,e.kind) }}.{% if e.get('delay_s') is not none %} Za {{ e.delay_s|round(1) }} s od prvního povelu.{% endif %}{% if e.kind=='pair_complete' %} Cíl {{ e.pending.a|round(1) }} s; změna PI {{ e.pending.p|round(1) }} s; povelů {{ e.pending.n }}.{% endif %} Jde o časovou souvislost hlášení, ne potvrzení pohybu ventilu.",'sensor.heating_observer_learning')
  ]}}
 ])
pair_actions.append(set_text(PAIR_BEAT,'{{ as_timestamp(now())|int }}'))
pair={
 'id':'heating_response_pair_v2','alias':'Topení – párování povelů a hlášení',
 'description':'Pasivní diagnostika v2. Páruje skalární set_temperature s novou změnou cíle a první změnou PI. Stejný povel do 30 s slučuje; jiný cíl ukončí předchozí párování. Timeout 600 s, přerušení při startu HA/reloadu automatizací. Nepotvrzuje doručení, pohyb ani příčinnost. Zapisuje pouze diagnostické input_text a deník. Parametry nejsou bezpečnostní limity.',
 'triggers':[{'trigger':'event','event_type':EVENT,'id':'record'},{'trigger':'time_pattern','seconds':'/15','id':'tick'},{'trigger':'homeassistant','event':'start','id':'reset'},{'trigger':'event','event_type':'automation_reloaded','id':'reset'}],
 'variables':{'r':"{{ trigger.event.data.get('record',{}) if trigger is defined and trigger.id=='record' else {} }}",'reset':"{{ trigger is defined and trigger.id=='reset' }}"},
 'conditions':[], 'actions':pair_actions,'mode':'queued','max':100,'max_exceeded':'warning'
}

snapshot=r'''{% set n=namespace(q=[],demands=[],zone_states={}) %}
{% set t=as_timestamp(now()) %}
{% set r=1 if is_state('switch.kotel_rele_spinac','on') else 0 if is_state('switch.kotel_rele_spinac','off') else -1 %}
{% set g=1 if is_state('binary_sensor.boiler_burngas','on') else 0 if is_state('binary_sensor.boiler_burngas','off') else -1 %}
{% set master=1 if is_state('input_boolean.topny_system_enable','on') else 0 if is_state('input_boolean.topny_system_enable','off') else -1 %}
{% set service=1 if is_state('input_boolean.heating_service_mode','on') else 0 if is_state('input_boolean.heating_service_mode','off') else -1 %}
{% if -1 in [r,g,master,service] %}{% set n.q=n.q+['unknown_control_state'] %}{% endif %}
{% if not is_state('sensor.system_bus_status','connected') %}{% set n.q=n.q+['bus_not_connected'] %}{% endif %}
{% for e in ['sensor.boiler_heatblock','sensor.boiler_curflowtemp'] %}
{% set st=states[e] %}
{% if st is none or not is_number(st.state) %}{% set n.q=n.q+['invalid:'~e] %}
{% elif (st.state|float)<-20 or (st.state|float)>150 %}{% set n.q=n.q+['range:'~e] %}
{% elif t-as_timestamp(st.last_reported)>45 or t-as_timestamp(st.last_reported)<0 %}{% set n.q=n.q+['stale:'~e] %}{% endif %}
{% endfor %}
{% for e in ['binary_sensor.boiler_wwcharging','binary_sensor.boiler_wwrecharging','binary_sensor.boiler_ww3wayvalve'] %}
{% if not is_state(e,'off') %}{% set n.q=n.q+['dhw_or_unknown:'~e] %}{% endif %}{% endfor %}
{% for e in climates %}
{% set st=states[e] %}{% set pi=state_attr(e,'pi_heating_demand') %}
{% if st is none or st.state not in ['heat','off'] or not is_number(pi) %}{% set n.q=n.q+['invalid:'~e] %}
{% elif (pi|float)<0 or (pi|float)>100 %}{% set n.q=n.q+['range:'~e] %}
{% else %}{% set n.demands=n.demands+[pi|float if st.state=='heat' else 0] %}{% endif %}
{% set n.zone_states=dict(n.zone_states,**{e:{'pi':pi,'target':state_attr(e,'temperature'),'state':states(e)}}) %}
{% endfor %}
{% if not is_number(states('sensor.boiler_servicecodenumber')) %}{% set n.q=n.q+['unknown_service_code'] %}{% endif %}
{% if states('sensor.boiler_servicecodenumber') in ['2964','2965','2966','2967'] %}{% set n.q=n.q+['active_fault'] %}{% endif %}
{% set f=namespace(edge=false,source='') %}
{% if trigger is defined and trigger.id in ['lastcode','code'] and trigger.from_state is not none and trigger.to_state is not none and trigger.from_state.state not in ['unknown','unavailable',''] %}
{% set old=trigger.from_state.state %}{% set new=trigger.to_state.state %}
{% if old!=new and ((trigger.id=='code' and new in ['2964','2965','2966','2967']) or (trigger.id=='lastcode' and old.split(' - ')[0]!=new.split(' - ')[0] and new|regex_search('\(296[4-7]\)'))) %}
{% set f.edge=true %}{% set f.source=trigger.id %}{% endif %}
{% endif %}
{{ dict(t=t,r=r,g=g,master=master,service=service,c10=n.demands|select('ge',10)|list|length,c20=n.demands|select('ge',20)|list|length,quality=n.q,block=states('sensor.boiler_heatblock')|float(none),flow=states('sensor.boiler_curflowtemp')|float(none),power=states('sensor.boiler_curburnpow')|float(none),zones=n.zone_states,fault_edge=f.edge,fault_source=f.source)|to_json|from_json }}'''

shadow={
 'id':'heating_restart_shadow_v1','alias':'Topení – pasivní pravidla interních restartů',
 'description':'restart-shadow-v1: jen diagnostika. R1 během pauzy uvnitř sledovaného požadavku <3 hlavice s PI>=10%; R2 <2 s PI>=20%; R3 R1 trvá 30 s. Onsety uchovává bez 180s ořezu a porovnává s prvním hlášením poslední chyby i aktuálním kódem. Samostatné statistiky restartů; po 300 s od gas-off nebo při dalším startu uzavře okno. 60 s je pouze porovnávací rozpočet. Při restartu/gapu vyřadí rozpracované okno. Neřídí žádné zařízení.',
 'triggers':[{'trigger':'time_pattern','seconds':'/10','id':'tick'},{'trigger':'homeassistant','event':'start','id':'reset'},{'trigger':'event','event_type':'automation_reloaded','id':'reset'},
 {'trigger':'state','entity_id':['switch.kotel_rele_spinac','binary_sensor.boiler_burngas','input_boolean.topny_system_enable','input_boolean.heating_service_mode'],'id':'control'},
 {'trigger':'state','entity_id':'sensor.boiler_servicecodenumber','id':'code'},
 {'trigger':'state','entity_id':'sensor.boiler_lastcode','id':'lastcode'}],
 'variables':{'climates':CLIMATES,'s':snapshot,'reset':"{{ trigger is defined and trigger.id=='reset' }}"},
 'conditions':[],
 'actions':[{'variables':{'phase':"{{ states('"+PHASE+"')[3:]|from_json([]) }}",'episode':"{{ states('"+EPISODE+"')[3:]|from_json([]) }}",'stats':"{{ states('"+STATS+"')[3:]|from_json([]) }}"}},
 {'variables':{'result':shadow_logic}},
 set_text(PHASE,'{{ result.phase|to_json }}'),
 {'if':[condition('{{ result.episode != episode }}')],'then':[set_text(EPISODE,'{{ result.episode|to_json }}')]},
 {'if':[condition('{{ result.stats != stats }}')],'then':[set_text(STATS,'{{ result.stats|to_json }}')]},
 {'repeat':{'for_each':'{{ result.events }}','sequence':[
 log('Topení – restart SHADOW DATA',"{{ dict(schema='restart-shadow-v1',physical_flow_confirmed=false,actuator_control=false,captured_at=s.t,event=repeat.item,snapshot=s)|to_json }}"),
 log('Topení – restart nanečisto',"{% set e=repeat.item %}{% set labels={'shadow_baseline':'Nový začátek pozorování','shadow_internal_restart':'Interní restart zachycen','shadow_other_start':'První nebo nezařazený start','shadow_warning_on':'Podmínka začala platit','shadow_warning_off':'Podmínka přestala platit','shadow_fault_first':'První hlášení poruchy','shadow_fault_update':'Další hlášení stejné skupiny poruch','shadow_episode_closed':'Okno restartu vyhodnoceno'} %}{{ labels.get(e.kind,e.kind) }}.{% if e.get('rule') is not none %} Pravidlo R{{ e.rule }}.{% endif %}{% if e.get('duration_s') is not none %} Délka {{ e.duration_s }} s.{% endif %}{% if e.get('outcome') %} Výsledek {{ e.outcome }}; důvod {{ e.reason }}.{% endif %}{% if e.get('leads_s') %} Předstihy R1/R2/R3: {{ e.leads_s|to_json }} s.{% endif %} Blok {{ s.block }} °C; hlavic PI≥10 %: {{ s.c10 }}. Pouze pozorování.",'sensor.heating_observer_learning')
 ]}}], 'mode':'queued','max':100,'max_exceeded':'warning'
}

def build(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 bundle={'helpers':HELPERS,'pair':pair,'shadow':shadow,'source_event':{'event':EVENT,'event_data':{'record':'{{ record }}'}}}
 (out/'diagnostics.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2))
 return bundle

if __name__=='__main__':
 import sys
 build(sys.argv[1])
