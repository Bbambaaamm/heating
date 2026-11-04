"""Corroboration without actuators, WW exemptions or temperature-only claims."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from custom_components.heating_observer.const import CRITICAL, INPUTS
from custom_components.heating_observer.database import AgentDatabase
from custom_components.heating_observer.engine import Observer
from custom_components.heating_observer.ignition import IgnitionEvidence


def sample(t, **changes):
    return dict(t=1800000000+t, gas=False, relay=False, ion_current=0,
                burn_starts=100, heat_starts=80, ww_starts=20,
                block=35, flow=34, pump=False, dhw=False, dhw_valve=False,
                code=200, **changes)


class IgnitionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.d = IgnitionEvidence()
        self.d.feed(sample(0))

    def test_ww_context_does_not_exempt_relay_off_and_all_channels_count_once(self):
        start = sample(10)
        start.update(gas=True, dhw=True, dhw_valve=True)
        events = self.d.feed(start)
        next_sample = dict(start, t=start['t']+10, ion_current=54.9,
                           burn_starts=101, ww_starts=21, block=44.3)
        self.d.feed(next_sample)
        report = self.d.report()
        self.assertEqual(report['observed_starts'], 1)
        self.assertEqual(report['relay_off_starts'], 1)
        record = report['recent'][0]
        self.assertEqual(record['classification'], 'unexplained_relay_off')
        self.assertTrue(record['at_start']['dhw_valve'])
        self.assertEqual(set(record['signals']), {'gas','ion_current'})
        self.assertEqual(set(record['counter_deltas']), {'burn_starts','ww_starts'})
        self.assertEqual(record['last_context']['ion_current'], 54.9)
        self.assertFalse(record['physical_contact_verified'])
        self.assertEqual(events[0]['kind'], 'ignition_evidence')

    def test_delayed_counter_preserves_relay_at_start_not_arrival(self):
        on = sample(10); on.update(gas=True, relay=True)
        self.d.feed(on)
        off = dict(on, t=on['t']+10, relay=False)
        self.d.feed(off)
        self.d.feed(dict(off, t=off['t']+10, burn_starts=101))
        record = self.d.report()['recent'][0]
        self.assertTrue(record['relay_at_start'])
        self.assertEqual(self.d.report()['relay_off_starts'], 0)
        self.assertIn('burn_starts', record['counter_deltas'])

    def test_counter_arriving_first_is_correlated_without_double_count(self):
        s=sample(10); s['burn_starts']=101
        first=self.d.feed(s)
        self.assertEqual(self.d.report()['counter_only_increments'],1)
        s=sample(20); s.update(burn_starts=101,gas=True)
        self.d.feed(s)
        report=self.d.report()
        self.assertEqual(report['observed_starts'],1)
        self.assertEqual(report['counter_only_increments'],0)
        delta=report['recent'][0]['counter_deltas']['burn_starts']
        self.assertEqual(delta['observation_id'],first[0]['observation_id'])
        self.assertTrue(delta['arrived_before_edge'])

    def test_distinct_short_burns_are_not_merged(self):
        for t, gas in [(10,True),(20,False),(30,True)]:
            s=sample(t); s['gas']=gas; self.d.feed(s)
        self.assertEqual(self.d.report()['relay_off_starts'], 2)
        s=sample(40); s['burn_starts']=102; self.d.feed(s)
        self.assertTrue(all('burn_starts' in r['counter_deltas'] for r in self.d.report()['recent']))

    def test_restart_reconnect_and_gaps_do_not_manufacture_starts(self):
        s=sample(10); s.update(gas=True, ion_current=54)
        for first in (True, None):
            d=IgnitionEvidence(deepcopy(self.d.data))
            initial=sample(0); initial['gas']=first; initial['ion_current']=None
            d.feed(initial); d.feed(s)
            self.assertEqual(d.report()['observed_starts'], 0)
        for time, gap in [(100,False),(10,True),(-1,False)]:
            d=IgnitionEvidence(); d.feed(sample(0))
            s=sample(time); s.update(gas=True, gap=gap); d.feed(s)
            self.assertEqual(d.report()['observed_starts'], 0)

    def test_unknown_relay_and_transition_to_off_are_not_known_off_at_start(self):
        for old, new in [(None,None),(True,False),(None,False)]:
            d=IgnitionEvidence(); s=sample(0); s['relay']=old; d.feed(s)
            s=sample(10); s.update(gas=True, relay=new); d.feed(s)
            self.assertEqual(d.report()['relay_off_starts'], 0)
            self.assertIsNone(d.report()['recent'][0]['relay_at_start'])

    def test_residual_temperature_rise_and_ion_jitter_are_not_new_starts(self):
        for t,temp in [(10,50),(20,70),(30,92.9)]:
            s=sample(t); s['block']=temp; self.d.feed(s)
        self.assertEqual(self.d.report()['observed_starts'], 0)
        for t,ion in [(40,50),(50,0),(60,50)]:
            s=sample(t); s.update(gas=True, ion_current=ion); self.d.feed(s)
        self.assertEqual(self.d.report()['observed_starts'], 1)

    def test_counter_reset_reconnect_and_large_delta_do_not_infer_relay_off_start(self):
        for t,n in [(10,0),(20,None),(30,500),(40,503)]:
            s=sample(t); s['burn_starts']=n; self.d.feed(s)
        self.assertEqual(self.d.report()['observed_starts'], 0)
        self.assertEqual(self.d.report()['counter_only_increments'], 3)

    def test_ion_alone_and_counters_missing_still_record_diagnostic(self):
        s=sample(10); s.update(ion_current=54, burn_starts=None, heat_starts=None, ww_starts=None)
        self.d.feed(s)
        self.assertEqual(self.d.report()['relay_off_starts'], 1)
        self.assertEqual(self.d.report()['recent'][0]['signals'], ['ion_current'])

    def test_engine_checkpoint_preserves_totals_and_old_checkpoint_is_compatible(self):
        engine=Observer('test')
        engine.feed(sample(0))
        s=sample(10); s['gas']=True; engine.feed(s)
        saved=deepcopy(engine.data)
        restored=Observer('test',saved)
        restored.feed(s)
        self.assertEqual(restored.report()['ignition_evidence']['relay_off_starts'],1)
        saved.pop('ignition_evidence')
        self.assertEqual(Observer('test',saved).report()['ignition_evidence']['observed_starts'],0)

    def test_input_listeners_include_all_new_channels(self):
        for key in ('ion_current','burn_starts','heat_starts','ww_starts'):
            self.assertIn(INPUTS[key],CRITICAL)

    def test_counters_after_gap_cannot_corroborate_an_earlier_start(self):
        s=sample(10); s['gas']=True; self.d.feed(s)
        s=sample(100); self.d.feed(s)
        s=sample(110); s['burn_starts']=101; self.d.feed(s)
        self.assertEqual(self.d.report()['recent'][0]['counter_deltas'], {})
        self.assertEqual(self.d.report()['counter_only_increments'],1)

    def test_checkpoint_restart_cannot_attach_new_evidence_to_old_start(self):
        s=sample(10); s['gas']=True; self.d.feed(s)
        d=IgnitionEvidence(self.d.data)
        d.feed(sample(20))
        s=sample(30); s['gas']=True; d.feed(s)
        self.assertEqual(d.report()['observed_starts'],2)
        self.assertNotEqual(d.report()['recent'][0]['id'],d.report()['recent'][1]['id'])

    def test_database_retains_evidence_and_corroboration_as_append_only_events(self):
        s=sample(10); s['gas']=True
        events=self.d.feed(s)
        with tempfile.TemporaryDirectory() as tmp:
            db=AgentDatabase(Path(tmp)/'agent.sqlite3','test'); db.initialize()
            db.write_batch(s,[],events,[],[])
            with sqlite3.connect(db.path) as con:
                row=con.execute("SELECT payload FROM event_log WHERE event_type='heating.ignition_evidence.v1'").fetchone()
            record=json.loads(row[0])['ignition']
            self.assertEqual(record['classification'],'unexplained_relay_off')
            self.assertTrue(db.event_log_is_append_only())
