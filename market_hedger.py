import os
import requests
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


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
    from alpaca_trader import BLOCKED_MESSAGE
    return 403, {"message": BLOCKED_MESSAGE}

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
        from alpaca_trader import BLOCKED_MESSAGE
        print(BLOCKED_MESSAGE)
        return False
            
    def execute_protective_put(self, otm_pct: float = 5.0, qty: int = 1) -> bool:
        from alpaca_trader import BLOCKED_MESSAGE
        print(BLOCKED_MESSAGE)
        return False
            
    def execute_synthetic_short(self, qty: int = 1) -> bool:
        from alpaca_trader import BLOCKED_MESSAGE
        print(BLOCKED_MESSAGE)
        return False
