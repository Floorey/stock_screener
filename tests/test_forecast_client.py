import copy
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import MagicMock,patch

import requests
from forecast_client import load_context,request_forecast,validate_result


def fixture(horizon=5):
    from zoneinfo import ZoneInfo
    # Deterministic session sequence with gaps; includes a holiday-style gap.
    now=datetime.now(timezone.utc)
    end=(now-timedelta(days=2)).astimezone(ZoneInfo('America/New_York')).replace(hour=16,minute=0,second=0,microsecond=0)
    sessions=[dict(session_date=(end-timedelta(days=i)).date(),closes_at=end-timedelta(days=i)) for i in range(119,-1,-1)]
    future=[dict(session_date=(now+timedelta(days=i+1)).date(),closes_at=now+timedelta(days=i+1)) for i in range(horizon)]
    rows=[dict(event_at=s['closes_at'],open=100,high=102,low=99,close=101,volume=10) for s in sessions]
    return sessions,future,rows


def connection(data):
    conn=MagicMock();conn.execute.return_value.fetchall.side_effect=[data[0][::-1],data[1],data[2]]
    return conn


def response(payload,model='kronos'):
    return dict(symbol='SPY',timeframe='1Day',data_asof=payload['bars'][-1]['time'],
       generated_at=datetime.now(timezone.utc).isoformat(),model='test',input_bars_count=120,
       predicted_candles=[dict(step=i+1,predicted_time=t,open=100,high=102,low=99,close=101,volume=10) for i,t in enumerate(payload['future_timestamps'])],quantile_forecast=None)


class ForecastClientTests(unittest.TestCase):
    def test_exact_feed_completed_bars_calendar(self):
        data=fixture();conn=connection(data);p=load_context(conn,'SPY','sip',5)
        self.assertEqual(len(p['bars']),120)
        self.assertEqual(p['future_timestamps'],[s['closes_at'].isoformat() for s in data[1]])
        self.assertEqual(conn.execute.call_args_list[-1].args[1][:2],('SPY','sip'))
    def test_missing_duplicate_bad_bars_and_calendar(self):
        for case in ('missing','duplicate','invalid','calendar','stale'):
            data=copy.deepcopy(fixture())
            if case=='missing': data[2].pop()
            if case=='duplicate': data[2][-1]=data[2][-2]
            if case=='invalid': data[2][-1]['volume']=-1
            if case=='calendar': data[1].pop()
            if case=='stale': data[1][0]['closes_at']=datetime.now(timezone.utc)-timedelta(hours=1)
            with self.subTest(case=case),self.assertRaises(ValueError):load_context(connection(data),'SPY','iex',5)
    def test_success_single_post_no_credentials_or_retry(self):
        conn=connection(fixture());p=load_context(connection(fixture()),'SPY','iex',5)
        r=MagicMock(status_code=200);r.json.return_value=response(p)
        # Use one deterministic context for request and expected response.
        with patch('forecast_client.connect') as db,patch('forecast_client.requests.post',return_value=r) as post,patch('forecast_client.load_context',return_value=p):
            db.return_value.__enter__.return_value=conn
            result=request_forecast('SPY','iex','kronos',5)
            self.assertEqual(result['selection']['model'],'kronos')
            self.assertEqual(post.call_count,1)
            self.assertEqual(post.call_args.kwargs['timeout'],(5,120))
            self.assertNotIn('headers',post.call_args.kwargs)
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
    def test_http_errors_timeout_malformed(self):
        for code in (409,422,429,503,500,302):
            with self.subTest(code=code),patch('forecast_client.connect') as db,patch('forecast_client.load_context',return_value={}),patch('forecast_client.requests.post',return_value=MagicMock(status_code=code)),self.assertRaises(ValueError):
                request_forecast('SPY','iex','kronos',5)
        with patch('forecast_client.connect'),patch('forecast_client.load_context',return_value={}),patch('forecast_client.requests.post',side_effect=requests.Timeout),self.assertRaisesRegex(ValueError,'Zeitlimit'):
            request_forecast('SPY','iex','kronos',5)
    def test_response_alignment_finiteness_and_ordering(self):
        p=load_context(connection(fixture()),'SPY','iex',5)
        for case in ('length','symbol','timestamp','nonfinite','ohlc'):
            r=response(p)
            if case=='length': r['predicted_candles'].pop()
            if case=='symbol': r['symbol']='AAPL'
            if case=='timestamp': r['predicted_candles'][0]['predicted_time']=p['bars'][-1]['time']
            if case=='nonfinite': r['predicted_candles'][0]['close']=float('nan')
            if case=='ohlc': r['predicted_candles'][0]['high']=90
            with self.subTest(case=case),self.assertRaises(ValueError):validate_result(r,p,'kronos')


if __name__=='__main__':unittest.main(verbosity=2)
