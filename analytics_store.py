"""Independent PostgreSQL research store; no broker/account state or order methods."""
import hashlib
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


SYMBOLS = ('SPY','QQQ','DIA','IWM','XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY',
           'TLT','SHY','HYG','LQD','GLD','USO')
SECTORS = ('XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY')
FRED_SERIES = ('VIXCLS','DGS2','DGS10','T10Y2Y','BAMLH0A0HYM2','BAMLC0A0CM','DFF','UNRATE','CPIAUCSL','INDPRO')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def connect():
    import psycopg
    from psycopg.rows import dict_row
    url = os.getenv('ANALYTICS_DATABASE_URL')
    if not url:
        raise ValueError('ANALYTICS_DATABASE_URL fehlt: separate PostgreSQL-Analysedatenbank konfigurieren.')
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def initialize(conn):
    conn.execute(Path(__file__).with_name('analytics_schema.sql').read_text())
    conn.commit()


def record_page(conn, source, request, response, http_status=200):
    from psycopg.types.json import Jsonb
    row = conn.execute('''INSERT INTO analytics.raw_pages(source,request_key,request,response,response_sha256,http_status)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(source,request_key,response_sha256)
        DO UPDATE SET request_key=EXCLUDED.request_key RETURNING id''',
        (source,digest(request),Jsonb(request),Jsonb(response),digest(response),http_status)).fetchone()
    return row['id']


def checkpoint(conn, key, source, request, cursor, status, count=0, error=None):
    from psycopg.types.json import Jsonb
    conn.execute('''INSERT INTO analytics.checkpoints(job_key,source,request,cursor,status,row_count,error)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(job_key) DO UPDATE SET
        cursor=EXCLUDED.cursor,status=EXCLUDED.status,row_count=analytics.checkpoints.row_count+EXCLUDED.row_count,
        error=EXCLUDED.error,updated_at=now()''',(key,source,Jsonb(request),cursor,status,count,error))


def normalize_bars(payload):
    """Reject malformed provider payloads before committing a page/checkpoint."""
    import math
    rows = []
    if not isinstance(payload.get('bars'), dict):
        raise ValueError('Alpaca response has no bars mapping')
    for symbol, bars in payload['bars'].items():
        for bar in bars or []:
            stamp = datetime.fromisoformat(bar['t'].replace('Z','+00:00'))
            values = tuple(float(bar[field]) for field in ('o','h','l','c','v'))
            o,h,l,c,v = values
            if stamp.tzinfo is None or not all(math.isfinite(x) for x in values) or min(o,h,l,c)<=0 or v<0 or not l<=min(o,c)<=max(o,c)<=h:
                raise ValueError('Invalid OHLCV/timezone in provider bar')
            rows.append((symbol,stamp,*values,digest(bar)))
    return rows


def save_bars(conn, payload, request, page_id):
    rows = normalize_bars(payload)
    with conn.cursor() as cur:
        cur.executemany('''INSERT INTO analytics.bars
          (symbol,timeframe,feed,adjustment,event_at,open,high,low,close,volume,revision_sha256,raw_page_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(symbol,timeframe,feed,adjustment,event_at,revision_sha256)
          DO UPDATE SET last_seen_at=clock_timestamp()''',
          [(s,request['timeframe'],request['feed'],request['adjustment'],t,o,h,l,c,v,sha,page_id)
           for s,t,o,h,l,c,v,sha in rows])
    return len(rows)


def vintage_available(stamp):
    # ALFRED exposes vintage dates, not historical intraday release times.
    return datetime.combine(date.fromisoformat(stamp)+timedelta(days=1),time(),ZoneInfo('America/New_York'))


