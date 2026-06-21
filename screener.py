import os
import sys
import requests
import json
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from dotenv import load_dotenv
from typing import List, Dict, Any, Tuple

# Reconfigure stdout to UTF-8 on Windows to prevent console print crashes
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")

# Load environment variables from .env file
load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Caching Configuration
CACHE_FILE = os.path.join(os.path.dirname(__file__), "screener_cache.json")
CACHE_EXPIRATION = 86400 # 24 Hours in seconds

def load_cache() -> Dict[str, Dict[str, Any]]:
    """Loads fundamental data cache from a local JSON file."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Cache] Fehler beim Laden des Caches: {e}")
        return {}

def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    """Saves fundamental data cache to a local JSON file."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Cache] Fehler beim Schreiben des Caches: {e}")

def get_alpaca_assets() -> Dict[str, Dict[str, bool]]:
    """
    Fetches all active US equities from Alpaca and returns a dictionary 
    mapping symbol -> {tradable: bool, shortable: bool, easy_to_borrow: bool}
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return {}
    
    url = f"{ALPACA_BASE_URL}/v2/assets"
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
    }
    params = {
        "status": "active",
        "asset_class": "us_equity"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            assets = response.json()
            asset_dict = {}
            for asset in assets:
                symbol = asset.get("symbol")
                asset_dict[symbol] = {
                    "tradable": asset.get("tradable", False),
                    "shortable": asset.get("shortable", False),
                    "easy_to_borrow": asset.get("easy_to_borrow", False)
                }
            print(f"[Alpaca] {len(asset_dict)} aktive US-Aktien erfolgreich geladen.")
            return asset_dict
        else:
            print(f"[Alpaca] Fehler beim Laden des Asset-Status: {response.status_code}")
    except Exception as e:
        print(f"[Alpaca] Fehler bei der Verbindung zur Alpaca API: {e}")
    
    return {}

def fetch_sp500_tickers() -> List[Tuple[str, str]]:
    """Scrapes S&P 500 tickers and company names from Wikipedia. Includes fallback list."""
    print("[Fetcher] Lade S&P 500 Ticker von Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            tables = pd.read_html(response.text)
            df = tables[0]
            df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
            tickers = list(zip(df["Symbol"], df["Security"]))
            print(f"[Fetcher] {len(tickers)} S&P 500 Ticker erfolgreich geladen.")
            return tickers
        else:
            print(f"[Fetcher] Wikipedia antwortete mit Status: {response.status_code}. Nutze Fallback.")
    except Exception as e:
        print(f"[Fetcher] Wikipedia-Scraping für S&P 500 fehlgeschlagen: {e}. Nutze Fallback.")
    
    # 50 Major S&P 500 Fallback list
    sp500_fallback = [
        ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corp."), ("NVDA", "NVIDIA Corp."), 
        ("AMZN", "Amazon.com Inc."), ("META", "Meta Platforms Inc."), ("GOOGL", "Alphabet Inc. Cl A"), 
        ("BRK-B", "Berkshire Hathaway"), ("LLY", "Eli Lilly & Co."), ("AVGO", "Broadcom Inc."), 
        ("JPM", "JPMorgan Chase & Co."), ("TSLA", "Tesla Inc."), ("UNH", "UnitedHealth Group Inc."), 
        ("V", "Visa Inc."), ("XOM", "Exxon Mobil Corp."), ("MA", "Mastercard Inc. Cl A"), 
        ("JNJ", "Johnson & Johnson"), ("PG", "Procter & Gamble Co."), ("HD", "Home Depot Inc."), 
        ("COST", "Costco Wholesale Corp."), ("AMD", "Advanced Micro Devices"), ("NFLX", "Netflix Inc."), 
        ("MRK", "Merck & Co. Inc."), ("PEP", "PepsiCo Inc."), ("CVX", "Chevron Corp."), 
        ("KO", "Coca-Cola Co."), ("ORCL", "Oracle Corp."), ("WMT", "Walmart Inc."), 
        ("BAC", "Bank of America Corp."), ("ADBE", "Adobe Inc."), ("CRM", "Salesforce Inc."), 
        ("ABT", "Abbott Laboratories"), ("DIS", "Walt Disney Co."), ("TXN", "Texas Instruments Inc."), 
        ("PM", "Philip Morris International"), ("LIN", "Linde plc"), ("TMO", "Thermo Fisher Scientific"), 
        ("QCOM", "Qualcomm Inc."), ("INTC", "Intel Corp."), ("CAT", "Caterpillar Inc."), 
        ("VZ", "Verizon Communications"), ("CMCSA", "Comcast Corp. Cl A"), ("IBM", "International Business Machines"), 
        ("AMGN", "Amgen Inc."), ("UNP", "Union Pacific Corp."), ("GE", "General Electric Co."), 
        ("PFE", "Pfizer Inc."), ("HON", "Honeywell International"), ("INTU", "Intuit Inc."), 
        ("SPGI", "S&P Global Inc."), ("COP", "ConocoPhillips")
    ]
    print(f"[Fetcher] Fallback geladen: {len(sp500_fallback)} S&P 500 Ticker.")
    return sp500_fallback

def fetch_dow_jones_tickers() -> List[Tuple[str, str]]:
    """Scrapes Dow Jones Industrial Average tickers and company names from Wikipedia. Includes fallback list."""
    print("[Fetcher] Lade Dow Jones Ticker von Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            tables = pd.read_html(response.text)
            for table in tables:
                columns = [str(col).lower() for col in table.columns]
                if "symbol" in columns or "ticker" in columns:
                    symbol_col = [col for col in table.columns if "symbol" in str(col).lower() or "ticker" in str(col).lower()][0]
                    name_col = [col for col in table.columns if "company" in str(col).lower() or "corporation" in str(col).lower()][0]
                    table[symbol_col] = table[symbol_col].str.replace(".", "-", regex=False)
                    tickers = list(zip(table[symbol_col], table[name_col]))
                    print(f"[Fetcher] {len(tickers)} Dow Jones Ticker erfolgreich geladen.")
                    return tickers
        else:
            print(f"[Fetcher] Wikipedia antwortete mit Status: {response.status_code}. Nutze Fallback.")
    except Exception as e:
        print(f"[Fetcher] Wikipedia-Scraping für Dow Jones fehlgeschlagen: {e}. Nutze Fallback.")
    
    # 30 Dow Jones Fallback list
    fallback = [
        ("AAPL", "Apple Inc."), ("AMZN", "Amazon.com Inc."), ("AXP", "American Express Co."),
        ("BA", "Boeing Co."), ("CAT", "Caterpillar Inc."), ("CRM", "Salesforce Inc."),
        ("CSCO", "Cisco Systems Inc."), ("CVX", "Chevron Corp."), ("DIS", "Walt Disney Co."),
        ("GS", "Goldman Sachs Group Inc."), ("HD", "Home Depot Inc."), ("HON", "Honeywell International Inc."),
        ("IBM", "International Business Machines Corp."), ("INTC", "Intel Corp."), ("JNJ", "Johnson & Johnson"),
        ("JPM", "JPMorgan Chase & Co."), ("KO", "Coca-Cola Co."), ("MCD", "McDonald's Corp."),
        ("MMM", "3M Co."), ("MRK", "Merck & Co. Inc."), ("MSFT", "Microsoft Corp."),
        ("NKE", "Nike Inc."), ("PG", "Procter & Gamble Co."), ("TRV", "Travelers Companies Inc."),
        ("UNH", "UnitedHealth Group Inc."), ("V", "Visa Inc."), ("VZ", "Verizon Communications Inc."),
        ("WBA", "Walgreens Boots Alliance Inc."), ("WMT", "Walmart Inc."), ("XOM", "Exxon Mobil Corp.")
    ]
    print(f"[Fetcher] Fallback geladen: {len(fallback)} Dow Jones Ticker.")
    return fallback

def fetch_russell2000_tickers() -> List[Tuple[str, str]]:
    """Fetches Russell 2000 tickers from ikoniaris repository on GitHub. Includes fallback list."""
    print("[Fetcher] Lade Russell 2000 Ticker von GitHub...")
    try:
        url = "https://raw.githubusercontent.com/ikoniaris/Russell2000/master/russell_2000_components.csv"
        df = pd.read_csv(url)
        df["Ticker"] = df["Ticker"].str.replace(".", "-", regex=False)
        tickers = list(zip(df["Ticker"], df["Company"]))
        print(f"[Fetcher] {len(tickers)} Russell 2000 Ticker erfolgreich geladen.")
        return tickers
    except Exception as e:
        print(f"[Fetcher] GitHub-Laden für Russell 2000 fehlgeschlagen: {e}. Nutze Fallback.")
    
    # 50 Major Russell 2000 Fallback list
    r2000_fallback = [
        ("SOFI", "SoFi Technologies Inc."), ("HOOD", "Robinhood Markets Inc."), ("RIOT", "Riot Platforms Inc."),
        ("MARA", "MARA Holdings Inc."), ("RUN", "Sunrun Inc."), ("GME", "GameStop Corp."),
        ("AMC", "AMC Entertainment Holdings"), ("ELF", "e.l.f. Beauty Inc."), ("KRE", "SPDR S&P Regional Banking ETF"),
        ("BBIO", "BridgeBio Pharma Inc."), ("WING", "Wingstop Inc."), ("AAON", "AAON Inc."),
        ("UCTT", "Ultra Clean Holdings"), ("FRSH", "Freshworks Inc."), ("CRSR", "Corsair Gaming Inc."),
        ("ANF", "Abercrombie & Fitch Co."), ("NKLA", "Nikola Corp."), ("DKNG", "DraftKings Inc."),
        ("PLUG", "Plug Power Inc."), ("CLSK", "CleanSpark Inc."), ("HUT", "Hut 8 Corp."),
        ("BLNK", "Blink Charging Co."), ("FCEL", "FuelCell Energy Inc."), ("NOVA", "Sunnova Energy International"),
        ("UPST", "Upstart Holdings Inc."), ("LCID", "Lucid Group Inc."), ("RIVN", "Rivian Automotive Inc."),
        ("NVAX", "Novavax Inc."), ("BYND", "Beyond Meat Inc."), ("SPCE", "Virgin Galactic Holdings"),
        ("FUBO", "FuboTV Inc."), ("OPEN", "Opendoor Technologies"), ("WISH", "ContextLogic Inc."),
        ("DK", "Delek US Holdings"), ("CGC", "Canopy Growth Corp."), ("TLRY", "Tilray Brands Inc."),
        ("ACB", "Aurora Cannabis Inc."), ("Sound", "SoundHound AI Inc."), ("BBAI", "BigBear.ai Holdings"),
        ("PLTR", "Palantir Technologies Inc."), ("AI", "C3.ai Inc."), ("SOUN", "SoundHound AI Inc."),
        ("SERV", "Serve Robotics Inc."), ("OKLO", "Oklo Inc."), ("LUNR", "Intuitive Machines Inc."),
        ("VLD", "Velo3D Inc."), ("DRUG", "Bright Minds Biosciences"), ("TEM", "Tempus AI Inc."),
        ("ZETA", "Zeta Global Holdings"), ("HIMS", "Hims & Hers Health Inc.")
    ]
    print(f"[Fetcher] Fallback geladen: {len(r2000_fallback)} Russell 2000 Ticker.")
    return r2000_fallback

def get_single_ticker_data(ticker_symbol: str, company_name: str, index_name: str, alpaca_status: Dict[str, bool]) -> Dict[str, Any]:
    """
    Downloads fundamental data for a single ticker from yfinance.
    """
    data = {
        "Symbol": ticker_symbol,
        "Company": company_name,
        "Index": index_name,
        "Tradable": alpaca_status.get("tradable", True),
        "Shortable": alpaca_status.get("shortable", True),
        "EasyToBorrow": alpaca_status.get("easy_to_borrow", False),
        "Sector": "N/A",
        "Industry": "N/A",
        "PE": None,
        "ForwardPE": None,
        "PB": None,
        "DebtToEquity": None,
        "CurrentRatio": None,
        "QuickRatio": None,
        "FCF": None,
        "OperatingCashflow": None,
        "NetMargin": None,
        "OperatingMargin": None,
        "ROE": None,
        "ROA": None,
        "RevenueGrowth": None,
        "EPSGrowth": None,
        "ShortInterestPercent": None,
        "Beta": None,
        "EV": None,
        "EVToRevenue": None,
        "EVToEbitda": None,
        "Price": None
    }
    
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        
        if not info or len(info) <= 5: 
            return data
            
        data["Sector"] = info.get("sector", "N/A")
        data["Industry"] = info.get("industry", "N/A")
        
        data["Price"] = info.get("currentPrice") or info.get("previousClose")
        data["PE"] = info.get("trailingPE")
        data["ForwardPE"] = info.get("forwardPE")
        data["PB"] = info.get("priceToBook")
        data["EV"] = info.get("enterpriseValue")
        data["EVToRevenue"] = info.get("enterpriseToRevenue")
        data["EVToEbitda"] = info.get("enterpriseToEbitda")
        
        data["DebtToEquity"] = info.get("debtToEquity")
        if data["DebtToEquity"] is not None:
            data["DebtToEquity"] = data["DebtToEquity"] / 100.0
            
        data["CurrentRatio"] = info.get("currentRatio")
        data["QuickRatio"] = info.get("quickRatio")
        
        data["FCF"] = info.get("freeCashflow")
        data["OperatingCashflow"] = info.get("operatingCashflow")
        data["NetMargin"] = info.get("profitMargins")
        data["OperatingMargin"] = info.get("operatingMargins")
        
        data["ROE"] = info.get("returnOnEquity")
        data["ROA"] = info.get("returnOnAssets")
        
        data["RevenueGrowth"] = info.get("revenueGrowth")
        data["EPSGrowth"] = info.get("earningsGrowth")
        
        data["ShortInterestPercent"] = info.get("shortPercentOfFloat")
        data["Beta"] = info.get("beta")
        
    except Exception:
        pass
        
    return data

def calculate_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates fundamental Long and Short scores for the assets."""
    df = df.copy()
    long_scores = []
    short_scores = []
    
    for idx, row in df.iterrows():
        l_score = 0
        s_score = 0
        
        # --- LONG SCORE ---
        pe = row["PE"]
        if pe is not None and 5 < pe < 25:
            l_score += 1
        pb = row["PB"]
        if pb is not None and pb < 3.0:
            l_score += 1
        
        de = row["DebtToEquity"]
        if de is not None and de < 1.0:
            l_score += 1
        cr = row["CurrentRatio"]
        if cr is not None and cr > 1.5:
            l_score += 1
            
        fcf = row["FCF"]
        if fcf is not None and fcf > 0:
            l_score += 1
            
        roe = row["ROE"]
        if roe is not None and roe > 0.12:
            l_score += 1
        rev_growth = row["RevenueGrowth"]
        if rev_growth is not None and rev_growth > 0.05:
            l_score += 1
            
        # --- SHORT SCORE ---
        if de is not None and de > 2.5:
            s_score += 1
        if cr is not None and cr < 1.0:
            s_score += 1
            
        if fcf is not None and fcf < 0:
            s_score += 1
            
        ev_rev = row["EVToRevenue"]
        if pe is None or pe < 0:
            if ev_rev is not None and ev_rev > 12:
                s_score += 1.5
        elif pe is not None and pe > 50:
            s_score += 1
            
        if rev_growth is not None and rev_growth < -0.05:
            s_score += 1
        net_margin = row["NetMargin"]
        if net_margin is not None and net_margin < -0.10:
            s_score += 1
            
        short_interest = row["ShortInterestPercent"]
        if short_interest is not None and short_interest > 0.20:
            s_score -= 0.5 
            
        long_scores.append(l_score)
        short_scores.append(s_score)
        
    df["LongScore"] = long_scores
    df["ShortScore"] = short_scores
    return df

