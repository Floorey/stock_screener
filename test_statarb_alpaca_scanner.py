"""
test_statarb_alpaca_scanner.py - Automated Unit & Integration Tests for Scanner and Alpaca Order Dispatcher
"""
import sys
import unittest
import polars as pl
import pandas as pd
from unittest.mock import patch, MagicMock

import statarb_engine as se
import alpaca_trader as at


class TestStatArbScannerAndAlpaca(unittest.TestCase):
    def test_scan_pair_universe(self):
        """Tests scan_pair_universe returning ranked sector pairs with Z-scores and signals."""
        pairs = [
            ("NVDA", "VRT", "AI Compute"),
            ("AAPL", "MSFT", "Tech Giants")
        ]
        data = {ticker: se.generate_synthetic_ohlcv(ticker) for a, b, _ in pairs for ticker in (a, b)}
        res_df = se.scan_pair_universe(pairs_list=pairs, rolling_window=15, entry_z=1.5, data_provider=data)
        
        self.assertIsInstance(res_df, pl.DataFrame)
        self.assertGreaterEqual(res_df.height, 2)
        
        cols = res_df.columns
        self.assertIn("ticker_a", cols)
        self.assertIn("ticker_b", cols)
        self.assertIn("current_zscore", cols)
        self.assertIn("signal", cols)
        self.assertIn("sharpe_ratio", cols)
        print("  ✓ scan_pair_universe test passed cleanly.")

    def test_legacy_pair_dispatch_is_blocked(self):
        with patch("requests.post") as post:
            result = at.place_statarb_pair_order("NVDA", "VRT", "LONG_SPREAD")
            self.assertEqual(result["status"], "error")
            post.assert_not_called()

    def test_place_statarb_pair_order_unconfigured(self):
        """Tests error response when Alpaca API keys are missing."""
        with patch("alpaca_trader.is_alpaca_configured", return_value=False):
            res = at.place_statarb_pair_order("NVDA", "VRT", "LONG_SPREAD")
            self.assertEqual(res["status"], "error")
            self.assertIn("gesperrt", res["message"])
        print("  ✓ place_statarb_pair_order unconfigured test passed cleanly.")


if __name__ == "__main__":
    unittest.main()
