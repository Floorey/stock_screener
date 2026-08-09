"""Manual and importable Alpaca options signal executor."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from dotenv import dotenv_values

try:
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import (
        ContractType,
        OrderSide,
        OrderType,
        PositionIntent,
        PositionSide,
        TimeInForce,
    )
    from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
except ModuleNotFoundError as exc:
    if exc.name != "alpaca":
        raise
    StockHistoricalDataClient = None
    StockLatestTradeRequest = None
    TradingClient = None
    ContractType = None
    OrderSide = None
    OrderType = None
    PositionIntent = None
    PositionSide = None
    TimeInForce = None
    GetOptionContractsRequest = None
    MarketOrderRequest = None
    ALPACA_IMPORT_ERROR = exc
else:
    ALPACA_IMPORT_ERROR = None


class ExecutionError(RuntimeError):
    """An expected configuration, market-data, or execution failure."""


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    secret_key: str
    paper: bool = True

    @classmethod
    def from_local_env(cls, path: Path | None = None) -> "AlpacaConfig":
        env_path = path or Path(__file__).with_name(".env")
        if not env_path.is_file():
            raise ExecutionError(f"Local credentials file not found: {env_path}")

        values = dotenv_values(env_path)
        api_key = (values.get("ALPACA_API_KEY") or values.get("APCA_API_KEY_ID") or "").strip()
        secret_key = (
            values.get("ALPACA_SECRET_KEY") or values.get("APCA_API_SECRET_KEY") or ""
        ).strip()
        if not api_key or not secret_key:
            raise ExecutionError(
                "The local .env must define ALPACA_API_KEY and ALPACA_SECRET_KEY."
            )

        base_url = (values.get("ALPACA_BASE_URL") or "").lower()
        paper_value = (values.get("ALPACA_PAPER") or "").strip().lower()
        paper = "paper" in base_url if base_url else paper_value not in {"0", "false", "no"}
        return cls(api_key=api_key, secret_key=secret_key, paper=paper)


class OptionsExecutionEngine:
    """Turns LONG, REDUCE, and SHORT signals into single-leg option orders."""

    def __init__(
        self,
        config: AlpacaConfig,
        *,
        trading_client: TradingClient | None = None,
        stock_data_client: StockHistoricalDataClient | None = None,
    ) -> None:
        self.trading = trading_client or TradingClient(
            config.api_key, config.secret_key, paper=config.paper
        )
        self.stock_data = stock_data_client or StockHistoricalDataClient(
            config.api_key, config.secret_key
        )

    def execute(self, symbol: str, signal: str, qty: int) -> list[object]:
        symbol = symbol.strip().upper()
        signal = signal.strip().upper()
        if not symbol.isalnum():
            raise ExecutionError("Symbol must contain only letters and numbers.")
        if signal not in {"LONG", "REDUCE", "SHORT"}:
            raise ExecutionError("Signal must be LONG, REDUCE, or SHORT.")
        if qty < 1:
            raise ExecutionError("Quantity must be at least 1 contract.")

        if signal == "REDUCE":
            return self.reduce(symbol, qty)
        if signal == "SHORT":
            orders = self.close_calls(symbol)
            orders.append(self.open_atm(symbol, ContractType.PUT, qty))
            return orders
        return [self.open_atm(symbol, ContractType.CALL, qty)]

    def underlying_price(self, symbol: str) -> float:
        trades = self.stock_data.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        trade = trades.get(symbol)
        if trade is None or float(trade.price) <= 0:
            raise ExecutionError(f"No current trade price available for {symbol}.")
        return float(trade.price)

    def find_atm_contract(self, symbol: str, contract_type: ContractType):
        price = self.underlying_price(symbol)
        today = date.today()
        request = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            type=contract_type,
            expiration_date_gte=today + timedelta(days=30),
            expiration_date_lte=today + timedelta(days=45),
            strike_price_gte=f"{price * 0.85:.2f}",
            strike_price_lte=f"{price * 1.15:.2f}",
            limit=1000,
        )
        response = self.trading.get_option_contracts(request)
        contracts = getattr(response, "option_contracts", [])
        liquid = [
            contract
            for contract in contracts
            if contract.tradable and int(contract.open_interest or 0) > 0
        ]
        if not liquid:
            raise ExecutionError(
                f"No liquid {contract_type.value} contract found for {symbol} "
                "with 30-45 days to expiration."
            )

        target_expiry = today + timedelta(days=37)
        return min(
            liquid,
            key=lambda contract: (
                abs(float(contract.strike_price) - price),
                abs((contract.expiration_date - target_expiry).days),
                -int(contract.open_interest or 0),
            ),
        )

    def open_atm(self, symbol: str, contract_type: ContractType, qty: int):
        contract = self.find_atm_contract(symbol, contract_type)
        return self._market_order(
            contract.symbol, qty, OrderSide.BUY, PositionIntent.BUY_TO_OPEN
        )

    def option_positions(self, symbol: str, contract_type: ContractType | None = None):
        matches = []
        for position in self.trading.get_all_positions():
            try:
                contract = self.trading.get_option_contract(position.symbol)
            except Exception:
                continue  # Equity and other non-option positions are expected here.
            if contract.underlying_symbol != symbol:
                continue
            if contract_type is not None and contract.type != contract_type:
                continue
            matches.append((position, contract))
        return matches

    def reduce(self, symbol: str, qty: int) -> list[object]:
        positions = self.option_positions(symbol)
        if not positions:
            raise ExecutionError(f"No open option position found for {symbol}.")

        remaining = qty
        orders = []
        for position, _contract in positions:
            if position.side != PositionSide.LONG or remaining == 0:
                continue
            available = int(float(position.qty_available or position.qty))
            close_qty = min(available, remaining)
            if close_qty:
                orders.append(
                    self._market_order(
                        position.symbol,
                        close_qty,
                        OrderSide.SELL,
                        PositionIntent.SELL_TO_CLOSE,
                    )
                )
                remaining -= close_qty

        if not orders:
            raise ExecutionError(f"No long option contracts available to reduce for {symbol}.")
        if remaining:
            print(
                f"Warning: requested {qty}, but only {qty - remaining} contract(s) were available.",
                file=sys.stderr,
            )
        return orders

    def close_calls(self, symbol: str) -> list[object]:
        orders = []
        for position, _contract in self.option_positions(symbol, ContractType.CALL):
            if position.side != PositionSide.LONG:
                raise ExecutionError(
                    f"Cannot Sell to Close short call position {position.symbol}."
                )
            qty = int(float(position.qty_available or position.qty))
            if qty:
                orders.append(
                    self._market_order(
                        position.symbol, qty, OrderSide.SELL, PositionIntent.SELL_TO_CLOSE
                    )
                )
        return orders

    def _market_order(
        self, symbol: str, qty: int, side: OrderSide, intent: PositionIntent
    ):
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            position_intent=intent,
        )
        return self.trading.submit_order(order_data=request)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute Alpaca option signals.")
    parser.add_argument("--symbol", required=True, help="Underlying ticker, e.g. AAPL")
    parser.add_argument(
        "--signal", required=True, type=str.upper, choices=["LONG", "REDUCE", "SHORT"]
    )
    parser.add_argument("--qty", required=True, type=int, help="Number of contracts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = OptionsExecutionEngine(AlpacaConfig.from_local_env())
        orders = engine.execute(args.symbol, args.signal, args.qty)
        if not orders:
            print("No closing orders were needed.")
        for order in orders:
            print(f"Submitted {order.side.value} {order.qty} {order.symbol} (order {order.id})")
        return 0
    except ExecutionError as exc:
        print(f"Warning: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Broker error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