def run_screener(index_name: str = "S&P 500", limit: int = None, max_workers: int = 10) -> pd.DataFrame:
    """
    Main screener engine. Fetches index tickers, cross-references local cache,
    downloads missing data from yfinance in parallel, and scores the results.
    """
    # 1. Fetch Tickers
    if index_name == "S&P 500":
        tickers_data = fetch_sp500_tickers()
    elif index_name == "Dow Jones":
        tickers_data = fetch_dow_jones_tickers()
    elif index_name == "Russell 2000":
        tickers_data = fetch_russell2000_tickers()
    else:
        print(f"Index {index_name} unbekannt. Breche ab.")
        return pd.DataFrame()
        
    if not tickers_data:
        print("[Error] Keine Ticker geladen.")
        return pd.DataFrame()
        
    # Apply limit if set (useful for quick testing)
    if limit and limit > 0:
        tickers_data = tickers_data[:limit]
        print(f"[Info] Limit auf {limit} Ticker gesetzt.")
        
    # 2. Get Alpaca assets lookup
    alpaca_assets = get_alpaca_assets()
    
    filtered_tickers = []
    for ticker, name in tickers_data:
        status = alpaca_assets.get(ticker, {"tradable": True, "shortable": True, "easy_to_borrow": False})
        filtered_tickers.append((ticker, name, status))
        
    # 3. Cache Check & Data Splits
    cache = load_cache()
    current_time = time.time()
    results = []
    tickers_to_fetch = []
    
    for ticker, name, status in filtered_tickers:
        cached_entry = cache.get(ticker)
        # Check if cache is fresh (less than 24 hours old)
        if cached_entry and (current_time - cached_entry.get("timestamp", 0) < CACHE_EXPIRATION):
            cached_data = cached_entry["data"]
            # Sync metadata dynamic values
            cached_data["Index"] = index_name
            cached_data["Tradable"] = status.get("tradable", True)
            cached_data["Shortable"] = status.get("shortable", True)
            cached_data["EasyToBorrow"] = status.get("easy_to_borrow", False)
            results.append(cached_data)
        else:
            tickers_to_fetch.append((ticker, name, status))
            
    # 4. Fetch missing tickers in parallel
    if tickers_to_fetch:
        print(f"[Fetcher] {len(results)} Ticker aus dem Cache geladen. Starte Download für {len(tickers_to_fetch)} Ticker mit {max_workers} Threads...")
        fetched_results = []
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(get_single_ticker_data, ticker, name, index_name, status): ticker 
                for ticker, name, status in tickers_to_fetch
            }
            
            completed = 0
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    data = future.result()
                    fetched_results.append(data)
                except Exception as e:
                    print(f"[Error] Fehler bei Ticker {ticker}: {e}")
                    
                completed += 1
                if completed % 25 == 0 or completed == len(tickers_to_fetch):
                    print(f"[Fetcher] Fortschritt: {completed}/{len(tickers_to_fetch)} heruntergeladen...")
                    
        duration = time.time() - start_time
        print(f"[Fetcher] Download abgeschlossen in {duration:.2f} Sekunden.")
        
        # 5. Process fetched results, update cache, and handle expired fallback
        cache_updated = False
        for data in fetched_results:
            ticker = data["Symbol"]
            if data["Sector"] != "N/A":
                # Download successful, save to cache
                cache[ticker] = {
                    "timestamp": current_time,
                    "data": data
                }
                cache_updated = True
                results.append(data)
            else:
                # yfinance fetch failed (rate-limited/blocked)
                # Fallback to expired cache if available as last resort
                old_entry = cache.get(ticker)
                if old_entry:
                    print(f"[Screener] yfinance fehlgeschlagen für {ticker}. Verwende abgelaufenen Cache als Fallback.")
                    fallback_data = old_entry["data"]
                    # Update dynamic metadata
                    for ticker_t, name_t, status_t in filtered_tickers:
                        if ticker_t == ticker:
                            fallback_data["Index"] = index_name
                            fallback_data["Tradable"] = status_t.get("tradable", True)
                            fallback_data["Shortable"] = status_t.get("shortable", True)
                            fallback_data["EasyToBorrow"] = status_t.get("easy_to_borrow", False)
                    results.append(fallback_data)
                else:
                    results.append(data)
                    
        if cache_updated:
            save_cache(cache)
    else:
        print(f"[Fetcher] Alle {len(filtered_tickers)} Ticker erfolgreich aus dem Cache geladen!")
        
    df = pd.DataFrame(results)
    
    # Drop rows that had failure loading key elements and had no cache backup
    valid_df = df[df["Sector"] != "N/A"].copy()
    print(f"[Screener] {len(valid_df)} von {len(df)} Tickers erfolgreich geladen.")
    
    if valid_df.empty:
        return pd.DataFrame()
        
    scored_df = calculate_scores(valid_df)
    
    # Reorder columns
    cols = ["Symbol", "Company", "Index", "Price", "Sector", "Industry", "LongScore", "ShortScore", "Tradable", "Shortable", "EasyToBorrow"]
    other_cols = [c for c in scored_df.columns if c not in cols]
    scored_df = scored_df[cols + other_cols]
    
    return scored_df

if __name__ == "__main__":
    print("=== FUNDAMENTAL STOCK SCREENER (Alpaca-kompatibel) ===")
    result_df = run_screener("Dow Jones", limit=15, max_workers=5)
    if not result_df.empty:
        print("\n--- TOP LONG CANDIDATES ---")
        long_candidates = result_df[result_df["Tradable"]].sort_values(by="LongScore", ascending=False)
        print(long_candidates[["Symbol", "Company", "LongScore", "PE", "DebtToEquity", "CurrentRatio"]].head(5).to_string(index=False))
        
        result_df.to_csv("screener_test_results.csv", index=False)
        print("\nTestergebnisse in 'screener_test_results.csv' gespeichert.")
