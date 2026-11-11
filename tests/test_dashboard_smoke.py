"""Original dashboard renders offline; no account calls or side effects permitted."""
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import requests
from streamlit.testing.v1 import AppTest


class DashboardSmoke(unittest.TestCase):
    def test_original_tabs_and_new_stress_render_without_credentials(self):
        ticker = MagicMock()
        ticker.info = {}
        ticker.history.return_value = pd.DataFrame()
        ticker.options = []
        ticker.news = []
        ticker.calendar = {}
        with patch.dict(os.environ, {}, clear=True), \
             patch('dotenv.load_dotenv', return_value=False), \
             patch('alpaca_trader.load_paper_credentials'), \
             patch('requests.sessions.Session.request', side_effect=requests.ConnectionError('offline test')), \
             patch('yfinance.download', return_value=pd.DataFrame()), \
             patch('yfinance.Ticker', return_value=ticker), \
             patch('token_tracker_ui.render_token_tracker_tab', return_value=None):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=45).run()
        self.assertEqual([e.message for e in app.exception], [])
        labels = [tab.label for tab in app.tabs]
        for label in ('🎯 Screener Dashboard', '⭐ Watchlist Manager',
                      '📄 PDF Finanzbericht Analyzer'):
            self.assertIn(label, labels)
        self.assertTrue(any('Marktstress' in label for label in labels))
        self.assertIn('🔮 Prognose', labels)


if __name__ == '__main__':
    unittest.main()
