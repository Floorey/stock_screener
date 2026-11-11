"""Read-only daily-bar forecast request, using the existing analytics store."""
import math
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from analytics_store import connect


def load_context(conn, symbol, feed, horizon):
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}', symbol) or feed not in ('iex','sip') or type(horizon) is not int or not 1 <= horizon <= 20:
        raise ValueError('Ticker, Feed oder Horizont ungültig.')
    now = datetime.now(timezone.utc)
    sessions = conn.execute('SELECT session_date,closes_at FROM analytics.sessions WHERE closes_at<=%s ORDER BY session_date DESC LIMIT 120',(now,)).fetchall()[::-1]
    if len(sessions) != 120:
        raise ValueError('Börsenkalender: 120 abgeschlossene Sitzungen fehlen.')
    # Refuse a truncated historical calendar instead of silently using old data.
    following = conn.execute('SELECT session_date,closes_at FROM analytics.sessions WHERE session_date>%s ORDER BY session_date LIMIT %s', (sessions[-1]['session_date'],horizon)).fetchall()
    if len(following) != horizon or following[0]['closes_at'] <= now:
        raise ValueError('Börsenkalender ist veraltet oder Zukunftsabdeckung fehlt.')
    rows = conn.execute("""SELECT event_at,open,high,low,close,volume FROM analytics.latest_bars
        WHERE symbol=%s AND timeframe='1Day' AND feed=%s AND adjustment='all'
        AND (event_at AT TIME ZONE 'America/New_York')::date BETWEEN %s AND %s ORDER BY event_at""",
        (symbol,feed,sessions[0]['session_date'],sessions[-1]['session_date'])).fetchall()
    return build_context(symbol, feed, horizon, sessions, following, rows)


def build_context(symbol, feed, horizon, sessions, following, rows):
    dates = [r['event_at'].astimezone(ZoneInfo('America/New_York')).date() for r in rows]
    if dates != [s['session_date'] for s in sessions]:
        raise ValueError('Kursdaten unvollständig oder doppelt: 120 lückenlose Tageskerzen benötigt.')
    bars=[]
    for row,session in zip(rows,sessions):
        values={k:float(row[k]) for k in ('open','high','low','close','volume')}
        if not all(math.isfinite(x) for x in values.values()) or min(values[k] for k in ('open','high','low','close'))<=0 or values['volume']<0 or not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
            raise ValueError('Ungültige OHLCV-Kursdaten.')
        bars.append(dict(symbol=symbol,time=session['closes_at'].isoformat(),**values))
    return dict(symbol=symbol,timeframe='1Day',horizon=horizon,bars=bars,
                future_timestamps=[s['closes_at'].isoformat() for s in following])


