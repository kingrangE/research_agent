import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import intelligence as ai
from evaluate_models import evaluate, evaluate_equity, evaluate_ranking

BODY = '한빛에너지는 미국 고객사와 3000억원 규모의 전력변압기 공급 계약을 체결했다고 공시했다. 계약 기간은 2027년부터 2029년까지다.'
GATE = {'driver':'기업 실적·수주·경쟁·비용 변화','reason':'실적에 영향을 주는 계약 변화','watch_for':'공시와 실적 전망 확인','stock_relevance':'주식 판단 재료','screen_policy_version':ai.SCREEN_VERSION}
READING = {'summary':'전력변압기 계약 체결','event_title':'한빛에너지 공급 계약','event_type':'계약','entities':['한빛에너지'],
           'certainty':'확정','amount':'3000억원','timing':'2027~2029년','evidence':[BODY.split('. ')[0]+'.'],'match_event_id':''}
ANALYZED = {**READING,'read_policy_version':ai.READ_VERSION}
ARTICLE = {'id':'a','url':'https://www.hankyung.com/article/2026111100001','title':'한빛에너지 계약','published_at':'2026-11-11T00:00:00Z'}


def rank_row(event_id,reason='사업 변화 확인'):
    return {'event_id':event_id,'reason':reason,'stock_relevance':'주식 판단 재료','watch_for':'공시와 실적 전망을 확인'}


