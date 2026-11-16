from datetime import datetime
import unittest

import calendar_reference as c
import event_reactions as r


def vendor(day,end='16:00:00-05:00'):
    return {'date':day,'regular_open':True,'regularMarket':{'startTime':day+'T09:30:00-05:00','endTime':day+'T'+end}}


class CalendarReferenceTest(unittest.TestCase):
    def test_exchange_closure_corrects_vendor_but_preserves_original(self):
        raw=vendor('2020-12-25');resolved=c.resolve('US',raw)
        self.assertFalse(resolved['regular_open']);self.assertIsNone(resolved['regularMarket'])
        self.assertTrue(resolved['calendar_source_conflict'])
        self.assertTrue(raw['regular_open']);self.assertEqual(resolved['vendor_regular_session'],raw['regularMarket'])
        self.assertTrue(resolved['calendar_reference']['sources'][0]['url'].startswith('https://ir.theice.com/'))
        self.assertFalse(resolved['calendar_reference']['point_in_time_page_version'])

    def test_early_close_dst_and_equal_instant_different_timezone(self):
        winter=c.resolve('US',vendor('2020-12-24'));summer=c.resolve('US',vendor('2024-07-03',end='16:00:00-04:00'))
        self.assertEqual(winter['regularMarket']['endTime'],'2020-12-24T13:00:00-05:00')
        self.assertEqual(summer['regularMarket']['endTime'],'2024-07-03T13:00:00-04:00')
        raw=vendor('2020-12-24');raw['regularMarket']['endTime']='2020-12-25T03:00:00+09:00'
        self.assertFalse(c.resolve('US',raw)['calendar_source_conflict'])

    def test_unknown_opening_is_not_fabricated_and_unlisted_dates_are_not_inferred(self):
        unknown=c.resolve('US',{'date':'2020-12-24','regular_open':False,'regularMarket':None})
        self.assertTrue(unknown['calendar_unverified'])
        self.assertFalse(r.calendar_complete({'2020-12-24':unknown},'2020-12-24','2020-12-24'))
        raw=vendor('2022-01-03');self.assertEqual(c.resolve('US',raw),raw)
        self.assertEqual(c.resolve('KR',vendor('2020-12-25')),vendor('2020-12-25'))
        self.assertFalse(c.resolve('US',vendor('2025-01-09'))['regular_open'])
