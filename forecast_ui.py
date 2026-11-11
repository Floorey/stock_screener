"""Explicit user-triggered forecasts; no model calls during Streamlit rendering."""
import pandas as pd
import streamlit as st
from forecast_client import prepare_context, predict_context


def trend_assessment(bars):
    if len(bars) < 25:
        return 'Nicht verfügbar', None, None
    change = (bars[-1]['close'] / bars[-21]['close'] - 1) * 100
    recent = sum(b['volume'] for b in bars[-5:]) / 5
    previous = sum(b['volume'] for b in bars[-25:-5]) / 20
    ratio = recent / previous if previous > 0 else None
    trend = 'Bullish' if change > 0 else 'Bearish' if change < 0 else 'Neutral'
    return trend, change, ratio


def render_forecast_tab():
    st.subheader('Prognose · Kronos / Timestral')
    st.caption('US-Aktien/ETFs · Tagesdaten · 120 abgeschlossene Börsensitzungen. Experimentelle Prognosen, keine kalibrierten Handelssignale.')
    with st.container():
        source=st.selectbox('Datenquelle',('alpaca','db'),format_func=lambda x:'Alpaca direkt' if x=='alpaca' else 'Datenbank',key='forecast_source')
        symbol=st.text_input('Ticker',value='SPY',key='forecast_symbol').strip().upper()
        feed=st.selectbox('Datenfeed',('iex','sip'),key='forecast_feed')
        model=st.selectbox('Modell',('kronos','timestral','combined'),format_func=lambda x:{'kronos':'Kronos','timestral':'Timestral','combined':'Beide'}[x],key='forecast_model')
        horizon=st.number_input('Handelssitzungen',min_value=1,max_value=20,value=5,step=1,key='forecast_horizon')
        load=st.button('Daten laden', key='forecast_load')
    current=dict(symbol=symbol,feed=feed,horizon=horizon,source=source)
    if load:
        st.session_state.pop('forecast_context',None)
        st.session_state.pop('forecast_output',None)
        try:
            with st.spinner('Kursdaten werden geladen …'):
                st.session_state['forecast_context']=prepare_context(**current)
        except Exception as exc:
            st.error(str(exc))
    context=st.session_state.get('forecast_context')
    if not context:
        st.info('„Daten laden“ ruft Alpaca direkt oder die ausdrücklich gewählte Datenbank ab. Ein Prognosedienst ist dafür nicht nötig.')
        return
    stale=current!=context['selection']
    if stale:
        st.warning('Die geladenen Daten gehören zur vorherigen Auswahl. Bitte erneut Daten laden.')
    bars=context['payload']['bars']
    st.caption(f"Geladene Daten: {context['selection']['symbol']} · Quelle {context['selection']['source']} · Feed {context['selection']['feed']} · Adjustment all · {len(bars)} Sitzungen · Stand {bars[-1]['time']}")
    history_frame=pd.DataFrame(bars)
    history_frame.index=pd.to_datetime(history_frame['time'],utc=True)
    st.line_chart(history_frame[['close']])
    trend, change, volume_ratio = trend_assessment(bars)
    if change is None:
        st.info('Trendbewertung benötigt mindestens 25 Sitzungen.')
    else:
        volume_text = f'{volume_ratio:.2f}×' if volume_ratio is not None else 'nicht verfügbar'
        st.write(f'**Trend: {trend}** · Kurs über 20 Sitzungen: {change:+.2f} % · Volumen: {volume_text} des vorherigen 20-Tage-Durchschnitts')
        st.caption('Volumen: Durchschnitt der letzten 5 Sitzungen gegenüber den 20 Sitzungen davor. Die Bewertung beschreibt historische Daten, keine Prognose.')
    if st.button('Prognose berechnen', key='forecast_submit',disabled=stale):
        st.session_state.pop('forecast_output',None)
        try:
            with st.spinner('Prognose wird berechnet …'):
                st.session_state['forecast_output']=predict_context(context,model)
        except Exception as exc:
            st.error(str(exc))
    output=st.session_state.get('forecast_output')
    if not output:
        return
    if stale or output['selection']['model']!=model:
        st.warning('Angezeigte Prognose gehört zur vorherigen Auswahl.')
    selection=output['selection'];payload=output['payload'];result=output['result']
    st.caption(f"Ergebnis: {selection['symbol']} · Feed {selection['feed']} · Adjustment all · {selection['horizon']} Sitzungen · Datenstand {payload['bars'][-1]['time']}")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4))
    def day(value): return pd.Timestamp(value).tz_convert('America/New_York').date()
    history=payload['bars'][-40:]
    ax.plot([day(b['time']) for b in history],[b['close'] for b in history],label='Historischer Schlusskurs',color='gray')
    names=('kronos','timestral') if selection['model']=='combined' else (selection['model'],)
    for name in names:
        part=result[name] if selection['model']=='combined' else result
        rows=part['predicted_candles'] if name=='kronos' else part['quantile_forecast']
        dates=[day(r['predicted_time']) for r in rows]
        values=[r['close' if name=='kronos' else 'p50'] for r in rows]
        ax.plot([day(history[-1]['time'])]+dates,[history[-1]['close']]+values,label='Kronos Close' if name=='kronos' else 'Timestral P50')
        if name=='timestral':
            ax.fill_between(dates,[r['p10'] for r in rows],[r['p90'] for r in rows],alpha=.2,label='P10–P90 · nominal 80 %')
        st.caption(f"{name}: {part['model']} · erstellt {part['generated_at']} · {part['input_bars_count']} Eingabekerzen")
        st.dataframe(pd.DataFrame(rows).drop(columns=['confidence','mean'],errors='ignore'),hide_index=True,use_container_width=True)
    ax.set_ylabel('USD');ax.legend();fig.autofmt_xdate();fig.tight_layout()
    st.pyplot(fig);plt.close(fig)
    st.caption('Prognoseband ist nicht empirisch kalibriert. Kalender und Feed werden nicht automatisch ersetzt.')
