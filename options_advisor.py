import math
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List, Dict, Any, Tuple

# Pure Python Normal CDF approximation (no scipy needed)
def norm_cdf(x: float) -> float:
    """Cumulative distribution function for the standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def calculate_black_scholes_metrics(s: float, k: float, days: int, r: float, iv: float, option_type: str = "put") -> Tuple[float, float]:
    """
    Calculates the option Delta and the probability of expiring Out of the Money (OTM)
    using the Black-Scholes-Merton model.
    
    s: current stock price
    k: strike price
    days: days to expiration
    r: risk-free interest rate (e.g. 0.045 for 4.5%)
    iv: implied volatility (e.g. 0.25 for 25%)
    option_type: "call" or "put"
    
    Returns: (delta, probability_otm)
    """
    t = max(days, 1) / 365.0
    
    # Fallbacks for edge cases
    if iv <= 0:
        iv = 0.20
    if s <= 0 or k <= 0:
        return 0.0, 0.5
        
    try:
        d1 = (math.log(s / k) + (r + 0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)
        
        if option_type.lower() == "call":
            delta = norm_cdf(d1)
            prob_otm = norm_cdf(-d2) # P(S_T < K)
        else: # put
            delta = norm_cdf(d1) - 1.0
            prob_otm = norm_cdf(d2) # P(S_T > K)
            
        return delta, prob_otm
    except Exception:
        # Fallback in case of math domain error or overflow
        if option_type.lower() == "call":
            delta = 0.5 if s == k else (1.0 if s > k else 0.0)
            prob_otm = 0.5 if s == k else (0.0 if s > k else 1.0)
        else:
            delta = -0.5 if s == k else (0.0 if s > k else -1.0)
            prob_otm = 0.5 if s == k else (1.0 if s > k else 0.0)
        return delta, prob_otm

def suggest_option_strategy(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Suggests the best option strategy based on fundamental scores.
    """
    long_score = row.get("LongScore", 0)
    short_score = row.get("ShortScore", 0)
    price = row.get("Price", 0.0)
    symbol = row.get("Symbol", "")
    
    strategy = "Neutral / Halten"
    explanation = "Fundamentaldaten zeigen keinen starken Trend für Option-Selling."
    icon = "⚪"
    
    # Define strategy
    if long_score >= 4:
        strategy = "Short Put (Cash-Secured Put)"
        explanation = (
            f"Starkes Long-Signal (Long Score: {long_score}/7). Die Fundamentaldaten zeigen hohe Qualität "
            f"und faire Bewertung. Der Verkauf eines Cash-Secured Puts (OTM) ermöglicht es, eine Prämie einzunehmen "
            f"und die Aktie mit Rabatt zu erwerben, falls sie angedient wird."
        )
        icon = "🟢"
    elif short_score >= 3:
        strategy = "Short Call (Covered Call) / Bear Call Spread"
        explanation = (
            f"Starkes Short-Signal (Short Score: {short_score}/7). Die Fundamentaldaten zeigen hohe Verschuldung, "
            f"Cash-Burn oder unrentables Wachstum. Der Verkauf von OTM Calls (Covered Call) oder Bear Call Spreads "
            f"nutzt die erwartete Schwäche oder Seitwärtsbewegung."
        )
        icon = "🔴"
    elif long_score >= 3:
        strategy = "Short Put (Cash-Secured Put)"
        explanation = f"Moderates Long-Signal (Long Score: {long_score}/7). Verkauf von weit aus dem Geld liegenden Puts empfohlen."
        icon = "🟡"
    elif short_score >= 2:
        strategy = "Short Call (Covered Call) / Bear Call Spread"
        explanation = f"Moderates Short-Signal (Short Score: {short_score}/7). Verkauf von OTM Calls empfohlen."
        icon = "🟠"
        
    return {
        "Symbol": symbol,
        "CurrentPrice": price,
        "LongScore": long_score,
        "ShortScore": short_score,
        "Strategy": strategy,
        "Explanation": explanation,
        "Icon": icon
    }

