from datetime import datetime, timezone
import concurrent.futures
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import alpaca_trader as at
import paper_orders as po


class PaperTradingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            "ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret",
            "ALPACA_BASE_URL": at.PAPER_URL, "ALPACA_TRADING_ENABLED": "true",
            "ALPACA_ACCOUNT_ID": "paper-test-account",
            "ALPACA_ORDER_DB": os.path.join(self.tmp.name, "orders.sqlite"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.account = {"id": "paper-test-account", "status": "ACTIVE", "cash": "100000",
                        "buying_power": "100000", "options_buying_power": "100000",
                        "options_trading_level": 3}
        self.ac = patch.object(at, "get_account_info", return_value=self.account).start()
        self.positions = patch.object(at, "get_positions", return_value=[]).start()
        self.get_order = patch.object(at, "get_order", return_value={"id": "broker-1", "status": "accepted"}).start()
        self.orders = patch.object(at, "get_open_orders", return_value=[]).start()
        self.asset = patch.object(at, "get_asset", return_value={"tradable": True, "fractionable": True,
                                                                "shortable": True, "easy_to_borrow": True}).start()
        self.quote = patch.object(at, "get_latest_quote", side_effect=lambda *a, **k: {"bp": 99, "ap": 101, "bs": 100, "as": 100, "t": datetime.now(timezone.utc).isoformat(), "feed": "iex"}).start()
        self.contract = patch.object(at, "get_option_contract", side_effect=lambda s: {
            "symbol": s, "status": "active", "tradable": True, "size": "100",
            "underlying_symbol": "SPY", "expiration_date": "2099-12-31", "type": "call",
            "strike_price": "500" if "00500000" in s else "510"}).start()
        self.addCleanup(patch.stopall)

    def preview(self):
        return po.preview_order({"symbol": "SPY", "qty": 1, "side": "buy", "type": "limit",
                                 "limit_price": "100", "time_in_force": "day"})

    def test_endpoint_rejects_live_and_redirect_destination(self):
        for endpoint in ("https://api.alpaca.markets", at.PAPER_URL + ".evil", at.PAPER_URL + "/v2", "http://paper-api.alpaca.markets"):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"ALPACA_BASE_URL": endpoint}):
                with self.assertRaises(at.AlpacaReadError):
                    at.get_alpaca_credentials()

    def test_legacy_write_paths_are_blocked_even_when_gate_enabled(self):
        with patch.object(requests, "post") as post, patch.object(requests, "delete") as delete:
            self.assertEqual(at.place_order("SPY", 1, "buy")["status"], "error")
            self.assertFalse(at.close_position("SPY"))
            self.assertFalse(at.cancel_order("order"))
            self.assertEqual(at.place_statarb_pair_order("SPY", "QQQ", "LONG_SPREAD")["status"], "error")
            post.assert_not_called()
            delete.assert_not_called()

    def test_gate_and_confirmation_required(self):
        p = self.preview()
        with patch.dict(os.environ, {"ALPACA_TRADING_ENABLED": "false"}), patch.object(requests, "post") as post:
            with self.assertRaises(po.OrderError):
                po.confirm_order(p["intent_id"], confirmed=True)
            post.assert_not_called()
        with self.assertRaises(po.OrderError):
            po.confirm_order(p["intent_id"], confirmed=False)

    def test_preview_integer_and_fractional_validation(self):
        self.assertEqual(self.preview()["payload"]["qty"], "1")
        for qty in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(qty=qty), self.assertRaises(po.OrderError):
                po.preview_order({"symbol": "SPY", "qty": qty, "side": "buy", "type": "market", "time_in_force": "day"})

    def test_duplicate_confirmation_submits_once_and_preserves_accepted_status(self):
        p = self.preview()
        response = Mock(status_code=200)
        response.json.return_value = {"id": "broker-1", "status": "accepted", "filled_qty": "0"}
        with patch.object(requests, "post", return_value=response) as post:
            first = po.confirm_order(p["intent_id"], confirmed=True)
            second = po.confirm_order(p["intent_id"], confirmed=True)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(first["broker_order"]["status"], "accepted")
        self.assertEqual(second["broker_order"]["filled_qty"], "0")

    def test_timeout_reconciles_without_resubmitting(self):
        p = self.preview()
        with patch.object(requests, "post", side_effect=requests.Timeout) as post:
            result = po.confirm_order(p["intent_id"], confirmed=True)
            self.assertEqual(result["state"], "unknown")
            with patch.object(at, "get_order_by_client_id", return_value={
                "id": "broker-after-timeout", "status": "partially_filled", "filled_qty": "0.5"}):
                reconciled = po.confirm_order(p["intent_id"], confirmed=True)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(reconciled["broker_order"]["status"], "partially_filled")

    def test_restart_and_concurrent_confirmation_never_duplicate(self):
        p = self.preview()
        response = Mock(status_code=201)
        response.json.return_value = {"id": "broker-1", "status": "new", "filled_qty": "0"}
        with patch.object(requests, "post", return_value=response) as post, patch.object(at, "get_order_by_client_id", return_value=None):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: po.confirm_order(p["intent_id"], confirmed=True), range(2)))
            self.assertEqual(post.call_count, 1)
        self.assertEqual(po.get_intent(p["intent_id"])["state"], "submitted")
        self.assertTrue(results)

    def test_account_change_and_expiration_block_submission(self):
        p = self.preview()
        self.account["id"] = "another-account"
        with self.assertRaises(po.OrderError):
            po.confirm_order(p["intent_id"], confirmed=True)
        self.account["id"] = "paper-test-account"
        with patch.object(po.time, "time", return_value=p["expires_at"] + 1), self.assertRaises(po.OrderError):
            po.confirm_order(p["intent_id"], confirmed=True)

    def test_native_multileg_uses_one_broker_request(self):
        p = po.preview_order({"qty": 1, "type": "limit", "limit_price": "1.25", "time_in_force": "day",
            "order_class": "mleg", "legs": [
                {"symbol": "SPY991231C00500000", "ratio_qty": 1, "side": "buy", "position_intent": "buy_to_open"},
                {"symbol": "SPY991231C00510000", "ratio_qty": 1, "side": "sell", "position_intent": "sell_to_open"}]})
        response = Mock(status_code=200)
        response.json.return_value = {"id": "native-spread", "status": "accepted", "filled_qty": "0"}
        with patch.object(requests, "post", return_value=response) as post:
            po.confirm_order(p["intent_id"], confirmed=True)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["order_class"], "mleg")
        self.assertEqual(len(post.call_args.kwargs["json"]["legs"]), 2)

    def test_uncovered_single_short_call_and_unknown_asset_block(self):
        with self.assertRaises(po.OrderError):
            po.preview_order({"symbol": "SPY991231C00500000", "qty": 1, "side": "sell", "type": "limit",
                              "limit_price": "2", "time_in_force": "day", "position_intent": "sell_to_open"})
        self.asset.return_value = {}
        with self.assertRaises(po.OrderError):
            self.preview()

    def test_missing_broker_response_cannot_be_reported_as_success(self):
        p = self.preview()
        response = Mock(status_code=200)
        response.json.return_value = {}
        with patch.object(requests, "post", return_value=response):
            self.assertEqual(po.confirm_order(p["intent_id"], confirmed=True)["state"], "unknown")

    def test_unknown_404_remains_locked_and_never_reposts(self):
        p = self.preview()
        with patch.object(requests, "post", side_effect=requests.Timeout) as post:
            po.confirm_order(p["intent_id"], confirmed=True)
            with patch.object(at, "get_order_by_client_id", return_value=None):
                self.assertEqual(po.confirm_order(p["intent_id"], confirmed=True)["state"], "unknown")
            with self.assertRaises(po.OrderError):
                self.preview()
        self.assertEqual(post.call_count, 1)

    def test_cancel_requires_preview_confirmation_and_does_not_claim_fill(self):
        p = self.preview()
        response = Mock(status_code=200)
        response.json.return_value = {"id": "broker-1", "status": "accepted", "filled_qty": "0"}
        with patch.object(requests, "post", return_value=response):
            po.confirm_order(p["intent_id"], confirmed=True)
        with patch.object(at, "get_order_by_client_id", return_value=response.json.return_value):
            cancel = po.preview_cancel(p["intent_id"])
            with self.assertRaises(po.OrderError):
                po.confirm_cancel(cancel["intent_id"], confirmed=False)
            with patch.object(requests, "delete", return_value=Mock(status_code=204)) as delete:
                self.assertEqual(po.confirm_cancel(cancel["intent_id"], confirmed=True)["state"], "cancel_pending")
                po.confirm_cancel(cancel["intent_id"], confirmed=True)
                self.assertEqual(delete.call_count, 1)
        self.get_order.return_value = {"id": "broker-1", "status": "canceled"}
        self.assertEqual(po.reconcile_order(cancel["intent_id"])["state"], "canceled")

    def test_cancel_timeout_stays_unknown_until_broker_confirms(self):
        p = self.preview()
        response = Mock(status_code=200)
        response.json.return_value = {"id": "broker-1", "status": "accepted"}
        with patch.object(requests, "post", return_value=response):
            po.confirm_order(p["intent_id"], confirmed=True)
        with patch.object(at, "get_order_by_client_id", return_value=response.json.return_value):
            cancel = po.preview_cancel(p["intent_id"])
            with patch.object(requests, "delete", side_effect=requests.Timeout) as delete:
                self.assertEqual(po.confirm_cancel(cancel["intent_id"], confirmed=True)["state"], "unknown")
                self.assertEqual(po.confirm_cancel(cancel["intent_id"], confirmed=True)["state"], "unknown")
                self.assertEqual(delete.call_count, 1)

    def test_position_reduction_needs_no_extra_buying_power(self):
        self.account["buying_power"] = "0"
        self.positions.return_value = [{"symbol": "SPY", "qty": "5"}]
        order = po.preview_order({"symbol": "SPY", "qty": 5, "side": "sell", "type": "limit", "limit_price": "100"})
        self.assertEqual(order["preview"]["conservative_required_usd"], "0")

    def test_account_shorting_permission_required(self):
        with self.assertRaisesRegex(po.OrderError, "Short-Freigabe"):
            po.preview_order({"symbol": "SPY", "qty": 1, "side": "sell", "type": "limit", "limit_price": "100"})

    def test_quote_staleness_and_options_level_block(self):
        self.quote.side_effect = None
        self.quote.return_value = {"bp": 99, "ap": 100, "bs": 1, "as": 1, "t": "2020-01-01T00:00:00Z", "feed": "sip"}
        with self.assertRaises(po.OrderError):
            self.preview()
        self.quote.return_value["t"] = datetime.now(timezone.utc).isoformat()
        self.account["options_trading_level"] = 1
        with self.assertRaisesRegex(po.OrderError, "Optionslevel 2"):
            po.preview_order({"symbol": "SPY991231C00500000", "qty": 1, "side": "buy", "position_intent": "buy_to_open", "type": "limit", "limit_price": "1"})

    def test_native_credit_limit_and_unbounded_call_ratio(self):
        order = {"qty": 1, "type": "limit", "limit_price": "-1.25", "order_class": "mleg", "legs": [
            {"symbol": "SPY991231C00500000", "ratio_qty": 1, "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": "SPY991231C00510000", "ratio_qty": 1, "side": "buy", "position_intent": "buy_to_open"}]}
        self.assertEqual(po.preview_order(order)["payload"]["limit_price"], "-1.25")
        order["legs"][0]["ratio_qty"] = 2
        with self.assertRaisesRegex(po.OrderError, "Call-Ratios"):
            po.preview_order(order)

    def test_external_order_cancel_preview_binds_broker_id_and_account(self):
        preview = po.preview_cancel_broker_order("broker-1")
        self.assertEqual(preview["payload"], {"action": "cancel", "order_id": "broker-1"})
        self.account["id"] = "changed-account"
        with patch.object(requests, "delete") as delete, self.assertRaises(po.OrderError):
            po.confirm_cancel(preview["intent_id"], confirmed=True)
        delete.assert_not_called()

    def test_reducing_close_revalidates_position_before_sending(self):
        self.positions.return_value = [{"symbol": "SPY", "qty": "5"}]
        with patch.object(at, "get_position_for_symbol", return_value={"symbol": "SPY", "qty": "5"}) as position:
            preview = po.preview_close_position("SPY", 5, limit_price="100")
            self.assertTrue(preview["preview"]["reducing_only"])
            self.assertEqual(preview["payload"]["side"], "sell")
            position.return_value = {"symbol": "SPY", "qty": "2"}
            with patch.object(requests, "post") as post, self.assertRaises(po.OrderError):
                po.confirm_order(preview["intent_id"], confirmed=True)
            post.assert_not_called()

    def test_risk_empty_is_empty_and_signed_hedges_offset(self):
        import pandas as pd
        import risk_manager as risk
        self.positions.return_value = []
        self.assertEqual(risk.fetch_portfolio_positions(), [])
        dates = pd.date_range("2025-01-01", periods=100)
        history = pd.DataFrame({"Close": [100 + (i % 7) for i in range(100)]}, index=dates)
        holdings = [{"underlying": "SPY", "market_value": 1000.0, "is_option": False},
                    {"underlying": "SPY", "market_value": -1000.0, "is_option": False}]
        with patch("yfinance.Ticker") as ticker:
            ticker.return_value.history.return_value = history
            self.assertEqual(risk.calculate_portfolio_var(holdings), (0.0, 0.0))
        with self.assertRaises(ValueError):
            risk.run_stress_test([{"is_option": True}])


class BrokerReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret", "ALPACA_BASE_URL": at.PAPER_URL}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_empty_positions_are_real_but_http_failures_are_not_empty(self):
        response = Mock(status_code=200)
        response.json.return_value = []
        with patch.object(requests, "get", return_value=response) as get:
            self.assertEqual(at.get_positions(), [])
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
        for code in (401, 403, 429, 500, 302):
            response.status_code = code
            response.headers = {"Retry-After": "2"}
            with patch.object(requests, "get", return_value=response), self.assertRaises(at.AlpacaReadError) as context:
                at.get_positions()
            self.assertEqual(context.exception.status_code, code)
        with patch.object(requests, "get", side_effect=requests.Timeout), self.assertRaises(at.AlpacaReadError) as context:
            at.get_positions()
        self.assertTrue(context.exception.retryable)

    def test_missing_keys_never_send_and_synthetic_quotes_use_shared_reader(self):
        with patch.dict(os.environ, {"ALPACA_SECRET_KEY": ""}), patch.object(requests, "get") as get:
            with self.assertRaises(at.AlpacaReadError):
                at.get_positions()
            get.assert_not_called()
        import synthetic_swap_builder
        with patch.object(at, "get_latest_quote", return_value={"bp": 1, "ap": 2, "t": "stamp", "feed": "indicative"}):
            self.assertEqual(synthetic_swap_builder.get_alpaca_option_quote("SPY991231C00500000")["mid"], 1.5)


if __name__ == "__main__":
    unittest.main()
