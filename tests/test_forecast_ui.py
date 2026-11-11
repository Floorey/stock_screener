import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def context():
    from test_forecast_client import fixture,connection,response
    from forecast_client import load_context
    payload=load_context(connection(fixture()),'SPY','iex',5)
    c=dict(selection=dict(symbol='SPY',feed='iex',horizon=5,source='alpaca'),payload=payload,adjustment='all')
    r=dict(selection={**c['selection'],'model':'kronos'},payload=payload,result=response(payload),adjustment='all')
    return c,r


class TrendTests(unittest.TestCase):
    def test_price_direction_and_volume(self):
        from forecast_ui import trend_assessment
        bars=[{'close':100, 'volume':100} for _ in range(25)]
        bars[-1]['close']=110
        for bar in bars[-5:]: bar['volume']=200
        trend, change, ratio=trend_assessment(bars)
        self.assertEqual(trend, 'Bullish'); self.assertAlmostEqual(change, 10); self.assertEqual(ratio, 2)
        bars[-1]['close']=90
        self.assertEqual(trend_assessment(bars)[0], 'Bearish')
        bars[-1]['close']=100
        self.assertEqual(trend_assessment(bars)[0], 'Neutral')
        for bar in bars[:-5]: bar['volume']=0
        self.assertIsNone(trend_assessment(bars)[2])
        self.assertEqual(trend_assessment(bars[:24])[0], 'Nicht verfügbar')


class ForecastUITests(unittest.TestCase):
    def test_no_call_before_click_and_no_inference_on_load(self):
        c,_=context()
        with patch('forecast_ui.prepare_context',return_value=c) as load,patch('forecast_ui.predict_context') as predict:
            app=AppTest.from_string('from forecast_ui import render_forecast_tab; render_forecast_tab()').run()
            app.run();load.assert_not_called();predict.assert_not_called()
            app.button(key='forecast_load').click().run()
            self.assertEqual(load.call_count,1);predict.assert_not_called()
            self.assertEqual(len(app.exception),0)
            self.assertIn('forecast_context',app.session_state)
            self.assertTrue(any('Trend:' in item.value for item in app.markdown))
            app.run();self.assertEqual(load.call_count,1)
    def test_service_error_keeps_data_and_chart(self):
        c,_=context()
        with patch('forecast_ui.prepare_context',return_value=c),patch('forecast_ui.predict_context',side_effect=ValueError('Prognosedienst nicht erreichbar.')) as predict:
            app=AppTest.from_string('from forecast_ui import render_forecast_tab; render_forecast_tab()').run()
            app.button(key='forecast_load').click().run()
            app.button(key='forecast_submit').click().run()
            self.assertEqual(predict.call_count,1)
            self.assertEqual(len(app.exception),0)
            self.assertIn('nicht erreichbar',app.error[0].value)
            self.assertEqual(len(app.session_state['forecast_context']['payload']['bars']),120)
            self.assertNotIn('forecast_output',app.session_state)
    def test_success_selection_change_requires_reload(self):
        c,r=context()
        with patch('forecast_ui.prepare_context',return_value=c) as load,patch('forecast_ui.predict_context',return_value=r) as predict:
            app=AppTest.from_string('from forecast_ui import render_forecast_tab; render_forecast_tab()').run()
            app.button(key='forecast_load').click().run()
            app.button(key='forecast_submit').click().run()
            self.assertEqual(len(app.exception),0);self.assertEqual(len(app.dataframe),1)
            app.selectbox(key='forecast_source').select('db').run()
            self.assertTrue(app.button(key='forecast_submit').disabled)
            self.assertTrue(any('vorherigen Auswahl' in item.value for item in app.warning))
            self.assertEqual(predict.call_count,1);self.assertEqual(load.call_count,1)


if __name__=='__main__':unittest.main(verbosity=2)
