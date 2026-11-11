from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import alpaca_trader as at
from paper_order_ui import stage_option, _apply_selection
from streamlit.testing.v1 import AppTest


CONTRACT = {"symbol": "SPY991231C00500000", "underlying_symbol": "SPY",
            "expiration_date": "2099-12-31", "type": "call", "strike_price": "500",
            "status": "active", "tradable": True, "size": "100"}


class OptionCatalogTests(unittest.TestCase):
    def test_all_pages_and_explicit_expiry_window(self):
        second = {**CONTRACT, "symbol": "SPY991231C00510000", "strike_price": "510"}
        seen = []
        def read(path, params):
            seen.append((path, deepcopy(params)))
            return {"option_contracts": [second] if params.get("page_token") else [CONTRACT],
                    "next_page_token": None if params.get("page_token") else "next"}
        with patch.object(at, "broker_get", side_effect=read):
            result = at.list_option_contracts("SPY", "2099-12-01", "2099-12-31")
        self.assertEqual([r["symbol"] for r in result], [CONTRACT["symbol"], second["symbol"]])
        self.assertEqual(seen[0][1]["expiration_date_lte"], "2099-12-31")
        self.assertEqual(seen[1][1]["page_token"], "next")

    def test_invalid_window_and_repeated_cursor_fail(self):
        with patch.object(at, "broker_get") as read:
            for symbol, start, end in (("SPY/../account", "2099-12-01", "2099-12-31"),
                                       ("SPY", "2099-01-01", "2099-12-31"),
                                       ("SPY", "2099-12-31", "2099-12-01")):
                with self.assertRaises(at.AlpacaReadError):
                    at.list_option_contracts(symbol, start, end)
            read.assert_not_called()
        with patch.object(at, "broker_get", return_value={"option_contracts": [CONTRACT], "next_page_token": "same"}):
            with self.assertRaises(at.AlpacaReadError):
                at.list_option_contracts("SPY", "2099-12-01", "2099-12-31")

    def test_unknown_eligibility_excluded_and_bad_metadata_rejected(self):
        with patch.object(at, "broker_get", return_value={"option_contracts": [{**CONTRACT, "tradable": None}]}):
            self.assertEqual(at.list_option_contracts("SPY", "2099-12-01", "2099-12-31"), [])
        with patch.object(at, "broker_get", return_value={"option_contracts": [{**CONTRACT, "strike_price": "NaN"}]}):
            with self.assertRaises(at.AlpacaReadError):
                at.list_option_contracts("SPY", "2099-12-01", "2099-12-31")

    def test_single_handoff_and_explicit_combination_legs_never_submit(self):
        state = {"paper_preview": "old-preview"}
        with patch("requests.post", side_effect=AssertionError("must not submit")):
            stage_option(state, CONTRACT["symbol"], "sell", limit="2.5")
            _apply_selection(state)
            self.assertEqual(state["manual_symbol"], CONTRACT["symbol"])
            self.assertEqual(state["manual_position_intent"], "sell_to_open")
            self.assertEqual(state["manual_limit"], "2.5")
            self.assertNotIn("paper_preview", state)
            stage_option(state, CONTRACT["symbol"], "buy", add_leg=True)
            _apply_selection(state)
            stage_option(state, "SPY991231C00510000", "sell", add_leg=True)
            _apply_selection(state)
            self.assertEqual(state["paper_staged_leg_count"], 2)
            self.assertEqual(state["leg_side_0"], "buy")
            self.assertEqual(state["leg_side_1"], "sell")
            self.assertEqual(state["manual_limit"], "")

    def test_broker_search_click_prefills_single_and_multileg_ticket(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {"ALPACA_ORDER_DB": str(Path(folder)/"orders.sqlite"), "ALPACA_TRADING_ENABLED": "true"}), \
             patch.object(at, "is_alpaca_configured", return_value=True), \
             patch.object(at, "get_account_info", return_value={"id": "fixture", "status": "ACTIVE"}), \
             patch.object(at, "get_positions", return_value=[]), \
             patch.object(at, "get_open_orders", return_value=[]), \
             patch.object(at, "list_option_contracts", return_value=[CONTRACT]), \
             patch.object(at, "get_latest_quote", return_value={"bp": 2, "ap": 2.5, "feed": "indicative", "t": "2099-12-30T16:00:00Z"}), \
             patch("requests.post", side_effect=AssertionError("search must not trade")):
            app = AppTest.from_string("from paper_order_ui import render_paper_order_tab\nrender_paper_order_tab()").run()
            search = next(b for b in app.button if b.label == "Handelbare Optionen bei Alpaca suchen")
            search.click().run()
            app.button(key="paper_take_single").click().run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertEqual(app.text_input(key="manual_symbol").value, CONTRACT["symbol"])
            self.assertEqual(app.text_input(key="manual_limit").value, "2.5")
            app.button(key="paper_take_leg").click().run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertEqual(app.text_input(key="leg_symbol_0").value, CONTRACT["symbol"])


if __name__ == "__main__":
    unittest.main()
