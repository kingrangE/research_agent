import copy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import data_worker as w
from tests.test_comparable_events import fact
from tests.test_event_reactions import inputs


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=patch.object(w,'PATH',Path(self.directory.name)/'jobs.sqlite3');self.path.start()
        self.addCleanup(self.path.stop);self.addCleanup(self.directory.cleanup)
        self.universe=patch.object(w,'universe',return_value={('KR','005930'):{'code':'005930'}});self.universe.start();self.addCleanup(self.universe.stop)

    def jobs(self):
        with w.db() as db:return db.execute('SELECT * FROM work ORDER BY created,id').fetchall()

    def test_enqueue_restart_and_revision_preserve_old_work(self):
        f=fact();self.assertEqual(w.enqueue([f]),2);self.assertEqual(w.enqueue([f]),0)
        old=self.jobs()[0];w.update(old['id'],'running','interrupted',delay=0)
        self.assertEqual(len(self.jobs()),2)
        f['review_id']='review';w.enqueue([f])
        self.assertEqual(sum(j['state']=='superseded' for j in self.jobs()),2)
        self.assertEqual(sum(j['state']=='pending' for j in self.jobs()),2)
        self.assertEqual(len(w.status()['recent_states']),4)

    def test_complete_cache_price_correction_and_immutable_run_references(self):
        f=fact();w.enqueue([f]);job=self.jobs()[0]
        data=inputs();result={'run_id':'first','windows':[{'raw_return':.01,'status':'observed_with_quality_limits'}],'status':'calculated'}
        with patch.object(w.event_facts,'snapshot',return_value={'proposals':[f]}),patch.object(w.reactions,'load_inputs',return_value=data),patch.object(w.reactions,'run',return_value=result) as run:
            w.observe(job);run.assert_called_once()
            cached=next(j for j in self.jobs() if j['id']==job['id']);self.assertEqual(cached['state'],'complete')
            w.observe(cached);self.assertEqual(run.call_count,1)
            changed=copy.deepcopy(data);changed['stock_prices'][0]['revision']=999
            with patch.object(w.reactions,'load_inputs',return_value=changed):
                run.return_value={**result,'run_id':'corrected'};w.observe(cached)
            self.assertEqual(run.call_count,2)
        with w.db() as db:
            outputs=[json.loads(r[0])['result_id'] for r in db.execute('SELECT payload FROM work_history')]
        self.assertIn('first',outputs);self.assertIn('corrected',outputs)

    def test_killed_running_work_retries_and_unknown_is_unsupported(self):
        f=fact();w.enqueue([f]);job=self.jobs()[0];w.update(job['id'],'running','interrupted',delay=0)
        job=next(j for j in self.jobs() if j['id']==job['id'])
        with patch.object(w.event_facts,'snapshot',return_value={'proposals':[f]}),patch.object(w.reactions,'load_inputs',return_value=inputs()),patch.object(w.reactions,'run',return_value={'run_id':'unknown','windows':[],'status':'event_time_unknown'}) as run:
            w.observe(job);run.assert_called_once()
        self.assertEqual(next(j for j in self.jobs() if j['id']==job['id'])['state'],'unsupported')

    def test_waiting_and_changed_event_are_not_success_zero(self):
        f=fact();w.enqueue([f]);job=self.jobs()[0]
        with patch.object(w.event_facts,'snapshot',return_value={'proposals':[f]}),patch.object(w.reactions,'load_inputs',return_value=inputs()),patch.object(w.reactions,'run',return_value={'run_id':'wait','windows':[{'raw_return':None,'status':'missing_price'}],'status':'calculated'}):w.observe(job)
        self.assertEqual(next(j for j in self.jobs() if j['id']==job['id'])['state'],'waiting')
        revised={**f,'source_key':'new'}
        with patch.object(w.event_facts,'snapshot',return_value={'proposals':[revised]}),patch.object(w.reactions,'run') as run:w.observe(job);run.assert_not_called()
        self.assertEqual(next(j for j in self.jobs() if j['id']==job['id'])['state'],'superseded')

    def test_provider_failure_is_visible_and_does_not_raise_into_news_collection(self):
        with patch.object(w.h,'collect',return_value={'status':'error','error':'HTTP 403'}) as collect:
            result=w.collect_one(object());collect.assert_called_once()
        self.assertEqual(result['status'],'error');self.assertEqual(w.status()['series'][0]['error'],'HTTP 403')

    def test_no_issuer_is_explicitly_unsupported(self):
        f=fact('infrastructure');w.enqueue([f])
        self.assertEqual([j['state'] for j in self.jobs()],['unsupported','unsupported'])

    def test_offline_recovery_continues_after_job_failure_and_lock_excludes_overlap(self):
        w.enqueue([fact()])
        with patch.object(w,'lease',return_value=nullcontext(False)):
            self.assertEqual(w.cycle(network=False),{'state':'busy'})
        with patch.object(w,'lease',side_effect=lambda *a:nullcontext(True)),patch.object(w.event_facts,'ingest',return_value={'processed':1}),patch.object(w,'discover',return_value=0),patch.object(w,'collect_one') as collect,patch.object(w,'refresh_themes'),patch.object(w,'observe',side_effect=ValueError('private')):
            result=w.cycle(network=False)
        collect.assert_not_called();self.assertEqual(result['ai_calls'],0)
        self.assertEqual(w.status()['counts']['error'],2)
        self.assertEqual(result['state'],'ok')
        self.assertNotIn('private',json.dumps(w.status()))


if __name__=='__main__':unittest.main()