def get_options_data_for_ticker(ticker_symbol: str, target_expiry: str = None) -> Tuple[List[str], Dict[str, pd.DataFrame]]:
    """
    Returns all available expiration dates and option chains (calls/puts) for a ticker.
    """
    t = yf.Ticker(ticker_symbol)
    dates = list(t.options)
    
    if not dates:
        return [], {}
        
    # If no expiry date is specified, pick the one closest to 30-45 days from now
    if not target_expiry:
        today = datetime.now()
        expiry_dates_dt = []
        for d in dates:
            try:
                expiry_dates_dt.append((d, datetime.strptime(d, "%Y-%m-%d")))
            except ValueError:
                pass
        
        # Sort by distance to 37 days (middle of 30-45 range)
        expiry_dates_dt.sort(key=lambda x: abs((x[1] - today).days - 37))
        target_expiry = expiry_dates_dt[0][0] if expiry_dates_dt else dates[0]
        
    try:
        chain = t.option_chain(target_expiry)
        return dates, {
            "expiry": target_expiry,
            "calls": chain.calls,
            "puts": chain.puts
        }
    except Exception as e:
        print(f"Error fetching option chain for {ticker_symbol} on {target_expiry}: {e}")
        return dates, {}

def build_option_screener_df(
    symbol: str,
    current_price: float,
    options_df: pd.DataFrame,
    days_to_expiry: int,
    r: float,
    option_type: str = "put"
) -> pd.DataFrame:
    """
    Enriches option chain dataframe with quantitative metrics (yields, delta, OTM probability).
    """
    if options_df.empty:
        return pd.DataFrame()
        
    df = options_df.copy()
    
    # Calculate Mid Price
    df["bid"] = df["bid"].fillna(0.0)
    df["ask"] = df["ask"].fillna(0.0)
    df["mid"] = (df["bid"] + df["ask"]) / 2.0
    
    # If bid is 0 but lastPrice exists, fallback mid to lastPrice or ask
    df.loc[df["mid"] == 0.0, "mid"] = df["lastPrice"]
    
    # Add distance to strike
    if option_type == "put":
        df["distance_pct"] = ((current_price - df["strike"]) / current_price) * 100
        # Filter for OTM puts (Strike < Current Price)
        df = df[df["strike"] <= current_price].copy()
    else:
        df["distance_pct"] = ((df["strike"] - current_price) / current_price) * 100
        # Filter for OTM calls (Strike > Current Price)
        df = df[df["strike"] >= current_price].copy()
        
    # Calculate Yields
    # Option seller return = Mid premium / strike for puts (secured capital), Mid / price for calls (covered yield)
    if option_type == "put":
        df["yield_pct"] = (df["mid"] / df["strike"]) * 100
    else:
        df["yield_pct"] = (df["mid"] / current_price) * 100
        
    df["annualized_yield_pct"] = df["yield_pct"] * (365.0 / days_to_expiry)
    
    # Implied Volatility
    df["impliedVolatility"] = df["impliedVolatility"].fillna(0.0)
    
    # Calculate BS Metrics (Delta and Prob of expiring OTM)
    deltas = []
    prob_otms = []
    
    for idx, row in df.iterrows():
        delta, prob_otm = calculate_black_scholes_metrics(
            s=current_price,
            k=row["strike"],
            days=days_to_expiry,
            r=r,
            iv=row["impliedVolatility"],
            option_type=option_type
        )
        deltas.append(delta)
        prob_otms.append(prob_otm)
        
    df["delta"] = deltas
    df["prob_otm_pct"] = [p * 100.0 for p in prob_otms]
    
    # Filter out illiquid options (e.g. bid = 0 or ask = 0)
    df = df[(df["bid"] > 0) | (df["ask"] > 0)].copy()
    
    return df

