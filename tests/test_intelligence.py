import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import intelligence as ai
from evaluate_models import evaluate_equity

BODY = '한빛에너지는 미국 고객사와 3000억원 규모의 전력변압기 공급 계약을 체결했다고 공시했다. 계약 기간은 2027년부터 2029년까지다.'
GATE = {'driver':'기업 실적·수주·경쟁·비용 변화','reason':'실적에 영향을 주는 계약 변화','watch_for':'공시와 실적 전망 확인','stock_relevance':'주식 판단 재료'}
READING = {'summary':'전력변압기 계약 체결','event_title':'한빛에너지 공급 계약','event_type':'계약','entities':['한빛에너지'],
           'certainty':'확정','amount':'3000억원','timing':'2027~2029년','evidence':[BODY.split('. ')[0]+'.'],'match_event_id':''}
ARTICLE = {'id':'a','url':'https://www.hankyung.com/article/2026111100001','title':'한빛에너지 계약','published_at':'2026-11-11T00:00:00Z'}


def rank_row(event_id,reason='사업 변화 확인'):
    return {'event_id':event_id,'reason':reason,'stock_relevance':'주식 판단 재료','watch_for':'공시와 실적 전망을 확인'}


class IntelligenceTest(unittest.TestCase):



    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher=patch.dict(os.environ,{'LLM_ENABLED':'1','LLM_PROVIDER':'ollama','LLM_MODEL':'test-7b','LLM_DAILY_CALL_LIMIT':'2','OLLAMA_URL':'http://127.0.0.1:11434'})
        patcher.start();self.addCleanup(patcher.stop)
        clock=patch('intelligence.now',return_value='2026-11-11T12:00:00+00:00');clock.start();self.addCleanup(clock.stop)
        self.engine=ai.Engine(Path(self.temp.name)/'test.sqlite3')

    def test_parser_only_reads_public_article_and_ignores_scripts(self):
        parser=ai.ArticleParser()
        parser.feed('<nav>메뉴</nav><div id="articletxt"><p>본문 하나</p><script>악성 지시</script><p>둘</p></div><footer>푸터</footer>')
        self.assertEqual(' '.join(parser.parts),'본문 하나 둘')
        self.assertTrue(ai.article_url(ARTICLE['url']))
        for url in ['http://www.hankyung.com/article/a','https://www.hankyung.com.evil.test/article/a','https://127.0.0.1/article/a','https://user@www.hankyung.com/article/a']:
            self.assertFalse(ai.article_url(url))
        with self.assertRaises(ValueError):
            ai.ArticleRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1/private')

    def test_evidence_must_exist_and_cluster_id_must_be_supplied(self):
        ai.validate_reading(READING,BODY,set())
        bad=copy.deepcopy(READING);bad['evidence']=['허구의 공시와 계약 문장입니다.']
        self.assertRaises(ValueError,ai.validate_reading,bad,BODY,set())
        bad=copy.deepcopy(READING);bad['match_event_id']='fake'
        self.assertRaises(ValueError,ai.validate_reading,bad,BODY,set())
        bad=copy.deepcopy(READING);bad['certainty']='상승 확정'
        self.assertRaises(ValueError,ai.validate_reading,bad,BODY,set())

    def test_rank_rejects_omissions_duplicates_and_unknown_events(self):
        rows=[rank_row('a','공시 확인'),rank_row('b','전망 확인')]
        self.assertEqual(ai.validate_ranking({'ranking':rows},{'a','b'}),rows)
        for bad in [rows[:1],[rows[0],rows[0]],[rows[0],rank_row('fake','허구')]]:
            self.assertRaises(ValueError,ai.validate_ranking,{'ranking':bad},{'a','b'})

    def test_reading_cache_survives_restart_and_invalidates_on_body_change(self):
        with patch.object(self.engine,'body',return_value=BODY),patch.object(self.engine,'call',return_value=copy.deepcopy(READING)) as call:
            first=self.engine.reading(ARTICLE,[])
            self.assertEqual(self.engine.reading(ARTICLE,[]),first)
            call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'body',return_value=BODY),patch.object(other,'call') as call:
            self.assertEqual(other.reading(ARTICLE,[]),first);call.assert_not_called()
        with patch.object(other,'body',return_value=BODY+' 정정 사항 추가.'),patch.object(other,'call',return_value=copy.deepcopy(READING)) as call:
            other.reading(ARTICLE,[]);call.assert_called_once()

    def test_body_mentions_are_proven_by_body_and_old_body_is_not_reused_for_new_headline(self):
        body='한빛에너지는 공급 계약을 체결했다. 엔비디아는 본문에만 언급됐다.'
        mentions=ai.entity_mentions(body,['엔비디아','가짜기업'])
        self.assertEqual([m['name'] for m in mentions],['엔비디아'])
        self.assertIn(mentions[0]['evidence'],body)
        stale={'text':BODY,'fingerprint':'old','observed_at':'2026-11-11T00:00:00Z','status':'pending','title':ARTICLE['title']}
        with patch('intelligence.archive.body_snapshot',return_value=stale),patch.object(self.engine,'body') as read,patch.object(self.engine,'call') as call:
            self.assertIsNone(self.engine.reading(ARTICLE,[]))
            read.assert_not_called();call.assert_not_called()
        stale.update(status='ok',title='이전 계약 체결')
        with patch('intelligence.archive.body_snapshot',return_value=stale),patch.object(self.engine,'call') as call:
            self.assertIsNone(self.engine.reading(ARTICLE,[]));call.assert_not_called()

    def test_cancellation_and_certainty_updates_cannot_merge_into_old_contract(self):
        anchors=[{'event_id':'old','certainty':'확정','event_title':'공급 계약 체결','event_type':'계약','summary':'계약 체결'}]
        cancel={**READING,'match_event_id':'old','event_title':'공급 계약 취소','event_type':'계약 취소'}
        self.assertEqual(ai.separate_event_update(cancel,anchors)['match_event_id'],'')
        self.assertEqual(ai.separate_event_update({**READING,'match_event_id':'old','certainty':'부인'},anchors)['match_event_id'],'')
        self.assertEqual(ai.separate_event_update({**READING,'match_event_id':'old'},anchors)['match_event_id'],'old')

    def test_old_undated_and_future_events_are_context_only(self):
        as_of=ai.analysis_store.epoch('2026-11-11T12:00:00Z')
        for date,state in [('2026-11-11T11:00:00Z','current'),('2026-11-10T10:00:00Z','current'),
                           ('2026-11-10T09:59:00Z','old'),(None,'unknown'),('2026-11-11T12:01:00Z','future')]:
            self.assertEqual(ai.event_recency(date,as_of),state)
        old={**READING,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],'published_at':'2026-10-01T00:00:00Z'}
        with patch.object(self.engine,'reading',return_value=old),patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'call') as call,patch('intelligence.market_snapshot') as market:
            result=self.engine.cycle([{**ARTICLE,'published_at':old['published_at']}])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['events'][0]['recency_status'],'old')
        self.assertEqual(result['assessments'][0]['stock_relevance'],'주식 판단 재료')
        market.assert_not_called();call.assert_not_called()

    def test_failed_read_has_cooldown_without_fabricated_result(self):
        with patch.object(self.engine,'body',return_value=BODY),patch.object(self.engine,'call',return_value={}) as call:
            self.assertRaises(ValueError,self.engine.reading,ARTICLE,[])
            self.assertIsNone(self.engine.reading(ARTICLE,[]));call.assert_called_once()

    def test_local_requests_ignore_daily_cap_and_keep_usage_after_restart(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'done':True,'done_reason':'stop','message':{'content':json.dumps(READING)},'prompt_eval_count':40,'eval_count':20}).encode()
        with patch('intelligence.urlopen',return_value=response) as request:
            self.assertEqual(self.engine.call('read',{'body':BODY},ai.READ_SCHEMA),READING)
            req=request.call_args.args[0];payload=json.loads(req.data)
            self.assertEqual(req.full_url,'http://127.0.0.1:11434/api/chat')
            self.assertNotIn('Authorization',req.headers)
            self.assertEqual(payload['format'],ai.READ_SCHEMA)
            self.assertFalse(payload['stream'])
        with patch('intelligence.urlopen',side_effect=TimeoutError):
            self.assertRaises(TimeoutError,self.engine.call,'read',{},ai.READ_SCHEMA)
        other=ai.Engine(self.engine.path)
        self.assertIsNone(other.daily_limit)
        with patch('intelligence.urlopen',return_value=response):
            self.assertEqual(other.call('read',{},ai.READ_SCHEMA),READING)
        self.assertEqual(other.usage(),{'calls_today':3,'input_tokens':80,'output_tokens':40})

    def test_cloud_daily_cap_still_counts_failures_after_restart(self):
        with patch.dict(os.environ, {'LLM_PROVIDER':'gemini','GEMINI_API_KEY':'test-only'}):
            engine=ai.Engine(self.engine.path)
            with patch('intelligence.urlopen',side_effect=TimeoutError):
                for _ in range(2):
                    self.assertRaises(TimeoutError,engine.call,'read',{},ai.READ_SCHEMA)
            other=ai.Engine(engine.path)
            self.assertEqual(other.daily_limit,2)
            with patch('intelligence.urlopen') as request:
                self.assertRaisesRegex(ValueError,'일일 LLM 요청 한도',other.call,'read',{},ai.READ_SCHEMA)
                request.assert_not_called()
            self.assertEqual(other.usage()['calls_today'],2)

    def test_local_cycle_continues_past_validation_errors_without_daily_cap(self):
        self.assertIsNone(self.engine.daily_limit)
        with patch.object(self.engine,'reading',side_effect=[ValueError('invalid'),None]) as reading,patch('intelligence.market_snapshot') as market:
            result=self.engine.cycle([ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}])
        self.assertEqual(reading.call_count,2)
        self.assertEqual(result['status'],'partial')
        self.assertIsNone(result['daily_call_limit'])
        market.assert_not_called()

    def test_disabled_model_does_not_fetch_bodies_market_or_call_api(self):
        self.engine.enabled=False
        with patch.object(self.engine,'reading') as reading,patch('intelligence.market_snapshot') as market:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['status'],'disabled');reading.assert_not_called();market.assert_not_called()

    def test_event_groups_preserve_each_article_evidence(self):
        a={**READING,'event_id':'event-a','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        b={**a,'article_id':'b','source_url':'https://www.hankyung.com/article/b'}
        grouped=ai.group_events([a,b])
        self.assertEqual(len(grouped),1);self.assertEqual(len(grouped[0]['articles']),2)
        self.assertEqual(grouped[0]['articles'][1]['evidence'],READING['evidence'])

    def test_market_comparison_uses_same_trading_date_and_preserves_missing(self):
        samples={'SPY':{'change_percent':1,'traded_at':'2026-11-10T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'},
                 'XLE':{'change_percent':3,'traded_at':'2026-11-10T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'},
                 'XLK':{'change_percent':4,'traded_at':'2026-11-09T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'}}
        def parse(data,code):
            return samples[code]
        with patch.object(ai,'MARKETS',{'SPY':'市場','XLE':'에너지','XLK':'기술','BAD':'실패'}),patch('intelligence.stocks.fetch',return_value='{}'),patch('intelligence.stocks.parse_quote',side_effect=parse):
            result=ai.market_snapshot()
        self.assertEqual(result['missing'],['BAD'])
        self.assertEqual(result['observations'][1]['relative_to_spy_pp'],2)
        self.assertNotIn('relative_to_spy_pp',result['observations'][2])

    def test_cycle_publishes_only_valid_ranking_and_reuses_it(self):
        reading={**copy.deepcopy(READING),'event_id':'event-a','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at'],'model':'test','analyzed_at':ai.now()}
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1','확정 공급 계약')]}) as call:
            first=self.engine.cycle([ARTICLE]);second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['status'],'ok');self.assertEqual(len(second['ranking']),1);call.assert_called_once()
        self.engine.rank_key='changed'
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'call',return_value={'ranking':[rank_row('invented','허구')]}):
            failed=self.engine.cycle([ARTICLE])
        self.assertFalse(failed['ranking_stale']);self.assertTrue(failed['ranking_partial']);self.assertEqual(failed['status'],'partial')
        self.assertEqual(failed['ranking'],first['ranking'])



    def test_queue_processes_more_than_thirty_articles_after_they_leave_feed_and_restart(self):
        articles=[{**ARTICLE,'id':str(i),'url':ARTICLE['url']+str(i)} for i in range(40)]
        def reading(article,anchors):
            return {**READING,'article_id':article['id'],'event_id':'e-'+article['id'],'source_url':article['url'],'published_at':article.get('published_at')}
        background={**GATE,'stock_relevance':'배경·상품 안내'}
        with patch.object(self.engine,'reading',side_effect=reading),patch.object(self.engine,'screen',return_value=background):
            self.engine.cycle(articles)
        self.assertEqual(self.engine.queue.summary()['done'],6)
        other=ai.Engine(self.engine.path)
        with patch.object(other,'reading',side_effect=reading),patch.object(other,'screen',return_value=background):
            for _ in range(6):
                other.cycle([])
        self.assertEqual(other.queue.summary()['done'],40)
        self.assertEqual(other.queue.summary()['pending'],0)

    def test_archive_sync_error_does_not_stop_existing_analysis_queue(self):
        with patch('intelligence.Engine',return_value=self.engine),patch('intelligence.archive.analysis_batch',side_effect=OSError),patch.object(self.engine,'cycle',return_value={'coverage':{'candidates':0}}) as cycle,patch('intelligence.time.sleep',side_effect=StopIteration),patch.object(ai,'STATE',{}):
            with self.assertRaises(StopIteration):
                ai.collector(lambda:[])
            cycle.assert_called_once_with([])
            self.assertIn('보관소 대기열 동기화 실패',ai.STATE['queue_sync_error'])

    def test_snapshot_marks_expired_ranking_without_model_call(self):
        with patch.object(ai,'STATE',{'ranked_at':'2000-01-01T00:00:00+00:00','ranking_stale':False}):
            self.assertTrue(ai.snapshot()['ranking_stale'])

    def test_ranking_request_requires_every_candidate_and_restores_original_ids(self):
        articles=[{**ARTICLE,'id':str(i),'url':ARTICLE['url']+str(i)} for i in range(9)]
        readings=[{**copy.deepcopy(READING),'event_id':'event-'+a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at']} for a in articles]
        def provider(task,payload,output_schema):
            rule=output_schema['properties']['ranking']
            self.assertEqual(rule.get('minItems'),len(payload['events']))
            self.assertEqual(rule.get('maxItems'),len(payload['events']))
            ids=[e['event_id'] for e in payload['events']]
            self.assertTrue(all(len(i)<=3 for i in ids))
            self.assertEqual(set(rule['items']['properties']['event_id']['enum']),set(ids))
            return {'ranking':[rank_row(i) for i in reversed(ids)]}
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',side_effect=lambda a,anchors: next(r for r in readings if r['article_id']==a['id'])),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',side_effect=provider):
            self.engine.cycle(articles)
            result=self.engine.cycle(articles)
        self.assertFalse(result['ranking_stale'])
        self.assertEqual([r['event_id'] for r in result['ranking']],['event-'+str(i) for i in reversed(range(9))])

    def test_product_announcements_are_assessed_but_not_stock_recommendations(self):
        reading={**copy.deepcopy(READING),'event_id':'bond','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        row={'event_id':'E1','reason':'국채 상품 안내이며 상장사의 실적 변화 근거 없음','stock_relevance':'배경·상품 안내','watch_for':'발행 조건 변경보다 주식 실적 영향 근거가 필요'}
        with patch.object(self.engine,'screen',return_value={**GATE,'driver':'금융상품 조건·청약·판매 안내','stock_relevance':'배경·상품 안내'}),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call') as call:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['status'],'ok')
        self.assertFalse(result['ranking_stale'])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['assessments'][0]['stock_relevance'],'배경·상품 안내')
        call.assert_not_called()



    def test_screening_is_per_event_cached_and_separate_from_ranking(self):
        output={'driver':'금융상품 조건·청약·판매 안내','reason':'국채 발행 조건 안내이며 증권사 이익 변화 미확인','watch_for':'상장사 실적 영향이 있는지 확인'}
        with patch.object(self.engine,'call',return_value=output) as call:
            first=self.engine.screen(READING)
            second=self.engine.screen(READING)
        self.assertEqual(first['stock_relevance'],'배경·상품 안내')
        self.assertEqual(first,second);call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'call') as call:
            self.assertEqual(other.screen(READING),first);call.assert_not_called()


if __name__=='__main__':unittest.main()
