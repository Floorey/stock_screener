import json
import os
from typing import List

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")

def load_watchlist() -> List[str]:
    """Loads the watchlist tickers from a JSON file."""
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Support both list of strings or list of dicts
            if isinstance(data, list):
                if all(isinstance(item, str) for item in data):
                    return data
                elif all(isinstance(item, dict) for item in data):
                    return [item["symbol"] for item in data if "symbol" in item]
    except Exception as e:
        print(f"Error loading watchlist: {e}")
    return []

def save_watchlist(tickers: List[str]) -> None:
    """Saves the watchlist tickers to a JSON file."""
    try:
        # Keep it unique and sorted
        unique_tickers = sorted(list(set(tickers)))
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(unique_tickers, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving watchlist: {e}")

def add_to_watchlist(ticker: str) -> bool:
    """Adds a single ticker to the watchlist. Returns True if added, False if already exists."""
    ticker = ticker.strip().upper()
    if not ticker:
        return False
    watchlist = load_watchlist()
    if ticker in watchlist:
        return False
    watchlist.append(ticker)
    save_watchlist(watchlist)
    return True

def remove_from_watchlist(ticker: str) -> bool:
    """Removes a single ticker from the watchlist. Returns True if removed, False otherwise."""
    ticker = ticker.strip().upper()
    watchlist = load_watchlist()
    if ticker not in watchlist:
        return False
    watchlist.remove(ticker)
    save_watchlist(watchlist)
    return True
