"""Contract tests for passive reducers: ordering, lost reports and fault timing."""
import importlib.util
import json
import math
from pathlib import Path
import unittest
from jinja2 import Environment, StrictUndefined

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('passive_build',ROOT/'scripts/passive_diagnostics/build.py')
B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)
ENV=Environment(undefined=StrictUndefined)
ENV.filters['to_json']=json.dumps
ENV.filters['from_json']=json.loads
ENV.globals['is_number']=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
TEMPLATES={}
def render(src,**ctx):
 import ast
 if src not in TEMPLATES:TEMPLATES[src]=ENV.from_string(src)
 return ast.literal_eval(TEMPLATES[src].render(**ctx))
def pair(p,r,t=1000,reset=False):return render(B.pair_logic,p=p,r=r,z='climate.sklep_michal',t=t,reset=reset)
def cmd(t=1000,v=29):return {'kind':'command','event_at':t,'service':'set_temperature','targets':['climate.sklep_michal'],'requested':{'temperature':v},'zones':{'climate.sklep_michal':{'target':21,'demand':10}},'context_id':'a'*26}
def reported(t,target=29,old_target=21,pi=10,old_pi=10,state='heat'):
 return {'kind':'reported_state','event_at':t,'entity':'climate.sklep_michal','before':{'target':old_target,'demand':old_pi,'state':'heat'},'after':{'target':target,'demand':pi,'state':state}}
def s(t,**kw):return dict(t=t,r=1,g=0,master=1,service=0,c10=2,c20=1,quality=[],fault_edge=False,fault_source='',**kw) if not kw else dict(s(t),**kw)
class Shadow:
 def __init__(self):self.phase=[];self.episode=[];self.stats=[];self.events=[]
 def feed(self,t,reset=False,**kw):
  out=render(B.shadow_logic,phase=self.phase,episode=self.episode,stats=self.stats,s=s(t,**kw),reset=reset)
  self.phase=out['phase'];self.episode=out['episode'];self.stats=out['stats'];self.events+=out['events']
  for obj in (self.phase,self.episode,self.stats):assert len(json.dumps(obj))<=255
  return out
 def request(self):
  self.feed(1000,r=0);self.feed(1001,r=1);self.feed(1002,g=1)
  for t in range(1010,1101,10):self.feed(t,g=1)
  self.feed(1102,g=0)
 def pause_until(self,end):
  for t in range(1110,end+1,10):self.feed(t)

class PairTest(unittest.TestCase):
 def test_target_and_pi_are_separate(self):
  p=pair({},cmd())['next'];r=pair(p,reported(1005),1005)
  self.assertEqual(r['next']['a'],5);self.assertIsNone(r['next']['p'])
  r=pair(r['next'],reported(1030,old_target=29,pi=80),1030)
  self.assertEqual(r['next']['p'],30);self.assertIn('pair_complete',[e['kind'] for e in r['events']])
 def test_duplicate_retains_first_command(self):
  p=pair({},cmd())['next'];p=pair(p,cmd(1010),1010)['next']
  self.assertEqual(p['t'],1000);self.assertEqual(p['n'],2)
  r=pair(p,reported(1015),1015);self.assertEqual(r['next']['a'],15)
 def test_out_of_order_cannot_match(self):
  p=pair({},cmd())['next'];r=pair(p,reported(999),1001)
  self.assertIsNone(r['next']['a']);self.assertEqual(r['events'][0]['kind'],'pair_out_of_order')
 def test_superseded_has_new_baseline(self):
  p=pair({},cmd())['next'];r=pair(p,cmd(1004,15),1004)
  self.assertEqual(r['next']['v'],15);self.assertEqual(r['events'][0]['kind'],'pair_superseded')
 def test_timeout_not_success(self):
  p=pair({},cmd())['next'];r=pair(p,{},1601)
  self.assertEqual(r['next'],{});self.assertEqual(r['events'][0]['kind'],'pair_timeout')
 def test_same_target_report_is_not_new_ack(self):
  p=pair({},cmd())['next'];r=pair(p,reported(1003,old_target=29),1003)
  self.assertIsNone(r['next']['a'])
 def test_restart_interrupts(self):
  p=pair({},cmd())['next'];r=pair(p,{},1001,True)
  self.assertEqual(r['next'],{});self.assertEqual(r['events'][0]['kind'],'pair_interrupted')
 def test_unknown_interrupts(self):
  p=pair({},cmd())['next'];r=pair(p,reported(1001,state='unavailable'),1001)
  self.assertEqual(r['next'],{})
 def test_pi_can_precede_target(self):
  p=pair({},cmd())['next'];r=pair(p,reported(1002,target=21,old_target=21,pi=30),1002)
  self.assertEqual(r['next']['p'],2);self.assertIsNone(r['next']['a'])
 def test_size_with_real_timestamps(self):
  p=pair({},cmd(1790115000.123),1790115000.123)['next']
  self.assertLessEqual(len(json.dumps(p)),255)

