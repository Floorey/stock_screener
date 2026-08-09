import yfinance as yf
import pandas as pd
import numpy as np
import time

# Top 30 NASDAQ (approximate based on search)
nasdaq_30 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "ASML",
    "AZN", "PEP", "LIN", "AMD", "ADBE", "TMUS", "CSCO", "INTU", "QCOM", "TXN",
    "AMAT", "ISRG", "AMGN", "HON", "BKNG", "SBUX", "MDLZ", "VRTX", "ADP", "INTC"
]

# Top 10 Russell 2000 (approximate based on search)
russell_10 = [
    "CVNA", "B", "MSTR", "INSM", "FIX", "SATS", "ASTS", "BE", "FTAI", "SMCI"
]

def get_data(tickers):
    data = yf.download(tickers, period="60d", interval="1d")['Close']
    return data

def calculate_zscore(price_a, price_b):
    # Ratio spread
    ratio = price_a / price_b
    mean = ratio.mean()
    std = ratio.std()
    zscore = (ratio.iloc[-1] - mean) / std
    return zscore

def main():
    all_tickers = list(set(nasdaq_30 + russell_10))
    print(f"Fetching data for {len(all_tickers)} tickers...")
    df = get_data(all_tickers)
    
    # Check for missing data
    df = df.dropna(axis=1, how='all')
    valid_tickers = df.columns.tolist()
    
    nasdaq_valid = [t for t in nasdaq_30 if t in valid_tickers]
    russell_valid = [t for t in russell_10 if t in valid_tickers]
    
    pairs = []
    # Intra-NASDAQ pairs
    for i in range(len(nasdaq_valid)):
        for j in range(i + 1, len(nasdaq_valid)):
            pairs.append((nasdaq_valid[i], nasdaq_valid[j]))
            
    # Intra-Russell pairs
    for i in range(len(russell_valid)):
        for j in range(i + 1, len(russell_valid)):
            pairs.append((russell_valid[i], russell_valid[j]))

    # Cross-index pairs
    for n in nasdaq_valid:
        for r in russell_valid:
            pairs.append((n, r))

    results = []
    target_z = 1.56
    tolerance = 0.05
    
    print(f"Analyzing {len(pairs)} pairs...")
    from arbitrage_lab import StatisticalArbitrageLab
    lab = StatisticalArbitrageLab()
    
    final_candidates = []
    
    for t1, t2 in pairs:
        try:
            z = calculate_zscore(df[t1], df[t2])
            if abs(abs(z) - target_z) < tolerance:
                # Get suitability score
                suit = lab.calculate_pair_suitability(t1, t2, period="60d")
                if suit.get("status") != "error":
                    score = suit.get("score", 0)
                    final_candidates.append({
                        "pair": f"{t1} - {t2}",
                        "z_score": z,
                        "suitability_score": score,
                        "recommendation": suit.get("recommendation", "N/A")
                    })
        except Exception:
            continue
            
    # Sort by suitability score
    final_candidates.sort(key=lambda x: x["suitability_score"], reverse=True)

    print("\nTop Pairs with Z-Score ~1.56 sorted by suitability:")
    for cand in final_candidates:
        print(f"{cand['pair']}: Z={cand['z_score']:.4f}, Suitability={cand['suitability_score']}, Rec={cand['recommendation']}")

if __name__ == "__main__":
    main()
