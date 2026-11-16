import unittest
from unittest.mock import patch
import market_watch

class MarketWatchTest(unittest.TestCase):
    def test_mixed_direction_average_and_missing_denominator(self):
        def recent(code,now):
            values={'SPY':.1,'NVDA.O':2,'AMD.O':1,'AVGO.O':-1,'TSM':None}
            value=values.get(code)
            return {'status':'ok' if value is not None else 'pending','change_percent':value}
        with patch('market_watch.prices.recent',side_effect=recent):
            r=market_watch.snapshot('US')
        semi=next(t for t in r['themes'] if t['id']=='semiconductor')
        self.assertEqual((semi['tracked'],semi['observed'],semi['up'],semi['down']),(4,3,2,1))
        self.assertAlmostEqual(semi['mean_percent'],2/3)
        self.assertAlmostEqual(semi['market_difference_pp'],2/3-.1)
        self.assertTrue(r['benchmark']['proxy'])

    def test_missing_observations_do_not_become_flat_or_eligible(self):
        with patch('market_watch.prices.recent',return_value={'status':'pending','change_percent':None}):
            r=market_watch.snapshot('KR')
        for t in r['themes']:
            self.assertFalse(t['eligible']);self.assertIsNone(t['mean_percent'])
            self.assertEqual(t['flat'],0)
        with self.assertRaises(ValueError):market_watch.snapshot('XX')

    def test_candidates_require_market_context_and_remove_duplicate_members(self):
        def recent(code,now):
            return {'status':'ok','change_percent':0 if code=='SPY' else 1}
        with patch('market_watch.prices.recent',side_effect=recent):
            r=market_watch.snapshot('US')
        selected=market_watch.candidates(r)
        self.assertTrue(selected)
        self.assertLessEqual(len(selected),5)
        seen=set()
        for item in selected:
            codes={s['code'] for s in item['stocks']}
            self.assertLessEqual(len(codes&seen)/len(codes),.5)
            seen.update(codes)
        r['benchmark']['recent']={'status':'pending','change_percent':None}
        self.assertEqual(market_watch.candidates(r),[])