def save_macro(conn, payload, series_id, page_id):
    import math
    rows = []
    for row in payload['observations']:
        value = None if row['value']=='.' else float(row['value'])
        if value is not None and not math.isfinite(value):
            raise ValueError('Nonfinite macro value')
        rows.append((series_id,row['date'],row['realtime_start'],row['realtime_end'],
                     vintage_available(row['realtime_start']),value,digest(row),page_id))
    with conn.cursor() as cur:
        cur.executemany('''INSERT INTO analytics.macro_observations
          (series_id,observation_date,vintage_start,vintage_end,available_at,value,revision_sha256,raw_page_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(series_id,observation_date,vintage_start,revision_sha256)
          DO UPDATE SET last_seen_at=clock_timestamp()''',rows)
    return len(rows)


def macro_asof(conn, series_id, asof):
    """No revised value may cross its vintage availability boundary."""
    return conn.execute('''SELECT DISTINCT ON(observation_date) observation_date,value,vintage_start,available_at
        FROM analytics.macro_observations WHERE series_id=%s AND available_at<=%s
        ORDER BY observation_date,vintage_start DESC,last_seen_at DESC''',(series_id,asof)).fetchall()


def coverage(conn, feed='sip'):
    bars = conn.execute('''SELECT symbol,timeframe,feed,adjustment,count(*) AS observed_bars,
        min(event_at) AS first_bar,max(event_at) AS last_bar,max(last_seen_at) AS last_import
        FROM analytics.latest_bars WHERE feed=%s GROUP BY symbol,timeframe,feed,adjustment ORDER BY timeframe,symbol''',(feed,)).fetchall()
    jobs = conn.execute('''SELECT source,status,count(*) AS jobs,sum(row_count) AS received_rows,
        max(updated_at) AS updated_at FROM analytics.checkpoints GROUP BY source,status ORDER BY source,status''').fetchall()
    errors = conn.execute('''SELECT source,request,status,error,updated_at FROM analytics.checkpoints
        WHERE status<>'complete' ORDER BY updated_at DESC LIMIT 50''').fetchall()
    matrix = conn.execute('''WITH recent AS (SELECT * FROM analytics.sessions WHERE closes_at<=now() ORDER BY session_date DESC LIMIT 30),
      expected AS (
        SELECT '1Day' AS timeframe,count(*)::bigint AS expected_bars FROM analytics.sessions WHERE closes_at<=now()
        UNION ALL SELECT '1Min',coalesce(sum(extract(epoch FROM(closes_at-opens_at))/60),0)::bigint FROM recent
      ), observed AS (
        SELECT b.symbol,b.timeframe,count(*)::bigint AS observed_bars FROM analytics.latest_bars b
        WHERE b.feed=%s AND b.adjustment='all' AND
        ((b.timeframe='1Day' AND EXISTS(SELECT 1 FROM analytics.sessions s WHERE s.closes_at<=now() AND s.session_date=(b.event_at AT TIME ZONE 'America/New_York')::date))
        OR (b.timeframe='1Min' AND EXISTS(SELECT 1 FROM recent s WHERE b.event_at>=s.opens_at AND b.event_at<s.closes_at)))
        GROUP BY b.symbol,b.timeframe
      ) SELECT symbol,e.timeframe,e.expected_bars,coalesce(o.observed_bars,0) AS observed_bars,
        greatest(0,e.expected_bars-coalesce(o.observed_bars,0)) AS missing_bars
      FROM unnest(%s::text[]) AS universe(symbol) CROSS JOIN expected e LEFT JOIN observed o USING(symbol,timeframe)
      ORDER BY e.timeframe,symbol''',(feed,list(SYMBOLS))).fetchall()
    macro = conn.execute('''SELECT series_id,count(*) AS vintage_rows,count(DISTINCT observation_date) AS observations,
        min(observation_date) AS first_observation,max(observation_date) AS last_observation,
        max(vintage_start) AS last_vintage,count(*) FILTER(WHERE value IS NULL) AS missing_values
        FROM analytics.macro_observations GROUP BY series_id ORDER BY series_id''').fetchall()
    calendar = conn.execute('SELECT min(session_date) AS first_session,max(session_date) AS last_session,count(*) AS sessions FROM analytics.sessions WHERE closes_at<=now()').fetchone()
    return {'bars':bars,'jobs':jobs,'gaps':errors,'matrix':matrix,'macro':macro,'calendar':calendar}
