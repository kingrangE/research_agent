from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analysis_store import Store


class AnalysisStoreTest(unittest.TestCase):
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
                 'summary':'계약 체결','evidence':['공개 근거'],'certainty':'확정'}
        self.store.complete(job,reading,{'stock_relevance':'주식 판단 재료'})

    def test_restart_preserves_all_jobs_and_fair_dispatch(self):
        self.store.enqueue([{'article':self.article(i)} for i in range(40)],{'archive_items':40})
        other=Store(self.path,'test-model-v1')
        self.assertEqual(other.summary()['pending'],40)
        self.assertEqual(other.cursors()['archive_items'],40)
        jobs=[other.claim() for _ in range(4)]
        self.assertEqual([j['article_id'] for j in jobs],['0','39','38','1'])
        self.assertEqual(len({j['id'] for j in jobs}),4)

    def test_newest_slots_follow_publication_time_instead_of_import_order(self):
        articles=[self.article(1,published_at='2026-11-11T01:00:00Z'),
                  self.article(2,published_at='2026-11-11T03:00:00Z'),
                  self.article(3,published_at='2026-11-11T02:00:00Z')]
        self.store.enqueue([{'article':a} for a in articles])
        self.assertEqual([self.store.claim()['article_id'] for _ in range(3)],['1','2','3'])

    def test_future_body_revision_is_not_used_as_earlier_event_context(self):
        a=self.article(1,_version_at='2026-11-11T02:00:00Z')
        self.store.enqueue([{'article':a,'body':'수정 본문','body_version':'v2'}])
        self.finish(self.store.claim())
        self.assertEqual(self.store.anchors(self.article(2,_version_at='2026-11-11T01:00:00Z')),[])
        self.assertEqual(len(self.store.anchors(self.article(2,_version_at='2026-11-11T03:00:00Z'))),1)

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
        self.assertEqual(other.anchors(self.article(2))[0]['event_id'],'event-contract')
        self.assertEqual(other.anchors(self.article(1)),[])
        self.assertEqual(other.anchors(self.article(2,published_at='2026-11-10T23:00:00+00:00')),[])
        isolated=Store(self.path,'other-model')
        self.assertEqual(isolated.summary()['done'],0)
        self.assertEqual(isolated.anchors(self.article(2)),[])

    def test_reprint_keeps_the_first_publication_time_of_the_event(self):
        for i,date in [(1,'2026-11-09T00:00:00Z'),(2,'2026-11-11T00:00:00Z')]:
            self.store.enqueue([{'article':self.article(i,published_at=date)}])
            self.finish(self.store.claim())
        self.assertEqual(self.store.first_published(['event-contract','missing']),
                         {'event-contract':'2026-11-09T00:00:00Z'})


if __name__=='__main__':unittest.main()