def load_alpaca_context(symbol, feed, horizon):
    from alpaca_trader import analytics_alpaca_get, load_paper_credentials
    from datetime import timedelta, time
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}',symbol) or feed not in ('iex','sip') or type(horizon) is not int or not 1<=horizon<=20:
        raise ValueError('Ticker, Feed oder Horizont ungültig.')
    load_paper_credentials()
    now=datetime.now(timezone.utc)
    calendar=analytics_alpaca_get('/v2/calendar',{
        'start':(now-timedelta(days=300)).date().isoformat(),
        'end':(now+timedelta(days=45)).date().isoformat()},data_api=False)
    if not isinstance(calendar,list):
        raise ValueError('Alpaca-Börsenkalender hat ein ungültiges Format.')
    try:
        ny=ZoneInfo('America/New_York')
        sessions=[dict(session_date=datetime.fromisoformat(c['date']).date(),
                       closes_at=datetime.combine(datetime.fromisoformat(c['date']).date(),time.fromisoformat(c['close']),ny)) for c in calendar]
        sessions.sort(key=lambda c:c['session_date'])
        if len({c['session_date'] for c in sessions})!=len(sessions):
            raise ValueError('Doppelte Kalendersitzungen.')
        history=[c for c in sessions if c['closes_at']<=now][-120:]
        future=[c for c in sessions if c['closes_at']>now][:horizon]
        if len(history)!=120 or len(future)!=horizon:
            raise ValueError('Alpaca-Börsenkalender bietet nicht genug vergangene/zukünftige Sitzungen.')
        params={'symbols':symbol,'timeframe':'1Day','feed':feed,'adjustment':'all','limit':1000,
                'start':datetime.combine(history[0]['session_date'],time(),ny).isoformat(),
                'end':now.isoformat(),'sort':'asc'}
        rows=[];seen=set()
        for _ in range(20):
            page=analytics_alpaca_get('/v2/stocks/bars',params,data_api=True)
            if not isinstance(page,dict) or not isinstance(page.get('bars'),dict) or not isinstance(page['bars'].get(symbol,[]),list):
                raise ValueError('Alpaca lieferte ungültige Kursdaten.')
            for b in page['bars'].get(symbol,[]):
                stamp=datetime.fromisoformat(b['t'].replace('Z','+00:00'))
                if stamp.tzinfo is None:
                    raise ValueError('Alpaca-Kerze ohne Zeitzone.')
                day=stamp.astimezone(ny).date()
                # Incomplete current sessions are never model context.
                if history[0]['session_date']<=day<=history[-1]['session_date']:
                    rows.append(dict(event_at=stamp,open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']))
            token=page.get('next_page_token')
            if not token:
                break
            if not isinstance(token,str) or token in seen:
                raise ValueError('Alpaca-Pagination ungültig oder wiederholt.')
            seen.add(token);params={**params,'page_token':token}
        else:
            raise ValueError('Alpaca-Pagination überschreitet das Abfragelimit.')
        rows.sort(key=lambda r:r['event_at'])
        return build_context(symbol,feed,horizon,history,future,rows)
    except (KeyError,TypeError,OverflowError) as exc:
        raise ValueError('Alpaca-Daten oder Börsenkalender unvollständig.') from exc


def prepare_context(symbol, feed, horizon, source='alpaca'):
    if source=='alpaca':
        payload=load_alpaca_context(symbol,feed,horizon)
    elif source=='db':
        with connect() as conn:
            payload=load_context(conn,symbol,feed,horizon)
    else:
        raise ValueError('Datenquelle ungültig.')
    return dict(selection=dict(symbol=symbol,feed=feed,horizon=horizon,source=source),
                adjustment='all',payload=payload)


def validate_result(result, payload, model):
    names=('kronos','timestral') if model=='combined' else (model,)
    for name in names:
        part=result[name] if model=='combined' else result
        if part['symbol']!=payload['symbol'] or part['timeframe']!='1Day' or datetime.fromisoformat(part['data_asof'])!=datetime.fromisoformat(payload['bars'][-1]['time']):
            raise ValueError('Prognose passt nicht zur Datenanfrage.')
        if datetime.fromisoformat(part['generated_at']).tzinfo is None:
            raise ValueError('Prognosezeitpunkt ohne Zeitzone.')
        rows=part['predicted_candles'] if name=='kronos' else part['quantile_forecast']
        if len(rows)!=payload['horizon']:
            raise ValueError('Falsche Prognoselänge.')
        for row,target in zip(rows,payload['future_timestamps']):
            if datetime.fromisoformat(row['predicted_time'])!=datetime.fromisoformat(target):
                raise ValueError('Falsche Prognosesitzung.')
            keys=('open','high','low','close','volume') if name=='kronos' else ('p10','p50','p90')
            if not all(type(row[k]) in (int,float) and math.isfinite(row[k]) for k in keys):
                raise ValueError('Nichtendliche Prognosewerte.')
            if name=='timestral' and not 0<=row['p10']<=row['p50']<=row['p90']:
                raise ValueError('Ungültiges Prognoseband.')
            if name=='kronos' and (not 0<row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high'] or row['volume']<0):
                raise ValueError('Ungültige prognostizierte OHLCV-Werte.')
    return result


def predict_context(context, model):
    if model not in ('kronos','timestral','combined'):
        raise ValueError('Modell ungültig.')
    payload=context['payload']
    url=os.getenv('TIMELINE_BASE_URL','http://127.0.0.1:8081').rstrip('/')
    try:
        response=requests.post(url+'/predict/'+model,json=payload,timeout=(5,120),allow_redirects=False)
        if response.status_code!=200:
            reasons={409:'Modell deaktiviert.',422:'Prognoseanfrage abgelehnt.',429:'Modell ist beschäftigt.',503:'Modell nicht bereit oder Inferenz fehlgeschlagen.'}
            raise ValueError(reasons.get(response.status_code,f'Prognosedienst: HTTP {response.status_code}.'))
        result=validate_result(response.json(),payload,model)
    except requests.Timeout as exc:
        raise ValueError('Prognose-Zeitlimit erreicht; laufende Berechnung kann noch aktiv sein. Kein automatischer Wiederholungsauftrag.') from exc
    except requests.RequestException as exc:
        raise ValueError('Prognosedienst nicht erreichbar.') from exc
    except (KeyError,TypeError) as exc:
        raise ValueError('Prognosedienst lieferte ein ungültiges Antwortformat.') from exc
    return dict(selection={**context['selection'],'model':model},
                adjustment='all',payload=payload,result=result)


def request_forecast(symbol, feed, model, horizon, source='db'):
    """Compatibility entry point; the interactive UI defaults to direct Alpaca."""
    if model not in ('kronos','timestral','combined'):
        raise ValueError('Modell ungültig.')
    return predict_context(prepare_context(symbol,feed,horizon,source),model)