def find_featured_trade(
    symbol: str,
    current_price: float,
    options_df: pd.DataFrame,
    days_to_expiry: int,
    r: float,
    option_type: str = "put"
) -> Dict[str, Any]:
    """
    Finds the single best option contract matching target conservative guidelines:
    - Delta between 0.15 and 0.30 (or -0.30 and -0.15 for puts)
    - Good trading volume and open interest
    - OTM probability > 70%
    """
    if options_df.empty:
        return {}
        
    df = build_option_screener_df(symbol, current_price, options_df, days_to_expiry, r, option_type)
    if df.empty:
        return {}
        
    # Find candidate closest to ideal delta of 0.20 (or -0.20 for puts)
    target_delta = -0.20 if option_type == "put" else 0.20
    
    # Filter by delta range and positive bid
    if option_type == "put":
        candidates = df[(df["delta"] <= -0.10) & (df["delta"] >= -0.35)].copy()
    else:
        candidates = df[(df["delta"] >= 0.10) & (df["delta"] <= 0.35)].copy()
        
    if candidates.empty:
        # Fallback: just look at distance to strike (e.g. around 5-10% OTM)
        candidates = df[(df["distance_pct"] >= 4.0) & (df["distance_pct"] <= 12.0)].copy()
        
    if candidates.empty:
        # Second fallback: take anything OTM
        candidates = df.copy()
        
    # Sort candidates by distance to target delta (or strike distance if delta is zero)
    candidates["delta_diff"] = (candidates["delta"] - target_delta).abs()
        
    candidates = candidates.sort_values(by="delta_diff", ascending=True)
    best_option = candidates.iloc[0].to_dict()
    
    return best_option

def calculate_cds_metrics(
    s: float,
    k: float,
    bid: float,
    ask: float,
    days: int,
    r: float,
    iv: float
) -> Dict[str, Any]:
    """
    Calculates Synthetic CDS (Credit Default Swap) metrics for a given option contract.
    - CDS Spread (Sell / Bid) in basis points (bps)
    - CDS Spread (Buy / Ask) in basis points (bps)
    - Implied Default Probability (PD proxy)
    - Credit Risk Rating
    """
    t = days / 365.0
    
    # 1. CDS spreads in bps (1 bps = 0.01% of protected capital)
    # Protection face value is the Strike Price (K)
    # Annualized premium as fraction of face value = (Premium / K) * (1 / t)
    # Multiplied by 10,000 to convert to basis points
    cds_sell_bps = 0.0
    cds_buy_bps = 0.0
    
    if k > 0 and t > 0:
        cds_sell_bps = (bid / k) * (365.0 / days) * 10000.0
        cds_buy_bps = (ask / k) * (365.0 / days) * 10000.0
        
    # 2. Implied Probability of Default (PD) proxy
    # In BS, this is the probability of the stock price falling below the strike K (which triggers the credit event)
    # PD = P(S_T < K) = norm_cdf(-d2)
    _, prob_otm = calculate_black_scholes_metrics(s, k, days, r, iv, "put")
    implied_pd = 1.0 - (prob_otm / 100.0) if prob_otm > 1.0 else 1.0 - prob_otm
    # Make sure implied_pd is formatted correctly as a probability fraction
    if implied_pd < 0:
        implied_pd = 0.0
    elif implied_pd > 1.0:
        implied_pd = implied_pd / 100.0
        
    # 3. Credit Risk Rating based on CDS spread
    spread = (cds_sell_bps + cds_buy_bps) / 2.0 if (cds_sell_bps > 0 and cds_buy_bps > 0) else (cds_sell_bps if cds_sell_bps > 0 else 0.0)
    
    if spread < 100:
        rating = "Low Risk (Investment Grade: AAA / AA)"
        color = "🟢"
    elif spread < 250:
        rating = "Moderate Risk (Investment Grade: A / BBB)"
        color = "🟢"
    elif spread < 500:
        rating = "Elevated Risk (High Yield: BB)"
        color = "🟡"
    elif spread < 1000:
        rating = "High Risk (Speculative: B)"
        color = "🟠"
    else:
        rating = "Distressed / High Default Risk (CCC / D)"
        color = "🚨"
        
    return {
        "cds_sell_bps": cds_sell_bps,
        "cds_buy_bps": cds_buy_bps,
        "implied_pd_pct": implied_pd * 100.0,
        "rating": rating,
        "rating_color": color,
        "spread_mid": spread
    }
