import numpy as np
import pandas as pd
import yfinance as yf
import math

class norm:
    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        
    @staticmethod
    def pdf(x):
        return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)
from datetime import datetime, timedelta

def calculate_black_scholes_delta(S, K, T, r, sigma, option_type="call"):
    """
    S: Stock price, K: Strike price, T: Time to expiration in years, 
    r: Risk-free rate, sigma: Implied volatility.
    """
    if T <= 0:
        if option_type.lower() == "call":
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0
            
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    if option_type.lower() == "call":
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1.0

def calculate_greeks(S, K, T, r, sigma, option_type="call"):
    """Calculates Delta, Gamma, Vega, Theta for options."""
    if T <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    # PDF of normal distribution
    pdf_d1 = norm.pdf(d1)
    
    delta = calculate_black_scholes_delta(S, K, T, r, sigma, option_type)
    gamma = pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * pdf_d1 * np.sqrt(T) / 100.0  # divided by 100 for 1% IV change
    
    # Theta (annualized, then divided by 365)
    if option_type.lower() == "call":
        theta = (- (S * pdf_d1 * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365.0
    else:
        theta = (- (S * pdf_d1 * sigma) / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365.0
        
    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta
    }

class StatisticalArbitrageLab:
    @staticmethod
    def fetch_pairs_data(ticker_a: str, ticker_b: str, period: str = "60d") -> pd.DataFrame:
        """Fetches historical close prices for two tickers and merges them."""
        # Clean inputs
        ticker_a = ticker_a.strip().upper()
        ticker_b = ticker_b.strip().upper()
        
        ta = yf.Ticker(ticker_a)
        tb = yf.Ticker(ticker_b)
        
        df_a = ta.history(period=period)["Close"].to_frame(name="Price_A")
        df_b = tb.history(period=period)["Close"].to_frame(name="Price_B")
        
        # Localize indexes to naive to avoid comparison error
        df_a.index = df_a.index.tz_localize(None)
        df_b.index = df_b.index.tz_localize(None)
        
        df = df_a.join(df_b, how="inner")
        return df

    @staticmethod
    def calculate_pairs_metrics(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """Calculates spread, rolling mean, rolling std, and z-score."""
        # We use a simple dynamic ratio hedge spread
        # spread = Price_A - (Hedge Ratio * Price_B)
        # For simplicity, we calculate the rolling hedge ratio as a rolling mean ratio
        rolling_ratio = (df["Price_A"].rolling(window).mean() / df["Price_B"].rolling(window).mean())
        
        df["Hedge_Ratio"] = rolling_ratio.ffill().bfill()
        df["Spread"] = df["Price_A"] - (df["Hedge_Ratio"] * df["Price_B"])
        
        df["Spread_Mean"] = df["Spread"].rolling(window).mean()
        df["Spread_Std"] = df["Spread"].rolling(window).std()
        df["Z_Score"] = (df["Spread"] - df["Spread_Mean"]) / df["Spread_Std"]
        
        # Signals
        df["Signal"] = 0
        # Buy Spread: Long A, Short B (z-score is low, spread should widen)
        # Sell Spread: Short A, Long B (z-score is high, spread should narrow)
        df.loc[df["Z_Score"] < -2.0, "Signal"] = 1  # Long Spread
        df.loc[df["Z_Score"] > 2.0, "Signal"] = -1  # Short Spread
        df.loc[df["Z_Score"].abs() < 0.2, "Signal"] = 0  # Exit Signal
        
        # Forward fill active signal state until exit
        df["Position"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
        # Force position exit when spread crosses zero/mean
        df.loc[df["Z_Score"].abs() < 0.2, "Position"] = 0
        
        return df
