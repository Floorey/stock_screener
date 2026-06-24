import os
import argparse
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY,
    "Content-Type": "application/json"
}

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
    """Places order on Alpaca and returns (status_code, response_json)."""
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

def execute_synthetic_swap(ticker: str, direction: str, qty: int, strike: float = None, expiry: str = None) -> bool:
    """
    Executes a Synthetic Swap (Long or Short) using Option contracts.
    
    Synthetic Long (Buy Call + Sell Put at Strike S):
    - Replicates 100 shares long exposure (Delta = +1.00 per contract).
    - Extremely capital efficient, close to $0.00 net premium.
    
    Synthetic Short (Buy Put + Sell Call at Strike S):
    - Replicates 100 shares short exposure (Delta = -1.00 per contract).
    - Eliminates borrow fees and short squeeze risks.
    """
    ticker = ticker.upper().strip()
    direction = direction.lower().strip()
    
    print(f"\n==================================================")
    print(f"⚡ BUILDING SYNTHETIC {direction.upper()} SWAP ON {ticker}")
    print(f"==================================================")
    
    if not API_KEY or not SECRET_KEY:
        print("Error: Alpaca API Keys not configured in .env!")
        return False
        
    tk = yf.Ticker(ticker)
    
    # 1. Resolve current price of underlying
    try:
        hist = tk.history(period="1d")
        current_price = hist["Close"].iloc[-1] if not hist.empty else 100.0
    except Exception as e:
        print(f"Error fetching current price for {ticker}: {e}")
        return False
        
    print(f"Current Stock Price: ${current_price:.2f}")
    
    # 2. Resolve ATM strike if not provided
    if not strike:
        strike = float(round(current_price))
        
    # 3. Resolve expiry date if not provided (approx 30 days DTE)
    options = list(tk.options)
    if not options:
        print(f"Error: No option chains available for {ticker}!")
        return False
        
    if not expiry:
        # Target about 30 days
        expiry = options[0]
        for d in options:
            dt = datetime.strptime(d, "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if 25 <= days <= 45:
                expiry = d
                break
                
    print(f"Target Strike: ${strike:.2f}")
    print(f"Expiration Date: {expiry}")
    
    # 4. Fetch option chain details
    try:
        chain = tk.option_chain(expiry)
        calls_df = chain.calls
        puts_df = chain.puts
        
        # Get closest contracts
        call_con = calls_df.iloc[(calls_df['strike'] - strike).abs().argsort()[:1]].iloc[0].to_dict()
        put_con = puts_df.iloc[(puts_df['strike'] - strike).abs().argsort()[:1]].iloc[0].to_dict()
    except Exception as e:
        print(f"Error loading option chain data: {e}")
        return False
        
    c_symbol = call_con["contractSymbol"]
    p_symbol = put_con["contractSymbol"]
    
    c_mid = (call_con.get("bid", 0.0) + call_con.get("ask", 0.0)) / 2.0 or call_con.get("lastPrice", 0.0)
    p_mid = (put_con.get("bid", 0.0) + put_con.get("ask", 0.0)) / 2.0 or put_con.get("lastPrice", 0.0)
    
    # 5. Define legs based on direction
    if direction == "long":
        # Synthetic Long: Buy Call, Sell Put
        c_action = "buy"
        c_price_type = "ask" # buy calls at ask
        p_action = "sell"
        p_price_type = "bid" # sell puts at bid
        
        c_limit = sanitize_price(call_con, c_price_type, c_mid)
        p_limit = sanitize_price(put_con, p_price_type, p_mid)
        
        legs = [
            {"name": "Leg 1: Buy Call (Long Call)", "symbol": c_symbol, "side": c_action, "limit_price": c_limit},
            {"name": "Leg 2: Sell Put (Short Put)", "symbol": p_symbol, "side": p_action, "limit_price": p_limit}
        ]
    elif direction == "short":
        # Synthetic Short: Buy Put, Sell Call
        p_action = "buy"
        p_price_type = "ask" # buy puts at ask
        c_action = "sell"
        c_price_type = "bid" # sell calls at bid
        
        p_limit = sanitize_price(put_con, p_price_type, p_mid)
        c_limit = sanitize_price(call_con, c_price_type, c_mid)
        
        legs = [
            {"name": "Leg 1: Buy Put (Long Put)", "symbol": p_symbol, "side": p_action, "limit_price": p_limit},
            {"name": "Leg 2: Sell Call (Short Call)", "symbol": c_symbol, "side": c_action, "limit_price": c_limit}
        ]
    else:
        print(f"Error: Unknown direction '{direction}'. Must be 'long' or 'short'.")
        return False
        
    # Show structure
    print("\nPositions to be executed:")
    for leg in legs:
        print(f"  * {leg['name']} -> Symbol: {leg['symbol']} | Action: {leg['side'].upper()} | Limit: ${leg['limit_price']:.2f}")
        
    print("\nSending orders to Alpaca...")
    success_count = 0
    for leg in legs:
        print(f"Submitting {leg['side'].upper()} order for {qty} contract(s) of {leg['symbol']}...")
        status, res = place_alpaca_order(leg["symbol"], qty, leg["side"], "limit", leg["limit_price"])
        if status in [200, 201]:
            print(f"  -> SUCCESS! Order ID: {res.get('id')} (Status: {res.get('status')})")
            success_count += 1
        else:
            print(f"  -> FAILED: {res.get('message', res)}")
            
    if success_count == len(legs):
        print(f"\n🔥 All orders of the Synthetic {direction.upper()} Swap were successfully executed!")
        return True
    else:
        print(f"\n⚠️ Warning: Strategy execution incomplete. Only {success_count}/{len(legs)} legs placed successfully.")
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
