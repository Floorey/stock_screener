"""Read-only provider imports. Run: python analytics_import.py --help."""
import argparse
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from analytics_store import (SYMBOLS, FRED_SERIES, checkpoint, connect, coverage, digest,
                             initialize, record_page, save_bars, save_macro)


def safe_error(exc):
    status = getattr(exc,'status_code',None)
    if type(exc).__name__=='AlpacaReadError' or (isinstance(exc,ValueError) and str(exc)=='FRED_API_KEY fehlt'):
        return str(exc)[:200]
    return f'{type(exc).__name__}; HTTP {status}' if status else type(exc).__name__


def retry_read(call, attempts=5, pause=time.sleep):
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            status = getattr(exc,'status_code',None)
            if status is None and getattr(exc,'response',None) is not None:
                status = exc.response.status_code
            retryable = getattr(exc,'retryable',False) or status==429 or (status is not None and 500<=status<600) or isinstance(exc,(requests.Timeout,requests.ConnectionError))
            if not retryable or attempt==attempts-1:
                raise
            wait = getattr(exc,'retry_after',None)
            if wait is None and getattr(exc,'response',None) is not None:
                wait = exc.response.headers.get('Retry-After')
            try:
                wait = min(60,max(0,float(wait))) if wait is not None else min(30,2**attempt)
            except (ValueError,TypeError):
                wait = min(30,2**attempt)
            pause(wait)


def alpaca_get(path, params, *, data_api=True):
    from alpaca_trader import analytics_alpaca_get
    return retry_read(lambda: analytics_alpaca_get(path,params,data_api=data_api))


def fred_get(params):
    key = os.getenv('FRED_API_KEY')
    if not key:
        raise ValueError('FRED_API_KEY fehlt')
    def read():
        response = requests.get('https://api.stlouisfed.org/fred/series/observations',
                                params={**params,'api_key':key,'file_type':'json'},timeout=45,allow_redirects=False)
        if response.status_code != 200:
            error = RuntimeError(f'FRED HTTP {response.status_code}')
            error.status_code = response.status_code
            error.retry_after = response.headers.get('Retry-After')
            raise error
        return response.json()
    return retry_read(read)


def import_pages(conn, source, request, fetch, save, *, refresh=False, pause=time.sleep):
    """Page data and its resume cursor commit together, including empty final pages."""
    key = digest({'source':source,**request})
    state = conn.execute('SELECT * FROM analytics.checkpoints WHERE job_key=%s',(key,)).fetchone()
    conn.commit()
    if state and state['status']=='complete' and not refresh:
        return 0
    cursor = None if refresh else (state['cursor'] if state else None)
    received = 0
    while True:
        page_request = dict(request)
        if source=='alpaca':
            if cursor:
                page_request['page_token'] = cursor
        else:
            page_request['offset'] = int(cursor or 0)
        try:
            payload = fetch(page_request)
            if source=='alpaca':
                next_cursor = payload.get('next_page_token')
            else:
                next_offset = int(payload['offset'])+len(payload['observations'])
                next_cursor = str(next_offset) if next_offset<int(payload['count']) else None
                if next_cursor and next_offset<=int(cursor or 0):
                    raise ValueError('FRED pagination made no progress')
            if next_cursor is not None and str(next_cursor)==str(cursor):
                raise ValueError('Provider repeated the same page cursor')
            page_id = record_page(conn,source,page_request,payload)
            count = save(conn,payload,request,page_id)
            checkpoint(conn,key,source,request,next_cursor,'running' if next_cursor else 'complete',count)
            conn.commit()
            received += count
            cursor = next_cursor
            if not cursor:
                return received
            pause(0.35)
        except Exception as exc:
            conn.rollback()
            status = getattr(exc,'status_code',None)
            # Never persist exception URLs or response bodies that may contain credentials.
            message = safe_error(exc)
            record_page(conn,source,page_request,{'error':message},status or 0)
            checkpoint(conn,key,source,request,cursor,'error',error=message)
            conn.commit()
            raise


