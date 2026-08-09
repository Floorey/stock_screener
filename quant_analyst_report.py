import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any
from alpaca_trader import get_positions, get_account_activities, is_alpaca_configured

def fetch_quant_data() -> Dict[str, Any]:
    """
    Fetches positions and trade activities (FILLS) from Alpaca.
    """
    if not is_alpaca_configured():
        return {"error": "Alpaca API not configured."}

    positions = get_positions()
    # Fetch trade fills
    activities = get_account_activities(activity_types=["FILL"])
    
    return {
        "positions": positions,
        "activities": activities
    }

def categorize_trades(activities: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Groups activities by symbol and calculates realized P/L to categorize trades.
    Note: Alpaca 'FILL' activities don't directly show realized P/L for a 'trade' 
    in a single record if it's spread across multiple fills.
    We'll attempt a simple FIFO/matching or use the 'price' and 'qty'.
    """
    cols = ["Symbol", "Total Bought", "Total Sold", "Avg Buy Price", "Avg Sell Price", "Realized P/L %", "Category"]
    if not activities:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(activities)
    # Ensure numeric types
    df['qty'] = pd.to_numeric(df['qty'])
    df['price'] = pd.to_numeric(df['price'])
    df['transaction_time'] = pd.to_datetime(df['transaction_time'])
    
    # Simple categorization based on individual fills is hard without matching.
    # However, the requirement says "categorize the trades". 
    # Usually, a trade is an entry and exit.
    
    # For the sake of this report, we will group by symbol and look at the net P/L 
    # if we can determine it, or categorize based on the price vs current price for open positions.
    
    trades_summary = []
    symbols = df['symbol'].unique()
    
    for sym in symbols:
        sym_df = df[df['symbol'] == sym].sort_values('transaction_time')
        
        # This is a simplified approach:
        # We'll look at the total P/L for closed portions.
        # For a truly accurate FIFO, we'd need more logic.
        
        total_bought_qty = sym_df[sym_df['side'] == 'buy']['qty'].sum()
        total_sold_qty = sym_df[sym_df['side'] == 'sell']['qty'].sum()
        
        avg_buy_price = 0
        if total_bought_qty > 0:
            avg_buy_price = (sym_df[sym_df['side'] == 'buy']['qty'] * sym_df[sym_df['side'] == 'buy']['price']).sum() / total_bought_qty
            
        avg_sell_price = 0
        if total_sold_qty > 0:
            avg_sell_price = (sym_df[sym_df['side'] == 'sell']['qty'] * sym_df[sym_df['side'] == 'sell']['price']).sum() / total_sold_qty
            
        realized_pl_pct = 0
        if avg_buy_price > 0 and total_sold_qty > 0:
            realized_pl_pct = (avg_sell_price / avg_buy_price - 1) * 100
            
        status = "Unprofitable"
        if realized_pl_pct > 2.0:
            status = "Profitable"
        elif realized_pl_pct >= 0:
            status = "Somewhat Profitable"
            
        trades_summary.append({
            "Symbol": sym,
            "Total Bought": total_bought_qty,
            "Total Sold": total_sold_qty,
            "Avg Buy Price": avg_buy_price,
            "Avg Sell Price": avg_sell_price,
            "Realized P/L %": realized_pl_pct,
            "Category": status
        })
        
    return pd.DataFrame(trades_summary, columns=cols)

def determine_strategy(positions: List[Dict[str, Any]], trades_df: pd.DataFrame) -> str:
    """
    Determines strategy for the next two weeks based on current performance.
    """
    if trades_df.empty:
        return "No sufficient trade data to determine strategy. Recommendation: Start with small defensive positions in SPY/QQQ."

    win_rate = len(trades_df[trades_df['Category'] != "Unprofitable"]) / len(trades_df)
    avg_pl = trades_df['Realized P/L %'].mean()
    
    strategy = ""
    if win_rate > 0.6 and avg_pl > 1.0:
        strategy = "Aggressive Expansion: High win rate and positive P/L detected. Increase position sizes in winning sectors. Look for momentum breakouts in tech (QQQ)."
    elif win_rate > 0.4:
        strategy = "Neutral / Tactical: Mixed results. Maintain current exposure. Focus on high-conviction setups with strict stop-losses. Hedging via Put Options recommended if volatility increases."
    else:
        strategy = "Defensive / Capital Preservation: Low win rate detected. Reduce overall exposure. Focus on cash preservation and wait for clearer market trend. Consider short-dated Treasury Bills (BIL/SHV) or inverse ETFs for hedging."
        
    # Check current positions for concentration
    if positions:
        total_val = sum(float(p['market_value']) for p in positions)
        for p in positions:
            weight = float(p['market_value']) / total_val
            if weight > 0.3:
                strategy += f" Warning: High concentration in {p['symbol']} ({weight:.1%}). Diversification is advised."
                
    return strategy

def generate_quant_report() -> Dict[str, Any]:
    data = fetch_quant_data()
    if "error" in data:
        return data
        
    trades_df = categorize_trades(data['activities'])
    strategy = determine_strategy(data['positions'], trades_df)
    
    return {
        "trades": trades_df,
        "positions": data['positions'],
        "strategy": strategy,
        "summary": {
            "Total Trades": len(trades_df),
            "Profitable": len(trades_df[trades_df['Category'] == "Profitable"]),
            "Somewhat Profitable": len(trades_df[trades_df['Category'] == "Somewhat Profitable"]),
            "Unprofitable": len(trades_df[trades_df['Category'] == "Unprofitable"]),
            "Win Rate": f"{len(trades_df[trades_df['Category'] != 'Unprofitable']) / len(trades_df):.1%}" if not trades_df.empty else "0%"
        }
    }

if __name__ == "__main__":
    report = generate_quant_report()
    if "error" in report:
        print(report["error"])
    else:
        print("--- Quant Analyst Report ---")
        print("\nSummary:")
        for k, v in report["summary"].items():
            print(f"{k}: {v}")
        print("\nStrategy for Next 2 Weeks:")
        print(report["strategy"])
        print("\nTrade Categorization:")
        print(report["trades"][["Symbol", "Realized P/L %", "Category"]])