class ShadowTest(unittest.TestCase):
 def test_first_start_not_internal(self):
  h=Shadow();h.request();self.assertEqual(h.episode,[])
 def test_unknown_running_at_load_not_internal(self):
  h=Shadow();h.feed(1000,g=1,reset=True);h.feed(1010,g=0);h.feed(1020,g=1)
  self.assertFalse(any(e['kind']=='shadow_internal_restart' for e in h.events))
 def test_actual_fault_precedes_service_code(self):
  h=Shadow();h.request();h.pause_until(1200);h.feed(1201,g=1)
  h.feed(1211,g=0,fault_edge=True,fault_source='lastcode')
  h.feed(1221,g=0,fault_edge=True,fault_source='code',quality=['active_fault'])
  for t in range(1230,1521,10):h.feed(t,r=0,master=0,service=1)
  self.assertEqual(h.stats[2],1);self.assertEqual(h.stats[3],0)
  closed=[e for e in h.events if e['kind']=='shadow_episode_closed'][-1]
  self.assertEqual(closed['first_fault_at'],1211)
  self.assertEqual(closed['leads_s'][0],109)
 def test_code_only_fault_not_censored_by_fault_itself(self):
  h=Shadow();h.request();h.pause_until(1200);h.feed(1201,g=1)
  h.feed(1210,g=0,fault_edge=True,fault_source='code',quality=['active_fault'])
  self.assertTrue(h.episode[4]);self.assertEqual(h.episode[5],1210)
 def test_clean_scoring_after_five_minutes(self):
  h=Shadow();h.request();h.pause_until(1140);h.feed(1141,g=1);h.feed(1151,g=0)
  for t in range(1160,1461,10):h.feed(t)
  self.assertEqual(h.stats[1],1);self.assertEqual(h.stats[4][0][0],1)
 def test_missing_telemetry_censors(self):
  h=Shadow();h.request();h.pause_until(1140);h.feed(1141,g=1)
  h.feed(1151,g=0,quality=['stale_flow'])
  for t in range(1160,1461,10):h.feed(t)
  self.assertEqual(h.stats[3],1);self.assertEqual(h.stats[1],0)
 def test_capture_gap_does_not_score_clean(self):
  h=Shadow();h.request();h.pause_until(1140);h.feed(1141,g=1);h.feed(1250,g=0)
  self.assertEqual(h.stats[3],1);self.assertEqual(h.stats[1],0)
 def test_continuous_low_pi_rule(self):
  h=Shadow();h.request();h.feed(1120);self.assertEqual(h.phase[6][2],0)
  h.feed(1135);self.assertEqual(h.phase[6][2],1135)
  h.feed(1140,c10=4,c20=3);self.assertEqual(h.phase[6],[0,0,0])
 def test_warning_onset_not_clipped_to_180_seconds(self):
  h=Shadow();h.request();h.pause_until(1400);h.feed(1401,g=1);h.feed(1410,g=0,fault_edge=True,fault_source='lastcode')
  self.assertEqual(h.episode[3][0],1102)
  self.assertEqual(h.events[-1]['leads_s'][0],308)
 def test_reload_censors_pending(self):
  h=Shadow();h.request();h.pause_until(1140);h.feed(1141,g=1);h.feed(1142,g=1,reset=True)
  self.assertEqual(h.stats[3],1);self.assertEqual(h.episode,[])
 def test_no_actuator_service_in_generated_configs(self):
  def walk(x):
   if isinstance(x,dict):
    if isinstance(x.get('action'),str):self.assertIn(x['action'],['input_text.set_value','logbook.log'])
    for v in x.values():walk(v)
   elif isinstance(x,list):
    for v in x:walk(v)
  walk(B.pair);walk(B.shadow)

if __name__=='__main__':unittest.main()
