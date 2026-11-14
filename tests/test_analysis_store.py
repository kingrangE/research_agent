from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from analysis_store import Store, timing_summary


class AnalysisStoreTest(unittest.TestCase):
    def test_latency_percentiles_keep_missing_data_distinct_from_zero(self):
        self.assertEqual(timing_summary([None,-1,*range(1,21)]),{'samples':20,'p50_seconds':10,'p95_seconds':19})
        self.assertEqual(timing_summary([]),{'samples':0,'p50_seconds':None,'p95_seconds':None})
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'analysis.sqlite3'
        self.store=Store(self.path,'test-model-v1')

    def article(self, i, **extra):
        return {'id':str(i),'title':f'한빛에너지 계약 {i}','url':f'https://example.com/{i}',
                'published_at':'2026-11-11T00:00:00+00:00',**extra}

    def finish(self, job, event='event-contract'):
        reading={'article_id':job['article_id'],'event_id':event,'event_title':job['title'],
                 'entities':['한빛에너지'],'published_at':job['article'].get('published_at'),
                 'summary':'계약 체결','evidence':['공개 근거'],'certainty':'확정','read_policy_version':'read-v1'}
        self.store.complete(job,reading,{'stock_relevance':'주식 판단 재료'})

    def test_restart_preserves_all_jobs_and_fair_dispatch(self):
        self.store.enqueue([{'article':self.article(i)} for i in range(40)],{'archive_items':40})
        other=Store(self.path,'test-model-v1')
        self.assertEqual(other.summary()['pending'],40)
        self.assertEqual(other.cursors()['archive_items'],40)
        jobs=[other.claim() for _ in range(4)]
        self.assertEqual([j['article_id'] for j in jobs],['0','39','38','1'])
        self.assertEqual(len({j['id'] for j in jobs}),4)

    def test_live_latency_excludes_imports_reviews_and_missing_dates(self):
        with patch('analysis_store.time.time',return_value=10000):
            self.store.enqueue([{'article':self.article(i,published_at='1970-01-01T02:30:00Z')} for i in range(1,5)])
            jobs=[self.store.claim() for _ in range(4)]
            for job in jobs:self.finish(job)
        with self.store.db() as db:
            db.execute('UPDATE analysis_jobs SET published_epoch=9000,enqueued_at=9010,finished_at=9070 WHERE id=?',(jobs[0]['id'],))
            db.execute('UPDATE analysis_jobs SET published_epoch=100,enqueued_at=5000,finished_at=9500 WHERE id=?',(jobs[1]['id'],))
            db.execute('UPDATE analysis_jobs SET job_key=\'screen-review:test\',published_epoch=9000,enqueued_at=9020,finished_at=9300 WHERE id=?',(jobs[2]['id'],))
            db.execute('UPDATE analysis_jobs SET published_epoch=0 WHERE id=?',(jobs[3]['id'],))
        with patch('analysis_store.time.time',return_value=10000):
            result=self.store.summary()
        self.assertEqual(result['live_analysis']['samples'],1)
        self.assertEqual(result['live_analysis']['p95_seconds'],70)
        self.assertEqual(result['done'],4)
        self.assertIsNotNone(result['recent_p95_seconds'])

    def test_live_pending_keeps_late_jobs_visible_and_empty_latency_is_unknown(self):
        with patch('analysis_store.time.time',return_value=1000):
            self.store.enqueue([{'article':self.article(1,published_at='1970-01-01T00:15:00Z')}])
        with patch('analysis_store.time.time',return_value=10000):
            result=self.store.summary()['live_analysis']
        self.assertEqual(result['pending'],1)
        self.assertEqual(result['oldest_unfinished_seconds'],9100)
        self.assertEqual(result['samples'],0)
        self.assertIsNone(result['p95_seconds'])

    def test_policy_review_is_idempotent_preserves_history_and_fair_dispatch(self):
        a=self.article(1)
        self.store.enqueue([{'article':a,'body':'보관 본문','body_version':'v1'}])
        old=self.store.claim();self.finish(old)
        self.store.enqueue_reviews([a],'policy-new','read-v1')
        self.store.enqueue_reviews([a],'policy-new','read-v1')
        self.store.enqueue([{'article':self.article(i)} for i in range(2,8)])
        normal=[self.store.claim() for _ in range(2)]
        self.assertTrue(all(not j['job_key'].startswith('screen-review:') for j in normal))
        review=self.store.claim()
        self.assertTrue(review['job_key'].startswith('screen-review:'))
        self.assertEqual(review['body'],'보관 본문')
        self.assertEqual(review['body_version'],'v1')
        self.assertEqual(self.store.summary()['done'],1)
        self.store.complete(review,{'event_id':'event-contract','article_id':'1','summary':'계약 체결','read_policy_version':'read-v1'},
                            {'screen_policy_version':'policy-new','stock_relevance':'배경·상품 안내'})
        self.store.enqueue_reviews([a],'policy-new','read-v1')
        self.assertEqual(self.store.summary()['done'],2)
        self.assertEqual(len(self.store.history('event-contract')),2)
        self.assertEqual(self.store.readings([a])[1][0]['stock_relevance'],'배경·상품 안내')
        self.assertEqual(self.store.first_published(['event-contract'])['event-contract'],a['published_at'])

    def test_review_does_not_bypass_newer_body_or_cross_model_namespace(self):
        a=self.article(1,_version_at='2026-11-11T01:00:00Z')
        self.store.enqueue([{'article':a,'body':'old','body_version':'old'}]);self.finish(self.store.claim())
        self.store.enqueue([{'article':{**a,'_version_at':'2026-11-11T02:00:00Z'},'body':'new','body_version':'new'}])
        self.store.enqueue_reviews([a],'policy-new','read-v1')
        self.assertEqual(self.store.summary()['pending'],1)
        other=Store(self.path,'other-model')
        other.enqueue_reviews([a],'policy-new','read-v1')
        self.assertEqual(other.summary()['pending'],0)

    def test_failed_review_survives_restart_without_exposing_the_old_decision(self):
        a=self.article(1)
        self.store.enqueue([{'article':a}]);self.finish(self.store.claim())
        self.store.enqueue_reviews([a],'new','read-v1')
        job=self.store.claim();self.store.retry(job,'temporary failure')
        other=Store(self.path,'test-model-v1')
        other.enqueue_reviews([a],'new','read-v1')
        self.assertIsNone(other.claim())
        self.assertEqual(other.readings([a]),([],[]))
        self.assertEqual(other.summary()['done'],1)
        self.assertEqual(other.summary()['retrying'],1)

    def test_reading_only_policy_change_keeps_the_old_result_and_reviews_once(self):
        a=self.article(1,published_at='1970-01-01T00:15:00Z')
        old={'event_id':'event','article_id':'1','summary':'이전 요약','published_at':a['published_at'],'read_policy_version':'read-old'}
        with patch('analysis_store.time.time',return_value=1000):
            self.store.enqueue([{'article':a}]);self.store.complete(self.store.claim(),old,{'screen_policy_version':'screen-current'})
        with patch('analysis_store.time.time',return_value=1100):
            self.store.enqueue_reviews([a],'screen-current','read-new')
            self.store.enqueue_reviews([a],'screen-current','read-new')
            self.assertEqual(self.store.summary()['pending'],1)
            job=self.store.claim()
            self.store.complete(job,{**old,'summary':'새 요약','read_policy_version':'read-new'},
                                {'screen_policy_version':'screen-current','assessed_at':'1970-01-01T00:01:00Z'})
            self.store.enqueue_reviews([a],'screen-current','read-new')
        self.assertEqual(self.store.summary()['done'],2)
        self.assertEqual(self.store.summary()['pending'],0)
        self.assertEqual(self.store.readings([a])[0][0]['read_policy_version'],'read-new')
        history=self.store.history('event')
        self.assertEqual([h['summary'] for h in history],['이전 요약','새 요약'])
        self.assertEqual(history[-1]['reviewed_at'],'1970-01-01T00:18:20+00:00')
        with self.store.db() as db:
            db.execute('UPDATE analysis_jobs SET finished_at=NULL WHERE id=?',(job['id'],))
        self.assertIsNone(self.store.history('event')[-1]['reviewed_at'])

    def test_newest_slots_follow_publication_time_instead_of_import_order(self):
        articles=[self.article(1,published_at='2026-11-11T01:00:00Z'),
                  self.article(2,published_at='2026-11-11T03:00:00Z'),
                  self.article(3,published_at='2026-11-11T02:00:00Z')]
        self.store.enqueue([{'article':a} for a in articles])
        self.assertEqual([self.store.claim()['article_id'] for _ in range(3)],['1','2','3'])

    def test_future_and_unknown_dates_do_not_displace_current_jobs_or_bypass_retry(self):
        dates=['1970-01-01T00:00:10Z','1970-01-01T00:16:41Z',None,
               'invalid','1970-01-01T00:16:39Z','1970-01-01T00:16:40Z',
               '1970-01-01T00:16:39.500Z']
        with patch('analysis_store.time.time',return_value=1000):
            self.store.enqueue([{'article':self.article(i,published_at=date)} for i,date in enumerate(dates)])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET available_at=1100,status='error' WHERE article_id='6'")
            selected=[self.store.claim()['article_id'] for _ in range(6)]
            self.assertEqual(selected,['0','5','4','1','3','2'])
            self.assertIsNone(self.store.claim())
            self.assertEqual(self.store.summary()['retrying'],1)
        with patch('analysis_store.time.time',return_value=1100):
            self.assertEqual(self.store.claim()['article_id'],'6')

    def test_review_latest_selection_also_rejects_future_priority(self):
        with patch('analysis_store.time.time',return_value=1000):
            self.store.enqueue([{'article':self.article(i,published_at=date)} for i,date in enumerate(
                ['1970-01-01T00:16:40Z','1970-01-01T00:16:41Z',None])])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET job_key='screen-review:'||id")
            self.assertEqual(self.store.claim()['article_id'],'0')
            self.assertEqual(self.store.claim()['article_id'],'2')
            self.assertEqual(self.store.claim()['article_id'],'1')

    def test_future_body_revision_is_not_used_as_earlier_event_context(self):
        a=self.article(1,_version_at='2026-11-11T02:00:00Z')
        self.store.enqueue([{'article':a,'body':'수정 본문','body_version':'v2'}])
        self.finish(self.store.claim())
        self.assertEqual(self.store.anchors(self.article(2,_version_at='2026-11-11T01:00:00Z'),'read-v1'),[])
        self.assertEqual(len(self.store.anchors(self.article(2,_version_at='2026-11-11T03:00:00Z'),'read-v1')),1)

    def test_same_revision_is_idempotent_but_body_changes_leave_history(self):
        a=self.article(1)
        self.store.enqueue([{'article':a,'body':'v1','body_version':'v1'}]*2)
        first=self.store.claim();self.finish(first,'event-first')
        self.store.enqueue([{'article':a,'body':'v2','body_version':'v2'}])
        second=self.store.claim();self.finish(second,'event-second')
        self.assertEqual(self.store.summary()['done'],2)
        history=self.store.history('event-second')
        self.assertEqual([h['body_version'] for h in history],['v1','v2'])
        self.assertEqual([h['event_id'] for h in history],['event-first','event-second'])
        self.assertIsNone(self.store.claim())

    def test_retry_and_expired_lease_survive_restart_without_stale_completion(self):
        with patch('analysis_store.time.time',return_value=1000):
            self.store.enqueue([{'article':self.article(1)}])
            first=self.store.claim()
        with patch('analysis_store.time.time',return_value=1001):
            other=Store(self.path,'test-model-v1')
            self.assertIsNone(other.claim())
        with patch('analysis_store.time.time',return_value=1301):
            second=other.claim()
            self.assertEqual(second['attempts'],2)
            self.store.complete(first,{'event_id':'stale'},{})
            self.assertEqual(other.summary()['processing'],1)
            other.retry(second,'temporary failure')
            self.assertIsNone(other.claim())
        with patch('analysis_store.time.time',return_value=1902):
            self.assertEqual(other.claim()['attempts'],3)

    def test_body_ready_supersedes_unprocessed_metadata_without_deleting_record(self):
        a=self.article(1)
        self.store.enqueue([{'article':a}])
        self.store.enqueue([{'article':a,'body':'원문','body_version':'full-sha'}])
        self.store.enqueue([{'article':a}])
        self.assertEqual(self.store.summary()['pending'],1)
        self.assertEqual(self.store.claim()['body'],'원문')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_jobs').fetchone()[0],2)

    def test_late_completion_of_old_revision_cannot_replace_newer_article_facts(self):
        a=self.article(1)
        for version,seen in [('old','2026-11-11T01:00:00Z'),('new','2026-11-11T02:00:00Z')]:
            self.store.enqueue([{'article':{**a,'_version_at':seen},'body':version,'body_version':version}])
        old=self.store.claim();new=self.store.claim()
        self.finish(new,'new-event');self.finish(old,'old-event')
        readings,_=self.store.readings([a])
        self.assertEqual(readings[0]['event_id'],'new-event')
        self.store.enqueue([{'article':{**a,'_version_at':'2026-11-11T03:00:00Z'},'body':'latest','body_version':'latest'}])
        self.assertEqual(self.store.readings([a])[0],[])

    def test_candidates_find_persistent_related_events_and_exclude_future_and_own_revisions(self):
        self.store.enqueue([{'article':self.article(1)}]);self.finish(self.store.claim())
        other=Store(self.path,'test-model-v1')
        self.assertEqual(other.anchors(self.article(2),'read-v1')[0]['event_id'],'event-contract')
        self.assertEqual(other.anchors(self.article(1),'read-v1'),[])
        self.assertEqual(other.anchors(self.article(2,published_at='2026-11-10T23:00:00+00:00'),'read-v1'),[])
        isolated=Store(self.path,'other-model')
        self.assertEqual(isolated.summary()['done'],0)
        self.assertEqual(isolated.anchors(self.article(2),'read-v1'),[])

    def test_candidate_policy_filter_precedes_the_recent_analysis_limit(self):
        self.store.enqueue([{'article':self.article(1)}]);self.finish(self.store.claim())
        self.store.enqueue([{'article':self.article(i)} for i in range(2,503)])
        old={'event_id':'old','event_title':'한빛에너지 계약','entities':['한빛에너지'],
             'published_at':self.article(1)['published_at'],'summary':'이전 기준 요약','read_policy_version':'read-old'}
        with self.store.db() as db:
            db.execute("UPDATE analysis_jobs SET status='done',finished_at=9999999999,event_id='old',result=?,assessment='{}' WHERE article_id!='1'",(json.dumps(old),))
            db.execute("UPDATE analysis_jobs SET result=json_remove(result,'$.read_policy_version') WHERE article_id='2'")
        found=self.store.anchors(self.article(999),reading_policy='read-v1')
        self.assertEqual([r['event_id'] for r in found],['event-contract'])
        self.assertEqual(self.store.anchors(self.article(999),reading_policy='read-missing'),[])
        self.assertEqual(self.store.summary()['done'],502)

    def test_reprint_keeps_the_first_publication_time_of_the_event(self):
        for i,date in [(1,'2026-11-09T00:00:00Z'),(2,'2026-11-11T00:00:00Z')]:
            self.store.enqueue([{'article':self.article(i,published_at=date)}])
            self.finish(self.store.claim())
        self.assertEqual(self.store.first_published(['event-contract','missing']),
                         {'event-contract':'2026-11-09T00:00:00Z'})


if __name__=='__main__':unittest.main()
