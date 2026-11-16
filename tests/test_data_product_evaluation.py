import copy
import unittest

import evaluate_data_product as e
import event_corpus


class EvaluationTest(unittest.TestCase):
    def test_abstention_and_wrong_class_remain_in_recall_denominator(self):
        rows=[{'gold':{'axis':['rates']},'predicted':{'axis':[]}},
              {'gold':{'axis':['rates']},'predicted':{'axis':['fx']}},
              {'gold':{'axis':['rates']},'predicted':{'axis':['rates']}}]
        result=e.metric(rows,'axis')
        self.assertEqual((result['true_positive'],result['false_positive'],result['false_negative']),(1,1,2))
        self.assertEqual(result['precision'],.5);self.assertAlmostEqual(result['recall'],1/3)
        self.assertEqual(result['abstained_cases'],1)
        self.assertIsNone(e.interval(0,0));self.assertGreater(e.interval(1,1)[0],0)

    def test_split_selection_does_not_mutate_labels_or_authorize_release(self):
        source=event_corpus.load()
        fixtures=[next(c for c in source['cases'] if c['split']=='development' and c['axis']==axis) for axis in ('rates','infrastructure')]
        data={**source,'cases':[{**c,'split':'final'} for c in fixtures]};before=copy.deepcopy(data)
        result=e.evaluate(data)
        self.assertEqual(data,before);self.assertEqual(result['cases'],2)
        self.assertFalse(result['release_approved']);self.assertEqual(result['llm_calls'],0)
        self.assertEqual(result['embedding_calls'],0)
        self.assertEqual({r['id'] for r in result['rows']},{c['id'] for c in data['cases'] if c['split']=='final'})
        self.assertIn('no_listed_label',result['groups']['markets'])


if __name__=='__main__':unittest.main()