def load_calendar(conn, start, end):
    params = {'start':start.isoformat(),'end':end.isoformat()}
    payload = alpaca_get('/v2/calendar',params,data_api=False)
    if not isinstance(payload,list):
        raise ValueError('Invalid Alpaca calendar response')
    sessions = []
    for row in payload:
        opening = datetime.fromisoformat(row['date']+'T'+row['open']).replace(tzinfo=ZoneInfo('America/New_York'))
        closing = datetime.fromisoformat(row['date']+'T'+row['close']).replace(tzinfo=ZoneInfo('America/New_York'))
        if closing<=opening:
            raise ValueError('Invalid calendar session')
        sessions.append((row['date'],opening,closing))
    page_id = record_page(conn,'alpaca-calendar',params,payload)
    with conn.cursor() as cur:
        cur.executemany('''INSERT INTO analytics.sessions(session_date,opens_at,closes_at,raw_page_id)
            VALUES(%s,%s,%s,%s) ON CONFLICT(session_date) DO UPDATE SET
            opens_at=EXCLUDED.opens_at,closes_at=EXCLUDED.closes_at,raw_page_id=EXCLUDED.raw_page_id''',
            [(day,opening,closing,page_id) for day,opening,closing in sessions])
    checkpoint(conn,digest({'source':'alpaca-calendar',**params}),'alpaca-calendar',params,None,'complete',len(sessions))
    conn.commit()
    return sessions


def plan_bar_jobs(sessions, start, feed, symbols, now):
    complete_sessions = [session for session in sessions if session[2]<=now]
    if not sessions:
        raise ValueError('No exchange sessions in requested interval')
    base = {'symbols':','.join(symbols),'feed':feed,'adjustment':'all','limit':10000,'sort':'asc'}
    jobs = []
    if complete_sessions:
        last_day = date.fromisoformat(complete_sessions[-1][0])
        for year in range(start.year,last_day.year+1):
            begin = max(start,date(year,1,1))
            finish = min(last_day+timedelta(days=1),date(year+1,1,1))
            if begin<finish:
                jobs.append({**base,'timeframe':'1Day','start':begin.isoformat()+'T00:00:00Z',
                             'end':(datetime.combine(finish,datetime.min.time(),timezone.utc)-timedelta(microseconds=1)).isoformat()})
    for day,opening,closing in complete_sessions[-30:]:
        jobs.append({**base,'timeframe':'1Min','start':opening.isoformat(),
                     'end':(closing-timedelta(microseconds=1)).isoformat()})
    cutoff = now.replace(second=0,microsecond=0)
    for day,opening,closing in sessions:
        if opening<cutoff<closing:
            jobs.append({**base,'timeframe':'1Min','start':opening.isoformat(),
                         'end':(cutoff-timedelta(microseconds=1)).isoformat()})
    return jobs


