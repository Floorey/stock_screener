import os
import sys
import json
from mcp.server.fastmcp import FastMCP

# Ensure parent directory is in the path to load local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alpaca_trader import (
    is_alpaca_configured,
    get_account_info,
    get_positions,
    place_order
)
from watchlist_manager import load_watchlist

# Create FastMCP server instance
mcp = FastMCP("Alpaca Stock Screener")

@mcp.tool()
def get_watchlist() -> list[str]:
    """Retrieves the list of stock ticker symbols on the user's watchlist."""
    return load_watchlist()

@mcp.tool()
def get_screener_scores() -> str:
    """
    Retrieves the cached stock screener results (including Long and Short scores) 
    for all tickers currently in the cache. This helps find potential trade candidates.
    """
    cache_path = os.path.join(os.path.dirname(__file__), "screener_cache.json")
    if not os.path.exists(cache_path):
        return "Keine Screener-Daten im Cache gefunden. Bitte starten Sie zuerst einen Scan im Dashboard."
    
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        from screener import calculate_scores
        import pandas as pd
        
        # Load cache into database rows
        rows = []
        for ticker, data in cache_data.items():
            if isinstance(data, dict):
                # Check structure (cache stores ticker name as key, metrics as values or info dict)
                if "info" in data:
                    rows.append(data["info"])
                else:
                    # Fallback for alternative cache structures
                    item = data.copy()
                    item["Symbol"] = ticker
                    rows.append(item)
                    
        if not rows:
            return "Der lokale Screener-Cache ist leer."
            
        df = pd.DataFrame(rows)
        df_scored = calculate_scores(df)
        
        # Select key columns to show in chat
        cols = ["Symbol", "Company", "LongScore", "ShortScore", "Price", "PE", "DebtToEquity", "CurrentRatio", "ROE"]
        cols_existing = [c for c in cols if c in df_scored.columns]
        
        # Sort by LongScore descending
        df_sorted = df_scored.sort_values(by="LongScore", ascending=False)
        return df_sorted[cols_existing].to_string(index=False)
    except Exception as e:
        return f"Fehler beim Laden des Caches: {str(e)}"

@mcp.tool()
def get_alpaca_account_summary() -> str:
    """Gets a summary of the Alpaca trading account including equity, cash, and buying power."""
    if not is_alpaca_configured():
        return "Alpaca API Keys sind nicht konfiguriert. Bitte in der .env oder Sidebar eintragen."
    
    acc = get_account_info()
    if not acc:
        return "Fehler beim Abrufen der Kontodaten."
    
    return (
        f"Konto-Status: {acc.get('status', 'ACTIVE')}\n"
        f"Portfolio-Wert (Equity): ${float(acc.get('equity', 0)):,.2f}\n"
        f"Freies Bargeld (Cash): ${float(acc.get('cash', 0)):,.2f}\n"
        f"Kaufkraft (Buying Power): ${float(acc.get('buying_power', 0)):,.2f}"
    )

@mcp.tool()
def get_alpaca_portfolio_positions() -> str:
    """Lists all open investment positions in the Alpaca account."""
    if not is_alpaca_configured():
        return "Alpaca API Keys sind nicht konfiguriert."
    
    positions = get_positions()
    if not positions:
        return "Keine offenen Positionen im Portfolio."
    
    lines = []
    for p in positions:
        lines.append(
            f"Symbol: {p.get('symbol')} | Menge: {p.get('qty')} | "
            f"Marktwert: ${float(p.get('market_value', 0)):,.2f} | "
            f"Einstiegspreis: ${float(p.get('avg_entry_price', 0)):.2f} | "
            f"GuV: ${float(p.get('unrealized_pl', 0)):,.2f} ({float(p.get('unrealized_plpc', 0))*100:.2f}%)"
        )
    return "\n".join(lines)

@mcp.tool()
def execute_alpaca_trade(symbol: str, qty: float, side: str, order_type: str = "market", limit_price: float = None) -> str:
    """
    Submits a buy or sell trade order to Alpaca.
    
    :param symbol: Stock ticker symbol (e.g. 'AAPL')
    :param qty: Quantity to buy or sell
    :param side: 'buy' or 'sell'
    :param order_type: 'market' or 'limit'
    :param limit_price: Limit price for limit orders (optional)
    """
    res = place_order(symbol=symbol, qty=qty, side=side, order_type=order_type, limit_price=limit_price)
    if res.get("status") == "success":
        ord_info = res.get("order", {})
        return f"Order erfolgreich platziert! ID: {ord_info.get('id')} | Status: {ord_info.get('status')} | Side: {side} | Qty: {qty} of {symbol}"
    else:
        return f"Fehler beim Platzieren der Order: {res.get('message')}"

if __name__ == "__main__":
    # When run directly, start the FastMCP server
    mcp.run()
