import copy
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pandas as pd
from alpaca_trader import AlpacaReadError
from forecast_client import prepare_context


class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,11,26,12,tzinfo=timezone.utc)


def provider():
    days=pd.bdate_range(end='2026-11-25',periods=120)
    cal=[dict(date=str(d.date()),close='16:00') for d in days]
    cal += [dict(date='2026-11-27',close='13:00'),dict(date='2026-11-30',close='16:00')]
    bars=[dict(t=datetime.combine(d.date(),datetime.min.time(),ZoneInfo('America/New_York')).isoformat(),o=100,h=102,l=99,c=101,v=10) for d in days]
    return cal,bars


class DirectForecastTests(unittest.TestCase):
    def run_source(self,cal,bars,mode='normal'):
        calls=[]
        def api(path,params,data_api):
            calls.append((path,dict(params)))
            if path=='/v2/calendar':return cal
            if mode=='repeat':return {'bars':{'SPY':bars[:60]},'next_page_token':'same'}
            if mode=='malformed':return {'bars':None}
            if 'page_token' not in params:return {'bars':{'SPY':bars[:60]},'next_page_token':'next'}
            return {'bars':{'SPY':bars[60:]},'next_page_token':None}
        with patch('forecast_client.datetime',Clock),patch('alpaca_trader.load_paper_credentials'),patch('alpaca_trader.analytics_alpaca_get',side_effect=api),patch('forecast_client.connect',side_effect=AssertionError('No DB allowed')):
            result=prepare_context('SPY','iex',2)
        return result,calls
    def test_pagination_closed_sessions_dst_holiday_early_close(self):
        cal,bars=provider()
        # A future/incomplete bar must not become model input.
        bars.append(dict(t='2026-11-27T05:00:00Z',o=100,h=102,l=99,c=101,v=1))
        result,calls=self.run_source(cal,bars)
        self.assertEqual(len(result['payload']['bars']),120)
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[-1][1]['page_token'],'next')
        self.assertEqual(result['payload']['future_timestamps'],['2026-11-27T13:00:00-05:00','2026-11-30T16:00:00-05:00'])
        self.assertTrue(result['payload']['bars'][0]['time'].endswith('-04:00'))
        self.assertTrue(result['payload']['bars'][-1]['time'].endswith('-05:00'))
    def test_repeated_cursor_malformed_missing_duplicate_and_bad_prices(self):
        for mode in ('repeat','malformed','missing','duplicate','price'):
            cal,bars=provider()
            if mode=='missing':bars.pop()
            if mode=='duplicate':bars[-1]=bars[-2]
            if mode=='price':bars[-1]['h']=0
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.run_source(cal,bars,mode)
    def test_provider_errors_never_switch_source(self):
        for code in (401,403,429):
            with self.subTest(code=code),patch('alpaca_trader.load_paper_credentials'),patch('alpaca_trader.analytics_alpaca_get',side_effect=AlpacaReadError('provider error',code)),patch('forecast_client.connect') as db:
                with self.assertRaises(AlpacaReadError) as error:prepare_context('SPY','sip',5)
                self.assertEqual(error.exception.status_code,code);db.assert_not_called()
    def test_network_timeout_never_switches_source(self):
        with patch('alpaca_trader.load_paper_credentials'),patch('alpaca_trader.analytics_alpaca_get',side_effect=AlpacaReadError('timeout',retryable=True)),patch('forecast_client.connect') as db:
            with self.assertRaises(AlpacaReadError):prepare_context('SPY','iex',5)
            db.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
