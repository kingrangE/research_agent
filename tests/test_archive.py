from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive
import intelligence


class ArchiveTest(unittest.TestCase):
    def test_archive_paging_preserves_ties_and_background_articles_and_searches_all_pages(self):
        rows=[self.item(f'배경 안내 {i}',f'https://example.com/{i:02}',source='신문A',kind='news') for i in range(35)]
        archive.store(rows)
        first=archive.browse(limit=30)
        second=archive.browse(limit=30,before=first['next'])
        self.assertEqual(first['total'],35)
        self.assertEqual(len(first['articles']),30)
        self.assertEqual(len(second['articles']),5)
        self.assertEqual(len({a['url'] for a in first['articles']+second['articles']}),35)
        self.assertIsNone(second['next'])
        self.assertEqual(archive.browse(query='배경 안내 0')['total'],1)
        self.assertEqual(archive.browse(source='신문A',since='2026-11-11',until='2026-11-11')['total'],35)
        self.assertEqual(archive.browse(since='2026-11-12')['total'],0)
        archive.store([{**rows[0],'title':'계약 취소'}])
        self.assertEqual(archive.browse(query='계약 취소')['total'],1)
        self.assertEqual(archive.browse()['total'],35)

    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher=patch.object(archive,'PATH',Path(temp.name)/'news.sqlite3')
        patcher.start();self.addCleanup(patcher.stop)

    def item(self,title='개인투자용국채 청약',url='https://www.hankyung.com/article/1',**extra):
        return {'id':url.rsplit('/',1)[-1],'source_id':'finance','title':title,'url':url,'published_at':'2026-11-11T00:00:00Z','collected_at':'first',**extra}

    def test_all_topics_are_retained_and_poll_time_does_not_create_revisions(self):
        rows=[self.item(),self.item('기업 수상','https://www.hankyung.com/article/2'),self.item('대규모 수주','https://www.hankyung.com/article/3')]
        archive.store(rows)
        archive.store([{**a,'collected_at':'second'} for a in rows])
        state=archive.summary()
        self.assertEqual(state['articles'],3);self.assertEqual(state['revisions'],3);self.assertEqual(state['pending'],3)
        self.assertEqual({a['title'] for a in archive.restore()},{a['title'] for a in rows})

    def test_changed_rss_is_versioned_and_latest_feed_restores_after_restart(self):
        archive.store([self.item(),self.item('이전 피드','https://www.hankyung.com/article/2')])
        archive.store([self.item('국채 청약 조건 정정')])
        self.assertEqual(archive.summary()['articles'],2)
        self.assertEqual(archive.summary()['revisions'],3)
        self.assertEqual([a['title'] for a in archive.restore()],['국채 청약 조건 정정'])
        archive.store([self.item()])
        self.assertEqual(archive.restore()[0]['title'],'개인투자용국채 청약')

    def test_public_body_is_not_truncated_and_revisions_are_preserved(self):
        url=self.item()['url'];archive.store([self.item()])
        full='공개 본문입니다. '*2000
        archive.save_body(url,full)
        self.assertEqual(archive.get_body(url),full)
        archive.save_body(url,full+' 정정')
        archive.save_body(url,full)
        self.assertEqual(archive.get_body(url),full)
        with archive.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bodies').fetchone()[0],2)
        self.assertIsNone(archive.pending())
        self.assertEqual(archive.summary()['bodies'],1)

    def test_body_failure_keeps_article_and_prior_body_with_retry_status(self):
        item=self.item();archive.store([item]);archive.save_body(item['url'],'보관된 공개 본문')
        archive.save_body(item['url'],error='수집 실패')
        self.assertEqual(archive.summary()['articles'],1)
        self.assertEqual(archive.summary()['errors'],1)
        self.assertEqual(archive.get_body(item['url']),'보관된 공개 본문')
        self.assertIsNone(archive.pending())
        archive.store([self.item('정정 제목')])
        self.assertEqual(archive.pending(),item['url'])

    def test_analysis_replay_keeps_articles_outside_latest_feed_and_full_body_versions(self):
        first=self.item('첫 기사')
        archive.store([first,self.item('이전 피드','https://www.hankyung.com/article/2')])
        full='원문 '*2000
        archive.save_body(first['url'],full)
        archive.save_body(first['url'],full+' 뒤쪽 정정')
        archive.save_body(first['url'],full)
        archive.save_body(first['url'],full)
        archive.store([self.item('새 피드','https://www.hankyung.com/article/3')])
        records,cursors=archive.analysis_batch({},limit=1)
        self.assertEqual(len(records),2)
        self.assertEqual(len(records[1]['body']),6000)
        more,next_cursors=archive.analysis_batch(cursors,limit=100)
        bodies=[r for r in records+more if r.get('body_version')]
        self.assertEqual(len(bodies),3)
        self.assertNotEqual(bodies[0]['body_version'],bodies[1]['body_version'])
        self.assertEqual(bodies[0]['body'],bodies[1]['body'])
        self.assertNotEqual(bodies[0]['body_version'],bodies[2]['body_version'])
        self.assertIn('이전 피드',[r['article']['title'] for r in more])
        self.assertEqual(archive.analysis_batch({**cursors,**next_cursors})[0],[])

    def test_existing_archive_migration_preserves_last_observed_reverted_body(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(archive.PATH)) as db, db:
            db.execute('CREATE TABLE bodies (url TEXT,fingerprint TEXT,text TEXT,fetched_at TEXT,last_seen TEXT,PRIMARY KEY(url,fingerprint))')
            db.executemany('INSERT INTO bodies VALUES(?,?,?,?,?)',[
                ('https://example.com/1','a','처음','2026-11-11T01:00:00Z','2026-11-11T03:00:00Z'),
                ('https://example.com/1','b','변경','2026-11-11T02:00:00Z','2026-11-11T02:00:00Z')])
        with archive.db() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT fingerprint FROM body_versions ORDER BY id')],['a','b','a'])
        self.assertEqual(archive.get_body('https://example.com/1'),'처음')

    def test_model_reuses_archive_but_only_limits_its_own_input(self):
        item=self.item();full='본문 원본 '*2000
        archive.store([item]);archive.save_body(item['url'],full)
        engine=intelligence.Engine(archive.PATH.parent/'analysis.sqlite3')
        with patch('intelligence.read_article') as fetch:
            self.assertEqual(engine.body(item['url']),full[:6000]);fetch.assert_not_called()
        self.assertEqual(archive.get_body(item['url']),full)


if __name__=='__main__':unittest.main()
