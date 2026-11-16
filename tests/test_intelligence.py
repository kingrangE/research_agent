import copy
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import intelligence as ai
from evaluate_models import evaluate, evaluate_equity, evaluate_ranking, evaluate_window_ranking, evaluate_pairwise, ranking_cases

BODY = '한빛에너지는 미국 고객사와 3000억원 규모의 전력변압기 공급 계약을 체결했다고 공시했다. 계약 기간은 2027년부터 2029년까지다.'
GATE = {'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':'기업 실적·수주·경쟁·비용 변화','reason':'실적에 영향을 주는 계약 변화','watch_for':'공시와 실적 전망 확인','stock_relevance':'주식 판단 재료','screen_policy_version':ai.SCREEN_VERSION}
READING = {'summary':'전력변압기 계약 체결','event_title':'한빛에너지 공급 계약','event_type':'계약','entities':['한빛에너지'],
           'certainty':'확정','amount':'3000억원','timing':'2027~2029년','evidence':[BODY.split('. ')[0]+'.'],'match_event_id':''}
ANALYZED = {**READING,'read_policy_version':ai.READ_VERSION}
ARTICLE = {'id':'a','url':'https://www.hankyung.com/article/2026111100001','title':'한빛에너지 계약','published_at':'2026-11-11T00:00:00Z'}


def rank_row(event_id,reason='사업 변화 확인'):
    return {'event_id':event_id,'reason':reason,'stock_relevance':'주식 판단 재료','watch_for':'공시와 실적 전망을 확인'}


def order_row(event_id,reason='사업 변화 확인'):
    return event_id