class IntelligenceTest(unittest.TestCase):
    def test_cluster_evaluation_uses_each_cases_anchors_and_skips_ranking(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.extract_reading.side_effect=[{'match_event_id':'same'},{'match_event_id':'wrong'}]
        cases=[{'id':'same-case','title':'재보도','body':'동일 사건의 재보도 본문입니다.','anchors':[{'event_id':'same'}],'expected_match':'same'},
               {'id':'different-case','body':'다른 행동을 설명하는 본문입니다.','anchors':[{'event_id':'wrong'}],'expected_match':''}]
        with patch('builtins.print'):
            report=evaluate(engine,{'readings':[],'clusters':cases},clusters_only=True)
        self.assertEqual(report['total'],2)
        self.assertEqual(report['all_checks_pass'],1)
        self.assertEqual(engine.extract_reading.call_args_list[0].args[1]['title'],'재보도')
        self.assertEqual(engine.extract_reading.call_args_list[0].args[1]['id'],'article-1')
        self.assertEqual(engine.extract_reading.call_args_list[1].args[1]['title'],'원문 기사')
        self.assertEqual(engine.extract_reading.call_args_list[1].args[2],cases[1]['anchors'])
        engine.rank.assert_not_called()

    def test_shared_rank_service_rejects_invalid_ids_before_calling_the_model(self):
        with patch.object(self.engine,'call') as call:
            self.assertEqual(self.engine.rank([],{}),[])
            self.assertRaises(ValueError,self.engine.rank,[{'event_id':'E1'},{'event_id':'E1'}],{})
            self.assertRaises(ValueError,self.engine.rank,[{'event_id':[]}],{})
        call.assert_not_called()

    def test_ranking_evaluator_matches_case_ids_even_when_the_model_changes_order(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.side_effect=[{'calls_today':0,'output_tokens':0},{'calls_today':1,'output_tokens':120}]
        engine.rank.return_value=[{**rank_row('E2'),'stock_relevance':'배경·상품 안내'},rank_row('E1')]
        data={'equity_screening':[{'id':'risk','summary':'확인된 차환 발행 실패입니다.','expected':'주식 판단 재료'},
                                  {'id':'award','summary':'매출 변화 없는 수상 소식입니다.','expected':'배경·상품 안내'}]}
        with patch('builtins.print'):
            report=evaluate_ranking(engine,data)
        self.assertTrue(report['valid'])
        self.assertEqual(report['passed'],2)
        self.assertEqual(report['call_delta'],1)
        self.assertEqual(report['output_tokens_delta'],120)
        self.assertEqual([r['id'] for r in report['checks']],['risk','award'])
        self.assertNotIn('summary',engine.rank.call_args.args[0][0])
        self.assertEqual(report['inputs'],engine.rank.call_args.args[0])
        engine.call.assert_not_called()

    def test_ranking_evaluator_does_not_score_incomplete_or_unknown_cases_as_success(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.return_value={}
        engine.rank.return_value=[rank_row('unknown')]
        with patch('builtins.print'):
            report=evaluate_ranking(engine,{'equity_screening':[{'id':'risk','summary':'확인된 차환 실패','expected':'주식 판단 재료'}]})
        self.assertFalse(report['valid'])
        self.assertEqual(report['passed'],0)
        self.assertIsNone(report['checks'][0]['actual'])

    def test_ranking_evaluator_rejects_invalid_expected_labels_without_model_calls(self):
        engine=MagicMock()
        self.assertRaises(ValueError,evaluate_ranking,engine,{'equity_screening':[{'id':'bad','summary':'평가용 본문입니다.','expected':'수혜 확정'}]})
        engine.rank.assert_not_called()

    def test_source_passages_cover_the_body_and_selected_ids_restore_exact_evidence(self):
        for length in (8,240,241,247,248,480,481,6000):
            original='가'*length
            split=ai.source_passages(original)
            self.assertEqual(''.join(p['text'] for p in split),original)
            self.assertTrue(all(8<=len(p['text'])<=300 for p in split))
        body=('매출과 계약 조건을 원문에서 확인합니다. '*30)+'끝'
        passages=ai.source_passages(body)
        self.assertEqual(''.join(p['text'] for p in passages),body)
        self.assertTrue(all(8<=len(p['text'])<=300 for p in passages))
        output={**READING,'evidence':[1,len(passages)]}
        with patch.object(self.engine,'call',return_value=output) as call:
            reading=self.engine.extract_reading(body,ARTICLE,[])
        self.assertEqual(reading['evidence'],[passages[0]['text'],passages[-1]['text']])
        self.assertEqual(output['evidence'],[1,len(passages)])
        self.assertNotIn('body',call.call_args.args[1])
        self.assertEqual(call.call_args.args[2]['properties']['evidence']['items']['enum'],list(range(1,len(passages)+1)))

    def test_source_selection_rejects_invented_duplicate_and_wrong_type_ids(self):
        for ids in ([0],[999],[True],['1'],[1,1],[]):
            with patch.object(self.engine,'call',return_value={**READING,'evidence':ids}):
                self.assertRaises(ValueError,self.engine.extract_reading,BODY,ARTICLE,[])

    def test_equity_evaluator_isolates_screening_and_continues_after_failure(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.screen.side_effect=[ValueError('bad quote'),{'stock_relevance':'주식 판단 재료'}]
        engine.usage.return_value={}
        cases=[{'id':str(i),'summary':'본문 근거입니다.','expected':'주식 판단 재료'} for i in range(2)]
        with patch('builtins.print'):
            result=evaluate_equity(engine,{'equity_screening':cases})
        self.assertEqual(result['passed'],1)
        self.assertEqual(result['checks'][0]['error'],'ValueError')
        engine.cycle.assert_not_called()

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
        self.assertTrue(ai.article_url('https://n.news.naver.com/article/001/0012345678'))
        self.assertFalse(ai.article_url('https://n.news.naver.com.evil.test/article/001/0012345678'))
        self.assertFalse(ai.article_url('https://n.news.naver.com/article/001/../secret'))
        portal=ai.ArticleParser();portal.feed('<div id="dic_area">실제 본문<script>skip</script></div><nav>메뉴</nav>')
        self.assertEqual(' '.join(portal.parts),'실제 본문')
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
        with patch.object(self.engine,'body',return_value=BODY),patch.object(self.engine,'call',return_value={**copy.deepcopy(READING),'evidence':[1]}) as call:
            first=self.engine.reading(ARTICLE,[])
            self.assertEqual(self.engine.reading(ARTICLE,[]),first)
            call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'body',return_value=BODY),patch.object(other,'call') as call:
            self.assertEqual(other.reading(ARTICLE,[]),first);call.assert_not_called()
        with patch.object(other,'body',return_value=BODY+' 정정 사항 추가.'),patch.object(other,'call',return_value={**copy.deepcopy(READING),'evidence':[1]}) as call:
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
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],'published_at':'2026-10-01T00:00:00Z'}
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
        usage=other.usage()
        self.assertEqual({k:usage[k] for k in ('calls_today','input_tokens','output_tokens')},{'calls_today':3,'input_tokens':80,'output_tokens':40})

    def test_model_request_timings_include_timeouts_and_survive_restart(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'done':True,'done_reason':'stop','message':{'content':'{}'}}).encode()
        with patch('intelligence.urlopen',return_value=response),patch('intelligence.time.monotonic',side_effect=[100,103.5]):
            self.engine.call('read',{},ai.READ_SCHEMA)
        with patch('intelligence.urlopen',side_effect=TimeoutError),patch('intelligence.time.monotonic',side_effect=[200,320]):
            self.assertRaises(TimeoutError,self.engine.call,'rank',{},ai.RANK_SCHEMA)
        other=ai.Engine(self.engine.path)
        timings={r['task']:r for r in other.usage()['timings']}
        self.assertEqual(timings['read']['p95_seconds'],3.5)
        self.assertEqual(timings['rank']['p95_seconds'],120)
        self.assertEqual(timings['rank']['failed'],1)
        self.assertEqual(other.usage()['calls_today'],2)

    def test_legacy_usage_migration_preserves_counts_without_fabricated_timings(self):
        with self.engine.db() as db:
            db.execute('DROP TABLE attempts')
            db.execute('CREATE TABLE attempts(id INTEGER PRIMARY KEY,day TEXT,task TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,status TEXT)')
            db.execute('INSERT INTO attempts VALUES(1,?,?,?,?,?,?)',(ai.now()[:10],'read',self.engine.model,40,20,'received'))
        other=ai.Engine(self.engine.path)
        self.assertEqual(other.usage()['calls_today'],1)
        self.assertEqual(other.usage()['input_tokens'],40)
        self.assertEqual(other.usage()['timings'],[])

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
        a={**ANALYZED,'event_id':'event-a','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        b={**a,'article_id':'b','source_url':'https://www.hankyung.com/article/b'}
        grouped=ai.group_events([a,b])
        self.assertEqual(len(grouped),1);self.assertEqual(len(grouped[0]['articles']),2)
        self.assertEqual(grouped[0]['articles'][1]['evidence'],READING['evidence'])

    def test_market_comparison_uses_same_trading_date_and_preserves_missing(self):
        samples={'SPY':{'change_percent':1,'traded_at':'2026-11-10T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'},
                 'XLE':{'change_percent':3,'traded_at':'2026-11-10T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'},
                 'XLK':{'change_percent':4,'traded_at':'2026-11-09T16:00:00-05:00','currency':'USD','source':'test','market_status':'CLOSE'}}
        for quote in samples.values():
            quote.update(delay_label='15분 지연',fetched_at='2026-11-11T00:00:00Z',session='미국 정규장')
        def parse(data,code):
            return samples[code]
        with patch.object(ai,'MARKETS',{'SPY':'市場','XLE':'에너지','XLK':'기술','BAD':'실패'}),patch('intelligence.stocks.fetch',return_value='{}'),patch('intelligence.stocks.parse_quote',side_effect=parse):
            result=ai.market_snapshot()
        self.assertEqual(result['missing'],['BAD'])
        self.assertEqual(result['observations'][1]['relative_to_spy_pp'],2)
        self.assertNotIn('relative_to_spy_pp',result['observations'][2])
        self.assertEqual(result['observations'][0]['delay_label'],'15분 지연')
        self.assertEqual(result['observations'][0]['fetched_at'],'2026-11-11T00:00:00Z')
        self.assertEqual(result['observations'][0]['session'],'미국 정규장')

    def test_real_estate_market_uses_verified_provider_identity(self):
        quote={'reutersCode':'XLRE.K','stockName':'State Street Real Estate Select Sector SPDR ETF',
               'closePrice':'44.36','fluctuationsRatio':'0.50','compareToPreviousPrice':{'code':'2'},
               'currencyType':{'code':'USD'},'localTradedAt':'2026-11-12T16:00:00-05:00',
               'marketStatus':'CLOSE','delayTimeName':'실시간'}
        real_estate={code:label for code,label in ai.MARKETS.items() if label=='미국 부동산'}
        with patch.object(ai,'MARKETS',real_estate),patch('intelligence.stocks.fetch',return_value=json.dumps(quote)) as fetch:
            result=ai.market_snapshot()
        self.assertEqual(result['missing'],[])
        self.assertEqual(result['observations'][0]['code'],'XLRE.K')
        self.assertEqual(result['observations'][0]['name'],'미국 부동산')
        fetch.assert_called_once_with('https://api.stock.naver.com/stock/XLRE.K/basic',200_000)

    def test_cycle_publishes_only_valid_ranking_and_reuses_it(self):
        reading={**copy.deepcopy(ANALYZED),'event_id':'event-a','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at'],'model':'test','analyzed_at':ai.now()}
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1','확정 공급 계약')]}) as call:
            first=self.engine.cycle([ARTICLE]);second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['status'],'ok');self.assertEqual(len(second['ranking']),1);call.assert_called_once()
        self.engine.rank_key='changed'
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'call',return_value={'ranking':[rank_row('invented','허구')]}):
            failed=self.engine.cycle([ARTICLE])
        self.assertFalse(failed['ranking_stale']);self.assertTrue(failed['ranking_partial']);self.assertEqual(failed['status'],'partial')
        self.assertEqual(failed['ranking'],first['ranking'])

    def test_finished_article_is_published_before_waiting_for_the_next_article(self):
        articles=[ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}]
        reading={**ANALYZED,'event_id':'event-a','article_id':ARTICLE['id'],'source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',side_effect=[reading,AssertionError('두 번째 기사 추론 대기')]) as read,patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1','확인한 계약')]}):
            result=self.engine.cycle(articles)
        self.assertEqual(read.call_count,1)
        self.assertEqual(result['queue']['pending'],1)
        self.assertEqual(result['ranking'][0]['event_id'],'event-a')

    def test_pending_work_continues_without_the_idle_thirty_second_wait(self):
        result={'coverage':{'candidates':1},'queue':{'pending':2}}
        with patch('intelligence.Engine',return_value=self.engine),patch('intelligence.archive.analysis_batch',return_value=([],{})),patch.object(self.engine,'cycle',return_value=result),patch('intelligence.time.sleep',side_effect=InterruptedError) as sleep:
            self.assertRaises(InterruptedError,ai.collector,lambda:[])
        sleep.assert_called_once_with(1)

    def test_queue_processes_more_than_thirty_articles_after_they_leave_feed_and_restart(self):
        articles=[{**ARTICLE,'id':str(i),'url':ARTICLE['url']+str(i)} for i in range(40)]
        def reading(article,anchors):
            return {**ANALYZED,'article_id':article['id'],'event_id':'e-'+article['id'],'source_url':article['url'],'published_at':article.get('published_at')}
        background={**GATE,'stock_relevance':'배경·상품 안내'}
        with patch.object(self.engine,'reading',side_effect=reading),patch.object(self.engine,'screen',return_value=background):
            self.engine.cycle(articles)
        self.assertEqual(self.engine.queue.summary()['done'],1)
        other=ai.Engine(self.engine.path)
        with patch.object(other,'reading',side_effect=reading),patch.object(other,'screen',return_value=background):
            for _ in range(39):
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
        readings=[{**copy.deepcopy(ANALYZED),'event_id':'event-'+a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at']} for a in articles]
        def provider(task,payload,output_schema):
            rule=output_schema['properties']['ranking']
            self.assertEqual(rule.get('minItems'),len(payload['events']))
            self.assertEqual(rule.get('maxItems'),len(payload['events']))
            ids=[e['event_id'] for e in payload['events']]
            self.assertTrue(all(len(i)<=3 for i in ids))
            self.assertEqual(set(rule['items']['properties']['event_id']['enum']),set(ids))
            return {'ranking':[rank_row(i) for i in reversed(ids)]}
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',side_effect=lambda a,anchors: next(r for r in readings if r['article_id']==a['id'])),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',side_effect=provider):
            for _ in articles:
                result=self.engine.cycle(articles)
        self.assertFalse(result['ranking_stale'])
        self.assertEqual([r['event_id'] for r in result['ranking']],['event-'+str(i) for i in reversed(range(9))])

    def test_ranking_uses_original_evidence_instead_of_generated_financial_claims(self):
        reading={**ANALYZED,'summary':'순이익 9999억원 증가 확정','event_title':'허구의 이익 증가',
                 'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}) as call:
            self.engine.cycle([ARTICLE])
        event=call.call_args.args[1]['events'][0]
        self.assertNotIn('summary',event)
        self.assertNotIn('event_title',event)
        self.assertNotIn('amount',event)
        self.assertEqual(event['evidence'],READING['evidence'])
        self.assertEqual(event['first_published_at'],ARTICLE['published_at'])

    def test_rank_cache_ignores_history_changes_but_tracks_sources_and_market(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine.queue,'history',side_effect=[[],[{'summary':'이력 추가'}]]),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}) as call:
            self.engine.cycle([ARTICLE]);self.engine.cycle([ARTICLE])
        self.assertEqual(call.call_count,1)
        changed={**reading,'evidence':['공급 계약 금액을 4000억원으로 정정했다.']}
        with patch.object(self.engine.queue,'readings',return_value=([changed],[dict(GATE,event_id='e')])),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}) as call:
            self.engine.cycle([ARTICLE])
            self.engine.last_market={**self.engine.last_market,'observations':[{'code':'SPY','change_percent':-2}]}
            self.engine.cycle([ARTICLE])
        self.assertEqual(call.call_count,2)

    def test_failed_reranking_cannot_reuse_reasons_from_different_evidence_or_market(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}):
            self.engine.cycle([ARTICLE])
        for changed in (True,False):
            fact={**reading,'evidence':['계약 금액을 4000억원으로 정정했다.']} if changed else reading
            if not changed:
                self.engine.last_market={**self.engine.last_market,'observations':[{'code':'SPY','change_percent':-3}]}
            with patch.object(self.engine.queue,'readings',return_value=([fact],[dict(GATE,event_id='e')])),patch.object(self.engine,'call',side_effect=ValueError('invalid response')):
                result=self.engine.cycle([ARTICLE])
            self.assertEqual(result['ranking'],[])
            self.assertTrue(result['ranking_stale'])
            self.assertTrue(result['ranking_partial'])

    def test_changed_facts_replace_previous_state_before_slow_ranking_finishes(self):
        old={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(ai,'STATE',{}),patch.object(self.engine,'reading',return_value=old),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1','이전 계약 근거')]}):
            initial=self.engine.cycle([ARTICLE])
            ai.STATE.update(initial)
            changed={**ARTICLE,'title':'한빛에너지 계약 변경'}
            new={**old,'article_title':changed['title'],'summary':'새 변경 사실','evidence':['계약의 공급 조건이 변경됐다고 회사가 밝혔다.']}
            observed=[]
            def rerank(*args):
                observed.append(ai.snapshot())
                raise TimeoutError('slow ranking')
            with patch.object(self.engine,'reading',return_value=new),patch.object(self.engine,'rank',side_effect=rerank) as rank:
                result=self.engine.cycle([changed])
            rank.assert_called_once()
            progress=observed[0]
            self.assertEqual(progress['events'][0]['summary'],'새 변경 사실')
            self.assertEqual(progress['ranking'],[])
            self.assertTrue(progress['ranking_stale'])
            self.assertTrue(progress['ranking_partial'])
            self.assertEqual(progress['ranked_at'],initial['ranked_at'])
            self.assertEqual(progress['status'],'processing')
            self.assertEqual(result['events'][0]['summary'],'새 변경 사실')
            self.assertEqual(result['ranking'],[])

    def test_final_source_review_can_remove_a_false_positive_without_filling_the_briefing(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        rejected={**rank_row('E1'),'stock_relevance':'배경·상품 안내','reason':'주식 실적 변화 없는 상품 조건 안내'}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rejected]}) as call:
            first=self.engine.cycle([ARTICLE]);second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['ranking'],[])
        self.assertEqual(first['assessments'][0]['stock_relevance'],'배경·상품 안내')
        self.assertFalse(first['ranking_stale'])
        self.assertFalse(first['ranking_partial'])
        self.assertEqual(second['ranking'],[])
        call.assert_called_once()

    def test_inflight_ranking_keeps_only_unchanged_compatible_previous_results(self):
        articles=[ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}]
        readings=[{**ANALYZED,'event_id':a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at']} for a in articles]
        gates=[dict(GATE,event_id=a['id']) for a in articles]
        with patch.object(ai,'STATE',{}),patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1'),rank_row('E2')]):
            initial=self.engine.cycle(articles)
            ai.STATE.update(initial)
            readings[0]={**readings[0],'evidence':['계약의 공급 조건이 변경됐다고 회사가 밝혔다.']}
            observed=[]
            def rerank(*args):
                observed.append(ai.snapshot())
                return [rank_row('E1'),rank_row('E2')]
            with patch.object(self.engine,'rank',side_effect=rerank):
                final=self.engine.cycle(articles)
            self.assertEqual([r['event_id'] for r in observed[0]['ranking']],['b'])
            self.assertTrue(observed[0]['ranking_partial'])
            self.assertFalse(observed[0]['ranking_stale'])
            self.assertEqual({r['event_id'] for r in final['ranking']},{'a','b'})

    def test_product_announcements_are_assessed_but_not_stock_recommendations(self):
        reading={**copy.deepcopy(ANALYZED),'event_id':'bond','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        row={'event_id':'E1','reason':'국채 상품 안내이며 상장사의 실적 변화 근거 없음','stock_relevance':'배경·상품 안내','watch_for':'발행 조건 변경보다 주식 실적 영향 근거가 필요'}
        with patch.object(self.engine,'screen',return_value={**GATE,'driver':'금융상품 조건·청약·판매 안내','stock_relevance':'배경·상품 안내'}),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call') as call:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['status'],'ok')
        self.assertFalse(result['ranking_stale'])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['assessments'][0]['stock_relevance'],'배경·상품 안내')
        call.assert_not_called()

    def test_previous_policy_is_not_ranked_while_review_fails(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':ai.READ_VERSION}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old-policy'})
        with patch.object(self.engine,'reading',return_value=old),patch.object(self.engine,'screen',side_effect=ValueError('temporary failure')),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}) as call,patch('intelligence.market_snapshot',return_value={'observations':[]}):
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['ranking'],[])
        call.assert_not_called()
        self.assertEqual(self.engine.queue.summary()['done'],1)

    def test_reading_policy_alone_triggers_review_and_blocks_old_facts(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':'old-reader'}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,GATE)
        with patch.object(self.engine,'reading',side_effect=ValueError('temporary failure')) as read,patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}) as call,patch('intelligence.market_snapshot',return_value={'observations':[]}):
            result=self.engine.cycle([ARTICLE])
        read.assert_called_once()
        call.assert_not_called()
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['events'],[])
        self.assertEqual(self.engine.queue.summary()['done'],1)

    def test_old_reading_cannot_supply_facts_or_override_a_current_gate_for_the_same_event(self):
        current={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at'],'summary':'현재 요약'}
        old={**current,'article_id':'b','summary':'이전 잘못된 요약','read_policy_version':'old-reader'}
        gates=[dict(GATE,event_id='e'),dict(GATE,event_id='e',stock_relevance='배경·상품 안내')]
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=([current,old],gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rank_row('E1')]}):
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['events'][0]['summary'],'현재 요약')
        self.assertEqual(len(result['events'][0]['articles']),1)
        self.assertEqual(result['ranking'][0]['event_id'],'e')

    def test_review_reuses_compatible_reading_and_preserves_both_assessments(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':ai.READ_VERSION}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old-policy'})
        with patch.object(self.engine,'reading') as read,patch.object(self.engine,'screen',return_value={**GATE,'stock_relevance':'배경·상품 안내'}) as screen,patch.object(self.engine,'call') as call:
            result=self.engine.cycle([ARTICLE])
        read.assert_not_called();call.assert_not_called()
        screen.assert_called_once()
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['assessments'][0]['stock_relevance'],'배경·상품 안내')
        self.assertEqual(self.engine.queue.summary()['done'],2)
        self.assertEqual(len(self.engine.queue.history('old')),2)
        with patch.object(self.engine,'screen') as screen:
            self.engine.cycle([ARTICLE])
        screen.assert_not_called()

    def test_review_rereads_when_the_saved_reading_policy_is_incompatible(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':'old-reading'}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old-policy'})
        with patch.object(self.engine,'reading',return_value={**old,'read_policy_version':ai.READ_VERSION}) as read,patch.object(self.engine,'screen',return_value={**GATE,'stock_relevance':'배경·상품 안내'}):
            self.engine.cycle([ARTICLE])
        read.assert_called_once()

    def test_policy_upgrade_leaves_historical_articles_out_of_the_review_sweep(self):
        a={**ARTICLE,'published_at':'2026-10-01T00:00:00Z'}
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':a['url'],'published_at':a['published_at']}
        self.engine.queue.enqueue([{'article':a}])
        self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old-policy'})
        with patch.object(self.engine,'screen') as screen,patch.object(self.engine,'call') as call:
            result=self.engine.cycle([a])
        screen.assert_not_called();call.assert_not_called()
        self.assertEqual(result['ranking'],[])
        self.assertEqual(self.engine.queue.summary()['pending'],0)
        self.assertEqual(self.engine.queue.summary()['done'],1)

    def test_stock_gate_requires_a_verbatim_economic_evidence_quote(self):
        base={'driver':ai.DRIVERS[0],'impact_evidence':0,'reason':'일반 투자심리 개선 가능','watch_for':'실적 확인'}
        with patch.object(self.engine,'call',return_value=base):
            result=self.engine.screen(READING)
        self.assertEqual(result['stock_relevance'],'연결 미확인')
        with patch.object(self.engine,'call',return_value={**base,'impact_evidence':'원문에 없는 계약 규모 100조원 발표'}):
            with self.assertRaisesRegex(ValueError,'원문 인용'):
                self.engine.screen({**READING,'summary':'다른 사건'})
        with patch.object(self.engine,'call',return_value={**base,'impact_evidence':1}):
            result=self.engine.screen({**READING,'summary':'확인한 계약'})
        self.assertEqual(result['stock_relevance'],'주식 판단 재료')
        self.assertEqual(result['impact_evidence'],READING['evidence'][0])

    def test_screen_selects_exact_passages_and_rejects_invalid_ids(self):
        quotes=['실제 공급 계약을 체결했고 조건을 공시했다. '*20,'고객 주문 취소로 공장 가동을 중단했다.']
        event={**READING,'evidence':quotes}
        output={'driver':ai.DRIVERS[0],'impact_evidence':len(ai.source_passages(quotes[0]))+1,'reason':'주문 취소로 공급 중단','watch_for':'정정 공시'}
        with patch.object(self.engine,'call',return_value=output) as call:
            result=self.engine.screen(event)
        self.assertEqual(result['impact_evidence'],quotes[1])
        payload=call.call_args.args[1]
        self.assertNotIn('event',payload)
        self.assertNotIn(READING['summary'],json.dumps(payload,ensure_ascii=False))
        self.assertEqual(''.join(p['text'] for p in payload['source_passages']),''.join(quotes))
        self.assertEqual(call.call_args.args[2]['properties']['impact_evidence']['enum'],list(range(output['impact_evidence']+1)))
        for value in (-1,999,True,'1',None):
            with patch.object(self.engine,'call',return_value={**output,'impact_evidence':value}):
                self.assertRaisesRegex(ValueError,'원문 인용',self.engine.screen,{**event,'summary':str(value)})

    def test_background_screen_can_abstain_without_inventing_a_followup(self):
        result={'driver':ai.DRIVERS[-1],'impact_evidence':0,'reason':'원문에 경제적 변화 근거 없음','watch_for':''}
        with patch.object(self.engine,'call',return_value=result):
            answer=self.engine.screen(READING)
        self.assertEqual(answer['stock_relevance'],'연결 미확인')
        self.assertEqual(answer['watch_for'],'')

    def test_screen_abstains_with_no_source_and_rejects_malformed_quotes(self):
        output={'driver':ai.DRIVERS[0],'impact_evidence':0,'reason':'원문 미확인','watch_for':''}
        with patch.object(self.engine,'call',return_value=output) as call:
            result=self.engine.screen({**READING,'evidence':[]})
        self.assertEqual(result['stock_relevance'],'연결 미확인')
        self.assertEqual(result['impact_evidence'],'')
        self.assertEqual(call.call_args.args[2]['properties']['impact_evidence']['enum'],[0])
        for quotes in (None,False,{},'문자열을 목록으로 사용', [42], ['짧음'], ['가'*501]):
            with patch.object(self.engine,'call') as call:
                self.assertRaises(ValueError,self.engine.screen,{**READING,'evidence':quotes})
                call.assert_not_called()

    def test_screen_policy_change_invalidates_cache_without_resetting_queue(self):
        output={'driver':ai.DRIVERS[-1],'impact_evidence':0,'reason':'경제적 변화 미확인','watch_for':''}
        with patch.object(ai,'SCREEN_VERSION','old'),patch.object(self.engine,'call',return_value=output):
            old=self.engine.screen(READING)
        self.engine.queue.enqueue([{'article':ARTICLE}])
        with patch.object(self.engine,'call',return_value=output) as call:
            fresh=self.engine.screen(READING)
        call.assert_called_once()
        self.assertNotEqual(old['screen_policy_version'],fresh['screen_policy_version'])
        self.assertEqual(self.engine.queue.summary()['pending'],1)

    def test_screening_is_per_event_cached_and_separate_from_ranking(self):
        output={'driver':'금융상품 조건·청약·판매 안내','impact_evidence':0,'reason':'국채 발행 조건 안내이며 증권사 이익 변화 미확인','watch_for':'상장사 실적 영향이 있는지 확인'}
        with patch.object(self.engine,'call',return_value=output) as call:
            first=self.engine.screen(READING)
            second=self.engine.screen(READING)
        self.assertEqual(first['stock_relevance'],'배경·상품 안내')
        self.assertEqual(first,second);call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'call') as call:
            self.assertEqual(other.screen(READING),first);call.assert_not_called()


if __name__=='__main__':unittest.main()
