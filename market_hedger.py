import os
import requests
import yfinance as yf
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

def place_alpaca_order(symbol: str, qty: float, side: str, order_type: str = "market", limit_price: float = None) -> tuple[int, dict]:
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

class MarketHedger:
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.tk = yf.Ticker(self.ticker)
        
    def get_current_price(self) -> float:
        """Fetches the latest price of the ETF."""
        try:
            hist = self.tk.history(period="1d")
            return hist["Close"].iloc[-1] if not hist.empty else 100.0
        except Exception:
            return 100.0
            
    def execute_physical_short(self, qty: int) -> bool:
        """
        Executes a direct physical short sale of the ETF.
        Sells shares on margin. Requires the asset to be shortable.
        """
        print(f"\n--- [Market Hedger] Physical Short Sale on {self.ticker} ---")
        print(f"Submitting SELL order for {qty} shares of {self.ticker}...")
        status, res = place_alpaca_order(self.ticker, qty, "sell", "market")
        if status in [200, 201]:
            print(f"SUCCESS: Order submitted! ID: {res.get('id')} | Status: {res.get('status')}")
            return True
        else:
            print(f"FAILED: {res.get('message', res)}")
            return False
            
    def execute_protective_put(self, otm_pct: float = 5.0, qty: int = 1) -> bool:
        """
        Buys a protective Out-Of-The-Money Put Option.
        Limits risk to the premium paid, while providing downside protection.
        """
        print(f"\n--- [Market Hedger] Buying Protective Put Hedges on {self.ticker} ---")
        current_p = self.get_current_price()
        target_strike = current_p * (1.0 - otm_pct / 100.0)
        
        # Fetch option chains
        options = list(self.tk.options)
        if not options:
            print("Error: No option contracts available for this ticker.")
            return False
            
        # Target expiry in about 30 to 45 days
        expiry = options[0]
        for d in options:
            dt = datetime.strptime(d, "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if 30 <= days <= 50:
                expiry = d
                break
                
        print(f"Selected Expiry: {expiry} | Current Price: ${current_p:.2f} | Target Strike: ${target_strike:.2f}")
        
        try:
            chain = self.tk.option_chain(expiry)
            puts = chain.puts
            # Find closest strike
            closest_put = puts.iloc[(puts["strike"] - target_strike).abs().argsort()[:1]].iloc[0]
            strike = closest_put["strike"]
            symbol = closest_put["contractSymbol"]
            ask = closest_put["ask"]
            
            print(f"Matching contract: {symbol} at Strike ${strike:.2f} (Ask: ${ask:.2f})")
            print(f"Submitting BUY order for {qty} Put(s)...")
            status, res = place_alpaca_order(symbol, qty, "buy", "limit", ask)
            if status in [200, 201]:
                print(f"SUCCESS: Protective Put placed! ID: {res.get('id')} | Status: {res.get('status')}")
                return True
            else:
                print(f"FAILED: {res.get('message', res)}")
                return False
        except Exception as e:
            print(f"Error fetching option chain or placing order: {e}")
            return False
            
    def execute_synthetic_short(self, qty: int = 1) -> bool:
        """
        Executes a Synthetic Short Option Structure (ATM Long Put + ATM Short Call).
        Replicates short stock position at near-zero entry cost.
        """
        print(f"\n--- [Market Hedger] Executing Synthetic Short Options on {self.ticker} ---")
        current_p = self.get_current_price()
        strike = float(round(current_p))
        
        options = list(self.tk.options)
        if not options:
            print("Error: No option contracts available.")
            return False
            
        # Choose closest monthly expiration date
        expiry = options[0]
        for d in options:
            dt = datetime.strptime(d, "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if 25 <= days <= 45:
                expiry = d
                break
                
        print(f"Selected Expiry: {expiry} | Current Price: ${current_p:.2f} | ATM Strike: ${strike:.2f}")
        
        try:
            chain = self.tk.option_chain(expiry)
            calls = chain.calls
            puts = chain.puts
            
            # Find closest strikes
            c_con = calls.iloc[(calls["strike"] - strike).abs().argsort()[:1]].iloc[0]
            p_con = puts.iloc[(puts["strike"] - strike).abs().argsort()[:1]].iloc[0]
            
            c_symbol = c_con["contractSymbol"]
            p_symbol = p_con["contractSymbol"]
            
            c_bid = c_con["bid"]
            p_ask = p_con["ask"]
            
            print(f"Leg 1 (Long Put): Buy {qty} Put(s) {p_symbol} at strike ${p_con['strike']:.2f} (Ask: ${p_ask:.2f})")
            print(f"Leg 2 (Short Call): Sell {qty} Call(s) {c_symbol} at strike ${c_con['strike']:.2f} (Bid: ${c_bid:.2f})")
            
            # Buy Put
            status_p, res_p = place_alpaca_order(p_symbol, qty, "buy", "limit", p_ask)
            if status_p not in [200, 201]:
                print(f"FAILED: Leg 1 Buy Put: {res_p.get('message', res_p)}")
                return False
                
            # Sell Call
            status_c, res_c = place_alpaca_order(c_symbol, qty, "sell", "limit", c_bid)
            if status_c not in [200, 201]:
                print(f"FAILED: Leg 2 Sell Call: {res_c.get('message', res_c)}")
                print("Warning: Leg 1 was filled. You are holding a single Put option.")
                return False
                
            print(f"SUCCESS: Synthetic Short option spread placed successfully on {self.ticker}!")
            return True
        except Exception as e:
            print(f"Error executing synthetic short options structure: {e}")
            return False
