from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive


class ArchiveTest(unittest.TestCase):
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



if __name__=='__main__':unittest.main()
