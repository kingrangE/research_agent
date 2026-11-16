from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from analysis_store import Store, timing_summary, CURRENT_EVENT_SECONDS, epoch


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

    def test_priority_window_distinguishes_ready_waiting_and_processing_without_hiding_other_work(self):
        from datetime import datetime, timezone
        t=200000
        with patch('analysis_store.time.time',return_value=t):
            dates=[t,t-CURRENT_EVENT_SECONDS,t-CURRENT_EVENT_SECONDS-1,None,t+1,t-1,t]
            self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(date,timezone.utc).isoformat() if date else None)} for i,date in enumerate(dates)])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET status='error',available_at=? WHERE article_id IN ('1','3')",(t+100,))
                db.execute("UPDATE analysis_jobs SET status='processing',available_at=? WHERE article_id='5'",(t+300,))
                db.execute("UPDATE analysis_jobs SET status='superseded' WHERE article_id='6'")
            summary=self.store.summary()
            self.assertEqual(summary['oldest_wait_seconds'],0)
            window=summary['priority_window']
        self.assertEqual(window,{'window_seconds':CURRENT_EVENT_SECONDS,'fresh_window_seconds':3600,'fresh_unfinished':2,'fresh_ready':1,'current_unfinished':3,'current_ready':1,'other_unfinished':3,'oldest_current_age_seconds':CURRENT_EVENT_SECONDS})
        with patch('analysis_store.time.time',return_value=t+1):
            window=self.store.summary()['priority_window']
            self.assertEqual((window['current_unfinished'],window['current_ready'],window['other_unfinished'],window['oldest_current_age_seconds']),(3,2,3,2))
        with patch('analysis_store.time.time',return_value=t+301):
            self.assertEqual(self.store.summary()['priority_window']['current_ready'],3)
        self.assertEqual(Store(self.path,'other-model').summary()['priority_window'],
                         {'window_seconds':CURRENT_EVENT_SECONDS,'fresh_window_seconds':3600,'fresh_unfinished':0,'fresh_ready':0,'current_unfinished':0,'current_ready':0,'other_unfinished':0,'oldest_current_age_seconds':None})

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

    def test_explicit_compatible_review_keeps_exact_prior_result_without_marking_it_new(self):
        a=self.article(1)
        reading={'event_id':'event','article_id':'1','summary':'계약 체결','read_policy_version':'read-v1','analyzed_at':'original'}
        gate={'screen_policy_version':'old','stock_relevance':'주식 판단 재료','assessed_at':'original'}
        self.store.enqueue([{'article':a,'body':'보관 본문','body_version':'body-v1'}])
        self.store.complete(self.store.claim(),reading,gate)
        expected=self.store.readings([a])
        self.store.enqueue_reviews([a],'new','read-v1')
        self.assertEqual(self.store.readings([a]),([],[]))
        compatibility={('read-v1','old')}
        self.assertEqual(self.store.readings([a],review_compatibility=compatibility),expected)
        self.assertEqual(self.store.readings([a],review_compatibility={('read-v2','old')}),([],[]))
        job=self.store.claim();self.store.retry(job,'temporary failure')
        other=Store(self.path,'test-model-v1')
        self.assertEqual(other.readings([a],review_compatibility=compatibility),expected)
        self.assertEqual(Store(self.path,'other-model').readings([a],review_compatibility=compatibility),([],[]))
        self.assertEqual(other.summary()['done'],1)
        newer={**a,'_version_at':'2026-11-11T01:00:00Z'}
        self.store.enqueue([{'article':newer,'body':'새 본문','body_version':'new-body'}])
        self.assertEqual(self.store.readings([newer],review_compatibility=compatibility),([],[]))
        self.store.enqueue([{'article':{**a,'title':'새 계약 조건'},'body':'새 본문','body_version':'body-v2'}])
        self.assertEqual(self.store.readings([{**a,'title':'새 계약 조건'}],review_compatibility=compatibility),([],[]))

    def test_reading_only_fallback_keeps_facts_without_upgrading_the_old_assessment(self):
        a=self.article(1)
        reading={'event_id':'e','article_id':'1','read_policy_version':'read-v1','analyzed_at':'original'}
        gate={'screen_policy_version':'old','stock_relevance':'주식 판단 재료','assessed_at':'original'}
        self.store.enqueue([{'article':a,'body':'원문 근거','body_version':'body-v1'}])
        self.store.complete(self.store.claim(),reading,gate)
        expected=self.store.readings([a])
        self.store.enqueue_reviews([a],'new','read-v1')
        self.assertEqual(self.store.readings([a]),([],[]))
        self.assertEqual(self.store.readings([a],reading_policy='read-v1'),expected)
        self.assertEqual(self.store.readings([a],reading_policy='read-v2'),([],[]))
        job=self.store.claim();self.store.retry(job,'retry')
        self.assertEqual(self.store.readings([a],reading_policy='read-v1'),expected)
        self.assertEqual(Store(self.path,'other-model').readings([a],reading_policy='read-v1'),([],[]))
        newer={**a,'_version_at':'2026-11-11T01:00:00Z'}
        self.store.enqueue([{'article':newer,'body':'변경된 본문','body_version':'body-v2'}])
        self.assertEqual(self.store.readings([newer],reading_policy='read-v1'),([],[]))

    def test_compatible_review_never_skips_a_newer_completed_rejection(self):
        a=self.article(1);reading={'event_id':'event','article_id':'1','read_policy_version':'read-v1'}
        self.store.enqueue([{'article':a}]);self.store.complete(self.store.claim(),reading,{'screen_policy_version':'old','stock_relevance':'주식 판단 재료'})
        self.store.enqueue_reviews([a],'newer','read-v1')
        self.store.complete(self.store.claim(),reading,{'screen_policy_version':'newer','stock_relevance':'배경·상품 안내'})
        self.store.enqueue_reviews([a],'future','read-v1')
        self.assertEqual(self.store.readings([a],review_compatibility={('read-v1','old')}),([],[]))
        kept=self.store.readings([a],review_compatibility={('read-v1','newer')})
        self.assertEqual(kept[1][0]['stock_relevance'],'배경·상품 안내')
        with self.store.db() as db:
            db.execute("UPDATE analysis_jobs SET result=? WHERE status='pending'",(json.dumps({**reading,'summary':'다른 원문 사실'}),))
        self.assertEqual(self.store.readings([a],review_compatibility={('read-v1','newer')}),([],[]))

    def test_compatible_priority_backfill_only_reviews_retained_readings(self):
        articles=[self.article(i) for i in range(3)]
        for a,relevance in zip(articles,('주식 판단 재료','배경·상품 안내','연결 미확인')):
            self.store.enqueue([{'article':a}])
            self.store.complete(self.store.claim(),{'event_id':a['id'],'article_id':a['id'],'read_policy_version':'read-v1'},
                                {'screen_policy_version':'old','stock_relevance':relevance})
        compatibility={('read-v1','old')}
        self.store.enqueue_reviews(articles,'new','read-v1',review_compatibility=compatibility)
        self.store.enqueue_reviews(articles,'new','read-v1',review_compatibility=compatibility)
        self.assertEqual(self.store.summary()['pending'],1)
        self.assertEqual(len(self.store.readings(articles,review_compatibility=compatibility)[0]),3)
        # New reading criteria still require the previous exclusions to be reviewed.
        self.store.enqueue_reviews(articles[1:],'new','read-v2',review_compatibility={('read-v2','old')})
        self.assertEqual(self.store.summary()['pending'],2)
        # Without an explicit compatibility declaration, normal review behavior remains.
        self.store.enqueue_reviews(articles[2:],'future','read-v1')
        self.assertEqual(self.store.summary()['pending'],3)

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

    def test_fresh_work_preempts_older_current_work_even_on_the_oldest_turn(self):
        from datetime import datetime, timezone
        as_of=200000
        with patch('analysis_store.time.time',return_value=as_of):
            dates=[as_of-4*3600,as_of-600,as_of-60,as_of-CURRENT_EVENT_SECONDS-1]
            self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(t,timezone.utc).isoformat())} for i,t in enumerate(dates)])
            selected=[]
            for _ in dates:
                job=self.store.claim();selected.append(job['article_id']);self.finish(job)
            self.assertEqual(selected,['1','2','0','3'])
            self.assertEqual(self.store.summary()['done'],4)

    def test_fresh_priority_does_not_bypass_retry_or_erase_older_jobs(self):
        from datetime import datetime, timezone
        as_of=200000
        with patch('analysis_store.time.time',return_value=as_of):
            for i,age in ((0,4000),(1,3600),(2,10)):
                self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(as_of-age,timezone.utc).isoformat())}])
            with self.store.db() as db:db.execute("UPDATE analysis_jobs SET status='error',available_at=? WHERE article_id='2'",(as_of+60,))
            self.assertEqual(self.store.claim()['article_id'],'1')
            self.assertEqual(self.store.claim()['article_id'],'0')
            self.assertIsNone(self.store.claim())
            with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM analysis_jobs').fetchone()[0],3)
        with patch('analysis_store.time.time',return_value=as_of+60):
            self.assertEqual(self.store.claim()['article_id'],'2')

    def test_older_current_review_does_not_take_the_fresh_work_reservation(self):
        from datetime import datetime, timezone
        as_of=200000
        with patch('analysis_store.time.time',return_value=as_of):
            for i,age in ((0,4000),(1,10)):
                self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(as_of-age,timezone.utc).isoformat())}])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET job_key='screen-review:'||id WHERE article_id='0'")
                db.execute("INSERT OR REPLACE INTO analysis_cursors VALUES('test-model-v1','dispatch',3)")
            self.assertEqual(self.store.claim()['article_id'],'1')
            self.assertEqual(self.store.claim()['article_id'],'0')

    def test_current_age_work_precedes_backfill_but_keeps_all_records_and_retry_deadlines(self):
        from datetime import datetime, timezone
        as_of=200000
        stamp=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        dates=[as_of-CURRENT_EVENT_SECONDS-1,as_of-CURRENT_EVENT_SECONDS,as_of-1,as_of,as_of+1]
        with patch('analysis_store.time.time',return_value=as_of):
            self.store.enqueue([{'article':self.article(i,published_at=stamp(t))} for i,t in enumerate(dates)])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET status='error',available_at=? WHERE article_id='3'",(as_of+100,))
            self.assertEqual([self.store.claim()['article_id'] for _ in range(4)],['2','1','0','4'])
            self.assertIsNone(self.store.claim())
            with self.store.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM analysis_jobs').fetchone()[0],5)
        with patch('analysis_store.time.time',return_value=as_of+100):
            self.assertEqual(Store(self.path,'test-model-v1').claim()['article_id'],'3')

    def test_oldest_slot_is_fair_within_current_work_and_falls_back_when_it_expires(self):
        from datetime import datetime, timezone
        as_of=200000
        with patch('analysis_store.time.time',return_value=as_of):
            dates=[as_of-CURRENT_EVENT_SECONDS-1,as_of-10,as_of-1,as_of-5]
            self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(t,timezone.utc).isoformat())} for i,t in enumerate(dates)])
            self.assertEqual([self.store.claim()['article_id'] for _ in range(3)],['1','2','3'])
        with patch('analysis_store.time.time',return_value=as_of+CURRENT_EVENT_SECONDS+1):
            self.assertEqual(self.store.claim()['article_id'],'0')

    def test_expired_review_cannot_preempt_current_work_and_current_review_precedes_backfill(self):
        from datetime import datetime, timezone
        as_of=200000
        with patch('analysis_store.time.time',return_value=as_of):
            dates=[as_of-CURRENT_EVENT_SECONDS-1,as_of-10,as_of-5]
            self.store.enqueue([{'article':self.article(i,published_at=datetime.fromtimestamp(t,timezone.utc).isoformat())} for i,t in enumerate(dates)])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET job_key='screen-review:'||id WHERE article_id IN ('0','2')")
                db.execute("INSERT OR REPLACE INTO analysis_cursors VALUES('test-model-v1','dispatch',3)")
            self.assertEqual([self.store.claim()['article_id'] for _ in range(3)],['2','1','0'])

    def test_old_review_slot_does_not_jump_a_ready_current_regular_job(self):
        with patch('analysis_store.time.time',return_value=200000):
            self.store.enqueue([{'article':self.article(0,published_at='1970-01-02T03:46:40Z')},
                                {'article':self.article(1,published_at='1970-01-03T07:33:19Z')}])
            with self.store.db() as db:
                db.execute("UPDATE analysis_jobs SET job_key='screen-review:'||id WHERE article_id='0'")
                db.execute("INSERT OR REPLACE INTO analysis_cursors VALUES('test-model-v1','dispatch',3)")
            self.assertEqual(self.store.claim()['article_id'],'1')
            self.assertEqual(self.store.claim()['article_id'],'0')

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

    def test_rejected_model_time_survives_history_but_cannot_reenter_anchors(self):
        self.store.enqueue([{'article':self.article(1)}])
        job=self.store.claim()
        self.store.complete(job,{'article_id':'1','event_id':'event','event_title':'한빛에너지 계약',
            'entities':['한빛에너지'],'summary':'계약을 체결했다.','evidence':['계약을 체결했다.'],
            'published_at':job['article']['published_at'],'timing':'미확인','timing_original':'2026-11-11',
            'read_policy_version':'read-v1'},{'stock_relevance':'주식 판단 재료'})
        saved=self.store.history('event')[0]
        self.assertEqual((saved['timing'],saved['timing_original']),('미확인','2026-11-11'))
        anchor=self.store.anchors(self.article(2),'read-v1')[0]
        self.assertEqual(anchor['timing'],'미확인')
        self.assertNotIn('timing_original',anchor)

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

    def test_title_wait_rechecks_without_attempts_and_resumes_only_with_matching_fresh_source(self):
        a=self.article(1,_version_at='2026-11-11T00:00:00Z')
        t=epoch(a['_version_at'])+10
        with patch('analysis_store.time.time',return_value=t):
            self.store.enqueue([{'article':a}]);job=self.store.claim()
            self.store.retry(job,'제목 불일치',source_waiting=True)
            self.assertEqual(self.store.summary()['source_waiting'],1)
        matching={'status':'ok','title':a['title'],'text':'공개된 정상 본문입니다.','observed_at':'2026-11-11T00:00:05Z'}
        with patch('analysis_store.time.time',return_value=t+3599),patch('archive.body_snapshot') as snapshot:
            self.store.recheck_sources();snapshot.assert_not_called()
        for i,source in enumerate((None,{**matching,'title':'다른 제목'},{**matching,'status':'error'},
                                   {**matching,'text':'속보'},{**matching,'observed_at':'2026-11-10T23:59:00Z'},
                                   {**matching,'observed_at':'2099-01-01T00:00:00Z'},matching),1):
            with patch('analysis_store.time.time',return_value=t+3600*i),patch('archive.body_snapshot',return_value=source):
                self.store.recheck_sources()
                if i<7:self.assertIsNone(self.store.claim())
                else:self.assertEqual(self.store.claim()['id'],job['id'])
        with self.store.db() as db:
            row=db.execute('SELECT attempts,article,last_error FROM analysis_jobs WHERE id=?',(job['id'],)).fetchone()
            self.assertEqual(row['attempts'],2)
            self.assertEqual(json.loads(row['article']),a)
            self.assertEqual(row['last_error'],'제목 불일치')

    def test_source_recheck_storage_failure_does_not_claim_or_discard_waiting_input(self):
        import sqlite3
        self.store.enqueue([{'article':self.article(1)}]);job=self.store.claim()
        self.store.retry(job,'제목 불일치',source_waiting=True)
        with patch('analysis_store.time.time',return_value=2000000000),patch('archive.body_snapshot',side_effect=sqlite3.OperationalError('busy')):
            self.store.recheck_sources()
            self.assertIsNone(self.store.claim())
            self.assertEqual(self.store.summary()['source_waiting'],1)

    def test_pinned_input_does_not_enter_title_wait_and_new_version_supersedes_wait(self):
        a=self.article(1)
        self.store.enqueue([{'article':a}]);job=self.store.claim();self.store.retry(job,'제목 불일치',source_waiting=True)
        self.store.enqueue([{'article':a,'body':'보관한 정상 본문입니다.','body_version':'full'}])
        self.assertEqual(self.store.summary()['source_waiting'],0)
        newer=self.store.claim();self.store.retry(newer,'일시 오류',source_waiting=True)
        self.assertEqual(self.store.summary()['retrying'],1)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM analysis_jobs WHERE id=?',(job['id'],)).fetchone()[0],'superseded')

    def test_fixed_short_body_waits_for_new_input_without_retrying_or_losing_versions(self):
        a=self.article(1)
        self.store.enqueue([{'article':a,'body':'속보','body_version':'short'}])
        job=self.store.claim();self.store.retry(job,'인용 가능한 본문 부족')
        with patch('analysis_store.time.time',return_value=2000000000):
            self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.summary()['insufficient_body'],1)
        self.assertEqual(self.store.summary()['done'],0)
        with self.store.db() as db:
            db.execute("UPDATE analysis_jobs SET status='error' WHERE id=?",(job['id'],))
        reopened=Store(self.path,'test-model-v1')
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.summary()['insufficient_body'],1)
        self.assertEqual(self.store.readings([a])[0],[])
        self.store.enqueue([{'article':a,'body':'속보','body_version':'short'}])
        self.assertIsNone(self.store.claim())
        self.store.enqueue([{'article':a,'body':'보강된 기사 본문입니다.','body_version':'full'}])
        newer=self.store.claim();self.assertEqual(newer['body_version'],'full');self.finish(newer)
        self.assertEqual(len(self.store.readings([a])[0]),1)
        with self.store.db() as db:
            old=db.execute('SELECT body,status,attempts FROM analysis_jobs WHERE id=?',(job['id'],)).fetchone()
            self.assertEqual(tuple(old),('속보','insufficient_body',1))
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_jobs').fetchone()[0],2)

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

    def test_candidate_retrieval_keeps_original_headlines_and_exact_matches_first(self):
        title='이런 폭락장 뒤엔 항상 반전 있었다'
        a=self.article(1,title=title)
        self.store.enqueue([{'article':a}]);job=self.store.claim();self.finish(job)
        with self.store.db() as db:
            r=json.loads(db.execute('SELECT result FROM analysis_jobs WHERE id=?',(job['id'],)).fetchone()[0])
            r.update(event_title='코스피 지수 급락 후 반등 가능성',entities=['코스피'])
            db.execute('UPDATE analysis_jobs SET result=? WHERE id=?',(json.dumps(r),job['id']))
        self.store.enqueue([{'article':self.article(2,title='다른 주제의 소개')}]);other=self.store.claim();self.finish(other,event='unrelated')
        with self.store.db() as db:
            r=json.loads(db.execute('SELECT result FROM analysis_jobs WHERE id=?',(other['id'],)).fetchone()[0])
            r.update(event_title=title,entities=['코스피'])
            db.execute('UPDATE analysis_jobs SET result=? WHERE id=?',(json.dumps(r),other['id']))
        found=self.store.anchors(self.article(3,title=title),'read-v1',limit=1)
        self.assertEqual([r['event_id'] for r in found],['event-contract'])
        self.assertEqual(found[0]['article_title'],title)
        self.assertEqual(found[0]['event_title'],'코스피 지수 급락 후 반등 가능성')
        self.assertEqual(self.store.anchors(self.article(3,title=title,published_at='2026-11-10'),'read-v1'),[])

    def test_candidate_uses_best_matching_reprint_without_future_or_own_revisions(self):
        title='동일한 공급 계약 원문 제목'
        for i,t in ((1,title),(2,'다른 표현의 후속 보도')):
            self.store.enqueue([{'article':self.article(i,title=t)}]);self.finish(self.store.claim())
        rows=self.store.anchors(self.article(3,title=title),'read-v1')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['article_title'],title)
        self.assertEqual(self.store.anchors(self.article(1,title=title),'read-v1'),[])

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