def import_alpaca(conn, start, end, feed, symbols=SYMBOLS, refresh=False):
    sessions = load_calendar(conn,start,end)
    jobs = plan_bar_jobs(sessions,start,feed,symbols,datetime.now(timezone.utc))
    failures = []
    from psycopg.types.json import Jsonb
    for request in jobs:
        conn.execute('''INSERT INTO analytics.checkpoints(job_key,source,request,status)
            VALUES(%s,'alpaca',%s,'pending') ON CONFLICT DO NOTHING''',
            (digest({'source':'alpaca',**request}),Jsonb(request)))
    conn.commit()
    for request in jobs:
        try:
            count = import_pages(conn,'alpaca',request,
                                 lambda params: alpaca_get('/v2/stocks/bars',params),save_bars,refresh=refresh)
            print(json.dumps({'source':'alpaca','timeframe':request['timeframe'],'start':request['start'],'received':count}))
        except Exception as exc:
            failures.append({'source':'alpaca','start':request['start'],'type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)})
            # Authentication/entitlement failures affect every following page with this explicit feed.
            if getattr(exc,'status_code',None) in (401,403):
                break
        time.sleep(0.35)
    return failures


def import_fred(conn, start, end, series=FRED_SERIES, refresh=False):
    failures = []
    requests_to_make = [{'series_id':series_id,'observation_start':start.isoformat(),'observation_end':end.isoformat(),
                   'realtime_start':'1776-07-04','realtime_end':'9999-12-31','output_type':1,
                   'limit':100000,'sort_order':'asc'} for series_id in series]
    from psycopg.types.json import Jsonb
    for request in requests_to_make:
        conn.execute('''INSERT INTO analytics.checkpoints(job_key,source,request,status)
            VALUES(%s,'fred-alfred',%s,'pending') ON CONFLICT DO NOTHING''',
            (digest({'source':'fred-alfred',**request}),Jsonb(request)))
    conn.commit()
    for request in requests_to_make:
        series_id = request['series_id']
        try:
            count = import_pages(conn,'fred-alfred',request,fred_get,
                                 lambda db,payload,params,page: save_macro(db,payload,params['series_id'],page),refresh=refresh)
            print(json.dumps({'source':'fred-alfred','series_id':series_id,'received':count}))
        except Exception as exc:
            failures.append({'source':'fred-alfred','series_id':series_id,'type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)})
            if not os.getenv('FRED_API_KEY') or getattr(exc,'status_code',None) in (400,401,403):
                break
        time.sleep(0.6)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description='Separate PostgreSQL research history; no trading calls.')
    parser.add_argument('command',choices=('init','import','coverage'))
    parser.add_argument('--source',choices=('all','alpaca','fred'),default='all')
    parser.add_argument('--start',type=date.fromisoformat,default=date(2007,1,1))
    parser.add_argument('--end',type=date.fromisoformat,default=datetime.now(ZoneInfo('Europe/Berlin')).date())
    parser.add_argument('--feed',choices=('sip','iex'),default='sip',help='Exact requested feed; no automatic fallback')
    parser.add_argument('--symbols',default=','.join(SYMBOLS))
    parser.add_argument('--fred-series',default=','.join(FRED_SERIES))
    parser.add_argument('--refresh',action='store_true',help='Re-fetch completed jobs and preserve changed revisions')
    args = parser.parse_args(argv)
    if args.start>args.end:
        parser.error('--start must be before --end')
    symbols = tuple(x.strip().upper() for x in args.symbols.split(',') if x.strip())
    series = tuple(x.strip() for x in args.fred_series.split(',') if x.strip())
    if not symbols or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',symbol) for symbol in symbols):
        parser.error('--symbols requires valid comma-separated US equity symbols')
    if not series or any(not re.fullmatch(r'[A-Za-z0-9_]+',item) for item in series):
        parser.error('--fred-series requires valid comma-separated FRED series IDs')
    from dotenv import load_dotenv
    load_dotenv(override=False)
    failures = []
    with connect() as conn:
        initialize(conn)
        if args.command=='import':
            # Prevent two workers from racing the same checkpoint within this database.
            if not conn.execute('SELECT pg_try_advisory_lock(7070601) AS locked').fetchone()['locked']:
                raise RuntimeError('Analytics import is already running')
            conn.commit()
            if args.source in ('all','alpaca'):
                try:
                    failures.extend(import_alpaca(conn,args.start,args.end,args.feed,
                                                 symbols,args.refresh))
                except Exception as exc:
                    conn.rollback()
                    request = {'start':args.start.isoformat(),'end':args.end.isoformat()}
                    record_page(conn,'alpaca-calendar',request,{'error':safe_error(exc)},getattr(exc,'status_code',None) or 0)
                    checkpoint(conn,digest({'source':'alpaca-calendar',**request}),'alpaca-calendar',request,None,'error',error=safe_error(exc))
                    conn.commit()
                    failures.append({'source':'alpaca-calendar','type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)})
            if args.source in ('all','fred'):
                failures.extend(import_fred(conn,args.start,args.end,
                                            series,args.refresh))
        if args.command in ('import','coverage'):
            print(json.dumps({'coverage':coverage(conn,args.feed),'failures':failures},default=str,indent=2))
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
