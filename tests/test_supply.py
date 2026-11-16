import copy
import hashlib
import json
import unittest
from unittest.mock import Mock,patch

import supply
import server


class SupplyTest(unittest.TestCase):
    def test_sourced_paths_never_assert_incremental_benefit(self):
        result=supply.snapshot('2026-11-16')
        self.assertGreaterEqual(len(result['claims']),6)
        self.assertTrue(all(c['evidence'] and c['path_hops']==1 and not c['beneficiary_confirmed'] for c in result['claims']))
        self.assertTrue(all(c['financial_impact'] is None for c in result['claims']))
        compute=[c for c in result['claims'] if c['id'].startswith('anthropic_')]
        self.assertEqual({c['kind'] for c in compute},{'supply','investment'})
        self.assertEqual(len({c['transaction_id'] for c in compute}),2)

    def test_product_generation_stage_time_constraints(self):
        get=lambda **kw:next(c for c in supply.snapshot('2026-11-16',**kw)['claims'] if c['id']=='hynix_tsmc')
        self.assertEqual(get(generation='HBM3')['event_link_status'],'blocked')
        self.assertIn('구매 확정으로 승격 불가',get(stage='purchase')['required_checks'])
        self.assertEqual(get(product='gpu')['event_link_status'],'blocked')
        self.assertTrue(all(c['event_link_status']=='blocked' for c in supply.snapshot('2020-01-01')['claims']))
        data=copy.deepcopy(supply.KNOWLEDGE);data['claims'][0]['valid_to']='2026-01-01'
        with patch.object(supply,'KNOWLEDGE',data):
            result=supply.snapshot('2026-11-16')['claims'][0]
            self.assertIn('관계 유효 기간 종료',result['blocked_reasons'])

    def test_conflicting_claims_preserve_original_and_legacy_rollback(self):
        before=json.dumps(supply.relations.KNOWLEDGE,sort_keys=True,ensure_ascii=False)
        self.assertEqual(hashlib.sha256(before.encode()).hexdigest(),supply.KNOWLEDGE['migration_digest'])
        data=copy.deepcopy(supply.KNOWLEDGE)
        denial={**data['claims'][0],'id':'test-denial','transaction_id':'test-denial','status':'denied','disputes':data['claims'][0]['id']}
        data['claims'].append(denial)
        with patch.object(supply,'KNOWLEDGE',data):
            result=supply.snapshot('2026-11-16')['claims']
            self.assertEqual(len(result),len(data['claims']))
            self.assertIn('후속 변경·상충 주장 존재',result[0]['blocked_reasons'])
        legacy=supply.snapshot(version='legacy')
        self.assertEqual(len(legacy['claims']),16)
        self.assertEqual(json.dumps(supply.relations.KNOWLEDGE,sort_keys=True,ensure_ascii=False),before)
        self.assertRaises(ValueError,supply.snapshot,version='unknown')

    def test_supply_api_and_unknown_filters(self):
        handler=object.__new__(server.Handler);handler.respond=Mock()
        handler.path='/api/supply?code=AMD.O&generation=MI450';handler.do_GET()
        result=json.loads(handler.respond.call_args.args[0])
        self.assertEqual(len(result['claims']),1)
        handler.path='/api/supply?stage=invalid';handler.do_GET()
        self.assertEqual(handler.respond.call_args.args[2],400)
