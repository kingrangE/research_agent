import copy
import json
import unittest
from unittest.mock import Mock,patch

import business_ontology as b
import server


class BusinessTest(unittest.TestCase):
    def test_reviewed_scope_and_unique_issuers(self):
        result=b.snapshot('2026-11-16')
        for theme in result['themes']:
            self.assertGreaterEqual(theme['countries']['KR'],2)
            self.assertGreaterEqual(theme['countries']['US'],2)
        self.assertLess(result['unique_issuers'],len(result['memberships']))
        naver=b.snapshot('2026-11-16',code='035420')['memberships'][0]
        self.assertEqual(naver['subject']['id'],'naver_cloud')
        self.assertNotEqual(naver['subject']['id'],naver['security']['issuer_id'])
        self.assertEqual(b.snapshot('2026-11-16',code='TSM')['memberships'][0]['security']['instrument'],'ADR')
        self.assertIsNone(naver['revenue_share'])

    def test_source_cutoff_expiry_and_unknown_dates(self):
        self.assertEqual(b.snapshot('2020-01-01')['memberships'],[])
        self.assertEqual(b.snapshot('2026-11-15',theme='power')['memberships'],[])
        data=copy.deepcopy(b.KNOWLEDGE)
        item=next(m for m in data['memberships'] if m['code']=='005930')
        item['valid_to']='2026-11-10'
        with patch.object(b,'KNOWLEDGE',data):
            self.assertEqual(b.snapshot('2026-11-16',code='005930')['memberships'],[])

    def test_invalid_links_and_queries_fail_explicitly(self):
        for key,value in [('subject_id','missing'),('status','unreviewed'),('sources',[])]:
            data=copy.deepcopy(b.KNOWLEDGE);data['memberships'][0][key]=value
            self.assertRaises(ValueError,b.validate,data)
        for args in [('bad',None,None),('2026-11-16','unknown',None),('2026-11-16',None,'bad')]:
            self.assertRaises(ValueError,b.snapshot,*args)
        handler=object.__new__(server.Handler);handler.respond=Mock()
        handler.path='/api/business?theme=power&as_of=2026-11-16';handler.do_GET()
        response=json.loads(handler.respond.call_args.args[0])
        self.assertTrue(all(m['theme']=='power' for m in response['memberships']))
        handler.path='/api/business?as_of=invalid';handler.do_GET()
        self.assertEqual(handler.respond.call_args.args[2],400)
