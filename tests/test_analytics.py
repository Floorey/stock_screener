import json
import math
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analytics_import import import_pages, plan_bar_jobs, retry_read
from analytics_metrics import daily_stress, detect_stress_events, event_window, intraday_stress
from analytics_store import (SECTORS, checkpoint, connect, digest, initialize, macro_asof,
                             normalize_bars, record_page, save_bars, save_macro, vintage_available)


class AnalyticsOfflineTests(unittest.TestCase):
    def test_active_session_import_excludes_incomplete_minute_and_uses_calendar_close(self):
        sessions = [('2026-11-05',datetime.fromisoformat('2026-11-05T14:30:00+00:00'),datetime.fromisoformat('2026-11-05T18:00:00+00:00')),
                    ('2026-11-06',datetime.fromisoformat('2026-11-06T14:30:00+00:00'),datetime.fromisoformat('2026-11-06T21:00:00+00:00'))]
        jobs = plan_bar_jobs(sessions,date(2026,11,5),'sip',('SPY',),datetime.fromisoformat('2026-11-06T15:07:42+00:00'))
        minutes = [job for job in jobs if job['timeframe']=='1Min']
        self.assertEqual(len(minutes),2)
        self.assertEqual(minutes[0]['end'],'2026-11-05T17:59:59.999999+00:00')
        self.assertEqual(minutes[1]['end'],'2026-11-06T15:06:59.999999+00:00')
        self.assertIn('2026-11-05',jobs[0]['end'])
        self.assertTrue(all(job['feed']=='sip' for job in jobs))

    def test_rule_event_thresholds_and_gap_suppression(self):
        dates = list(pd.bdate_range('2026-10-26',periods=7).date)
        prices = [100,99,98,97,96,94,94]
        bars = pd.DataFrame([{'symbol':'SPY','event_at':pd.Timestamp(day,tz='America/New_York').tz_convert('UTC'),'close':price}
                             for day,price in zip(dates,prices)])
        events = detect_stress_events(bars,dates)
        self.assertTrue(any(event['date']==dates[5].isoformat() and '1T' in event['name'] and '5T' in event['name'] for event in events))
        missing = detect_stress_events(bars.iloc[[0,1,2,4,5,6]],dates)
        event = next(event for event in missing if event['date']==dates[5].isoformat())
        self.assertNotIn('5T',event['name'])
        self.assertEqual(event['rule_version'],'stress-rules-1.0.0')

    def test_digest_stable_and_refuses_nonfinite_json(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
        with self.assertRaises(ValueError):
            digest({'bad':float('nan')})

    def test_normalize_rejects_malformed_ohlcv_and_naive_time(self):
        valid = {'t':'2026-11-02T14:30:00Z','o':100,'h':105,'l':99,'c':102,'v':1}
        self.assertEqual(normalize_bars({'bars':{'SPY':[valid]}})[0][0],'SPY')
        for changed in ({'v':-1},{'c':float('inf')},{'h':101},{'t':'2026-11-02T14:30:00'}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                normalize_bars({'bars':{'SPY':[{**valid,**changed}]}})

    def test_retries_429_and_503_but_never_403(self):
        calls,pauses = [],[]
        def call():
            calls.append(1)
            if len(calls)<3:
                exc = RuntimeError('limited')
                exc.status_code = 429 if len(calls)==1 else 503
                exc.retry_after = '2'
                raise exc
            return 'ok'
        self.assertEqual(retry_read(call,pause=pauses.append),'ok')
        self.assertEqual(pauses,[2,2])
        def forbidden():
            exc = RuntimeError('denied')
            exc.status_code = 403
            raise exc
        with self.assertRaises(RuntimeError):
            retry_read(forbidden,pause=lambda _: self.fail('403 must not retry'))

    def test_network_retry_is_bounded(self):
        calls = []
        def offline():
            calls.append(1)
            raise requests.ConnectionError('offline')
        with self.assertRaises(requests.ConnectionError):
            retry_read(offline,attempts=3,pause=lambda _:None)
        self.assertEqual(len(calls),3)
        def wrapped_transport():
            exc = RuntimeError('safe transport error')
            exc.retryable = True
            raise exc
        pauses = []
        with self.assertRaises(RuntimeError):
            retry_read(wrapped_transport,attempts=2,pause=pauses.append)
        self.assertEqual(pauses,[1])

    def test_vintage_available_next_new_york_midnight_with_dst(self):
        self.assertEqual(vintage_available('2020-03-08').astimezone(timezone.utc).isoformat(),'2020-03-09T04:00:00+00:00')
        self.assertEqual(vintage_available('2020-11-01').astimezone(timezone.utc).isoformat(),'2020-11-02T05:00:00+00:00')

    def test_returns_preserve_missing_exchange_session(self):
        bars = pd.DataFrame([{'symbol':'SPY','event_at':'2026-11-02T05:00:00Z','close':100},
                             {'symbol':'SPY','event_at':'2026-11-04T05:00:00Z','close':90}])
        metrics = daily_stress(bars,[date(2026,11,2),date(2026,11,3),date(2026,11,4)])
        self.assertTrue(math.isnan(metrics.iloc[-1]['SPY Tagesrendite %']))
        self.assertTrue(math.isnan(metrics.iloc[-1]['Sektorbreite negativ %']))

    def test_breadth_requires_all_eleven_and_uses_negative_sign(self):
        rows = [{'symbol':symbol,'event_at':f'2026-11-0{day}T05:00:00Z','close':100 if day==2 else 99}
                for symbol in SECTORS for day in (2,3)]
        complete = daily_stress(pd.DataFrame(rows))
        self.assertEqual(complete.iloc[-1]['Sektorbreite negativ %'],100)
        missing = daily_stress(pd.DataFrame([r for r in rows if r['symbol']!='XLC']))
        self.assertTrue(math.isnan(missing.iloc[-1]['Sektorbreite negativ %']))

    def test_intraday_drawdown_and_volatility_require_complete_session(self):
        bars = pd.DataFrame([{'symbol':'SPY','event_at':'2026-11-02T14:30:00Z','open':100,'close':110},
                             {'symbol':'SPY','event_at':'2026-11-02T14:31:00Z','open':110,'close':99}])
        sessions = pd.DataFrame([{'session_date':date(2026,11,2),'opens_at':pd.Timestamp('2026-11-02T14:30:00Z'),
                                  'closes_at':pd.Timestamp('2026-11-02T14:32:00Z')}])
        metrics = intraday_stress(bars,sessions)
        self.assertAlmostEqual(metrics.iloc[0]['Beobachteter Close-Drawdown %'],-10)
        self.assertTrue(metrics.iloc[0]['Vollständig'])
        partial = intraday_stress(bars.iloc[:1],sessions)
        self.assertTrue(math.isnan(partial.iloc[0]['Realisierte Tagesvolatilität %']))
        self.assertFalse(partial.iloc[0]['Vollständig'])

    def test_event_baseline_is_pre_event_close_and_missing_day_is_not_shifted(self):
        dates = [date(2026,11,day) for day in (2,3,4,5)]
        bars = pd.DataFrame([{'symbol':'SPY','event_at':f'2026-11-0{day}T05:00:00Z','close':price}
                             for day,price in ((2,100),(3,100),(4,90),(5,95))])
        window = event_window(bars,'2026-11-04',before=2,after=2,session_dates=dates)
        self.assertAlmostEqual(window.loc[date(2026,11,4),'SPY'],-10)
        self.assertEqual(window.loc[date(2026,11,4),'Handelstage relativ'],0)
        missing = event_window(bars[bars['close']!=90],'2026-11-04',session_dates=dates)
        self.assertTrue(math.isnan(missing.loc[date(2026,11,4),'SPY']))
        self.assertEqual(missing.attrs['event_session'],date(2026,11,4))

    def test_event_catalog_version_and_unique_ids(self):
        catalog = json.loads(Path(__file__).resolve().parents[1].joinpath('analytics_events.json').read_text())
        self.assertTrue(catalog['version'])
        self.assertEqual(len({event['id'] for event in catalog['events']}),len(catalog['events']))
        for event in catalog['events']:
            date.fromisoformat(event['date'])
            self.assertTrue(event['source'].startswith('https://'))


@unittest.skipUnless(os.getenv('ANALYTICS_TEST_DATABASE_URL'),'No PostgreSQL integration test URL configured')
class AnalyticsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['ANALYTICS_DATABASE_URL'] = os.environ['ANALYTICS_TEST_DATABASE_URL']
        cls.conn = connect()
        initialize(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_reverting_provider_revision_becomes_current_without_losing_history(self):
        with self.conn.transaction(force_rollback=True):
            symbol = 'TEST_'+uuid.uuid4().hex
            request = {'symbols':symbol,'timeframe':'1Day','feed':'test','adjustment':'all'}
            first = {'bars':{symbol:[{'t':'2020-01-02T05:00:00Z','o':100,'h':105,'l':95,'c':100,'v':10}]}}
            changed = {'bars':{symbol:[{**first['bars'][symbol][0],'c':99}]}}
            first_id = record_page(self.conn,'test',request,first)
            save_bars(self.conn,first,request,first_id)
            save_bars(self.conn,changed,request,record_page(self.conn,'test',request,changed))
            self.assertEqual(self.conn.execute('SELECT close FROM analytics.latest_bars WHERE symbol=%s',(symbol,)).fetchone()['close'],99)
            save_bars(self.conn,first,request,first_id)
            self.assertEqual(self.conn.execute('SELECT close FROM analytics.latest_bars WHERE symbol=%s',(symbol,)).fetchone()['close'],100)
            self.assertEqual(self.conn.execute('SELECT count(*) n FROM analytics.bars WHERE symbol=%s',(symbol,)).fetchone()['n'],2)

    def test_raw_dedup_revisions_and_vintage_point_in_time(self):
        with self.conn.transaction(force_rollback=True):
            request = {'test':str(uuid.uuid4())}
            original = {'observations':[{'date':'2020-01-01','realtime_start':'2020-02-01','realtime_end':'2020-03-01','value':'1'}]}
            revision = {'observations':[{'date':'2020-01-01','realtime_start':'2020-03-02','realtime_end':'9999-12-31','value':'2'}]}
            first = record_page(self.conn,'test',request,original)
            self.assertEqual(record_page(self.conn,'test',request,original),first)
            series = 'TEST_'+uuid.uuid4().hex
            save_macro(self.conn,original,series,first)
            save_macro(self.conn,revision,series,record_page(self.conn,'test',request,revision))
            self.assertEqual(macro_asof(self.conn,series,datetime(2020,2,1,tzinfo=timezone.utc)),[])
            self.assertEqual(macro_asof(self.conn,series,datetime(2020,2,3,tzinfo=timezone.utc))[0]['value'],1)
            self.assertEqual(macro_asof(self.conn,series,datetime(2020,3,4,tzinfo=timezone.utc))[0]['value'],2)

    def test_page_failure_keeps_committed_cursor_and_resume_deduplicates(self):
        symbol = 'TEST_'+uuid.uuid4().hex
        request = {'symbols':symbol,'timeframe':'1Day','feed':'test','adjustment':'all'}
        key = digest({'source':'alpaca',**request})
        def payload(day,token=None):
            return {'bars':{symbol:[{'t':f'2020-01-0{day}T05:00:00Z','o':100,'h':101,'l':99,'c':100,'v':10}]},'next_page_token':token}
        def interrupted(params):
            if params.get('page_token')=='next':
                raise requests.ConnectionError('offline')
            return payload(2,'next')
        try:
            with self.assertRaises(requests.ConnectionError):
                import_pages(self.conn,'alpaca',request,interrupted,save_bars,pause=lambda _:None)
            state = self.conn.execute('SELECT cursor,status,row_count FROM analytics.checkpoints WHERE job_key=%s',(key,)).fetchone()
            self.conn.commit()
            self.assertEqual(state,{'cursor':'next','status':'error','row_count':1})
            calls = []
            def resumed(params):
                calls.append(params.get('page_token'))
                return payload(3)
            self.assertEqual(import_pages(self.conn,'alpaca',request,resumed,save_bars,pause=lambda _:None),1)
            self.assertEqual(calls,['next'])
            self.assertEqual(import_pages(self.conn,'alpaca',request,resumed,save_bars,pause=lambda _:None),0)
            self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM analytics.bars WHERE symbol=%s',(symbol,)).fetchone()['n'],2)
            self.conn.commit()
        finally:
            self.conn.rollback()
            self.conn.execute('DELETE FROM analytics.bars WHERE symbol=%s',(symbol,))
            self.conn.execute('DELETE FROM analytics.checkpoints WHERE job_key=%s',(key,))
            self.conn.execute("DELETE FROM analytics.raw_pages WHERE request->>'symbols'=%s",(symbol,))
            self.conn.commit()


if __name__=='__main__':
    unittest.main()
