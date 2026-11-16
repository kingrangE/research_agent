from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import json

import archive
import event_facts as f
import server


class EventFactsTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in (patch.object(f,'PATH',Path(temp.name)/'facts.sqlite3'),patch.object(archive,'PATH',Path(temp.name)/'news.sqlite3')):
            p.start();self.addCleanup(p.stop)

    def article(self,id='a',title='삼성SDS, 데이터센터 투자 계획'):
        return {'id':id,'url':'https://example.com/'+id,'title':title,'source_id':'test','source':'test',
                'published_at':'2026-11-16T00:00:00+00:00','kind':'news'}

    def save(self,article,body=None):
        archive.store([article])
        if body:archive.save_body(article['url'],text=body)
        f.ingest()

    def test_stage_types_and_exact_evidence(self):
        for text,kind,stage in [('삼성SDS 데이터센터 지분 투자 계획','equity_investment','planned'),
          ('삼성SDS 데이터센터 GPU 구매 계약 체결','compute_purchase','announced'),
          ('삼성SDS 데이터센터 증설 MOU 체결','facility_investment','mou'),
          ('삼성SDS 데이터센터 투자 취소','facility_investment','cancelled'),
          ('삼성SDS 데이터센터 계약 취소설 부인','facility_investment','denied')]:
            a=self.article(title=text);p=f.extract(a)
            self.assertEqual((p['event_type'],p['stage']),(kind,stage))
            for e in p['evidence']:self.assertEqual(e['quote'],a[e['section']][e['start']:e['end']])
        p=f.extract(self.article(title='삼성SDS 데이터센터 투자'),'삼성SDS는 데이터센터에 1.5조원을 투자한다고 발표했다.')
        self.assertEqual(p['amounts'][0]['raw'],'1.5조원')
        self.assertEqual(f.extract(self.article(title='OpenAI GPU 구매 계약 체결'))['event_type'],'compute_purchase')

    def test_identical_body_deduplicates_but_same_amount_does_not(self):
        body='삼성SDS는 구미 데이터센터에 6000억원을 투자할 계획이라고 발표했다. '+('공개 사업 계획에 관한 설명이다. '*8)
        self.save(self.article('a'),body)
        self.save(self.article('b'),body)
        self.assertEqual(len(f.snapshot()['events']),1)
        self.save(self.article('c','SK텔레콤 데이터센터 투자 계획'),body.replace('삼성SDS','SK텔레콤'))
        self.assertEqual(len(f.snapshot()['events']),2)
        f.ingest();self.assertEqual(len(f.snapshot()['events']),2)

    def test_review_merge_split_correction_survives_reingest(self):
        self.save(self.article('a'));self.save(self.article('b'))
        proposals=f.snapshot()['proposals'];keys=[p['source_key'] for p in proposals]
        base={'reviewer':'test reviewer','reviewer_kind':'human','reason':'동일 프로젝트 원문 대조',
              'evidence':[{'section':'title','quote':'데이터센터 투자 계획'}]}
        review={**base,'action':'merge','source_keys':keys}
        rid=f.apply_review(review);self.assertEqual(f.apply_review(review),rid)
        self.assertEqual(len(f.snapshot()['events']),1)
        f.apply_review({**base,'action':'split','source_keys':[keys[0]],'reason':'서로 다른 프로젝트로 확인'})
        self.assertEqual(len(f.snapshot()['events']),2)
        f.apply_review({**base,'action':'correct','source_keys':[keys[0]],'changes':{'stage':'planned'}})
        f.ingest();result=f.snapshot()
        self.assertEqual(result['reviews'],3)
        target=next(p for p in result['proposals'] if p['source_key']==keys[0])
        self.assertEqual(len(target['review_history']),3)
        self.assertEqual(target['review_status'],'reviewed')
        with patch.object(f,'RULE_VERSION','event-rules-test-v2'):
            f.ingest()
            changed=next(p for p in f.snapshot()['proposals'] if p['source_key']==keys[0])
            self.assertEqual(changed['review_status'],'reviewed')
            self.assertEqual(len(changed['review_history']),3)
        self.assertRaises(ValueError,f.apply_review,{**base,'action':'correct','source_keys':[keys[0]],'evidence':[{'section':'title','quote':'없는 근거 구절'}]})

    def test_unclassified_and_portal_time_preserved_in_api(self):
        self.save({**self.article(title='일반 금융 상품 안내'),'timestamp_basis':'portal_display'})
        p=f.snapshot()['proposals'][0]
        self.assertIsNone(p['axis']);self.assertIsNone(p['published_at'])
        self.assertTrue(p['portal_display_at']);self.assertTrue(p['first_seen_at'])
        handler=object.__new__(server.Handler);handler.respond=Mock()
        handler.path='/api/events?axis=bad';handler.do_GET()
        self.assertEqual(handler.respond.call_args.args[2],400)
        handler.path='/api/events';handler.do_GET()
        self.assertEqual(json.loads(handler.respond.call_args.args[0])['proposals'][0]['review_status'],'unclassified')

    def test_background_infrastructure_in_legal_market_or_personnel_news_is_not_primary(self):
        body='삼성SDS 데이터센터 투자 계획을 설명했다.'
        for title in ('복귀 노리는 젠슨 황, 백악관 대응팀 꾸렸다','인텔 주주들로부터 피소','젠슨 황 쇼크 지속…코스피 하락',
                      'AI 전력망 지금이 투자 적기','엔비디아 AI 자금줄 제동 땐 투자금 썰물'):
            self.assertIsNone(f.extract(self.article(title=title),body)['axis'])
        self.assertIsNone(f.extract(self.article(title='유진證 한국전력 AI 전력망 투자 확대 기대…목표가↓'),body)['axis'])
        conflicting=f.extract(self.article(title='삼성SDS 데이터센터 MOU 체결'),'삼성SDS 데이터센터는 가동을 시작했다.')
        self.assertEqual(conflicting['stage'],'unknown')
        self.assertTrue(conflicting['stage_conflict'])

    def test_axis_filter_precedes_window_and_latest_source_version_wins(self):
        self.save(self.article('first'))
        for i in range(5):self.save(self.article(str(i),'일반 금융 상품'))
        self.assertEqual(len(f.snapshot(axis='infrastructure',limit=1)['proposals']),1)
        self.save(self.article('first','일반 금융 상품으로 정정'))
        self.assertEqual(f.snapshot(axis='infrastructure',limit=1)['proposals'],[])
        self.assertGreaterEqual(len(next(p for p in f.snapshot()['proposals'] if p['article_id']=='first')['source_history']),2)