class IntelligenceTest(unittest.TestCase):
    def test_startup_snapshot_waits_for_settings_instead_of_claiming_disconnection(self):
        result=subprocess.run([sys.executable,'-c',
            'import intelligence,json; print(json.dumps(intelligence.snapshot()))'],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True)
        snapshot=json.loads(result.stdout)
        self.assertEqual(snapshot['status'],'starting')
        self.assertFalse(snapshot['ranking'])
        self.assertIsNone(snapshot['updated_at'])

    def test_separate_legal_counterparties_cannot_merge_via_the_same_stock(self):
        catalogue={'NVDA.O':{'code':'NVDA.O','name':'NVIDIA','legal_name':'NVIDIA Corporation','country':'US'},
                   'GOOGL.O':{'code':'GOOGL.O','name':'Alphabet Class A','legal_name':'Alphabet Inc.','country':'US'}}
        matcher,names=ai.stocks.compile_names(catalogue)
        old_body='NVIDIA Corporation은 Google LLC와 공급 계약을 체결했다.'
        body='NVIDIA Corporation은 Alphabet Inc.와 별도의 공급 계약을 체결했다.'
        anchor={**READING,'event_id':'old','event_title':'NVIDIA Corporation Google LLC 공급 계약',
                'entities':['NVIDIA Corporation','Google LLC'],'summary':old_body,'evidence':[old_body]}
        raw={**READING,'summary':body,'event_title':'NVIDIA Corporation Alphabet Inc. 공급 계약',
             'entities':['NVIDIA Corporation','Alphabet Inc.'],'evidence':[1],'match_event_id':'old'}
        with patch.object(ai.stocks,'CATALOGUE',catalogue),patch.object(ai.stocks,'NAME_MATCHER',matcher),patch.object(ai.stocks,'NAME_CODES',names),patch.object(self.engine,'call',return_value=raw):
            result=self.engine.extract_reading(body,{'id':'current','title':raw['event_title'],'published_at':'2026-11-11T00:00:00Z'},[anchor])
        self.assertEqual(result['match_event_id'],'')
        self.assertEqual(result['summary'],body)
        short={**raw,'event_title':'NVIDIA Alphabet 공급 계약','entities':['NVIDIA','Alphabet']}
        short_anchor={**anchor,'event_title':'NVIDIA Google 공급 계약','entities':['NVIDIA','Google']}
        with patch.object(ai.stocks,'CATALOGUE',catalogue),patch.object(ai.stocks,'NAME_MATCHER',matcher),patch.object(ai.stocks,'NAME_CODES',names),patch.object(self.engine,'call',return_value=short):
            self.assertEqual(self.engine.extract_reading(body,{'id':'current','title':short['event_title'],'published_at':'2026-11-11'},[short_anchor])['match_event_id'],'')

    def test_legal_party_guard_keeps_reprints_and_abstains_without_specific_legal_names(self):
        catalogue={'NVDA.O':{'code':'NVDA.O','name':'NVIDIA','legal_name':'NVIDIA Corporation','country':'US'},
                   'GOOGL.O':{'code':'GOOGL.O','name':'Alphabet Class A','legal_name':'Alphabet Inc.','country':'US'},
                   'AMZN.O':{'code':'AMZN.O','name':'Amazon','legal_name':'Amazon.com, Inc.','country':'US'}}
        matcher,names=ai.stocks.compile_names(catalogue)
        cases=[('Amazon.com, Inc.','Amazon Web Services, Inc.','2026-11-11',''),
               ('Amazon Web Services, Inc.','Amazon Web Services EMEA SARL','2026-11-11',''),
               ('Amazon Web Services, Inc.','Amazon Web Services Inc.','2026-11-11','old'),
               ('Google LLC','Google L.L.C.','2026-11-11','old'),
               ('AWS','Amazon Web Services, Inc.','2026-11-11','old'),
               ('Amazon Web Services, Inc.','Amazon Web Services EMEA SARL','2026-10-28','old')]
        for old_name,current_name,date,expected in cases:
            old_body=f'NVIDIA Corporation은 {old_name}와 공급 계약을 체결했다.'
            body=f'NVIDIA Corporation은 {current_name}와 공급 계약을 체결했다.'
            anchor={**READING,'event_id':'old','event_title':f'NVIDIA Corporation {old_name} 공급 계약',
                    'entities':['NVIDIA Corporation',old_name],'summary':old_body,'evidence':[old_body]}
            raw={**READING,'summary':body,'event_title':f'NVIDIA Corporation {current_name} 공급 계약',
                 'entities':['NVIDIA Corporation',current_name],'evidence':[1],'match_event_id':'old'}
            with self.subTest(old=old_name,current=current_name,date=date),patch.object(ai.stocks,'CATALOGUE',catalogue),patch.object(ai.stocks,'NAME_MATCHER',matcher),patch.object(ai.stocks,'NAME_CODES',names),patch.object(self.engine,'call',return_value=raw):
                result=self.engine.extract_reading(body,{'id':'current','title':raw['event_title'],'published_at':date},[anchor])
                self.assertEqual(result['match_event_id'],expected)

    def test_registered_legal_parties_remain_distinct_when_both_map_to_one_stock(self):
        old_body='Google LLC와 Alphabet Inc.는 공급 계약을 체결했다.'
        body='Google LLC와 Amazon.com, Inc.는 공급 계약을 체결했다.'
        anchor={**READING,'event_id':'old','event_title':'Google LLC Alphabet Inc. 공급 계약',
                'entities':['Google LLC','Alphabet Inc.'],'summary':old_body,'evidence':[old_body]}
        output={**READING,'event_title':'Google LLC Amazon.com, Inc. 공급 계약',
                'entities':['Google LLC','Amazon.com, Inc.'],'summary':body,'evidence':[body],'match_event_id':'old'}
        def listed(name,*args):
            code='AMZN.O' if name.startswith('Amazon') else 'GOOGL.O'
            return [{'code':code,'relation':'direct'}]
        with patch('intelligence.stocks.related_stocks',side_effect=listed):
            self.assertEqual(ai.separate_event_update(output,[anchor],'2026-11-11')['match_event_id'],'')

    def test_contract_party_guard_uses_source_checked_summary_when_title_omits_customer(self):
        proof='한빛에너지는 동부전력과 3000억원 공급 계약을 체결했다.'
        anchor={**READING,'event_id':'old','event_title':'한빛에너지 공급 계약','entities':['한빛에너지','동부전력'],
                'summary':proof,'evidence':[proof]}
        current={**anchor,'match_event_id':'old','event_title':'한빛에너지 서부전력 계약',
                 'entities':['한빛에너지','서부전력'],'summary':'한빛에너지는 서부전력과 공급 계약을 체결했다.',
                 'evidence':['한빛에너지는 서부전력과 공급 계약을 체결했다. 기존 동부전력 계약과 별도다.']}
        self.assertEqual(ai.separate_event_update(current,[anchor],'2026-11-15')['match_event_id'],'')
        reprint={**anchor,'match_event_id':'old'}
        self.assertEqual(ai.separate_event_update(reprint,[anchor],'2026-11-15')['match_event_id'],'old')
        ambiguous={**anchor,'summary':proof+' 서부전력도 언급했다.','entities':['한빛에너지','동부전력','서부전력'],
                   'evidence':[proof+' 서부전력도 언급했다.']}
        self.assertEqual(ai.contract_party_names(ambiguous)[0],[])
        no_proof={**anchor,'evidence':['한빛에너지는 신규 계약을 공시했다.']}
        self.assertEqual(ai.contract_party_names(no_proof)[0],[])

    def test_same_legal_party_is_preserved_across_security_identifiers(self):
        anchor={**READING,'event_id':'old','event_title':'NVIDIA Corporation Alphabet Inc. 공급 계약',
                'entities':['NVIDIA Corporation','Alphabet Inc.'],
                'evidence':['NVIDIA Corporation은 Alphabet Inc.와 공급 계약을 체결했다.']}
        output={**READING,'event_title':'NVIDIA Corporation Alphabet, Inc. 공급 계약',
                'entities':['NVIDIA Corporation','Alphabet, Inc.'],
                'evidence':['NVIDIA Corporation은 Alphabet, Inc.와 공급 계약을 체결했다.'],'match_event_id':'old'}
        def listed(name,*args):
            code='NVDA.O' if name.startswith('NVIDIA') else 'GOOG.O' if name.startswith('Alphabet,') else 'GOOGL.O'
            return [{'code':code,'relation':'direct'}]
        with patch('intelligence.stocks.related_stocks',side_effect=listed):
            self.assertEqual(ai.separate_event_update(output,[anchor],'2026-11-11')['match_event_id'],'old')

    def test_normalized_issuer_names_keep_literal_source_aliases_in_fresh_and_cached_views(self):
        import server
        catalogue={'122870':{'code':'122870','name':'와이지엔터테인먼트','market':'코스닥','country':'KR','industry':'엔터테인먼트','products':'음반'},
                   '005930':{'code':'005930','name':'삼성전자','market':'유가증권','country':'KR','industry':'전자','products':'반도체'}}
        body='삼성전자는 배경으로 언급됐다. 신한투자증권은 내년 와이지엔터의 실적을 전망했다.'
        article={**ARTICLE,'title':'내년 엔터테인먼트 실적 전망','_analysis_body':body}
        raw={**READING,'summary':'YG Entertainment의 내년 실적 전망이다.','event_title':'엔터테인먼트 실적 전망',
             'entities':['YG Entertainment'],'certainty':'전망','amount':'미확인','timing':'내년','evidence':[1]}
        with patch.dict(ai.stocks.ALIASES,{'122870':['YG Entertainment','와이지엔터']}):
            matcher,names=ai.stocks.compile_names(catalogue)
        with patch.object(ai.stocks,'CATALOGUE',catalogue),patch.object(ai.stocks,'NAME_MATCHER',matcher),patch.object(ai.stocks,'NAME_CODES',names),patch.object(self.engine,'call',return_value=raw):
            fresh=self.engine.reading(article,[])
            matched=ai.stocks.body_related_stocks(fresh['entity_mentions'],article['url'])
            self.assertEqual([s['code'] for s in matched],['122870'])
            self.assertEqual(fresh['entity_mentions'][0]['name'],'와이지엔터')
            self.assertIn(fresh['entity_mentions'][0]['evidence'],body)
            saved={**fresh,'entity_mentions':[]}
            grouped,_=ai.group_events([saved],[GATE])
            rendered=server.classify(article,reading=grouped[0]['articles'][0])
            self.assertEqual([s['code'] for s in rendered['related_stocks']],['122870'])
            self.assertEqual(rendered['related_stocks'][0]['relation'],'body')
            self.assertEqual(saved['entity_mentions'],[])
            self.assertEqual(grouped[0]['entities'],['YG Entertainment'])
            split={**saved,'evidence':['첫 인용에서는 YG','Entertainment만 두 번째 인용에 등장했다.']}
            separate_quotes,_=ai.group_events([split],[GATE])
            self.assertEqual(separate_quotes[0]['articles'][0]['entity_mentions'],[])

    def test_alias_evidence_cannot_link_other_issuers_or_expand_unknown_names(self):
        catalogue={'111111':{'code':'111111','name':'한빛'},'222222':{'code':'222222','name':'한빛홀딩스'},
                   '333333':{'code':'333333','name':'한빛우'}}
        with patch.dict(ai.stocks.ALIASES,{'111111':['Example Parent','Shared Brand'],'222222':['Shared Brand']}):
            matcher,names=ai.stocks.compile_names(catalogue)
        with patch.object(ai.stocks,'NAME_MATCHER',matcher),patch.object(ai.stocks,'NAME_CODES',names),patch.object(ai.stocks,'related_stocks',side_effect=AssertionError('테마 확장 호출 금지')):
            for entity,body in [('Example Parent','한빛홀딩스, 실적 전망 발표.'),
                                ('Example Parent','한빛우, 배당 확대 발표.'),
                                ('Shared Brand','한빛, 실적 전망 발표.'),
                                ('PrivateModelCo','비상장 AI 기업과 한빛, 공동 행사.')]:
                with self.subTest(entity=entity,body=body):
                    self.assertEqual(ai.entity_mentions(body,[entity]),[])
            body='한빛홀딩스, 실적 발표. 한빛, 공급 계약 체결.'
            mentions=ai.entity_mentions(body,['Example Parent'])
            self.assertEqual([m['name'] for m in mentions],['한빛'])
            match=next(m for m in ai.stocks.direct_mentions(body) if m['code']=='111111')
            self.assertEqual(match['start'],body.rindex('한빛,'))
            self.assertEqual(body[match['start']:match['end']],'한빛')

    def seed_previous_time_policy(self, cache_policy='source-passages-v6-contract-parties', body=BODY, **changes):
        article={**ARTICLE,'_analysis_body':body,'_body_version':ai.sha256(body.encode()).hexdigest()}
        previous={**READING,'timing':'2026-11-11','read_policy_version':cache_policy,
                  'article_id':article['id'],'article_title':article['title'],'source_url':article['url'],
                  'published_at':article['published_at'],'body_version':article['_body_version'],
                  'body_chars':len(body),'model':self.engine.model,'analyzed_at':'2026-11-11T10:00:00+00:00',
                  'source_version_at':'2026-11-11T09:00:00+00:00','event_id':'original-event',**changes}
        with patch.object(ai,'READ_VERSION',cache_policy):
            key=self.engine.reading_key(article,body)
        if body!=BODY and 'evidence' not in changes:
            previous['evidence']=[body]
        if 'event_id' not in changes:
            previous['event_id']=previous['match_event_id'] or 'event-'+key[:20]
        with self.engine.db() as db:
            db.execute('DELETE FROM readings')
            db.execute('INSERT INTO readings VALUES(?,?,?,?)',(key,article['id'],json.dumps(previous),previous['analyzed_at']))
        return article,previous,key

    def test_time_only_policy_revalidates_exact_cached_source_without_new_model_analysis(self):
        article,previous,old_key=self.seed_previous_time_policy()
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('불필요한 본문 모델 호출')):
            result=self.engine.reading(article,[])
        self.assertEqual(result['timing'],'미확인')
        self.assertEqual(result['timing_original'],previous['timing'])
        self.assertEqual(result['read_policy_version'],ai.READ_VERSION)
        for key in ('summary','amount','certainty','evidence','event_id','analyzed_at','source_version_at'):
            self.assertEqual(result[key],previous[key])
        with self.engine.db() as db:
            old=json.loads(db.execute('SELECT payload FROM readings WHERE cache_key=?',(old_key,)).fetchone()[0])
            current=json.loads(db.execute('SELECT payload FROM readings WHERE cache_key=?',(self.engine.reading_key(article,BODY),)).fetchone()[0])
        self.assertEqual(old,previous)
        self.assertEqual(current,result)
        other=ai.Engine(self.engine.path)
        with patch.object(other,'extract_reading',side_effect=AssertionError('재시작 후 중복 모델 호출')):
            self.assertEqual(other.reading(article,[]),result)

    def test_new_connection_check_rereads_linked_legacy_results_and_keeps_current_links(self):
        for policy in ('source-passages-v6-contract-parties','source-passages-v7-source-time'):
            body='한빛에너지는 Google LLC와 3000억원 규모의 공급 계약을 체결했다.'
            article,_,_=self.seed_previous_time_policy(cache_policy=policy,body=body,entities=['한빛에너지','Google LLC'],event_title='한빛에너지 Google LLC 공급 계약',match_event_id='existing-contract')
            with self.subTest(policy=policy),patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
                self.engine.reading(article,[])
                read.assert_called_once()
        article,previous,_=self.seed_previous_time_policy(match_event_id='existing-contract')
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('새 법인 검사가 적용되지 않는 연결의 중복 호출')):
            self.assertEqual(self.engine.reading(article,[])['event_id'],previous['event_id'])
        article,previous,_=self.seed_previous_time_policy(cache_policy=ai.READ_VERSION,match_event_id='existing-contract',timing='미확인')
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('현재 승인 연결의 중복 호출')):
            result=self.engine.reading(article,[])
        self.assertEqual(result['event_id'],previous['event_id'])

    def test_unlinked_time_policy_cache_revalidates_but_does_not_override_a_newer_link(self):
        article,old,old_key=self.seed_previous_time_policy()
        article,previous,_=self.seed_previous_time_policy(cache_policy='source-passages-v7-source-time',timing='미확인',timing_original='2026-11-11')
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('연결 없는 본문의 중복 호출')):
            result=self.engine.reading(article,[])
        self.assertEqual(result['timing_original'],previous['timing_original'])
        self.assertEqual(result['analyzed_at'],previous['analyzed_at'])
        body='한빛에너지는 Google LLC와 공급 계약을 체결했다.'
        article,old,old_key=self.seed_previous_time_policy(body=body,entities=['한빛에너지','Google LLC'],event_title='한빛에너지 Google LLC 공급 계약')
        article,_,_=self.seed_previous_time_policy(cache_policy='source-passages-v7-source-time',body=body,entities=['한빛에너지','Google LLC'],event_title='한빛에너지 Google LLC 공급 계약',match_event_id='existing-contract')
        with self.engine.db() as db:
            db.execute('INSERT INTO readings VALUES(?,?,?,?)',(old_key,article['id'],json.dumps(old),old['analyzed_at']))
        with patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
            self.engine.reading(article,[])
            read.assert_called_once()

    def test_revalidation_preserves_an_event_id_inherited_from_an_earlier_policy(self):
        article,original,_=self.seed_previous_time_policy()
        checked={**original,'read_policy_version':'source-passages-v7-source-time',
                 'timing':'미확인','timing_original':original['timing']}
        with self.engine.db() as db:
            key=self.engine.reading_key(article,BODY,'source-passages-v7-source-time')
            db.execute('INSERT INTO readings VALUES(?,?,?,?)',(key,article['id'],json.dumps(checked),ai.now()))
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('버전 전환으로 상속한 사건 ID의 불필요한 재분석')):
            result=self.engine.reading(article,[])
        self.assertEqual(result['event_id'],original['event_id'])
        self.assertEqual(result['analyzed_at'],original['analyzed_at'])

    def test_time_revalidation_rejects_incompatible_metadata_and_invalid_facts(self):
        for change in ({'read_policy_version':'unknown-policy'},{'article_id':'other'},
                       {'article_title':'다른 기사'},{'source_url':'https://example.com/other'},
                       {'published_at':'2026-11-12T00:00:00Z'},{'model':'other-model'},
                       {'body_version':'other-version'},{'body_chars':1},{'analyzed_at':None},
                       {'analyzed_at':'2999-01-01T00:00:00Z'},{'evidence':['원문에 없는 계약 문장']},
                       {'certainty':'잘못된 단계'},{'event_id':'unrelated-event'}):
            article,_,_=self.seed_previous_time_policy(**change)
            with self.subTest(change=change),patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
                result=self.engine.reading(article,[])
                read.assert_called_once()
                self.assertEqual(result['analyzed_at'],ai.now())

    def test_time_revalidation_cannot_cross_source_model_or_future_policy_changes(self):
        for change in ({'title':'계약 정정'},{'url':ARTICLE['url']+'new'},
                       {'_analysis_body':BODY+' 추가 조건이 있다.'},{'_body_version':'new-version'}):
            article,_,_=self.seed_previous_time_policy()
            with self.subTest(change=change),patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
                self.engine.reading({**article,**change},[])
                read.assert_called_once()
        for attribute,value in (('provider','gemini'),('model','other-model')):
            article,_,_=self.seed_previous_time_policy()
            with self.subTest(attribute=attribute),patch.object(self.engine,attribute,value),patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
                self.engine.reading(article,[])
                read.assert_called_once()
        article,_,_=self.seed_previous_time_policy()
        with patch.object(ai,'READ_VERSION','future-policy'),patch.object(self.engine,'extract_reading',return_value=copy.deepcopy(READING)) as read:
            self.engine.reading(article,[])
            read.assert_called_once()

    def test_time_only_review_keeps_original_analysis_time_and_adds_review_history(self):
        article,previous,_=self.seed_previous_time_policy()
        self.engine.queue.enqueue([{'article':article,'body':BODY,'body_version':article['_body_version']}])
        self.engine.queue.complete(self.engine.queue.claim(),previous,GATE)
        with patch.object(self.engine,'extract_reading',side_effect=AssertionError('불필요한 본문 모델 호출')),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1')]):
            self.engine.cycle([article])
        history=self.engine.queue.history(previous['event_id'])
        self.assertEqual(len(history),2)
        self.assertEqual([h['analyzed_at'] for h in history],[previous['analyzed_at']]*2)
        self.assertEqual(history[0]['timing'],previous['timing'])
        self.assertEqual(history[1]['timing'],'미확인')
        self.assertEqual(history[1]['timing_original'],previous['timing'])
        self.assertTrue(history[1]['assessment_review'])
        self.assertIsNotNone(history[1]['reviewed_at'])

    def test_captured_unsupported_time_cannot_become_a_fact_or_discard_other_facts(self):
        body='가상 종합지수는 전일 대비 2.5% 상승 마감했다. 기관 매수가 확대됐다.'
        for timing in ('오늘','현재','2026-11-11'):
            raw={'summary':'가상 종합지수는 전일 대비 2.5% 상승 마감.',
                 'event_title':'가상 종합지수 2.5% 상승 마감','event_type':'주가 변동',
                 'entities':[],'certainty':'확정','amount':'2.5% 상승','timing':timing,
                 'evidence':[1],'match_event_id':''}
            with self.subTest(timing=timing),patch.object(self.engine,'call',return_value=raw):
                result=self.engine.extract_reading(body,{'id':'current','title':'가상 종합지수 2.5% 상승 마감'},[{'event_id':'older','timing':timing}])
                self.assertEqual(result['timing'],'미확인')
                self.assertEqual(result['timing_original'],timing)
                self.assertEqual({k:v for k,v in result.items() if k not in ('timing','timing_original','evidence')},
                                 {k:v for k,v in raw.items() if k not in ('timing','evidence')})
                self.assertEqual(result['evidence'],[body])
                self.assertEqual(raw['timing'],timing)

    def test_time_source_check_preserves_dates_ranges_and_explicit_relative_time(self):
        cases=[('2027~2029년','공급 기간은 2027년부터 2029년까지다.','2027~2029년'),
               ('2027년 ~ 2029년','계약 기간은 2027년부터 2029년까지다.','2027년 ~ 2029년'),
               ('2026-11-11','11일 계약을 체결했다고 밝혔다.','미확인'),
               ('2026-11-11','2026년 11월 11일 계약을 체결했다.','2026-11-11'),
               ('2026.01.02','2026년 1월 2일 계약을 체결했다.','2026.01.02'),
               ('2026년 1월 2일','계약일은 2026-01-02다.','2026년 1월 2일'),
               ('2027~2029년','계약 기간은 2027년부터 2030년까지다.','미확인'),
               ('11일','계약일은 21일이라고 밝혔다.','미확인'),
               ('1일','계약일은 11일이라고 밝혔다.','미확인'),
               ('2027~2029년','숫자 12027~2029년은 기간이 아니다.','미확인'),
               ('3분기','3분기 실적을 발표했다고 밝혔다.','3분기'),
               ('오늘부터','지원 제도는 오늘부터 시행된다.','오늘부터'),
               ('오늘','가상 종합지수는 2.5% 상승 마감했다.','미확인'),
               ('미확인','계약 기간은 공개하지 않았다.','미확인'),
               ('','계약 기간은 공개하지 않았다.','미확인')]
        for timing,body,expected in cases:
            with self.subTest(timing=timing,body=body),patch.object(self.engine,'call',return_value={**READING,'timing':timing,'evidence':[1]}):
                result=self.engine.extract_reading(body,ARTICLE,[])
                self.assertEqual(result['timing'],expected)
                if expected==timing:
                    self.assertNotIn('timing_original',result)

    def test_captured_customer_swap_cannot_merge_but_same_customer_reprint_can(self):
        dataset=json.loads((Path('tests/fixtures')/'event_linking_eval.json').read_text())
        cases={c['id']:c for c in dataset['clusters']}
        for case_id,customer,expected in [('new-customer-same-amount','동부전력',''),('contract-paraphrase','서부전력','west-contract')]:
            case=cases[case_id]
            captured={'summary':f'한빛에너지는 {customer}과 3000억원 규모의 변압기 공급 계약을 체결했다. 계약 기간은 2027년부터 2029년까지다.',
                'event_title':f'한빛에너지 {customer} 변압기 공급 계약','event_type':'계약','entities':['한빛에너지',customer],
                'certainty':'확정','amount':'3000억원','timing':'2027~2029년','evidence':[1],'match_event_id':'west-contract'}
            for with_quote in (False,True):
                anchors=copy.deepcopy(case['anchors'])
                if with_quote:anchors[0]['evidence']=[anchors[0]['summary']]
                with self.subTest(case_id=case_id,with_quote=with_quote),patch.object(self.engine,'call',return_value=captured) as call:
                    result=self.engine.extract_reading(case['body'],{'id':'current','title':case['title']},anchors)
                    self.assertEqual(result['match_event_id'],expected)
                    self.assertIn(customer,result['entities'])
                    self.assertEqual(result['amount'],'3000억원')
                    self.assertNotIn('evidence',call.call_args.args[1]['existing_events'][0])

    def test_contract_party_guard_keeps_verified_aliases_and_ignores_background_entities(self):
        anchor={**READING,'event_id':'old','event_title':'SK하이닉스 서부전력 공급 계약',
                'entities':['SK하이닉스','서부전력','배경기업'],'summary':'SK하이닉스와 서부전력의 공급 계약이다.',
                'evidence':['SK하이닉스와 서부전력이 공급 계약을 체결했다.']}
        current={**READING,'match_event_id':'old','event_title':'하이닉스 서부전력 공급 계약',
                 'entities':['하이닉스','서부전력','다른배경기업'],'evidence':['하이닉스와 서부전력이 공급 계약을 체결했다.']}
        def resolve(title):
            return [{'code':'000660','relation':'direct'}] if title in ('SK하이닉스,','하이닉스,') else []
        with patch('intelligence.stocks.related_stocks',side_effect=resolve) as lookup:
            self.assertEqual(ai.separate_event_update(current,[anchor])['match_event_id'],'old')
            lookup.assert_any_call('SK하이닉스,');lookup.assert_any_call('하이닉스,')
            self.assertFalse(any('배경기업' in c.args[0] for c in lookup.call_args_list))

    def test_contract_party_guard_abstains_without_two_proven_title_parties(self):
        anchor={**READING,'event_id':'old','event_title':'한빛에너지 서부전력 공급 계약',
                'entities':['한빛에너지','서부전력'],'summary':'한빛에너지가 서부전력에 공급한다.',
                'evidence':['한빛에너지가 서부전력과 공급 계약을 체결했다.']}
        for title,proof in [('한빛에너지 공급 계약','한빛에너지가 동부전력에 공급한다.'),
                            ('한빛에너지 동부전력 공급 계약','한빛에너지의 계약이며 고객은 비공개다.')]:
            current={**READING,'match_event_id':'old','event_title':title,'entities':['한빛에너지','동부전력'],'evidence':[proof]}
            self.assertEqual(ai.separate_event_update(current,[anchor])['match_event_id'],'old')

    def test_reading_evaluation_compares_measure_tokens_not_numeric_substrings(self):
        cases=[('3000','30000억원',False),('3000','13000억원',False),('3000','3000.5억원',False),
               ('3000','3,000억원',True),('3000','3000억원',True),('1%','11%',False),
               ('20GW','120GW',False),('20GW','20 GWh',False),('20GW','20 GW',True),
               ('26.6','126.6%',False),('26.6','26.6%',True),('5%','5%포인트',False),
               ('5%','5 %p',False),('5%','5%.',True),('20GW','20GW. 확정',True),
               ('3000억원','3000만원',False),('3000억원','3000원',False),
               ('3000억원','3000달러',False),('3000억원','3,000 억원',True)]
        for expected,actual,matches in cases:
            engine=MagicMock(model='mock',provider='ollama');engine.usage.return_value={}
            engine.extract_reading.return_value={'certainty':'확정','entities':['한빛에너지'],'amount':actual}
            dataset={'readings':[{'id':'measure','body':'한빛에너지가 공개한 규모를 확인한다.',
                                 'expected':{'certainty':'확정','entities':['한빛에너지'],'amount_contains':expected}}]}
            with self.subTest(expected=expected,actual=actual),patch('builtins.print'):
                result=evaluate(engine,dataset,readings_only=True)
                self.assertTrue(result['cases'][0]['valid'])
                self.assertEqual(result['cases'][0]['checks']['amount'],matches)

    def pair_oracle(self,dataset):
        bodies={c['id']:c['summary'] for c in dataset['equity_screening']}
        higher={frozenset((bodies[a],bodies[b])):bodies[a] for a,b in dataset['priority_pairs']}
        def compare(task,payload,output_schema):
            events=payload['events']
            winner=higher[frozenset(e['evidence'][0] for e in events)]
            return {'winner':next(e['event_id'] for e in events if e['evidence'][0]==winner),'reason':'원문에서 더 큰 경제적 변화가 확인된다.'}
        return compare

    def test_pairwise_comparison_reverses_positions_without_leaking_expected_ids(self):
        dataset=self.coverage_fixture();engine=MagicMock(model='mock',provider='ollama')
        engine.usage.return_value={};engine.call.side_effect=self.pair_oracle(dataset)
        with patch('builtins.print'):report=evaluate_pairwise(engine,dataset)
        self.assertEqual((report['passed'],report['valid'],report['consistent'],report['total']),(4,4,4,4))
        self.assertEqual(engine.call.call_count,8);engine.rank.assert_not_called()
        for check in report['checks']:
            left,right=check['runs']
            self.assertEqual(left['labels']['E1'],right['labels']['E2'])
            self.assertEqual(left['actual'],check['higher']);self.assertEqual(right['actual'],check['higher'])
        for call in engine.call.call_args_list:
            payload=call.args[1]
            self.assertEqual({e['event_id'] for e in payload['events']},{'E1','E2'})
            for higher,lower in dataset['priority_pairs']:
                self.assertNotIn(higher,json.dumps(payload));self.assertNotIn(lower,json.dumps(payload))
        self.assertIn('격리',report['limitations'])

    def test_pairwise_comparison_uses_provided_source_quotes_instead_of_replacing_them_with_the_summary(self):
        quotes=['회사는 대규모 계약 취소를 공시했다.','해당 계약은 연간 매출의 절반 규모다.']
        small='회사는 소액의 배당 인상을 공시했다.'
        data={'equity_screening':[{'id':'risk','summary':' '.join(quotes),'evidence':quotes,'expected':'주식 판단 재료'},
                                  {'id':'small','summary':small,'expected':'주식 판단 재료'}],
              'priority_pairs':[['risk','small']]}
        engine=MagicMock(model='test',provider='ollama');engine.usage.return_value={}
        def compare(task,payload,output_schema):
            self.assertEqual({tuple(e['evidence']) for e in payload['events']},{tuple(quotes),(small,)})
            return {'winner':next(e['event_id'] for e in payload['events'] if e['evidence']==quotes),'reason':'계약 취소의 변화 규모가 크다.'}
        engine.call.side_effect=compare
        with patch('builtins.print'):result=evaluate_pairwise(engine,data)
        self.assertEqual((result['passed'],result['valid']),(1,1))

    def test_pairwise_position_bias_and_ties_cannot_pass(self):
        dataset=self.coverage_fixture()
        for winner,consistent in [('E1',0),('동순위',4)]:
            engine=MagicMock(model='mock',provider='ollama');engine.usage.return_value={}
            engine.call.return_value={'winner':winner,'reason':'비교 결과'}
            with patch('builtins.print'):report=evaluate_pairwise(engine,dataset)
            self.assertEqual((report['passed'],report['valid'],report['consistent']),(0,4,consistent))

    def test_pairwise_invalid_second_response_is_not_a_consistent_pass(self):
        dataset=self.coverage_fixture();engine=MagicMock(model='mock',provider='ollama');engine.usage.return_value={}
        oracle=self.pair_oracle(dataset);calls=[]
        def compare(*args):
            calls.append(args)
            return {'winner':'invented','reason':'허구 번호'} if len(calls)==2 else oracle(*args)
        engine.call.side_effect=compare
        with patch('builtins.print'):report=evaluate_pairwise(engine,dataset)
        self.assertEqual((report['passed'],report['valid'],report['consistent']),(3,3,3))
        self.assertIsNone(report['checks'][0]['consistent'])
        self.assertEqual(report['checks'][0]['runs'][1]['error'],'ValueError')
        self.assertIsNone(report['checks'][0]['runs'][1]['actual'])

    def test_pairwise_bad_expectations_fail_before_model_calls(self):
        for pairs in (None,[],[['missing','small-order']],[['signed-orders','signed-orders']],
                      [['signed-orders','bond-subscription']],[['signed-orders','small-order'],['small-order','signed-orders']],[[True,'small-order']]):
            dataset={**self.coverage_fixture(),'priority_pairs':pairs};engine=MagicMock()
            self.assertRaises(ValueError,evaluate_pairwise,engine,dataset)
            engine.call.assert_not_called();engine.usage.assert_not_called()

    def coverage_fixture(self):
        return json.loads((Path(__file__).parent/'fixtures/ranking_coverage_eval.json').read_text())

    def mock_screening(self,engine,dataset):
        labels={tuple(c['evidence']):c['expected'] for c in ranking_cases(dataset)}
        engine.screen.side_effect=lambda event:{'stock_relevance':labels[tuple(event['evidence'])]}

    def coverage_oracle(self,dataset):
        cases=dataset['equity_screening']
        priorities={case['summary']:i+2 for i,case in enumerate(cases)}
        for index,critical in enumerate(dataset['priority_checks']):
            priorities[next(c['summary'] for c in cases if c['id']==critical)]=index
        labels={c['summary']:c['expected'] for c in cases}
        def rank(events,market):
            return [dict(rank_row(e['event_id']),stock_relevance=labels[e['evidence'][0]]) for e in sorted(events,key=lambda e:priorities[e['evidence'][0]])]
        return rank

    def test_window_comparison_covers_tail_candidates_with_a_consistent_mock_ranker(self):
        dataset=self.coverage_fixture()
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.return_value={}
        engine.rank.side_effect=self.coverage_oracle(dataset)
        with patch('builtins.print'):
            self.mock_screening(engine,dataset);report=evaluate_window_ranking(engine,dataset)
        first,forward,reverse=report['runs']
        self.assertEqual((report['window_size'],report['step'],report['top_k']),(12,4,8))
        self.assertGreater(sum(c['expected']=='주식 판단 재료' for c in dataset['equity_screening']),8)
        self.assertEqual(engine.rank.call_count,5)
        self.assertEqual(engine.screen.call_count,24)
        self.assertEqual((first['reviewed'],first['critical_hits']),(12,0))
        for run in (forward,reverse):
            self.assertTrue(run['valid'])
            self.assertEqual((run['reviewed'],run['passed'],run['critical_hits']),(15,24,2))
            self.assertEqual(run['eligibility_passed'],24)
            self.assertEqual(len({r['event_id'] for r in run['ranking']}),15)
            self.assertEqual([len(w['inputs']) for w in run['windows']],[12,11])
        original={c['summary'] for c in dataset['equity_screening']}
        for call in engine.rank.call_args_list:
            self.assertEqual([e['event_id'] for e in call.args[0]],[f'E{i+1}' for i in range(len(call.args[0]))])
            for event in call.args[0]:
                self.assertEqual(set(event),{'event_id','evidence','published_at','first_published_at','stock_relevance'})
                self.assertIn(event['evidence'][0],original)
                self.assertRegex(event['event_id'],r'^E\d+$')

    def test_failed_window_is_not_full_coverage_even_after_a_successful_window(self):
        dataset=self.coverage_fixture()
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.return_value={}
        oracle=self.coverage_oracle(dataset)
        count=0
        def rank(events,market):
            nonlocal count
            count+=1
            if count==3:raise TimeoutError()
            return oracle(events,market)
        engine.rank.side_effect=rank
        with patch('builtins.print'):
            self.mock_screening(engine,dataset);report=evaluate_window_ranking(engine,dataset)
        run=report['runs'][1]
        self.assertFalse(run['valid'])
        self.assertEqual(run['error'],'TimeoutError')
        self.assertEqual((run['reviewed'],run['passed'],run['total']),(12,21,24))
        self.assertEqual(run['eligibility_passed'],24)
        self.assertEqual(sum(c['reviewed'] for c in run['checks']),12)

    def test_window_boundaries_keep_top_eight_with_a_consistent_ranker(self):
        for size in (13,19,35):
            cases=[{'id':str(i),'summary':f'공개 계약 원문 사례 번호 {i}','expected':'주식 판단 재료'} for i in range(size)]
            dataset={'equity_screening':cases,'priority_checks':[str(size-1),str(size-2)]}
            engine=MagicMock(model='test',provider='ollama')
            engine.usage.return_value={}
            engine.rank.side_effect=lambda events,market:[rank_row(e['event_id']) for e in sorted(events,key=lambda e:int(e['evidence'][0].split()[-1]),reverse=True)]
            with patch('builtins.print'):
                self.mock_screening(engine,dataset);report=evaluate_window_ranking(engine,dataset)
            for run in report['runs'][1:]:
                self.assertEqual(run['reviewed'],size)
                self.assertEqual(run['top8'],[str(i) for i in range(size-1,size-9,-1)])
                self.assertTrue(all(len(w['inputs'])<=12 for w in run['windows']))

    def test_excluded_rows_cannot_displace_better_material_events_from_the_next_window(self):
        cases=[{'id':str(i),'summary':f'공개 원문 검증용 사례 번호 {i}',
                'expected':'배경·상품 안내' if 4<=i<8 else '주식 판단 재료'} for i in range(16)]
        dataset={'equity_screening':cases,'priority_checks':['8','9']}
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.return_value={}
        def rank(events,market):
            def number(event):return int(event['evidence'][0].split()[-1])
            ordered=sorted(events,key=lambda e:(0 if 4<=number(e)<8 else 1,-number(e)))
            return [dict(rank_row(e['event_id']),stock_relevance=cases[number(e)]['expected']) for e in ordered]
        engine.rank.side_effect=rank
        with patch('builtins.print'):
            self.mock_screening(engine,dataset);result=evaluate_window_ranking(engine,dataset)
        self.assertEqual(result['retention_policy'],'screened-candidates-only-v2')
        self.assertEqual(engine.screen.call_count,16)
        for run in result['runs'][1:]:
            self.assertEqual(run['top8'],[str(i) for i in range(15,7,-1)])
            self.assertEqual(run['eligibility_passed'],16)
            self.assertEqual(run['critical_hits'],2)
            for call in engine.rank.call_args_list:
                self.assertTrue(all(not 4<=int(e['evidence'][0].split()[-1])<8 for e in call.args[0]))

    def test_window_evaluator_rejects_bad_model_ids_and_missing_expected_labels(self):
        dataset=self.coverage_fixture()
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.return_value={}
        engine.rank.return_value=[rank_row('invented')]
        with patch('builtins.print'):
            self.mock_screening(engine,dataset);report=evaluate_window_ranking(engine,dataset)
        self.assertTrue(all(not r['valid'] and r['reviewed']==0 for r in report['runs']))
        self.assertTrue(all(r['eligibility_passed']==24 for r in report['runs']))
        for broken in ({**dataset,'priority_checks':['not-a-case']},
                       {**dataset,'equity_screening':[{**c,'expected':'unknown'} for c in dataset['equity_screening']]}):
            engine.rank.reset_mock()
            self.assertRaises(ValueError,evaluate_window_ranking,engine,broken)
            engine.rank.assert_not_called()

    def test_cluster_evaluation_checks_facts_and_does_not_pass_unlabelled_cases(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.extract_reading.return_value={**READING,'match_event_id':'same'}
        cases=[{'id':'same-case','body':BODY,'anchors':[{'event_id':'same'}],'expected_match':'same',
                'expected':{'certainty':'계획','entities':['한빛에너지']}},
               {'id':'unlabelled','body':BODY}]
        with patch('builtins.print'):
            report=evaluate(engine,{'readings':[],'clusters':cases},clusters_only=True)
        self.assertEqual(report['valid'],1)
        self.assertEqual(report['all_checks_pass'],0)
        self.assertTrue(report['cases'][0]['checks']['same_event'])
        self.assertFalse(report['cases'][0]['checks']['certainty'])

    def test_reading_evaluation_skips_cluster_and_rank_calls_without_label_hints(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.extract_reading.return_value=dict(READING)
        with patch('builtins.print'):
            report=evaluate(engine,{'readings':[{'id':'confirmed-contract','body':BODY,'expected':{'certainty':'확정','entities':['한빛에너지'],'amount_contains':'3000'}}],
                                    'clusters':[{'id':'unused'}]},readings_only=True)
        self.assertEqual(report['total'],1)
        self.assertEqual(report['all_checks_pass'],1)
        engine.extract_reading.assert_called_once()
        self.assertEqual(engine.extract_reading.call_args.args[1],{'id':'article-1','title':'원문 기사'})
        engine.rank.assert_not_called()

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

    def reconciliation_pair(self):
        return [{**copy.deepcopy(ANALYZED),'event_id':'e'+str(i),'article_id':'a'+str(i),
                 'article_title':'같은 계약 보도','source_url':'https://example.com/'+str(i),
                 'published_at':f'2026-11-11T0{i}:00:00Z','first_published_at':f'2026-11-11T0{i}:00:00Z'} for i in (1,2)]

    def test_reconciliation_is_source_bound_cached_and_does_not_rewrite_facts(self):
        pair=self.reconciliation_pair();original=copy.deepcopy(pair)
        with patch.object(self.engine,'call',return_value={'same_event':True}) as call:
            links,status=self.engine.reconcile_events(pair)
        self.assertEqual(links['e2']['event_id'],'e1')
        self.assertEqual(status['matched_pairs'],1)
        self.assertEqual(pair,original)
        call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'call') as call:
            again,_=other.reconcile_events(list(reversed(pair)))
        call.assert_not_called();self.assertEqual(again,links)
        version=copy.deepcopy(pair);version[1]['body_version']='new-version'
        with patch.object(other,'call') as call:
            stale,status=other.reconcile_events(version,allow_review=False)
        self.assertEqual(stale,{});self.assertEqual(status['pending_pairs'],1);call.assert_not_called()
        with patch.dict(os.environ,{'LLM_MODEL':'different-model'}):different=ai.Engine(self.engine.path)
        with patch.object(different,'call') as call:
            stale,status=different.reconcile_events(pair,allow_review=False)
        self.assertEqual(stale,{});self.assertEqual(status['pending_pairs'],1);call.assert_not_called()
        changed=copy.deepcopy(pair);changed[1]['evidence']=['한빛에너지는 계약 금액을 4000억원으로 공시했다.']
        with patch.object(other,'call') as call:
            stale,status=other.reconcile_events(changed,allow_review=False)
        self.assertEqual(stale,{})
        self.assertEqual(status['pending_pairs'],1)
        call.assert_not_called()
        with patch.object(other,'call',return_value={'same_event':False}):
            negative,_=other.reconcile_events(changed)
        self.assertEqual(negative,{})
        with other.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM event_links').fetchone()[0],2)

    def test_reconciliation_abstains_on_invalid_reply_and_preserves_retry(self):
        pair=self.reconciliation_pair();clock=ai.time.time()
        with patch('intelligence.time.time',return_value=clock),patch.object(self.engine,'call',return_value={'same_event':1}) as call:
            links,status=self.engine.reconcile_events(pair)
            self.assertEqual(links,{})
            self.assertEqual(status['pending_pairs'],1)
            self.assertTrue(status['errors'])
            self.engine.reconcile_events(pair)
        call.assert_called_once()
        with patch('intelligence.time.time',return_value=clock+60),patch.object(self.engine,'call',return_value={'same_event':False}) as call:
            links,status=self.engine.reconcile_events(pair)
        call.assert_called_once();self.assertEqual(links,{})
        self.assertEqual(status['pending_pairs'],0)
        with patch.object(self.engine,'call') as call:self.engine.reconcile_events(pair)
        call.assert_not_called()

    def test_reconciliation_defers_larger_groups_and_blocks_changed_state(self):
        pair=self.reconciliation_pair();pair[1]['certainty']='부인'
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair)
        call.assert_not_called();self.assertEqual(links,{})
        self.assertEqual(status['blocked_pairs'],1)
        pair=self.reconciliation_pair();pair.append({**pair[1],'event_id':'e3','article_id':'a3'})
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair)
        call.assert_not_called();self.assertEqual(links,{})
        self.assertEqual(status['deferred_groups'],1)

    def test_reconciliation_budget_and_existing_multi_article_groups_remain_explicit(self):
        first=self.reconciliation_pair()
        second=[{**e,'event_id':'other-'+e['event_id'],'article_title':'다른 동일 제목'} for e in first]
        with patch.object(self.engine,'call',return_value={'same_event':False}) as call:
            links,status=self.engine.reconcile_events(first+second)
        call.assert_called_once();self.assertEqual(links,{})
        self.assertEqual(status['reviewed_pairs'],1);self.assertEqual(status['pending_pairs'],1)
        many=copy.deepcopy(first);many[0]['articles']=[{'id':'x'},{'id':'y'}]
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(many)
        call.assert_not_called();self.assertEqual(links,{})
        self.assertEqual(status['deferred_groups'],1)

    def test_reconciliation_defers_busy_work_and_rejects_damaged_or_changed_policy_cache(self):
        pair=self.reconciliation_pair()
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair,allow_review=False)
        call.assert_not_called();self.assertEqual(status['pending_pairs'],1)
        with patch.object(self.engine,'call',return_value={'same_event':True}):self.engine.reconcile_events(pair)
        with self.engine.db() as db:
            saved=json.loads(db.execute('SELECT payload FROM event_links').fetchone()[0]);saved['same_event']='true'
            db.execute('UPDATE event_links SET payload=?',(json.dumps(saved),))
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair,allow_review=False)
        self.assertEqual(links,{});self.assertEqual(status['pending_pairs'],1);call.assert_not_called()
        with patch.object(self.engine,'call',return_value={'same_event':True}):self.engine.reconcile_events(pair)
        with patch.object(ai,'LINK_VERSION','next'),patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair,allow_review=False)
        call.assert_not_called();self.assertEqual(links,{})
        with patch.object(ai,'LINK_POLICY',ai.LINK_POLICY+' 새 기준'),patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(pair,allow_review=False)
        call.assert_not_called();self.assertEqual(links,{})
        future=copy.deepcopy(pair);future[1]['source_version_at']='2026-11-12T00:00:00Z'
        with patch.object(self.engine,'call') as call:self.assertEqual(self.engine.reconcile_events(future)[0],{})
        call.assert_not_called()
        corrected=copy.deepcopy(pair);corrected[1]['event_title']='계약 금액 정정'
        with patch.object(self.engine,'call') as call:
            links,status=self.engine.reconcile_events(corrected)
        call.assert_not_called();self.assertEqual(status['blocked_pairs'],1)

    def test_cycle_projects_reconciled_events_and_preserves_original_ids_and_history(self):
        pair=self.reconciliation_pair();articles=[]
        for r in pair:
            a={**ARTICLE,'id':r['article_id'],'title':r['article_title'],'url':r['source_url'],'published_at':r['published_at']}
            self.engine.queue.enqueue([{'article':a}]);self.engine.queue.complete(self.engine.queue.claim(),r,GATE);articles.append(a)
        def provider(task,payload,output_schema):
            return {'same_event':True} if task=='link' else {'ranking':[e['event_id'] for e in payload['events']]}
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine,'call',side_effect=provider),patch('intelligence.market_snapshot',return_value={'observations':[]}):
            result=self.engine.cycle(articles)
        self.assertEqual(len(result['events']),1)
        e=result['events'][0];self.assertEqual(e['event_id'],'e1')
        self.assertEqual(e['linked_event_ids'],['e1','e2'])
        self.assertEqual({a['original_event_id'] for a in e['articles']},{'e1','e2'})
        self.assertEqual({h['event_id'] for h in e['history']},{'e1','e2'})
        self.assertEqual(e['first_published_at'],pair[0]['published_at'])
        self.assertEqual(len(result['ranking']),1)
        with self.engine.queue.db() as db:self.assertEqual({r[0] for r in db.execute('SELECT event_id FROM analysis_jobs')},{'e1','e2'})
        other=ai.Engine(self.engine.path)
        with patch.object(other.queue,'claim',return_value=None),patch.object(other,'call') as call:
            restored=other.cycle(articles)
        call.assert_not_called();self.assertEqual(restored['ranking'],result['ranking'])
        self.assertEqual(restored['ranked_at'],result['ranked_at'])

    def test_reconciliation_cannot_refresh_the_age_of_an_old_reprinted_event(self):
        pair=self.reconciliation_pair();articles=[]
        old={**ARTICLE,'id':'old-source','url':'https://example.com/old','published_at':'2026-11-09T00:00:00Z'}
        self.engine.queue.enqueue([{'article':old}])
        self.engine.queue.complete(self.engine.queue.claim(),{**pair[0],'article_id':old['id'],'source_url':old['url'],'published_at':old['published_at']},GATE)
        for r in pair:
            a={**ARTICLE,'id':r['article_id'],'title':r['article_title'],'url':r['source_url'],'published_at':r['published_at']}
            self.engine.queue.enqueue([{'article':a}]);self.engine.queue.complete(self.engine.queue.claim(),r,GATE);articles.append(a)
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine,'call',return_value={'same_event':True}) as call:
            result=self.engine.cycle(articles)
        self.assertEqual(result['event_linking']['matched_pairs'],1)
        self.assertEqual(result['events'][0]['first_published_at'],old['published_at'])
        self.assertEqual(result['events'][0]['recency_status'],'old')
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['coverage']['eligible_events'],0)
        self.assertEqual([c.args[0] for c in call.call_args_list],['link'])

    def test_shared_rank_service_rejects_invalid_ids_before_calling_the_model(self):
        with patch.object(self.engine,'call') as call:
            self.assertEqual(self.engine.rank([],{}),[])
            self.assertRaises(ValueError,self.engine.rank,[{'event_id':'E1','stock_relevance':'주식 판단 재료'},{'event_id':'E1','stock_relevance':'주식 판단 재료'}],{})
            self.assertRaises(ValueError,self.engine.rank,[{'event_id':[],'stock_relevance':'주식 판단 재료'}],{})
        call.assert_not_called()

    def test_rank_orders_only_screened_events_and_does_not_ask_for_reclassification(self):
        event={'event_id':'E1','evidence':['회사와 고객이 계약 해지설을 사실무근이라고 공식 확인했다.'],
               'stock_relevance':'주식 판단 재료'}
        raw={'event_id':'E1','reason':'계약 해지설을 공식 부인했다.','watch_for':'후속 공시 확인'}
        with patch.object(self.engine,'call',return_value={'ranking':['E1']}) as call:
            output=self.engine.rank([event],{})
        self.assertEqual(output[0]['reason'],event['evidence'][0])
        self.assertEqual(output[0]['stock_relevance'],'주식 판단 재료')
        self.assertEqual(call.call_args.args[2]['properties']['ranking']['items']['type'],'string')
        self.assertNotIn('stock_relevance',call.call_args.args[1]['events'][0])
        for label in (None,'배경·상품 안내','연결 미확인'):
            with patch.object(self.engine,'call') as call:
                self.assertRaises(ValueError,self.engine.rank,[{**event,'stock_relevance':label}],{})
            call.assert_not_called()
        with patch.object(self.engine,'call',return_value={'ranking':[{**raw,'stock_relevance':'배경·상품 안내'}]}):
            self.assertRaises(ValueError,self.engine.rank,[event],{})

    def test_order_only_output_binds_source_notes_by_id(self):
        events=[{'event_id':'E1','stock_relevance':'주식 판단 재료','evidence':['코스피 지수가 급락한 뒤 반등했다.']},
                {'event_id':'E2','stock_relevance':'주식 판단 재료','evidence':['신용융자 자금이 특정 종목에 집중됐다.']}]
        with patch.object(self.engine,'call',return_value={'ranking':['E2','E1']}) as call:
            rows=self.engine.rank(events,{})
        self.assertEqual([r['reason'] for r in rows],[e['evidence'][0] for e in reversed(events)])
        self.assertNotIn('신용융자',rows[1]['reason'])
        self.assertEqual(call.call_args.args[2]['properties']['ranking']['items']['type'],'string')
        for evidence in ([], '가짜 원문', ['짧음'], [None]):
            with patch.object(self.engine,'call') as call:
                self.assertRaises(ValueError,self.engine.rank,[{**events[0],'evidence':evidence}],{})
            call.assert_not_called()
        for raw in ({'ranking':['E1','E1']},{'ranking':['E1','unknown']},
                    {'ranking':[{'event_id':'E1','reason':'하락세 지속, 신용융자 자금 집중'}]},
                    {'ranking':['E1','E2'],'reason':'추가 추정'}):
            with patch.object(self.engine,'call',return_value=raw):
                self.assertRaises(ValueError,self.engine.rank,events,{})

    def test_ranking_evaluator_matches_case_ids_even_when_the_model_changes_order(self):
        engine=MagicMock(model='test',provider='ollama')
        engine.usage.side_effect=[{'calls_today':0,'output_tokens':0},{'calls_today':4,'output_tokens':120}]
        engine.rank.return_value=[rank_row('E3'),rank_row('E1')]
        data={'equity_screening':[{'id':'risk','summary':'확인된 차환 발행 실패입니다.','expected':'주식 판단 재료'},
                                  {'id':'award','summary':'매출 변화 없는 수상 소식입니다.','expected':'배경·상품 안내'},
                                  {'id':'other','summary':'확인된 공급 계약 취소입니다.','expected':'주식 판단 재료'}]}
        self.mock_screening(engine,data)
        with patch('builtins.print'):report=evaluate_ranking(engine,data)
        self.assertTrue(report['valid'])
        self.assertEqual((report['passed'],report['screened'],report['ordered']),(3,3,2))
        self.assertEqual(report['call_delta'],4)
        self.assertEqual(report['output_tokens_delta'],120)
        self.assertEqual([r['id'] for r in report['checks']],['risk','award','other'])
        self.assertEqual([e['event_id'] for e in engine.rank.call_args.args[0]],['E1','E3'])
        self.assertTrue(all(e['stock_relevance']=='주식 판단 재료' for e in engine.rank.call_args.args[0]))
        self.assertEqual([r['event_id'] for r in report['ranking']],['E3','E1'])
        engine.call.assert_not_called()

    def test_ranking_evaluator_keeps_screen_results_but_never_passes_failed_ordering(self):
        engine=MagicMock(model='test',provider='ollama');engine.usage.return_value={}
        engine.rank.return_value=[rank_row('unknown')]
        data={'equity_screening':[{'id':'risk','summary':'확인된 차환 실패 공시입니다.','expected':'주식 판단 재료'}]}
        self.mock_screening(engine,data)
        with patch('builtins.print'):report=evaluate_ranking(engine,data)
        self.assertFalse(report['valid'])
        self.assertEqual((report['passed'],report['screened'],report['ordered']),(0,1,0))
        self.assertEqual(report['checks'][0]['actual'],'주식 판단 재료')
        self.assertTrue(report['checks'][0]['eligibility_pass'])
        self.assertFalse(report['checks'][0]['reviewed'])

    def test_ranking_evaluator_rejects_invalid_expected_labels_without_model_calls(self):
        engine=MagicMock()
        self.assertRaises(ValueError,evaluate_ranking,engine,{'equity_screening':[{'id':'bad','summary':'평가용 본문입니다.','expected':'수혜 확정'}]})
        engine.rank.assert_not_called()

    def test_mixed_evaluator_preserves_multiple_source_quotes_and_rejects_invented_evidence(self):
        quotes=['회사는 계약 해지설을 사실무근이라고 공시했다.','고객도 기존 공급 계약이 유지된다고 확인했다.']
        data={'equity_screening':[{'id':'confirmation','summary':' '.join(quotes),'evidence':quotes,'expected':'주식 판단 재료'}]}
        engine=MagicMock(model='test',provider='ollama');engine.usage.return_value={}
        engine.screen.return_value={'stock_relevance':'주식 판단 재료'};engine.rank.return_value=[rank_row('E1')]
        with patch('builtins.print'):result=evaluate_ranking(engine,data)
        self.assertTrue(result['valid'])
        engine.screen.assert_called_once_with({'evidence':quotes})
        self.assertEqual(engine.rank.call_args.args[0][0]['evidence'],quotes)
        data['equity_screening'][0]['evidence']=['기사에 없는 임의의 판단 근거입니다.']
        engine.reset_mock()
        self.assertRaises(ValueError,evaluate_ranking,engine,data)
        engine.screen.assert_not_called();engine.rank.assert_not_called()

    def test_mixed_evaluator_never_orders_excluded_only_inputs(self):
        data={'equity_screening':[{'id':'guide','summary':'실적 변화 없는 정기 상품 안내입니다.','expected':'배경·상품 안내'}]}
        engine=MagicMock(model='test',provider='ollama');engine.usage.return_value={}
        self.mock_screening(engine,data)
        with patch('builtins.print'):result=evaluate_ranking(engine,data)
        self.assertTrue(result['valid'])
        self.assertEqual((result['screened'],result['ordered'],result['passed']),(1,0,1))
        engine.rank.assert_not_called()

    def test_ranking_evaluator_separates_label_agreement_from_eligibility_and_keeps_screen_failures_unknown(self):
        engine=MagicMock(model='test',provider='ollama');engine.usage.return_value={}
        data={'equity_screening':[{'id':'background','summary':'일반 금융교육 일정 안내입니다.','expected':'배경·상품 안내'},
                                  {'id':'risk','summary':'상장사 채무 불이행 공시입니다.','expected':'주식 판단 재료'}]}
        engine.screen.side_effect=[{'stock_relevance':'연결 미확인'},{'stock_relevance':'배경·상품 안내'}]
        with patch('builtins.print'):result=evaluate_ranking(engine,data)
        self.assertEqual((result['passed'],result['eligibility_passed']),(0,1))
        self.assertTrue(result['checks'][0]['eligibility_pass'])
        self.assertFalse(result['checks'][1]['eligibility_pass'])
        engine.rank.assert_not_called()
        engine.screen.side_effect=TimeoutError('screen failed')
        with patch('builtins.print'):missing=evaluate_ranking(engine,data)
        self.assertFalse(missing['valid'])
        self.assertEqual(missing['eligibility_passed'],0)
        self.assertEqual(len(missing['screen_errors']),2)
        self.assertTrue(all(c['actual'] is None and not c['eligibility_pass'] for c in missing['checks']))
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

    def test_equity_evaluation_preserves_real_multi_quote_input_and_legacy_summary_fallback(self):
        dataset=json.loads(Path('tests/fixtures/fund_screening_eval.json').read_text())
        actual=dataset['equity_screening'][0]
        self.assertGreater(len(actual['evidence']),1)
        self.assertGreater(len(actual['summary']),500)
        self.assertTrue(all(8<=len(q)<=500 for q in actual['evidence']))
        legacy={'id':'legacy','summary':'이전 형식의 실제 원문입니다.','expected':'주식 판단 재료'}
        engine=MagicMock(model='test',provider='ollama')
        engine.screen.side_effect=[{'stock_relevance':actual['expected']},{'stock_relevance':legacy['expected']}]
        with patch('builtins.print'):
            result=evaluate_equity(engine,{'equity_screening':[actual,legacy]})
        self.assertEqual(result['passed'],2)
        self.assertEqual(engine.screen.call_args_list[0].args[0]['evidence'],actual['evidence'])
        self.assertEqual(engine.screen.call_args_list[1].args[0]['evidence'],[legacy['summary']])

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

    def test_public_reader_keeps_short_news_and_captions_but_rejects_missing_text(self):
        caption='[인천공항=뉴시스] 전신 기자 = 원·달러 환율이 1330원대 후반에서 횡보하고 있는 가운데 15일 인천국제공항 1터미널 환전소 전광판에 환율이 표시돼 2026.11.15. photo1006@newsis.com'
        for text in ('한빛에너지는 3000억원 공급 계약이 취소됐다고 공시했다.',caption,'짧음'):
            response=MagicMock()
            response.__enter__.return_value=response
            response.headers.get_content_charset.return_value='utf-8'
            response.read.return_value=('<nav>메뉴</nav><article id="dic_area">'+text+'</article><footer>푸터</footer>').encode()
            with patch('intelligence.build_opener') as opener:
                opener.return_value.open.return_value=response
                self.assertEqual(ai.read_article(ARTICLE['url']),text)
            if len(text)>=8:
                self.assertEqual(ai.source_passages(text),[{'id':1,'text':text}])
            else:
                self.assertRaises(ValueError,ai.source_passages,text)
        for html in ('<nav>본문 밖 메뉴</nav>','<article id="dic_area"> <img src="table.png"><script>숨긴 글</script></article>'):
            response.read.return_value=html.encode()
            with patch('intelligence.build_opener') as opener:
                opener.return_value.open.return_value=response
                self.assertRaises(ValueError,ai.read_article,ARTICLE['url'])

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

    def test_invalid_content_and_incomplete_responses_are_counted_separately_from_transport(self):
        responses=[{'done':True,'done_reason':'stop','message':{'content':'{'},'prompt_eval_count':10,'eval_count':2},
                   {'done':True,'done_reason':'length','message':{'content':'{}'},'prompt_eval_count':10,'eval_count':2},[]]
        for payload in responses:
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps(payload).encode()
            with patch('intelligence.urlopen',return_value=response):
                self.assertRaises((ValueError,AttributeError),self.engine.call,'read',{},ai.READ_SCHEMA)
        timing=self.engine.usage()['timings'][0]
        self.assertEqual(timing['failed'],0)
        self.assertEqual(timing['response_checked'],3)
        self.assertEqual(timing['response_failed'],3)
        self.assertEqual(self.engine.usage()['calls_today'],3)
        self.assertEqual(self.engine.usage()['output_tokens'],4)

    def test_response_json_success_is_not_an_analysis_schema_success_and_legacy_is_unknown(self):
        with self.engine.db() as db:
            db.execute('INSERT INTO attempts(day,task,model,status,duration_seconds) VALUES(?,?,?,?,?)',(ai.now()[:10],'read',self.engine.model,'received',1))
        timing=self.engine.usage()['timings'][0]
        self.assertEqual(timing['response_checked'],0)
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'done':True,'done_reason':'stop','message':{'content':'[]'}}).encode()
        with patch('intelligence.urlopen',return_value=response):
            self.assertEqual(self.engine.call('read',{},ai.READ_SCHEMA),[])
        timing=self.engine.usage()['timings'][0]
        self.assertEqual(timing['response_checked'],1)
        self.assertEqual(timing['response_failed'],0)

    def test_cloud_response_failures_keep_reported_tokens_without_retrying(self):
        cases=[{'choices':[]},
               {'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},
               {'choices':[{'finish_reason':'stop','message':{'refusal':'blocked','content':'{}'}}]}]
        for payload in cases:
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps({**payload,'usage':{'prompt_tokens':20,'completion_tokens':5}}).encode()
            with patch.object(self.engine,'provider','gemini'),patch('intelligence.urlopen',return_value=response) as request:
                self.assertRaises((ValueError,IndexError),self.engine.call,'read',{},ai.READ_SCHEMA)
            request.assert_called_once()
        timing=self.engine.usage()['timings'][0]
        self.assertEqual(timing['response_failed'],3)
        self.assertEqual(self.engine.usage()['input_tokens'],60)
        self.assertEqual(self.engine.usage()['output_tokens'],15)

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

    def test_title_mismatch_waits_without_repeated_reads_or_model_calls(self):
        with patch('archive.body_snapshot',return_value={'title':'변경된 새 제목','status':'ok','text':BODY}),patch.object(self.engine,'reading',return_value=None) as read,patch.object(self.engine,'call') as call:
            first=self.engine.cycle([ARTICLE])
            second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['queue']['source_waiting'],1)
        self.assertEqual(second['queue']['source_waiting'],1)
        self.assertEqual(second['queue']['retrying'],0)
        self.assertEqual(read.call_count,1)
        call.assert_not_called()
        with self.engine.queue.db() as db:
            self.assertEqual(db.execute('SELECT attempts FROM analysis_jobs').fetchone()[0],1)

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
        grouped,gates=ai.group_events([a,b],[GATE,GATE])
        self.assertEqual(len(grouped),1);self.assertEqual(len(grouped[0]['articles']),2)
        self.assertEqual(grouped[0]['articles'][1]['evidence'],READING['evidence'])

    def test_event_representative_keeps_its_own_gate_and_original_evidence(self):
        brief={**ANALYZED,'event_id':'e','article_id':'brief','source_url':ARTICLE['url']+'brief',
               'published_at':'2026-11-11T01:00:00Z','summary':'공급 계약 재보도','evidence':['한빛에너지는 공급 계약을 맺었다고 간략히 밝혔다.']}
        detailed={**brief,'article_id':'detailed','source_url':ARTICLE['url']+'detailed','published_at':ARTICLE['published_at'],
                  'summary':'5000억원 공급 계약 체결','evidence':['한빛에너지는 서부전력과 5000억원 공급 계약을 체결했다.']}
        gates=[dict(GATE,event_id='e'),dict(GATE,event_id='e',stock_relevance='연결 미확인',reason='구체 조건 확인 필요')]
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=([detailed,brief],gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1')]) as rank:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['ranking'][0]['event_id'],'e')
        self.assertEqual(result['events'][0]['article_id'],'detailed')
        self.assertEqual(result['assessments'][0]['stock_relevance'],'주식 판단 재료')
        self.assertEqual(rank.call_args.args[0][0]['evidence'],detailed['evidence'])

    def test_future_representative_is_not_ranked_using_an_older_event_origin(self):
        future={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':'2026-11-11T13:00:00Z'}
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=([future],[dict(GATE,event_id='e')])),patch.object(self.engine.queue,'first_published',return_value={'e':ARTICLE['published_at']}),patch('intelligence.market_snapshot') as market,patch.object(self.engine,'rank') as rank:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['events'][0]['recency_status'],'future')
        rank.assert_not_called()
        market.assert_not_called()

    def test_representative_selection_is_order_independent_and_ignores_old_gates(self):
        a={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        b={**a,'article_id':'b','published_at':'2026-11-11T01:00:00Z','summary':'짧은 재보도'}
        qualified=dict(GATE,event_id='e',reason='현재 계약 근거')
        unknown=dict(GATE,event_id='e',stock_relevance='연결 미확인',reason='원문 근거 부족')
        for readings,gates in [([a,b],[qualified,unknown]),([b,a],[unknown,qualified])]:
            grouped,selected=ai.group_events(readings,gates)
            self.assertEqual(grouped[0]['article_id'],'a')
            self.assertEqual(selected[0]['reason'],'현재 계약 근거')
            self.assertEqual({r['id'] for r in grouped[0]['articles']},{'a','b'})
        grouped,selected=ai.group_events([a,b],[unknown,{**qualified,'screen_policy_version':'old'}])
        self.assertEqual(grouped[0]['article_id'],'a')
        self.assertEqual(selected[0]['stock_relevance'],'연결 미확인')
        grouped,selected=ai.group_events([a,{**b,'published_at':'2026-11-11T13:00:00Z'}],[unknown,qualified])
        self.assertEqual(grouped[0]['article_id'],'a')
        self.assertEqual(selected[0]['stock_relevance'],'연결 미확인')

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
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1','확정 공급 계약')]}) as call:
            first=self.engine.cycle([ARTICLE]);second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['status'],'ok');self.assertEqual(len(second['ranking']),1);call.assert_called_once()
        self.engine.rank_key='changed'
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'call',return_value={'ranking':[order_row('invented','허구')]}):
            failed=self.engine.cycle([ARTICLE])
        self.assertFalse(failed['ranking_stale']);self.assertTrue(failed['ranking_partial']);self.assertEqual(failed['status'],'partial')
        self.assertEqual(failed['ranking'],first['ranking'])

    def test_restart_reuses_only_the_same_fresh_rank_inputs_and_generation_time(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1')]):
            first=self.engine.cycle([ARTICLE])
        other=ai.Engine(self.engine.path)
        with patch.object(other,'rank',return_value=[rank_row('E1')]) as rank,patch('intelligence.market_snapshot',return_value={'observations':[]}) as market:
            restored=other.cycle([ARTICLE])
        rank.assert_not_called();market.assert_not_called()
        self.assertEqual(restored['ranking'],first['ranking'])
        self.assertEqual(restored['ranked_at'],first['ranked_at'])
        self.assertEqual(restored['market'],first['market'])

    def seed_saved_rank(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1')]):
            result=self.engine.cycle([ARTICLE])
        return reading,result

    def seed_market_rank(self, rank_delay=0):
        market={'as_of':'2026-11-11T12:00:00+00:00','missing':[],'limitations':'ETF 관측 일부',
                'observations':[{'code':'SPY','name':'S&P500','change_percent':0.5,
                    'traded_at':'2026-11-10T16:00:00-05:00','fetched_at':'2026-11-11T12:00:00+00:00',
                    'market_status':'CLOSE','currency':'USD','source':'공개 시세','delay_label':'지연',
                    'session':'regular','relative_to_spy_pp':0}]}
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        clock=[ai.time.time()]
        def finish(*args):
            clock[0]+=rank_delay
            return [rank_row('E1')]
        with patch('intelligence.time.time',side_effect=lambda:clock[0]),patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value=market),patch.object(self.engine,'rank',side_effect=finish):
            first=self.engine.cycle([ARTICLE])
        return market,first

    def test_market_poll_does_not_rerank_before_five_minutes_since_inference_completed(self):
        market,first=self.seed_market_rank(rank_delay=60)
        changed=copy.deepcopy(market);changed['as_of']='2026-11-11T12:05:01+00:00'
        changed['observations'][0]['fetched_at']=changed['as_of']
        with patch('intelligence.time.time',return_value=self.engine.ranked_at+241),patch('intelligence.market_snapshot',return_value=changed) as fetch,patch.object(self.engine,'rank') as rank:
            result=self.engine.cycle([ARTICLE])
        fetch.assert_called_once();rank.assert_not_called()
        self.assertEqual(result['ranking'],first['ranking'])
        self.assertEqual(result['ranked_at'],first['ranked_at'])
        self.assertEqual(result['market']['as_of'],changed['as_of'])

    def test_market_poll_times_keep_valid_rank_during_refresh_and_retry_after_restart(self):
        market,first=self.seed_market_rank()
        clock=self.engine.ranked_at+301
        changed=copy.deepcopy(market);changed['as_of']='2026-11-11T12:05:00+00:00'
        changed['observations'][0]['fetched_at']=changed['as_of']
        progress=[]
        def fail(*args):
            progress.append(ai.snapshot())
            raise TimeoutError()
        with patch('intelligence.time.time',return_value=clock),patch.object(ai,'STATE',{}):
            other=ai.Engine(self.engine.path)
            with patch('intelligence.market_snapshot',return_value=changed),patch.object(other,'rank',side_effect=fail) as rank:
                result=other.cycle([ARTICLE])
        rank.assert_called_once()
        self.assertEqual(progress[0]['ranking'],first['ranking'])
        self.assertEqual(result['ranking'],first['ranking'])
        self.assertFalse(result['ranking_stale']);self.assertTrue(result['ranking_partial'])
        self.assertEqual(result['ranked_at'],first['ranked_at'])
        self.assertEqual(result['market']['as_of'],changed['as_of'])
        self.assertEqual(result['market']['observations'][0]['fetched_at'],changed['as_of'])
        changed['as_of']='2026-11-11T12:05:10+00:00';changed['observations'][0]['fetched_at']=changed['as_of']
        with patch('intelligence.time.time',return_value=clock+10):
            restarted=ai.Engine(self.engine.path)
            with patch('intelligence.market_snapshot',return_value=changed),patch.object(restarted,'rank') as rank:
                waiting=restarted.cycle([ARTICLE])
        rank.assert_not_called()
        self.assertEqual(waiting['ranking'],first['ranking'])
        self.assertEqual(waiting['rank_retry_at'],result['rank_retry_at'])
        self.assertEqual(waiting['ranked_at'],first['ranked_at'])
        with patch('intelligence.time.time',return_value=clock+301),patch('intelligence.market_snapshot',return_value=changed),patch.object(other,'rank',side_effect=TimeoutError):
            expired=other.cycle([ARTICLE])
        self.assertTrue(expired['ranking_stale'])
        self.assertEqual(expired['ranked_at'],first['ranked_at'])

    def test_actual_market_changes_do_not_keep_previous_rank_on_refresh_failure(self):
        market,first=self.seed_market_rank()
        changes=[('change_percent',-2),('traded_at','2026-11-11T16:00:00-05:00'),
                 ('market_status','OPEN'),('currency','KRW'),('source','다른 제공처'),
                 ('delay_label','실시간'),('session','extended'),('relative_to_spy_pp',1),
                 ('new_observation_field','새 관측')]
        variants=[]
        for field,value in changes:
            changed=copy.deepcopy(market);changed['observations'][0][field]=value;variants.append((field,changed))
        variants.extend([('missing',{**market,'observations':[],'missing':['SPY']}),
                         ('limitations',{**market,'limitations':'환율 관측 추가'}),
                         ('new_context',{**market,'new_context':'새 시장 사실'})])
        for name,changed in variants:
            with self.subTest(field=name),patch('intelligence.time.time',return_value=self.engine.ranked_at+301):
                other=ai.Engine(self.engine.path)
                with patch('intelligence.market_snapshot',return_value=changed),patch.object(other,'rank',side_effect=TimeoutError) as rank:
                    result=other.cycle([ARTICLE])
                rank.assert_called_once()
                self.assertEqual(result['ranking'],[])
                self.assertTrue(result['ranking_stale'])
                self.assertEqual(result['ranked_at'],first['ranked_at'])

    def test_saved_rank_isolated_by_model_and_each_analysis_policy(self):
        self.seed_saved_rank()
        for policy in ('READ_VERSION','SCREEN_VERSION','RANK_VERSION'):
            with patch.object(ai,policy,'changed-policy'):
                other=ai.Engine(self.engine.path)
            self.assertEqual(other.last_ranking,[])
            self.assertIsNone(other.rank_cache_error)
        with patch.dict(os.environ,{'LLM_MODEL':'other-model'}):
            other=ai.Engine(self.engine.path)
        self.assertEqual(other.last_ranking,[])
        with patch.dict(os.environ,{'LLM_PROVIDER':'gemini','LLM_MODEL':self.engine.model,'GEMINI_API_KEY':''}):
            other=ai.Engine(self.engine.path)
        self.assertEqual(other.last_ranking,[])

    def test_previous_market_fingerprint_cache_namespace_is_not_restored_as_current(self):
        self.seed_saved_rank()
        old_namespace=ai.sha256(json.dumps([self.engine.queue.namespace,ai.READ_VERSION,ai.SCREEN_VERSION,ai.RANK_VERSION]).encode()).hexdigest()
        with self.engine.db() as db:
            payload=db.execute('SELECT payload FROM rank_snapshots WHERE namespace=?',(self.engine.rank_namespace,)).fetchone()[0]
            db.execute('DELETE FROM rank_snapshots WHERE namespace=?',(self.engine.rank_namespace,))
            db.execute('INSERT INTO rank_snapshots VALUES(?,?)',(old_namespace,payload))
        other=ai.Engine(self.engine.path)
        self.assertEqual(other.last_ranking,[])
        self.assertIsNone(other.rank_cache_error)

    def test_restored_market_and_rank_still_refresh_after_the_original_five_minutes(self):
        self.seed_saved_rank()
        later=self.engine.ranked_at+301
        with patch('intelligence.time.time',return_value=later):
            other=ai.Engine(self.engine.path)
            with patch('intelligence.market_snapshot',return_value={'observations':[]}) as market,patch.object(other,'rank',return_value=[rank_row('E1')]) as rank:
                result=other.cycle([ARTICLE])
        market.assert_called_once();rank.assert_called_once()
        self.assertEqual(result['market']['fetched_epoch'],later)
        self.assertEqual(other.ranked_at,later)

    def test_expired_future_or_damaged_rank_cache_cannot_block_readings_or_restore_rank(self):
        self.seed_saved_rank()
        with self.engine.db() as db:
            saved=json.loads(db.execute('SELECT payload FROM rank_snapshots WHERE namespace=?',(self.engine.rank_namespace,)).fetchone()[0])
        variants=[('expired',{**saved,'ranked_at':ai.time.time()-601}),
                  ('future',{**saved,'ranked_at':ai.time.time()+60}),
                  ('bad-source',{**saved,'sources':{'e':'bad'}}),
                  ('bad-schema',{**saved,'ranking':[{'event_id':'e'}]}),
                  ('future-market',{**saved,'market':{**saved['market'],'fetched_epoch':ai.time.time()+60}}),
                  ('broken-json',None)]
        for name,payload in variants:
            with self.subTest(name=name),self.engine.db() as db:
                db.execute('UPDATE rank_snapshots SET payload=? WHERE namespace=?',('{' if payload is None else json.dumps(payload),self.engine.rank_namespace))
            other=ai.Engine(self.engine.path)
            self.assertEqual(other.last_ranking,[])
            self.assertEqual(other.queue.summary()['done'],1)
            if name!='expired':
                self.assertIn('복구 실패',other.rank_cache_error)

    def test_changed_evidence_after_restart_cannot_reuse_previous_reasons_on_failure(self):
        reading,first=self.seed_saved_rank()
        other=ai.Engine(self.engine.path)
        changed={**ARTICLE,'title':'계약 변경 공시'}
        new={**reading,'article_title':changed['title'],'summary':'새 계약 조건','evidence':['한빛에너지는 공급 조건이 변경됐다고 공시했다.']}
        with patch.object(other,'reading',return_value=new),patch.object(other,'screen',return_value=GATE),patch.object(other,'rank',side_effect=TimeoutError):
            result=other.cycle([changed])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['events'][0]['summary'],'새 계약 조건')
        self.assertEqual(result['ranked_at'],first['ranked_at'])

    def test_cached_reclassification_is_rejected_before_it_can_override_a_source_screen(self):
        self.seed_saved_rank()
        with self.engine.db() as db:
            saved=json.loads(db.execute('SELECT payload FROM rank_snapshots WHERE namespace=?',(self.engine.rank_namespace,)).fetchone()[0])
            saved['ranking'][0]['stock_relevance']='배경·상품 안내'
            db.execute('UPDATE rank_snapshots SET payload=? WHERE namespace=?',(json.dumps(saved),self.engine.rank_namespace))
        other=ai.Engine(self.engine.path)
        self.assertEqual(other.last_ranking,[])
        self.assertIn('복구 실패',other.rank_cache_error)
        with patch.object(other,'rank',return_value=[rank_row('E1')]) as rank,patch('intelligence.market_snapshot',return_value={'observations':[]}):
            result=other.cycle([ARTICLE])
        rank.assert_called_once()
        self.assertEqual(len(result['ranking']),1)
        self.assertEqual(result['assessments'][0]['stock_relevance'],'주식 판단 재료')

    def test_failed_unchanged_rank_waits_while_background_readings_keep_progressing(self):
        reading,saved=self.seed_saved_rank()
        articles=[ARTICLE,*[{**ARTICLE,'id':i,'url':ARTICLE['url']+i} for i in ('b','c')]]
        clock=self.engine.ranked_at+301
        def background(article,anchors):
            return {**reading,'article_id':article['id'],'event_id':'background-'+article['id'],'source_url':article['url']}
        with patch('intelligence.time.time',return_value=clock),patch.object(self.engine,'reading',side_effect=background),patch.object(self.engine,'screen',return_value={**GATE,'stock_relevance':'배경·상품 안내'}),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',side_effect=TimeoutError) as rank:
            first=self.engine.cycle(articles)
            second=self.engine.cycle(articles)
        self.assertEqual(rank.call_count,1)
        self.assertEqual(second['queue']['done'],3)
        self.assertTrue(second['ranking_partial'])
        self.assertEqual(second['status'],'partial')
        self.assertEqual(second['ranking'],saved['ranking'])
        self.assertEqual(second['ranked_at'],saved['ranked_at'])
        self.assertFalse(second['ranking_stale'])
        self.assertIsNotNone(first['rank_retry_at'])
        self.assertEqual(second['rank_retry_at'],first['rank_retry_at'])

    def test_rank_response_validation_failure_retries_at_deadline_and_keeps_only_valid_results(self):
        _,first=self.seed_saved_rank()
        self.engine.rank_key='force-refresh'
        clock=ai.time.time()
        with patch('intelligence.time.time',return_value=clock),patch.object(self.engine,'call',return_value={'ranking':[order_row('unknown')]}) as call:
            failed=self.engine.cycle([ARTICLE])
            waiting=self.engine.cycle([ARTICLE])
        call.assert_called_once()
        self.assertEqual(waiting['ranking'],first['ranking'])
        self.assertEqual(waiting['ranked_at'],first['ranked_at'])
        self.assertFalse(waiting['ranking_stale'])
        with patch('intelligence.time.time',return_value=clock+59),patch.object(self.engine,'rank') as rank:
            self.engine.cycle([ARTICLE])
        rank.assert_not_called()
        with patch('intelligence.time.time',return_value=clock+60),patch.object(self.engine,'rank',return_value=[rank_row('E1','재검토한 원문 사실')]) as rank:
            recovered=self.engine.cycle([ARTICLE])
        rank.assert_called_once()
        self.assertIsNone(recovered['rank_retry_at'])
        self.assertFalse(recovered['ranking_partial'])
        self.assertEqual(recovered['ranking'][0]['reason'],READING['evidence'][0])
        self.assertNotEqual(failed['ranked_at'],recovered['ranked_at'])
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM failures WHERE cache_key LIKE 'rank:%'").fetchone()[0],0)

    def test_new_source_and_market_inputs_bypass_failed_rank_wait_without_old_reasons(self):
        reading,_=self.seed_saved_rank()
        self.engine.rank_key='force-refresh'
        changed={**ARTICLE,'title':'계약 취소 공시'}
        new={**reading,'article_title':changed['title'],'summary':'계약 취소','evidence':['한빛에너지는 기존 공급 계약을 취소했다고 공시했다.']}
        with patch.object(self.engine,'rank',side_effect=TimeoutError) as rank:
            self.engine.cycle([ARTICLE])
            with patch.object(self.engine,'reading',return_value=new),patch.object(self.engine,'screen',return_value=GATE):
                updated=self.engine.cycle([changed])
            self.engine.last_market={**self.engine.last_market,'observations':[{'code':'SPY','change_percent':-2}]}
            market_updated=self.engine.cycle([changed])
        self.assertEqual(rank.call_count,3)
        self.assertEqual(updated['ranking'],[])
        self.assertEqual(updated['events'][0]['summary'],'계약 취소')
        self.assertEqual(market_updated['ranking'],[])

    def test_failed_rank_wait_is_not_shared_with_another_model_or_provider(self):
        reading,_=self.seed_saved_rank()
        self.engine.rank_key='force-refresh'
        with patch.object(self.engine,'rank',side_effect=TimeoutError):
            self.engine.cycle([ARTICLE])
        for provider,model in [('ollama','another-model'),('gemini',self.engine.model)]:
            with patch.dict(os.environ,{'LLM_PROVIDER':provider,'LLM_MODEL':model,'GEMINI_API_KEY':'test-only'}):
                other=ai.Engine(self.engine.path)
            other.last_market=copy.deepcopy(self.engine.last_market)
            with patch.object(other,'reading',return_value=reading),patch.object(other,'screen',return_value=GATE),patch.object(other,'rank',return_value=[rank_row('E1')]) as rank:
                result=other.cycle([ARTICLE])
            rank.assert_called_once()
            self.assertIsNone(result['rank_retry_at'])

    def test_rank_cache_write_failure_keeps_current_valid_result_and_empty_inputs_clear_cache(self):
        reading,first=self.seed_saved_rank()
        with patch.object(self.engine,'db',side_effect=sqlite3.OperationalError('busy')):
            self.engine.save_rank()
        self.assertEqual(self.engine.last_ranking,first['ranking'])
        self.assertIn('저장 실패',self.engine.rank_cache_error)
        with patch.object(self.engine.queue,'readings',return_value=([reading],[dict(GATE,event_id='e',stock_relevance='배경·상품 안내')])):
            self.engine.cycle([ARTICLE])
        self.assertEqual(ai.Engine(self.engine.path).last_ranking,[])

    def test_finished_article_is_published_before_waiting_for_the_next_article(self):
        articles=[ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}]
        reading={**ANALYZED,'event_id':'event-a','article_id':ARTICLE['id'],'source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',side_effect=[reading,AssertionError('두 번째 기사 추론 대기')]) as read,patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1','확인한 계약')]}):
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
            self.assertEqual(set(rule['items']['enum']),set(ids))
            return {'ranking':[order_row(i) for i in reversed(ids)]}
        with patch.object(self.engine,'screen',return_value=GATE),patch.object(self.engine,'reading',side_effect=lambda a,anchors: next(r for r in readings if r['article_id']==a['id'])),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',side_effect=provider):
            for _ in articles:
                result=self.engine.cycle(articles)
        self.assertFalse(result['ranking_stale'])
        self.assertEqual([r['event_id'] for r in result['ranking']],['event-'+str(i) for i in reversed(range(9))])

    def test_ranking_uses_original_evidence_instead_of_generated_financial_claims(self):
        reading={**ANALYZED,'summary':'순이익 9999억원 증가 확정','event_title':'허구의 이익 증가',
                 'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}) as call:
            self.engine.cycle([ARTICLE])
        event=call.call_args.args[1]['events'][0]
        self.assertNotIn('summary',event)
        self.assertNotIn('event_title',event)
        self.assertNotIn('amount',event)
        self.assertEqual(event['evidence'],READING['evidence'])
        self.assertEqual(event['first_published_at'],ARTICLE['published_at'])

    def test_rank_cache_ignores_history_changes_but_tracks_sources_and_market(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine.queue,'history',side_effect=[[],[{'summary':'이력 추가'}]]),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}) as call:
            self.engine.cycle([ARTICLE]);self.engine.cycle([ARTICLE])
        self.assertEqual(call.call_count,1)
        changed={**reading,'evidence':['공급 계약 금액을 4000억원으로 정정했다.']}
        with patch.object(self.engine.queue,'readings',return_value=([changed],[dict(GATE,event_id='e')])),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}) as call:
            self.engine.cycle([ARTICLE])
            self.engine.last_market={**self.engine.last_market,'observations':[{'code':'SPY','change_percent':-2}]}
            self.engine.cycle([ARTICLE])
        self.assertEqual(call.call_count,2)

    def test_rank_cache_survives_candidate_reordering_and_restart_without_remapping_results(self):
        articles=[ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}]
        readings=[{**ANALYZED,'event_id':a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at'],'evidence':['첫 번째 사건의 계약 조건을 공시했다.' if a['id']=='a' else '두 번째 사건의 계약 조건을 공시했다.']} for a in articles]
        gates=[dict(GATE,event_id=a['id']) for a in articles]
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E2','두 번째 사건'),rank_row('E1','첫 번째 사건')]) as rank:
            first=self.engine.cycle(articles)
            readings.reverse();gates.reverse()
            second=self.engine.cycle(list(reversed(articles)))
            rank.assert_called_once()
        self.engine.last_ranking[0]['reason']='다른 사건의 신용융자 내용'
        self.engine.last_ranking[0]['watch_for']='다른 사건의 확인 사항'
        self.engine.save_rank()
        other=ai.Engine(self.engine.path)
        with patch.object(other.queue,'claim',return_value=None),patch.object(other.queue,'readings',return_value=(readings,gates)),patch.object(other,'rank') as rank:
            restored=other.cycle(list(reversed(articles)))
            rank.assert_not_called()
        for result in (second,restored):
            self.assertEqual(result['ranking'],first['ranking'])
            self.assertEqual(result['ranked_at'],first['ranked_at'])
            self.assertFalse(result['ranking_partial'])
            self.assertEqual(result['assessments'][0]['screen_reason'],GATE['reason'])
            self.assertEqual(result['rank_reason_source'],'article_evidence')
            self.assertTrue(all(r['watch_for']==GATE['watch_for'] for r in result['ranking']))
            self.assertEqual([(r['event_id'],r['reason']) for r in result['ranking']],[('b','두 번째 사건의 계약 조건을 공시했다.'),('a','첫 번째 사건의 계약 조건을 공시했다.')])
        readings[0]={**readings[0],'event_id':'new-event'};gates[0]={**gates[0],'event_id':'new-event'}
        with patch.object(other.queue,'claim',return_value=None),patch.object(other.queue,'readings',return_value=(readings,gates)),patch.object(other,'rank',return_value=[rank_row('E1'),rank_row('E2')]) as rank:
            changed=other.cycle(articles)
            rank.assert_called_once()
        self.assertEqual({r['event_id'] for r in changed['ranking']},{'a','new-event'})

    def test_candidate_reordering_cannot_bypass_same_input_failure_backoff(self):
        articles=[ARTICLE,{**ARTICLE,'id':'b','url':ARTICLE['url']+'b'}]
        readings=[{**ANALYZED,'event_id':a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at']} for a in articles]
        gates=[dict(GATE,event_id=a['id']) for a in articles]
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',side_effect=TimeoutError) as rank:
            failed=self.engine.cycle(articles)
            readings.reverse();gates.reverse()
            waiting=self.engine.cycle(list(reversed(articles)))
            rank.assert_called_once()
            self.assertEqual(waiting['rank_retry_at'],failed['rank_retry_at'])
            self.assertEqual(waiting['status'],'partial')
            readings[0]={**readings[0],'evidence':['계약 금액과 공급 조건을 정정했다고 공시했다.']}
            self.engine.cycle(articles)
            self.assertEqual(rank.call_count,2)

    def test_failed_reranking_cannot_reuse_reasons_from_different_evidence_or_market(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}):
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
        with patch.object(ai,'STATE',{}),patch.object(self.engine,'reading',return_value=old),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1','이전 계약 근거')]}):
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

    def test_ordering_reclassification_is_rejected_without_overwriting_the_source_screen(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        rejected={**rank_row('E1'),'stock_relevance':'배경·상품 안내','reason':'주식 실적 변화 없는 상품 조건 안내'}
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[rejected]}) as call:
            first=self.engine.cycle([ARTICLE]);second=self.engine.cycle([ARTICLE])
        self.assertEqual(first['ranking'],[])
        self.assertEqual(first['assessments'][0]['stock_relevance'],'주식 판단 재료')
        self.assertTrue(first['ranking_stale'])
        self.assertTrue(first['ranking_partial'])
        self.assertEqual(second['ranking'],[])
        call.assert_called_once()

    def test_candidate_limit_cannot_be_reported_as_complete_after_independent_screening(self):
        articles=[{**ARTICLE,'id':str(i),'url':ARTICLE['url']+str(i)} for i in range(16)]
        readings=[{**ANALYZED,'event_id':a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at']} for a in articles]
        gates=[dict(GATE,event_id=a['id']) for a in articles]
        gates[13]['stock_relevance']='배경·상품 안내'
        readings[14]['published_at']='2026-11-09T00:00:00Z'
        readings[15]['published_at']='2026-11-12T00:00:00Z'
        rows=[rank_row('E'+str(i)) for i in range(1,13)]
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=rows) as rank:
            first=self.engine.cycle(articles)
            second=self.engine.cycle(articles)
        rank.assert_called_once()
        self.assertEqual(len(rank.call_args.args[0]),12)
        for result in (first,second):
            self.assertTrue(result['ranking_partial'])
            self.assertEqual(result['status'],'partial')
            self.assertFalse(result['ranking_stale'])
            self.assertEqual(result['coverage']['eligible_events'],13)
            self.assertEqual(result['coverage']['reviewed_events'],12)
            self.assertEqual(result['coverage']['unreviewed_events'],1)
            self.assertEqual(len(result['ranking']),12)

    def priority_candidates(self):
        articles=[{**ARTICLE,'id':str(i),'url':ARTICLE['url']+str(i)} for i in range(14)]
        readings=[{**ANALYZED,'event_id':a['id'],'article_id':a['id'],'source_url':a['url'],'published_at':a['published_at'],
                   'evidence':[f'서로 다른 사건 {i}의 공시 원문 근거입니다.']} for i,a in enumerate(articles)]
        gates=[dict(GATE,event_id=a['id'],priority=10) for a in articles]
        gates[-2].update(stock_relevance='배경·상품 안내',priority=100)
        return articles,readings,gates

    def test_priority_shortlist_reaches_tail_events_without_promoting_background_scores(self):
        articles,readings,gates=self.priority_candidates();gates[-1]['priority']=100
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E'+str(i)) for i in range(1,13)]) as rank:
            result=self.engine.cycle(articles)
        evidence=[e['evidence'] for e in rank.call_args.args[0]]
        self.assertEqual(evidence[0],readings[-1]['evidence'])
        self.assertNotIn(readings[-2]['evidence'],evidence)
        self.assertEqual(evidence[1:],[r['evidence'] for r in readings[:11]])
        self.assertEqual(result['candidate_selection'],'pointwise_priority')
        self.assertEqual(result['coverage']['priority_scored_events'],13)
        self.assertEqual(result['coverage']['priority_pending_events'],0)
        self.assertEqual(result['coverage']['reviewed_events'],12)
        self.assertEqual(result['coverage']['unreviewed_events'],1)

    def test_missing_priority_never_becomes_zero_or_displaces_unscored_events(self):
        articles,readings,gates=self.priority_candidates()
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=(readings,gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E'+str(i)) for i in range(1,13)]) as rank:
            gates[0].update(screen_policy_version='source-passages-v3-examples',priority=100)
            legacy=self.engine.cycle(articles)
            self.assertEqual(legacy['coverage']['screen_pending_events'],1)
            self.assertEqual(legacy['coverage']['priority_pending_events'],0)
            self.assertEqual(legacy['candidate_selection'],'pointwise_priority')
            gates[0]['screen_policy_version']=ai.SCREEN_VERSION
            for value in (None,True,101,-1,'90'):
                gates[0]['priority']=value
                result=self.engine.cycle(articles)
                self.assertEqual(result['candidate_selection'],'input_order_pending_priority')
                self.assertEqual(result['coverage']['priority_pending_events'],1)
                self.assertEqual([e['evidence'] for e in rank.call_args.args[0]],[r['evidence'] for r in readings[:12]])
            gates[0]['priority']=0
            result=self.engine.cycle(articles)
            self.assertEqual(result['candidate_selection'],'pointwise_priority')
            self.assertEqual(result['coverage']['priority_pending_events'],0)

    @patch.object(ai,'SCREEN_VERSION','source-passages-v4-pointwise-priority')
    def test_priority_backfill_keeps_compatible_legacy_selection_and_original_reading(self):
        reading={**ANALYZED,'event_id':'e','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at'],'analyzed_at':ai.now()}
        legacy={**GATE,'screen_policy_version':'source-passages-v3-examples','assessed_at':'old-assessment'}
        legacy.pop('priority',None)
        with patch.object(self.engine,'reading',return_value=reading),patch.object(self.engine,'screen',return_value=legacy),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'rank',return_value=[rank_row('E1')]):
            first=self.engine.cycle([ARTICLE])
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine,'rank') as rank:
            pending=self.engine.cycle([ARTICLE])
        rank.assert_not_called()
        self.assertEqual(pending['ranking'],first['ranking'])
        self.assertEqual(pending['coverage']['analyzed_articles'],1)
        self.assertEqual(pending['coverage']['priority_pending_events'],1)
        with patch.object(self.engine,'reading',side_effect=AssertionError('priority backfill must reuse the existing source reading')),patch.object(self.engine,'screen',return_value={**GATE,'screen_policy_version':ai.SCREEN_VERSION,'priority':75}),patch.object(self.engine,'rank') as rank:
            finished=self.engine.cycle([ARTICLE])
        rank.assert_not_called()
        self.assertEqual(finished['ranking'],first['ranking'])
        self.assertEqual(finished['events'][0]['analyzed_at'],reading['analyzed_at'])
        self.assertEqual(finished['coverage']['priority_pending_events'],0)
        self.assertEqual(finished['candidate_selection'],'pointwise_priority')
        with patch.object(ai,'SCREEN_VERSION','future-eligibility-change'):
            self.assertEqual(ai.screen_policies(),('future-eligibility-change',))

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
            self.assertEqual(observed[0]['coverage']['reviewed_events'],1)
            self.assertEqual(observed[0]['coverage']['unreviewed_events'],1)
            self.assertEqual({r['event_id'] for r in final['ranking']},{'a','b'})
            self.assertEqual(final['coverage']['reviewed_events'],2)
            self.assertEqual(final['coverage']['unreviewed_events'],0)

    def test_product_announcements_are_assessed_but_not_stock_recommendations(self):
        reading={**copy.deepcopy(ANALYZED),'event_id':'bond','article_id':'a','source_url':ARTICLE['url'],'published_at':ARTICLE['published_at']}
        row={'event_id':'E1','reason':'국채 상품 안내이며 상장사의 실적 변화 근거 없음','stock_relevance':'배경·상품 안내','watch_for':'발행 조건 변경보다 주식 실적 영향 근거가 필요'}
        with patch.object(self.engine,'screen',return_value={**GATE,'driver':'금융상품 조건·청약·판매 안내','stock_relevance':'배경·상품 안내'}),patch.object(self.engine,'reading',return_value=reading),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call') as call:
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['status'],'ok')
        self.assertFalse(result['ranking_stale'])
        self.assertEqual(result['ranking'],[])
        self.assertEqual(result['assessments'][0]['stock_relevance'],'배경·상품 안내')
        self.assertEqual(result['coverage']['eligible_events'],0)
        self.assertEqual(result['coverage']['reviewed_events'],0)
        self.assertEqual(result['coverage']['unreviewed_events'],0)
        call.assert_not_called()

    def test_previous_policy_is_not_ranked_while_review_fails(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':ai.READ_VERSION}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old-policy'})
        with patch.object(self.engine,'reading',return_value=old),patch.object(self.engine,'screen',side_effect=ValueError('temporary failure')),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}) as call,patch('intelligence.market_snapshot',return_value={'observations':[]}):
            result=self.engine.cycle([ARTICLE])
        self.assertEqual(result['ranking'],[])
        call.assert_not_called()
        self.assertEqual(self.engine.queue.summary()['done'],1)

    def test_reading_policy_alone_triggers_review_and_blocks_old_facts(self):
        old={**ANALYZED,'event_id':'old','article_id':'a','source_url':ARTICLE['url'],
             'published_at':ARTICLE['published_at'],'read_policy_version':'old-reader'}
        self.engine.queue.enqueue([{'article':ARTICLE}])
        self.engine.queue.complete(self.engine.queue.claim(),old,GATE)
        with patch.object(self.engine,'reading',side_effect=ValueError('temporary failure')) as read,patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}) as call,patch('intelligence.market_snapshot',return_value={'observations':[]}):
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
        with patch.object(self.engine.queue,'claim',return_value=None),patch.object(self.engine.queue,'readings',return_value=([current,old],gates)),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(self.engine,'call',return_value={'ranking':[order_row('E1')]}):
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

    def test_legacy_review_uses_pinned_body_even_after_latest_headline_changes(self):
        old_article={**ARTICLE,'source_id':'finance','title':'[속보] 공급 계약 발표'}
        policy='source-passages-v7-source-time'
        key=self.engine.reading_key(old_article,BODY,policy)
        old={**copy.deepcopy(ANALYZED),'read_policy_version':policy,'article_id':old_article['id'],
             'article_title':old_article['title'],'source_url':old_article['url'],'published_at':old_article['published_at'],
             'event_id':'event-'+key[:20],'body_version':ai.sha256(BODY.encode()).hexdigest(),'body_chars':len(BODY),
             'model':self.engine.model,'analyzed_at':'2026-11-11T01:00:00Z','source_version_at':'2026-11-11T00:30:00Z'}
        self.engine.queue.enqueue([{'article':old_article}]);self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old'})
        with self.engine.db() as db:db.execute('INSERT INTO readings VALUES(?,?,?,?)',(key,old_article['id'],json.dumps(old),ai.now()))
        with patch('archive.PATH',Path(self.temp.name)/'archive.sqlite3'):
            ai.archive.store([old_article]);ai.archive.save_body(old_article['url'],BODY)
            ai.archive.store([{**old_article,'title':'공급 계약 발표'}])
            self.assertIsNone(self.engine.reading(old_article,[]))
            with patch.object(self.engine,'call') as call,patch.object(self.engine,'screen',return_value={**GATE,'stock_relevance':'배경·상품 안내'}):
                result=self.engine.cycle([old_article])
        call.assert_not_called()
        self.assertEqual(result['coverage']['screen_pending_events'],0)
        self.assertEqual(result['events'][0]['read_policy_version'],ai.READ_VERSION)
        self.assertEqual(result['events'][0]['analyzed_at'],old['analyzed_at'])
        self.assertEqual(result['events'][0]['source_version_at'],old['source_version_at'])
        self.assertEqual(self.engine.queue.summary()['done'],2)

    def test_review_cannot_recover_a_body_for_mismatched_metadata_or_future_source(self):
        for i,change in enumerate(({'source_url':'https://example.com/other'}, {'source_version_at':'2026-11-12T00:00:00Z'})):
            with self.subTest(change=change):
                a={**ARTICLE,'id':'bound-'+str(i),'url':ARTICLE['url']+str(i)}
                old={**ANALYZED,'read_policy_version':'old','event_id':'old-'+str(i),'article_id':a['id'],
                     'article_title':a['title'],'source_url':a['url'],'published_at':a['published_at'],
                     'body_version':ai.sha256(BODY.encode()).hexdigest(),'source_version_at':'2026-11-11T00:30:00Z',**change}
                self.engine.queue.enqueue([{'article':a}]);self.engine.queue.complete(self.engine.queue.claim(),old,{**GATE,'screen_policy_version':'old'})
                with patch.object(ai.archive,'analysis_body') as source,patch.object(self.engine,'reading',return_value=None):
                    self.engine.cycle([a])
                source.assert_not_called()

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
        base={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[0],'impact_evidence':0,'reason':'일반 투자심리 개선 가능','watch_for':'실적 확인'}
        with patch.object(self.engine,'call',return_value=base):
            result=self.engine.screen(READING)
        self.assertEqual(result['stock_relevance'],'연결 미확인')
        with self.engine.db() as db:db.execute('DELETE FROM screens')
        with patch.object(self.engine,'call',return_value={**base,'impact_evidence':'원문에 없는 계약 규모 100조원 발표'}):
            with self.assertRaisesRegex(ValueError,'원문 인용'):
                self.engine.screen({**READING,'summary':'다른 사건'})
        with patch.object(self.engine,'call',return_value={**base,'impact_evidence':1}):
            result=self.engine.screen({**READING,'summary':'확인한 계약'})
        self.assertEqual(result['stock_relevance'],'주식 판단 재료')
        self.assertEqual(result['impact_evidence'],READING['evidence'][0])

    def test_screen_basis_keeps_information_updates_and_blocks_opinion_with_a_positive_driver(self):
        bases=['실적·영업·자본·수급의 관측 변화','권한 있는 주체의 구체적 조치·제안','공식 확인·정정·근거 있는 추정 변경',
               '의견·청원·지지 표현','배경·일반 안내','근거 부족']
        for index,basis in enumerate(bases):
            with self.engine.db() as db:db.execute('DELETE FROM screens')
            output={'change_basis':basis,'priority':80,'driver':ai.DRIVERS[0],'impact_evidence':1,'reason':'모델의 해석','watch_for':'추가 확인'}
            with patch.object(self.engine,'call',return_value=output) as call:
                result=self.engine.screen(READING)
            self.assertEqual(next(iter(call.call_args.args[2]['properties'])),'change_basis')
            self.assertEqual(result['stock_relevance'],'주식 판단 재료' if index<3 else '연결 미확인')
            self.assertEqual(result['impact_evidence'],READING['evidence'][0])
            if index>=3:
                self.assertEqual(result['model_driver'],output['driver'])
                self.assertEqual(result['model_reason'],output['reason'])

    def test_screen_basis_validation_and_cache_cannot_bypass_the_eligibility_guard(self):
        good={'change_basis':ai.CHANGE_BASES[2],'priority':75,'driver':ai.DRIVERS[0],'impact_evidence':1,'reason':'공식 확인','watch_for':'추가 공시'}
        for value in (None,True,5,[],{},'다른 성격'):
            with patch.object(self.engine,'call',return_value={**good,'change_basis':value}):
                self.assertRaisesRegex(ValueError,'정보 성격',self.engine.screen,READING)
        with patch.object(self.engine,'call',return_value={k:v for k,v in good.items() if k!='change_basis'}):
            self.assertRaises(ValueError,self.engine.screen,READING)
        with patch.object(self.engine,'call',return_value=good):
            saved=self.engine.screen(READING)
        bad=[{k:v for k,v in saved.items() if k!='change_basis'},
             {**saved,'change_basis':'알 수 없음'},
             {**saved,'change_basis':ai.CHANGE_BASES[3],'stock_relevance':'주식 판단 재료'}]
        for value in bad:
            with self.engine.db() as db:db.execute('UPDATE screens SET payload=?',(json.dumps(value),))
            with patch.object(self.engine,'call',return_value=good) as call:
                self.assertEqual(self.engine.screen(READING)['stock_relevance'],'주식 판단 재료')
            call.assert_called_once()

    def test_product_policy_rechecks_old_positive_gate_without_reading_or_changing_source_facts(self):
        reading={**ANALYZED,'event_id':'product','article_id':ARTICLE['id'],'article_title':ARTICLE['title'],
                 'source_url':ARTICLE['url'],'published_at':ARTICLE['published_at'],'analyzed_at':'2026-11-11T01:00:00Z'}
        old={**GATE,'priority':75,'screen_policy_version':'source-passages-v5-information-basis'}
        self.engine.queue.enqueue([{'article':ARTICLE}]);original=self.engine.queue.claim()
        self.engine.queue.complete(original,reading,old)
        with patch.object(self.engine.queue,'claim',return_value=None):
            pending=self.engine.cycle([ARTICLE])
        self.assertEqual(pending['coverage']['screen_pending_events'],1)
        self.assertEqual(pending['assessments'],[])
        self.assertEqual(pending['events'][0]['analyzed_at'],reading['analyzed_at'])
        excluded={**GATE,'driver':ai.DRIVERS[4],'change_basis':ai.CHANGE_BASES[4],'impact_evidence':'',
                  'stock_relevance':'배경·상품 안내','priority':5}
        with patch.object(self.engine,'reading',side_effect=AssertionError('reuse original source facts')),patch.object(self.engine,'screen',return_value=excluded),patch.object(self.engine,'rank') as rank:
            done=self.engine.cycle([ARTICLE])
        rank.assert_not_called()
        self.assertEqual(done['ranking'],[])
        self.assertEqual(done['assessments'][0]['stock_relevance'],'배경·상품 안내')
        self.assertEqual(done['events'][0]['analyzed_at'],reading['analyzed_at'])
        with self.engine.queue.db() as db:
            saved=db.execute('SELECT result,assessment FROM analysis_jobs WHERE id=?',(original['id'],)).fetchone()
            self.assertEqual(json.loads(saved['result'])['analyzed_at'],reading['analyzed_at'])
            self.assertEqual(json.loads(saved['assessment']),old)

    def test_information_policy_review_preserves_source_facts_without_approving_old_screens(self):
        self.assertEqual(ai.screen_policies(),(ai.SCREEN_VERSION,))
        for index,label in enumerate(('주식 판단 재료','연결 미확인','배경·상품 안내')):
            engine=ai.Engine(Path(self.temp.name)/f'information-review-{index}.sqlite3')
            reading={**ANALYZED,'event_id':'e','article_id':ARTICLE['id'],'source_url':ARTICLE['url'],
                     'published_at':ARTICLE['published_at'],'analyzed_at':'2026-11-11T01:00:00Z'}
            old={**GATE,'screen_policy_version':'source-passages-v4-pointwise-priority','stock_relevance':label}
            old.pop('change_basis',None)
            engine.queue.enqueue([{'article':ARTICLE}]);engine.queue.complete(engine.queue.claim(),reading,old)
            with patch.object(engine.queue,'claim',return_value=None),patch.object(engine,'rank') as rank:
                pending=engine.cycle([ARTICLE])
            rank.assert_not_called()
            self.assertEqual(pending['coverage']['analyzed_articles'],1)
            self.assertEqual(pending['coverage']['screened_events'],0)
            self.assertEqual(pending['coverage']['screen_pending_events'],1)
            self.assertEqual(pending['events'][0]['analyzed_at'],reading['analyzed_at'])
            self.assertEqual(pending['assessments'],[])
            self.assertEqual(pending['ranking'],[])
            self.assertEqual(engine.queue.summary()['pending'],1)
            with patch.object(engine,'reading',side_effect=AssertionError('source facts must be reused')),patch.object(engine,'screen',return_value=GATE),patch('intelligence.market_snapshot',return_value={'observations':[]}),patch.object(engine,'rank',return_value=[rank_row('E1')]):
                done=engine.cycle([ARTICLE])
            self.assertEqual(done['coverage']['screened_events'],1)
            self.assertEqual(done['coverage']['screen_pending_events'],0)
            self.assertEqual(done['events'][0]['analyzed_at'],reading['analyzed_at'])
            self.assertEqual(done['assessments'][0]['screen_policy_version'],ai.SCREEN_VERSION)
            self.assertEqual(len(done['ranking']),1)

    def test_screen_selects_exact_passages_and_rejects_invalid_ids(self):
        quotes=['실제 공급 계약을 체결했고 조건을 공시했다. '*20,'고객 주문 취소로 공장 가동을 중단했다.']
        event={**READING,'evidence':quotes}
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[0],'impact_evidence':len(ai.source_passages(quotes[0]))+1,'reason':'주문 취소로 공급 중단','watch_for':'정정 공시'}
        with patch.object(self.engine,'call',return_value=output) as call:
            result=self.engine.screen(event)
        self.assertEqual(result['impact_evidence'],quotes[1])
        payload=call.call_args.args[1]
        self.assertNotIn('event',payload)
        self.assertNotIn(READING['summary'],json.dumps(payload,ensure_ascii=False))
        self.assertEqual(''.join(p['text'] for p in payload['source_passages']),''.join(quotes))
        self.assertEqual(call.call_args.args[2]['properties']['impact_evidence']['enum'],list(range(output['impact_evidence']+1)))
        with self.engine.db() as db:db.execute('DELETE FROM screens')
        for value in (-1,999,True,'1',None):
            with patch.object(self.engine,'call',return_value={**output,'impact_evidence':value}):
                self.assertRaisesRegex(ValueError,'원문 인용',self.engine.screen,{**event,'summary':str(value)})

    def test_background_screen_can_abstain_without_inventing_a_followup(self):
        result={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[-1],'impact_evidence':0,'reason':'원문에 경제적 변화 근거 없음','watch_for':''}
        with patch.object(self.engine,'call',return_value=result):
            answer=self.engine.screen(READING)
        self.assertEqual(answer['stock_relevance'],'연결 미확인')
        self.assertEqual(answer['watch_for'],'')

    def test_screen_priority_rejects_missing_boolean_fractional_and_out_of_range_values(self):
        base={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[0],'impact_evidence':1,'reason':'계약 변경 확인','watch_for':'공시 확인'}
        with patch.object(self.engine,'call',return_value={k:v for k,v in base.items() if k!='priority'}):
            self.assertRaises(ValueError,self.engine.screen,READING)
        for value in (None,True,'50',50.5,-1,101):
            with patch.object(self.engine,'call',return_value={**base,'priority':value}):
                self.assertRaisesRegex(ValueError,'중요도',self.engine.screen,READING)
        for value in (0,100):
            with self.engine.db() as db:db.execute('DELETE FROM screens')
            with patch.object(self.engine,'call',return_value={**base,'priority':value}):
                result=self.engine.screen(READING)
            self.assertEqual(result['priority'],value)
            with patch.object(self.engine,'call',side_effect=AssertionError('valid score cache must not call model')):
                self.assertEqual(self.engine.screen(READING),result)

    def test_screen_cache_with_unusable_priority_is_rebuilt_instead_of_treated_as_zero(self):
        raw={'change_basis':ai.CHANGE_BASES[0],'priority':75,'driver':ai.DRIVERS[0],'impact_evidence':1,'reason':'계약 변경 확인','watch_for':'공시 확인'}
        with patch.object(self.engine,'call',return_value=raw):saved=self.engine.screen(READING)
        for bad in ({k:v for k,v in saved.items() if k!='priority'},{**saved,'priority':True},{**saved,'priority':101}):
            with self.engine.db() as db:db.execute('UPDATE screens SET payload=?',(json.dumps(bad),))
            with patch.object(self.engine,'call',return_value=raw) as call:
                result=self.engine.screen(READING)
            call.assert_called_once()
            self.assertEqual(result['priority'],75)

    def test_screen_abstains_with_no_source_and_rejects_malformed_quotes(self):
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[0],'impact_evidence':0,'reason':'원문 미확인','watch_for':''}
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
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[-1],'impact_evidence':0,'reason':'경제적 변화 미확인','watch_for':''}
        with patch.object(ai,'SCREEN_VERSION','old'),patch.object(self.engine,'call',return_value=output):
            old=self.engine.screen(READING)
        self.engine.queue.enqueue([{'article':ARTICLE}])
        with patch.object(self.engine,'call',return_value=output) as call:
            fresh=self.engine.screen(READING)
        call.assert_called_once()
        self.assertNotEqual(old['screen_policy_version'],fresh['screen_policy_version'])
        self.assertEqual(self.engine.queue.summary()['pending'],1)

    def test_screening_is_per_event_cached_and_separate_from_ranking(self):
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':'금융상품 조건·청약·판매 안내','impact_evidence':0,'reason':'국채 발행 조건 안내이며 증권사 이익 변화 미확인','watch_for':'상장사 실적 영향이 있는지 확인'}
        with patch.object(self.engine,'call',return_value=output) as call:
            first=self.engine.screen(READING)
            second=self.engine.screen(READING)
        self.assertEqual(first['stock_relevance'],'배경·상품 안내')
        self.assertEqual(first,second);call.assert_called_once()
        other=ai.Engine(self.engine.path)
        with patch.object(other,'call') as call:
            self.assertEqual(other.screen(READING),first);call.assert_not_called()

    def test_screen_cache_uses_only_actual_source_input_and_keeps_original_assessment_time(self):
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[0],'impact_evidence':1,'reason':'원문에서 계약 체결 확인','watch_for':'이행 확인'}
        changed={**READING,'summary':'다른 생성 요약','event_title':'다른 제목','amount':'다른 규모',
                 'entities':['다른 생성 당사자'],'certainty':'계획','timing':'다른 시점','published_at':'2026-11-12T00:00:00Z'}
        with patch.object(self.engine,'call',return_value=output) as call,patch('intelligence.now',return_value='2026-11-11T01:00:00Z'):
            first=self.engine.screen(READING)
        expected_payload=call.call_args.args[1]
        with patch.object(ai.Engine,'call',return_value=output) as call,patch('intelligence.now',return_value='2026-11-12T01:00:00Z'):
            second=ai.Engine(self.engine.path).screen(changed)
            call.assert_not_called()
        self.assertEqual(first,second)
        self.assertEqual(second['assessed_at'],'2026-11-11T01:00:00Z')
        with patch.object(self.engine,'call',return_value=output) as call:
            self.engine.screen({**changed,'evidence':['계약 금액이 4000억원으로 정정됐다고 공시했다.']})
        call.assert_called_once()
        self.assertNotEqual(call.call_args.args[1],expected_payload)

    def test_screen_cache_isolates_model_provider_and_policy_text(self):
        output={'change_basis':ai.CHANGE_BASES[0],'priority':50,'driver':ai.DRIVERS[-1],'impact_evidence':0,'reason':'경제적 변화 미확인','watch_for':''}
        with patch.object(self.engine,'call',return_value=output):self.engine.screen(READING)
        for field,value in [('model','other-model'),('provider','other-provider')]:
            with patch.object(self.engine,field,value),patch.object(self.engine,'call',return_value=output) as call:
                self.engine.screen(READING)
                call.assert_called_once()
        with patch.object(ai,'GATE_POLICY',ai.GATE_POLICY+' 추가 지침'),patch.object(self.engine,'call',return_value=output) as call:
            self.engine.screen(READING)
            call.assert_called_once()


if __name__=='__main__':unittest.main()
