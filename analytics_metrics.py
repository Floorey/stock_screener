"""Descriptive stress measures. Missing observations stay missing; no forecast model."""
import numpy as np
import pandas as pd
import json
from pathlib import Path

from analytics_store import SECTORS


def detect_stress_events(bars, session_dates=None, rules=None):
    rules = rules or json.loads(Path(__file__).with_name('analytics_rules.json').read_text())
    if bars.empty:
        return []
    frame = bars[bars['symbol']==rules['symbol']].copy()
    if frame.empty:
        return []
    frame['date'] = pd.to_datetime(frame['event_at'],utc=True).dt.tz_convert('America/New_York').dt.date
    prices = frame.set_index('date')['close'].sort_index()
    if session_dates is not None:
        prices = prices.reindex(sorted(session_dates))
    daily = prices.pct_change(fill_method=None)*100
    five = ((daily/100+1).rolling(5,min_periods=5).apply(np.prod,raw=True)-1)*100
    events = []
    for day in prices.index:
        reasons = []
        if daily.loc[day]<=rules['daily_return_pct_lte']:
            reasons.append(f"1T {daily.loc[day]:.2f}%")
        if five.loc[day]<=rules['five_session_return_pct_lte']:
            reasons.append(f"5T {five.loc[day]:.2f}%")
        if reasons:
            events.append({'id':f"{rules['version']}:{day}",'date':day.isoformat(),
                           'name':f"Regelereignis {rules['symbol']} · "+', '.join(reasons),
                           'rule_version':rules['version']})
    return events


def daily_stress(bars, session_dates=None):
    if bars.empty:
        return pd.DataFrame()
    frame = bars.copy()
    frame['date'] = pd.to_datetime(frame['event_at'],utc=True).dt.tz_convert('America/New_York').dt.date
    prices = frame.pivot(index='date',columns='symbol',values='close').sort_index()
    if session_dates is not None:
        prices = prices.reindex(sorted(session_dates))
    returns = prices.pct_change(fill_method=None)
    result = pd.DataFrame(index=prices.index)
    if 'SPY' in prices:
        result['SPY Tagesrendite %'] = returns['SPY']*100
        result['SPY Verlust %'] = (-returns['SPY']*100).clip(lower=0)
        result['SPY RV 21T p.a. %'] = np.log(prices['SPY']).diff().rolling(21,min_periods=21).std(ddof=1)*np.sqrt(252)*100
    sector_returns = returns.reindex(columns=list(SECTORS))
    complete = sector_returns.notna().all(axis=1)
    result['Sektoren beobachtet'] = sector_returns.notna().sum(axis=1)
    result['Sektorbreite negativ %'] = ((sector_returns<0).sum(axis=1)/len(SECTORS)*100).where(complete)
    correlations = pd.Series(np.nan,index=prices.index,dtype=float)
    for offset in range(19,len(sector_returns)):
        window = sector_returns.iloc[offset-19:offset+1]
        if window.notna().all().all():
            matrix = window.corr().to_numpy()
            upper = matrix[np.triu_indices(len(SECTORS),k=1)]
            if np.isfinite(upper).all():
                correlations.iloc[offset] = upper.mean()
    result['Mittlere Sektorkorrelation 20T'] = correlations
    return result


def intraday_stress(bars, sessions):
    if bars.empty or sessions.empty:
        return pd.DataFrame()
    frame = bars.copy()
    frame['event_at'] = pd.to_datetime(frame['event_at'],utc=True)
    output = []
    for session in sessions.to_dict('records'):
        opening,closing = pd.Timestamp(session['opens_at']),pd.Timestamp(session['closes_at'])
        expected = int((closing-opening).total_seconds()/60)
        day = frame[(frame['event_at']>=opening)&(frame['event_at']<closing)]
        for symbol,group in day.groupby('symbol'):
            group = group.sort_values('event_at')
            close = group['close'].astype(float)
            expected_times = pd.date_range(opening,closing,freq='min',inclusive='left')
            complete = len(group)==expected and pd.DatetimeIndex(group['event_at']).equals(expected_times)
            # Opening price supplies the first minute return and the first high-water mark.
            path = pd.Series([float(group['open'].iloc[0]),*close.tolist()])
            drawdown = (path/path.cummax()-1).min()*100
            rv = np.sqrt(np.square(np.log(path).diff().dropna()).sum())*100
            output.append({'Datum':session['session_date'],'Symbol':symbol,'Minuten':len(group),
                           'Erwartete Minuten':expected,'Vollständig':complete,
                           'Beobachteter Close-Drawdown %':drawdown,
                           'Realisierte Tagesvolatilität %':rv if complete else np.nan})
    return pd.DataFrame(output)


def event_window(bars, event_date, before=20, after=20, session_dates=None):
    """Trading-session offsets; zero is the first observed date on/after the event."""
    if bars.empty:
        return pd.DataFrame()
    frame = bars.copy()
    frame['date'] = pd.to_datetime(frame['event_at'],utc=True).dt.tz_convert('America/New_York').dt.date
    prices = frame.pivot(index='date',columns='symbol',values='close').sort_index()
    if session_dates is not None:
        prices = prices.reindex(sorted(session_dates))
    event = pd.Timestamp(event_date).date()
    candidates = np.flatnonzero(np.array(prices.index)>=event)
    if not len(candidates):
        return pd.DataFrame()
    anchor = int(candidates[0])
    if anchor==0:
        return pd.DataFrame()
    selected = prices.iloc[max(0,anchor-before):anchor+after]
    baseline = prices.iloc[anchor-1]
    result = (selected/baseline-1)*100
    result.insert(0,'Handelstage relativ',np.arange(max(0,anchor-before)-anchor,len(selected)+max(0,anchor-before)-anchor))
    result.attrs['event_session'] = prices.index[anchor]
    result.attrs['before_observed'] = int(selected.iloc[:min(before,anchor)].notna().any(axis=1).sum())
    result.attrs['after_observed'] = int(selected.iloc[min(before,anchor):].notna().any(axis=1).sum())
    return result
