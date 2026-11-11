import os
import argparse
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def _log(msg: str = ""):
    print(msg, file=sys.stderr)

# Load Alpaca configuration and override any stale environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)


def format_osi_symbol(ticker: str, expiry_date_str: str, option_type: str, strike: float) -> str:
    """Formats option symbol to standard OSI format (compact, no spaces)."""
    ticker_part = ticker.upper().strip()
    dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
    expiry_part = dt.strftime("%y%m%d")
    type_part = "C" if option_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    strike_part = f"{strike_int:08d}"
    return f"{ticker_part}{expiry_part}{type_part}{strike_part}"

def place_alpaca_order(symbol: str, qty: float, side: str, order_type: str = "limit", limit_price: float = None) -> tuple[int, dict]:
    from alpaca_trader import BLOCKED_MESSAGE
    return 403, {"message": BLOCKED_MESSAGE}

def sanitize_price(contract_dict: dict, price_type: str, mid_fallback: float) -> float:
    """Safely extracts a limit price with mid, lastPrice, and minimum fallbacks."""
    val = contract_dict.get(price_type, 0.0)
    if val is None or val <= 0 or val != val:
        val = mid_fallback
    if val is None or val <= 0 or val != val:
        val = contract_dict.get("lastPrice", 0.01)
    if val is None or val <= 0 or val != val:
        val = 0.01
    return float(val)

def get_alpaca_option_quote(symbol: str) -> dict:
    from alpaca_trader import get_latest_quote
    quote = get_latest_quote(symbol, option=True)
    bid, ask = float(quote["bp"]), float(quote["ap"])
    return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2,
            "feed": quote["feed"], "timestamp": quote["t"]}

def get_alpaca_option_contracts(underlying: str) -> list[dict]:
    from alpaca_trader import broker_get
    return broker_get("/v2/options/contracts", {"underlying_symbols": underlying.upper(), "status": "active", "limit": 1000}).get("option_contracts", [])

def execute_synthetic_swap(ticker: str, direction: str, qty: int, strike: float = None, expiry: str = None) -> bool:
    from alpaca_trader import BLOCKED_MESSAGE
    print(BLOCKED_MESSAGE)
    return False


def main():
    parser = argparse.ArgumentParser(description="Build and execute Option Synthetic Swaps (Long or Short) on Alpaca.")
    parser.add_argument("--ticker", required=True, type=str, help="Underlying stock or ETF ticker (e.g. SPY, TSLA, QQQ)")
    parser.add_argument("--direction", required=True, choices=["long", "short"], help="Swap direction: 'long' or 'short'")
    parser.add_argument("--qty", type=int, default=1, help="Quantity of option contract sets (default: 1)")
    parser.add_argument("--strike", type=float, help="Custom basis strike price (defaults to ATM)")
    parser.add_argument("--expiry", type=str, help="Option expiration date (YYYY-MM-DD, defaults to nearest monthly (~30d DTE))")
    args = parser.parse_args()
    
    execute_synthetic_swap(
        ticker=args.ticker,
        direction=args.direction,
        qty=args.qty,
        strike=args.strike,
        expiry=args.expiry
    )

if __name__ == "__main__":
    main()
