import requests
import yfinance as yf
import pandas as pd
import json
from typing import List, Dict, Any

def fetch_macro_futures() -> pd.DataFrame:
    """
    Fetches major stock futures, volatility, treasury yields, and commodities.
    Returns a pandas DataFrame with Symbol, Name, Last Price, Change, and Change %.
    """
    macro_tickers = {
        "ES=F": "S&P 500 Futures",
        "NQ=F": "Nasdaq 100 Futures",
        "RTY=F": "Russell 2000 Futures",
        "^VIX": "VIX Volatilitätsindex",
        "^TNX": "10-Jahre US-Anleiherendite",
        "DX-Y.NYB": "US-Dollar-Index",
        "GC=F": "Gold Futures",
        "CL=F": "Rohöl Futures (WTI)"
    }
    
    results = []
    for ticker_symbol, name in macro_tickers.items():
        try:
            t = yf.Ticker(ticker_symbol)
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            
            # If standard info fails, try history
            if price is None and prev_close is None:
                hist = t.history(period="2d")
                if len(hist) >= 2:
                    price = hist["Close"].iloc[-1]
                    prev_close = hist["Close"].iloc[-2]
                elif len(hist) == 1:
                    price = hist["Close"].iloc[0]
                    prev_close = price
            
            if price is not None:
                change = 0.0
                change_pct = 0.0
                if prev_close:
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100.0
                    
                results.append({
                    "Symbol": ticker_symbol,
                    "Name": name,
                    "Kurs": f"{price:.2f}" if ticker_symbol != "^TNX" else f"{price:.3f}%",
                    "Änderung": f"{change:+.2f}" if ticker_symbol != "^TNX" else f"{change:+.3f}",
                    "Änderung %": f"{change_pct:+.2f}%",
                    "Raw_Change_Pct": change_pct # For coloring
                })
        except Exception as e:
            # Skip if fetch fails
            pass
            
    return pd.DataFrame(results)

def search_polymarket_markets(query: str) -> List[Dict[str, Any]]:
    """
    Searches Polymarket for active prediction markets related to a query.
    Handles both raw lists and stringified JSON formats in response.
    Returns a list of dictionaries with Event Title, Outcomes, Prices, and Close Date.
    """
    url = "https://gamma-api.polymarket.com/public-search"
    params = {
        "q": query
    }
    
    parsed_markets = []
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            events = data.get("events", [])
            
            for event in events:
                event_title = event.get("title", "")
                markets = event.get("markets", [])
                
                for m in markets:
                    # Filter for active markets
                    if m.get("closed") or m.get("archived"):
                        continue
                        
                    outcomes_raw = m.get("outcomes", [])
                    prices_raw = m.get("outcomePrices", [])
                    
                    # Safe parsing of outcomes
                    outcomes = []
                    if isinstance(outcomes_raw, str):
                        try:
                            outcomes = json.loads(outcomes_raw)
                        except:
                            outcomes = [outcomes_raw] if outcomes_raw else []
                    elif isinstance(outcomes_raw, list):
                        outcomes = outcomes_raw
                        
                    # Safe parsing of outcome prices
                    prices = []
                    if isinstance(prices_raw, str):
                        try:
                            prices = json.loads(prices_raw)
                        except:
                            prices = [prices_raw] if prices_raw else []
                    elif isinstance(prices_raw, list):
                        prices = prices_raw
                    
                    # Formulate outcome probability text e.g. "Yes: 65%, No: 35%"
                    odds = []
                    if outcomes and prices:
                        for o, p in zip(outcomes, prices):
                            try:
                                prob_pct = float(p) * 100.0
                                odds.append(f"{o}: {prob_pct:.1f}%")
                            except:
                                odds.append(f"{o}: {p}")
                                
                    odds_text = ", ".join(odds)
                    
                    # Format date
                    end_date = m.get("endDate", "N/A")
                    try:
                        if end_date != "N/A":
                            end_date = pd.to_datetime(end_date).strftime('%d.%m.%Y')
                    except:
                        pass
                    
                    parsed_markets.append({
                        "Thema": event_title,
                        "Wettfrage": m.get("question", ""),
                        "Wahrscheinlichkeiten": odds_text,
                        "Enddatum": end_date,
                        "Volumen": f"${float(m.get('volume', 0)):,.0f}" if m.get('volume') else "$0",
                        "Link": f"https://polymarket.com/event/{event.get('slug')}"
                    })
    except Exception as e:
        print(f"Error searching Polymarket: {e}")
        
    # Return top 8 most active/relevant markets
    return parsed_markets[:8]

def fetch_company_news(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetches news stories for a specific stock ticker using yfinance.
    Adapts dynamically to both flat and nested 'content' JSON structures in yfinance.
    """
    articles = []
    try:
        t = yf.Ticker(symbol)
        news = t.news
        if news:
            for item in news[:6]: # Take top 6 news articles
                content = item.get("content", {})
                if not content:
                    # Fallback to old flat structure if nested content is not present
                    content = item
                
                title = content.get("title", "Kein Titel")
                
                # Extract publisher
                provider = content.get("provider", {})
                publisher = provider.get("displayName") or content.get("publisher", "Unbekannt")
                
                # Extract date
                pub_date = content.get("pubDate") or content.get("displayTime")
                time_str = "N/A"
                if pub_date:
                    try:
                        if isinstance(pub_date, str):
                            time_str = pd.to_datetime(pub_date).strftime('%d.%m.%Y %H:%M')
                        else:
                            time_str = pd.to_datetime(pub_date, unit='s').strftime('%d.%m.%Y %H:%M')
                    except Exception:
                        time_str = str(pub_date)
                
                # Extract link
                url_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
                link = url_info.get("url") or content.get("link") or "#"
                
                articles.append({
                    "Titel": title,
                    "Herausgeber": publisher,
                    "Datum": time_str,
                    "Link": link
                })
    except Exception as e:
        print(f"Error fetching news for {symbol}: {e}")
    return articles

def fetch_wsb_trending() -> Dict[str, Dict[str, Any]]:
    """
    Fetches trending tickers from ApeWisdom API for WallStreetBets.
    Returns a dictionary mapping ticker -> {rank, mentions, upvotes, rank_24h_ago, mentions_24h_ago}.
    """
    url = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            wsb_dict = {}
            for item in results:
                ticker = item.get("ticker")
                if ticker:
                    wsb_dict[ticker] = {
                        "rank": item.get("rank"),
                        "mentions": item.get("mentions"),
                        "upvotes": item.get("upvotes"),
                        "rank_24h_ago": item.get("rank_24h_ago"),
                        "mentions_24h_ago": item.get("mentions_24h_ago")
                    }
            return wsb_dict
    except Exception as e:
        print(f"Error fetching WSB trending data: {e}")
    return {}
