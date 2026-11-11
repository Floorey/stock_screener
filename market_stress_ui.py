"""Streamlit research tab, reads only the independent analytics PostgreSQL store."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from analytics_metrics import daily_stress, detect_stress_events, event_window, intraday_stress
from analytics_store import FRED_SERIES, connect, coverage, macro_asof


def render_market_stress_tab():
    today = datetime.now(ZoneInfo('Europe/Berlin')).date()
    st.subheader('Marktstress · historische Datenbasis')
    st.caption('Deskriptive Analyse; kein kalibriertes Prognosemodell. Historische Kursdaten belegen keine damalige Verfügbarkeit.')
    feed = st.selectbox('Exakter Datenfeed',('sip','iex'),key='stress_feed')
    st.caption('SIP und IEX bleiben getrennt. IEX bildet nur einen Handelsplatz ab; Datenlücken werden nicht ersetzt.')
    try:
        with connect() as conn:
            status = coverage(conn,feed)
            st.write('Datenabdeckung')
            if not status['calendar']['sessions']:
                st.warning('Noch kein Börsenkalender importiert. Erwartete Abdeckung kann nicht berechnet werden.')
            else:
                st.caption(f"Kalender: {status['calendar']['first_session']} bis {status['calendar']['last_session']}; Minutenfenster: letzte 30 vollständig geschlossene Sitzungen dieses Kalenders.")
            st.dataframe(pd.DataFrame(status['matrix']),use_container_width=True,hide_index=True)
            if status['gaps']:
                st.warning('Importaufträge sind unvollständig oder fehlgeschlagen. Berechtigungen, Feed und Konfiguration prüfen.')
                st.dataframe(pd.DataFrame(status['gaps']),use_container_width=True,hide_index=True)
            with st.expander('Importjournal und Makroabdeckung'):
                st.dataframe(pd.DataFrame(status['jobs']),use_container_width=True)
                macro = pd.DataFrame(status['macro'])
                st.dataframe(macro,use_container_width=True)
                available = set(macro['series_id']) if not macro.empty else set()
                absent = sorted(set(FRED_SERIES)-available)
                if absent:
                    st.warning('FRED/ALFRED fehlt: '+', '.join(absent))
            span = st.date_input('Analysezeitraum',(today-timedelta(days=365),today),key='stress_dates')
            if not isinstance(span,(tuple,list)) or len(span)!=2:
                return
            start,end = span
            query = '''SELECT symbol,event_at,open,close FROM analytics.latest_bars
                WHERE timeframe=%s AND feed=%s AND adjustment='all'
                AND (event_at AT TIME ZONE 'America/New_York')::date BETWEEN %s AND %s
                ORDER BY event_at,symbol'''
            # Extra preceding sessions keep rolling features independent of the display start.
            daily = pd.DataFrame(conn.execute(query,('1Day',feed,start-timedelta(days=90),end)).fetchall())
            if daily.empty:
                st.info('Für diese Auswahl fehlen Tageskurse. Import über analytics_import.py starten.')
                return
            dates = [row['session_date'] for row in conn.execute('SELECT session_date FROM analytics.sessions WHERE session_date BETWEEN %s AND %s ORDER BY session_date',(start-timedelta(days=90),end)).fetchall()]
            stress = daily_stress(daily,dates)
            stress = stress.loc[(stress.index>=start)&(stress.index<=end)]
            if 'SPY Tagesrendite %' in stress:
                st.line_chart(stress[['SPY Tagesrendite %','SPY RV 21T p.a. %']])
            st.dataframe(stress,use_container_width=True)
            st.caption('RV: Standardabweichung täglicher Logrenditen über 21 Sitzungen × √252. Breite und Korrelation benötigen alle 11 Sektoren; fehlende Werte bleiben leer.')
            minutes = pd.DataFrame(conn.execute(query,('1Min',feed,start,end)).fetchall())
            sessions = pd.DataFrame(conn.execute('''SELECT session_date,opens_at,closes_at FROM analytics.sessions
                WHERE session_date BETWEEN %s AND %s ORDER BY session_date''',(start,end)).fetchall())
            intraday = intraday_stress(minutes,sessions)
            st.write('Intraday · reguläre Sitzung')
            if intraday.empty:
                st.info('Keine Minutenkurse für diese Auswahl vorhanden.')
            else:
                st.dataframe(intraday,use_container_width=True,hide_index=True)
            st.caption('Drawdown: beobachtete Minuten-Schlusskurse ab Sitzungsöffnung. Bei Lücken nur Untergrenze der Verlusttiefe; Tagesvolatilität bleibt dann leer. Kein Tick-Drawdown.')
            catalog = json.loads(Path(__file__).with_name('analytics_events.json').read_text())
            rules = json.loads(Path(__file__).with_name('analytics_rules.json').read_text())
            st.write('Historische Ereignisfenster')
            st.caption(f"Katalog {catalog['version']}: {catalog['selection']}")
            rule_bars = pd.DataFrame(conn.execute("SELECT symbol,event_at,close FROM analytics.latest_bars WHERE symbol=%s AND timeframe='1Day' AND feed=%s AND adjustment='all' ORDER BY event_at",(rules['symbol'],feed)).fetchall())
            rule_dates = [row['session_date'] for row in conn.execute('SELECT session_date FROM analytics.sessions WHERE closes_at<=now() ORDER BY session_date').fetchall()]
            detected = detect_stress_events(rule_bars,rule_dates,rules)
            st.caption(f"{rules['version']}: {rules['description']} {len(detected)} Tage erkannt.")
            events = sorted(catalog['events']+detected,key=lambda item:item['date'],reverse=True)
            event = st.selectbox('Ereignis',events,format_func=lambda item:f"{item['date']} · {item['name']}",key='stress_event')
            if event.get('source'):
                st.markdown(f"[Primärquelle]({event['source']})")
            day = date.fromisoformat(event['date'])
            historical = pd.DataFrame(conn.execute(query,('1Day',feed,day-timedelta(days=100),day+timedelta(days=100))).fetchall())
            event_dates = [row['session_date'] for row in conn.execute('SELECT session_date FROM analytics.sessions WHERE session_date BETWEEN %s AND %s ORDER BY session_date',(day-timedelta(days=100),day+timedelta(days=100))).fetchall()]
            window = event_window(historical,day,session_dates=event_dates)
            if window.empty:
                st.warning('Für das Ereignis fehlen Kurse einschließlich des vorherigen Schlusskurses. Keine Ersatzdaten.')
            else:
                st.caption(f"t=0: {window.attrs['event_session']}; vorher {window.attrs['before_observed']}/20, ab Ereignis {window.attrs['after_observed']}/20 beobachtete Sitzungen. Renditen relativ zum Schlusskurs t=-1.")
                assets = [x for x in ('SPY','QQQ','DIA','IWM','TLT','GLD') if x in window]
                st.line_chart(window.set_index('Handelstage relativ')[assets])
                st.dataframe(window,use_container_width=True)
            with st.expander('Makrodaten: damaliger Datenstand'):
                vintage_day = st.date_input('Informationsstand (Tagesende New York)',today,key='stress_vintage')
                series = st.selectbox('FRED-Reihe',FRED_SERIES,key='stress_macro')
                from analytics_store import vintage_available
                observations = macro_asof(conn,series,vintage_available(vintage_day.isoformat()))
                st.caption('ALFRED-Vintages haben Tagesgenauigkeit. Konservativ erst ab dem nächsten New-York-Mitternachtstermin verfügbar; genaue Veröffentlichungsuhrzeiten sind unbekannt.')
                if observations:
                    st.dataframe(pd.DataFrame(observations),use_container_width=True,hide_index=True)
                else:
                    st.info('Für diesen Informationsstand sind keine Vintages importiert.')
    except Exception as exc:
        st.error(f'Analysedatenbank nicht verfügbar oder Schema nicht initialisiert ({type(exc).__name__}).')
        st.info('ANALYTICS_DATABASE_URL konfigurieren; anschließend analytics_import.py init und import ausführen.')
