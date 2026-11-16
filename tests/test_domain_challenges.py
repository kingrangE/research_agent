import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluate_domain_challenges as e


class DomainChallengeTest(unittest.TestCase):
    def test_domain_counterexamples_are_not_real_event_accuracy(self):
        result=e.run()
        self.assertEqual(result['failed'],0)
        self.assertIsNone(result['real_event_accuracy'])
        self.assertEqual(result['reviewer_kind'],'agent')
        self.assertTrue(any(c['synthetic'] for c in result['cases']))

    def test_a_wrong_expected_answer_fails_without_altering_the_answer(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);path=Path(tmp.name)/'challenge.json'
        case={'id':'wrong','type':'event','synthetic':True,'input':'일반 금융 상품 안내','expected':{'axis':'infrastructure'}}
        path.write_text(json.dumps({'version':'fixture','reviewer_kind':'agent','counts_as_real_corpus_events':False,'cases':[case]}))
        with patch.object(e,'PATH',path):
            result=e.run();self.assertEqual(result['failed'],1);self.assertFalse(result['cases'][0]['passed'])
