import os
import requests
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration from the stock screener directory and override stale variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)


def get_alpaca_option_contracts(underlying: str) -> list[dict]:
    from alpaca_trader import broker_get
    return broker_get("/v2/options/contracts", {"underlying_symbols": underlying.upper(), "status": "active", "limit": 1000}).get("option_contracts", [])

def place_order(symbol, qty, side, order_type="market", limit_price=None):
    from alpaca_trader import BLOCKED_MESSAGE
    return 403, {"message": BLOCKED_MESSAGE}

def format_osi_symbol(ticker: str, expiry_date_str: str, option_type: str, strike: float) -> str:
    """Formats option symbol to standard OSI format (compact, no spaces)."""
    ticker_part = ticker.upper().strip()
    dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
    expiry_part = dt.strftime("%y%m%d")
    type_part = "C" if option_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    strike_part = f"{strike_int:08d}"
    return f"{ticker_part}{expiry_part}{type_part}{strike_part}"

def execute_synthetic_short_bond(ticker="TLT", expiry=None, strike=None, qty=1):
    from alpaca_trader import BLOCKED_MESSAGE
    print(BLOCKED_MESSAGE)
    return False

if __name__ == "__main__":
    import sys
    print("Strategy Runner loaded. Running a test simulation...")
    # Change ticker/strike/expiry if you want to run from terminal:
    # python trade_strategy_runner.py
    # To run real trade, uncomment below line:
    # execute_synthetic_short_bond(ticker="TLT", qty=1)
