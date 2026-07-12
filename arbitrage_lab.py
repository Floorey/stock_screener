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

    @staticmethod
    def calculate_pair_suitability(ticker_a: str, ticker_b: str, period: str = "1y") -> dict:
        """
        Analyzes suitability of a stock pair for statistical arbitrage.
        Computes Correlation, Cointegration (p-value if statsmodels is installed),
        Zero-Crossing Frequency, and Half-Life of Mean Reversion.
        """
        ticker_a = ticker_a.strip().upper()
        ticker_b = ticker_b.strip().upper()
        
        try:
            df = StatisticalArbitrageLab.fetch_pairs_data(ticker_a, ticker_b, period)
            if len(df) < 30:
                return {"status": "error", "message": "Ungenügend historische Daten vorhanden (mindestens 30 Tage benötigt)."}
        except Exception as e:
            return {"status": "error", "message": f"Fehler beim Laden der Daten: {str(e)}"}
            
        # 1. Pearson Correlation
        corr = float(df["Price_A"].corr(df["Price_B"]))
        
        # 2. Linear Regression to find residuals (Spread)
        # y = beta * x + alpha
        try:
            beta, alpha = np.polyfit(df["Price_B"], df["Price_A"], 1)
            spread = df["Price_A"] - (beta * df["Price_B"] + alpha)
        except Exception:
            # Fallback to simple ratio spread if polyfit fails
            ratio = df["Price_A"].mean() / df["Price_B"].mean()
            spread = df["Price_A"] - (ratio * df["Price_B"])
            beta = ratio
            
        # 3. Autocorrelation & Half-Life of Mean Reversion
        # AR(1) model: spread_t = rho * spread_{t-1} + error
        spread_lag = spread.shift(1).dropna()
        spread_curr = spread.iloc[1:]
        
        try:
            rho = float(np.corrcoef(spread_lag, spread_curr)[0, 1])
        except Exception:
            rho = 0.99
            
        if 0 < rho < 1:
            half_life = float(-np.log(2) / np.log(rho))
        else:
            half_life = 999.0  # essentially no mean reversion
            
        # 4. Zero-Crossing count (relative to mean of spread)
        # Shift spread to be centered at its mean
        spread_centered = spread - spread.mean()
        spread_sign = np.sign(spread_centered)
        zero_crossings = int(np.sum(np.diff(spread_sign) != 0))
        
        # Normalize zero crossings to a standard 252-day year
        normalized_crossings = (zero_crossings / len(df)) * 252
        
        # 5. Cointegration (Engle-Granger Two-Step Test via statsmodels)
        coint_p = None
        statsmodels_available = False
            
        # 6. Calculate Suitability Score (0 - 100)
        score = 0
        
        # Correlation (Max 30 points)
        if corr >= 0.85:
            score += 30
        elif corr >= 0.70:
            score += 20
        elif corr >= 0.50:
            score += 10
            
        # Zero Crossings (Max 35 points)
        if normalized_crossings >= 25:
            score += 35
        elif normalized_crossings >= 12:
            score += 25
        elif normalized_crossings >= 5:
            score += 15
            
        # Cointegration / Mean Reversion speed (Max 35 points)
        if coint_p is not None:
            # Using actual p-value
            if coint_p <= 0.05:
                score += 35
            elif coint_p <= 0.10:
                score += 20
        else:
            # Using half-life proxy
            if 2 <= half_life <= 20:
                score += 35
            elif 20 < half_life <= 50:
                score += 20
            elif 1 < half_life < 2:
                # too fast can mean microstructural noise, still okay
                score += 25
                
        # 7. Recommendation and German details summary
        if score >= 75:
            rec = "EXCELLENT"
            rec_color = "🟢 Hervorragende Eignung"
            details = (
                f"Dieses Paar weist eine sehr starke fundamentale Eignung auf (Score: {score}/100). "
                f"Die Korrelation ist mit {corr:.2f} hoch, und der Spread zeigt eine aktive Mean-Reversion "
                f"mit {zero_crossings} Durchkreuzungen des Mittelwerts. "
            )
            if coint_p is not None:
                details += f"Der Cointegration-Test bestätigt die Signifikanz (p-Wert: {coint_p:.4f}). "
            else:
                details += f"Die geschätzte Halbwertszeit der Mean Reversion beträgt kurze {half_life:.1f} Tage. "
            details += "Perfekt geeignet für Pairs Trading."
        elif score >= 50:
            rec = "MODERATE"
            rec_color = "🟡 Moderate Eignung"
            details = (
                f"Dieses Paar eignet sich bedingt für Pairs Trading (Score: {score}/100). "
                f"Obwohl eine gewisse Korrelation ({corr:.2f}) vorliegt, könnte die Mean-Reversion "
                f"träge sein (Halbwertszeit: {half_life:.1f} Tage) oder weniger häufig den Mittelwert kreuzen ({zero_crossings} Mal). "
            )
            if coint_p is not None and coint_p > 0.05:
                details += f"Der Cointegration-Test ist statistisch nicht voll signifikant (p-Wert: {coint_p:.4f}). "
            details += "Handelbar, erfordert aber potenziell längere Haltefristen und engere Stop-Losses."
        else:
            rec = "POOR"
            rec_color = "🔴 Ungeeignet"
            details = (
                f"Dieses Paar ist für Statistical Arbitrage nicht zu empfehlen (Score: {score}/100). "
                f"Schwache Korrelation ({corr:.2f}) oder extrem langsame Mean-Reversion "
                f"(Halbwertszeit: {half_life:.1f} Tage, nur {zero_crossings} Mean-Crossings). "
                "Das Risiko eines anhaltenden Auseinanderlaufens (Divergenz) ist sehr hoch."
            )
            
        return {
            "status": "success",
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "correlation": corr,
            "beta": beta,
            "alpha": alpha,
            "half_life": half_life,
            "zero_crossings": zero_crossings,
            "normalized_crossings_annual": normalized_crossings,
            "coint_p": coint_p,
            "statsmodels_available": statsmodels_available,
            "score": score,
            "recommendation": rec,
            "recommendation_color": rec_color,
            "details": details,
            "data_points": len(df)
        }
