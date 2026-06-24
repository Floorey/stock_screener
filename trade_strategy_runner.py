import os
import requests
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration from the stock screener directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY,
    "Content-Type": "application/json"
}

def place_order(symbol, qty, side, order_type="market", limit_price=None):
    """Utility to place standard or option order on Alpaca."""
    url = f"{BASE_URL}/v2/orders"
    data = {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": side.lower(),
        "type": order_type.lower(),
        "time_in_force": "day"
    }
    if order_type.lower() == "limit" and limit_price is not None:
        data["limit_price"] = f"{limit_price:.2f}"
        
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.status_code, response.json()
    except Exception as e:
        return 0, {"message": str(e)}

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
    """
    Executes a Synthetic Short on US Treasury Bonds (Option A from Blackgate Macro Memo).
    It buys an ATM Put and sells an ATM Call, replicating a 100% short stock position.
    
    Risk: Uncapped loss potential on the short call. Requires strict stop-loss.
    """
    print(f"--- Running Option A: Synthetic Short on {ticker} ---")
    if not API_KEY or not SECRET_KEY:
        print("Error: Alpaca API Keys not configured in .env!")
        return False
        
    tk = yf.Ticker(ticker)
    
    # Get current price if strike is not provided
    if not strike:
        info = tk.info
        current_price = info.get("currentPrice") or info.get("previousClose") or 90.0
        strike = float(round(current_price))
        print(f"Detected current price for {ticker}: ${current_price:.2f}. Suggesting Strike: ${strike:.2f}")
        
    # Get closest expiration date (approx 30 days) if not provided
    if not expiry:
        dates = list(tk.options)
        if not dates:
            print(f"Error: No options chain available for {ticker}!")
            return False
        expiry = dates[0] # Take first available for test, or user can specify
        print(f"Suggesting Expiration Date: {expiry}")
        
    # Format Option Symbols
    put_symbol = format_osi_symbol(ticker, expiry, "put", strike)
    call_symbol = format_osi_symbol(ticker, expiry, "call", strike)
    
    print(f"Structuring position for {qty} contract(s):")
    print(f"  1. Buy Put: {put_symbol} at strike ${strike:.2f}")
    print(f"  2. Sell Call: {call_symbol} at strike ${strike:.2f}")
    
    # Place orders
    print("\nPlacing orders on Alpaca...")
    
    # Leg 1: Buy Put
    code_put, res_put = place_order(put_symbol, qty, "buy", "market")
    if code_put in [200, 201]:
        print(f"SUCCESS: Purchased {qty} Put(s) ({put_symbol}). Order ID: {res_put.get('id')}")
    else:
        print(f"FAILED: Buy Put ({put_symbol}): {res_put.get('message', res_put)}")
        return False
        
    # Leg 2: Sell Call
    code_call, res_call = place_order(call_symbol, qty, "sell", "market")
    if code_call in [200, 201]:
        print(f"SUCCESS: Sold {qty} Call(s) ({call_symbol}). Order ID: {res_call.get('id')}")
    else:
        print(f"FAILED: Sell Call ({call_symbol}): {res_call.get('message', res_call)}")
        # Warning: Left with naked long put, which is defined risk, so not critical but inconsistent
        print("Warning: Only the long put leg was executed. You now hold a standard long put.")
        return False
        
    print("\n--- Strategy execution completed successfully! ---")
    return True

if __name__ == "__main__":
    import sys
    print("Strategy Runner loaded. Running a test simulation...")
    # Change ticker/strike/expiry if you want to run from terminal:
    # python trade_strategy_runner.py
    # To run real trade, uncomment below line:
    # execute_synthetic_short_bond(ticker="TLT", qty=1)
