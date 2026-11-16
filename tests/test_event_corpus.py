import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import event_corpus as c


class CorpusTest(unittest.TestCase):
    def test_count_is_not_a_claim_of_price_truth_or_expert_accuracy(self):
        report=c.report(c.load())
        self.assertTrue(report['source_count_goal_met'])
        self.assertGreaterEqual(report['real_independent_cases'],100)
        self.assertTrue(all(report['axes'][a]>=10 for a in c.AXES))
        self.assertEqual(report['price_ground_truth_cases'],0)
        self.assertFalse(report['ready_for_final_evaluation'])
        self.assertEqual(report['annotators'],['agent'])
        self.assertEqual(report['independent_second_reviews'],0)
        self.assertTrue(any(r['status']=='excluded_date_mismatch' for r in report['collection_failures_or_exclusions']))

    def test_same_family_future_and_duplicate_events_are_rejected(self):
        original=c.load()
        mutated=copy.deepcopy(original)
        a=next(r for r in mutated['cases'] if r['split']=='development');b=next(r for r in mutated['cases'] if r['split']=='final')
        b['family_id']=a['family_id'];self.assertRaises(ValueError,c.validate,mutated)
        mutated=copy.deepcopy(original);mutated['cases'][1]['independent_event_id']=mutated['cases'][0]['independent_event_id']
        self.assertRaises(ValueError,c.validate,mutated)
        mutated=copy.deepcopy(original);mutated['cases'][-1]['split']='development';self.assertRaises(ValueError,c.validate,mutated)
        mutated=copy.deepcopy(original);mutated['cases'][0]['source']['proof']='changed';self.assertRaises(ValueError,c.validate,mutated)

    def test_manifest_freezes_content_and_source_checks_detect_replaced_files(self):
        original=c.load();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        case=original['cases'][0];cache=root/case['source']['cached_file'];cache.write_text('different source')
        self.assertEqual(c.source_check({'cases':[case]},root)[0]['status'],'hash_mismatch')
        path=root/'corpus.json';lock=root/'lock.json';path.write_text(json.dumps(original));lock.write_text(c.LOCK.read_text())
        with patch.object(c,'PATH',path),patch.object(c,'LOCK',lock):
            self.assertEqual(c.load()['version'],original['version'])
            original['limitations'].append('changed');path.write_text(json.dumps(original))
            self.assertRaises(ValueError,c.load)
