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
        res_df = se.scan_pair_universe(pairs_list=pairs, rolling_window=15, entry_z=1.5)
        
        self.assertIsInstance(res_df, pl.DataFrame)
        self.assertGreaterEqual(res_df.height, 2)
        
        cols = res_df.columns
        self.assertIn("ticker_a", cols)
        self.assertIn("ticker_b", cols)
        self.assertIn("current_zscore", cols)
        self.assertIn("signal", cols)
        self.assertIn("sharpe_ratio", cols)
        print("  ✓ scan_pair_universe test passed cleanly.")

    @patch("alpaca_trader.is_alpaca_configured", return_value=True)
    @patch("alpaca_trader.place_order")
    def test_place_statarb_pair_order_success(self, mock_place_order, mock_is_config):
        """Tests place_statarb_pair_order dispatching dual leg orders to Alpaca."""
        mock_place_order.side_effect = [
            {"status": "success", "order": {"id": "ord_1", "symbol": "NVDA", "qty": "50", "side": "buy"}},
            {"status": "success", "order": {"id": "ord_2", "symbol": "VRT", "qty": "62", "side": "sell"}}
        ]
        
        res = at.place_statarb_pair_order(
            ticker_a="NVDA",
            ticker_b="VRT",
            side="LONG_SPREAD",
            total_capital_usd=10000.0,
            price_a=100.0,
            price_b=80.0,
            hedge_ratio_beta=1.0,
            order_type="market"
        )
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ticker_a"], "NVDA")
        self.assertEqual(res["ticker_b"], "VRT")
        self.assertEqual(res["side_a"], "buy")
        self.assertEqual(res["side_b"], "sell")
        self.assertEqual(res["qty_a"], 50.0)
        self.assertEqual(res["qty_b"], 62.0)
        self.assertEqual(mock_place_order.call_count, 2)
        print("  ✓ place_statarb_pair_order success test passed cleanly.")

    def test_place_statarb_pair_order_unconfigured(self):
        """Tests error response when Alpaca API keys are missing."""
        with patch("alpaca_trader.is_alpaca_configured", return_value=False):
            res = at.place_statarb_pair_order("NVDA", "VRT", "LONG_SPREAD")
            self.assertEqual(res["status"], "error")
            self.assertIn("not configured", res["message"])
        print("  ✓ place_statarb_pair_order unconfigured test passed cleanly.")


if __name__ == "__main__":
    unittest.main()
