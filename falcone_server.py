import os
import sys
import json
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Ensure parent directory is in path to load local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alpaca_trader import get_alpaca_credentials, get_positions, get_account_info, place_order, is_alpaca_configured

# Initialize FastMCP Server v2.0.0
mcp = FastMCP(
    "falcone-capital-engine",
    version="2.0.0",
    description="Entkoppeltes Trading-System: Trennung von Markt-Scanning (60 Symbole) und reiner Signal-Execution."
)

# Define Ticker Universes
NASDAQ_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "PEP",
    "COST", "CSCO", "NFLX", "ADBE", "AMD", "CMCSA", "TMUS", "TXN", "HON", "AMGN",
    "INTC", "INTU", "QCOM", "SBUX", "MDLZ", "ISRG", "AMAT", "BKNG", "GILD", "ADP"
]

RUSSELL_TICKERS = [
    "SMCI", "VRT", "DECK", "NSP", "ANF", "RGLD", "FSLR", "AIT", "MSTR", "LANC",
    "SSD", "GME", "NBIX", "MEDP", "DKS", "ELF", "SAIA", "FRPT", "UFPI", "FIX",
    "IBOC", "GBCI", "SFM", "APG", "KNSL", "CRI", "JBL", "POWI", "WFRD", "CACC"
]

def log_event(message: str):
    log_path = os.path.join(os.path.dirname(__file__), "falcone_engine.log")
    timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

def check_ticker_spike(ticker: str, multiplier: float) -> Optional[dict]:
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="15d")
        if df.empty or len(df) < 5:
            return None
        
        latest_bar = df.iloc[-1]
        latest_vol = latest_bar["Volume"]
        latest_close = latest_bar["Close"]
        latest_high = latest_bar["High"]
        latest_low = latest_bar["Low"]
        
        preceding_vol = df.iloc[:-1]["Volume"].mean()
        if preceding_vol <= 0:
            return None
            
        ratio = latest_vol / preceding_vol
        if ratio >= multiplier:
            return {
                "ticker": ticker,
                "close": float(latest_close),
                "high": float(latest_high),
                "low": float(latest_low),
                "volume": int(latest_vol),
                "avg_volume": int(preceding_vol),
                "ratio": float(ratio)
            }
    except Exception:
        pass
    return None

@mcp.tool(name="scan_markets", description="Scannt parallel das gesamte definierte Universum (Top 30 Nasdaq Large Caps & Top 30 Russell Small/Mid Caps) auf Volumen-Spikes.")
def scan_markets(multiplier: float = 3.0) -> str:
    """
    Scannt parallel das gesamte definierte Universum (Top 30 Nasdaq Large Caps & Top 30 Russell Small/Mid Caps) auf Volumen-Spikes.
    
    :param multiplier: Volumen-Schwellenwert-Faktor (Standard: 3.0)
    """
    tickers = NASDAQ_TICKERS + RUSSELL_TICKERS
    spikes = []
    
    # Run parallel scanning with ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_ticker_spike, ticker, multiplier): ticker for ticker in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                spikes.append(res)
                
    if not spikes:
        msg = f"=== Market Scan Completed ===\nFaktor: {multiplier}x\nEs wurden keine Volumen-Spikes im definierten Universum gefunden."
        log_event(f"[INFO] scan_markets: Completed. No spikes found.")
        return msg
        
    spikes.sort(key=lambda x: x["ratio"], reverse=True)
    
    lines = [f"=== Volume Spikes Detected ({len(spikes)} tickers) ==="]
    for s in spikes:
        category = "NASDAQ" if s["ticker"] in NASDAQ_TICKERS else "RUSSELL"
        risk = s["close"] - s["low"]
        if risk <= 0.01:
            risk = s["close"] * 0.015
        stop_loss = s["low"] - (risk * 0.05)
        target = s["close"] + (2.0 * risk)
        
        lines.append(
            f"• {s['ticker']} ({category}) | Close: ${s['close']:.2f} | "
            f"Vol-Faktor: {s['ratio']:.2f}x | "
            f"Stop-Loss: ${stop_loss:.2f} | Target: ${target:.2f}"
        )
        
    log_event(f"[INFO] scan_markets: Completed. Found {len(spikes)} spikes with multiplier {multiplier}x.")
    return "\n".join(lines)

@mcp.tool(name="execute_signal", description="Nimmt ein validiertes Signal entgegen, berechnet die risikoadjustierte Positionsgröße und feuert die Order an den Broker ab.")
def execute_signal(ticker: str, category: str, signal_price: float, stop_loss: float, target: float) -> str:
    """
    Nimmt ein validiertes Signal entgegen, berechnet die risikoadjustierte Positionsgröße und feuert die Order an den Broker ab.
    
    :param ticker: Handelssymbol (z. B. AAPL)
    :param category: Marktkategorie für Risikofaktoren (NASDAQ oder RUSSELL)
    :param signal_price: Einstiegskurs
    :param stop_loss: Berechneter Stop-Loss-Punkt
    :param target: Profit-Target
    """
    ticker = ticker.upper().strip()
    category = category.upper().strip()
    
    if category not in ["NASDAQ", "RUSSELL"]:
        return "Fehler: Kategorie muss NASDAQ oder RUSSELL sein."
        
    # Get portfolio equity
    equity = 100000.0
    alpaca_active = is_alpaca_configured()
    
    if alpaca_active:
        try:
            acc = get_account_info()
            if acc:
                equity = float(acc.get("equity", 100000.0))
        except Exception:
            pass
            
    # Risk factor: NASDAQ = 1.0%, RUSSELL = 0.5%
    risk_pct = 0.01 if category == "NASDAQ" else 0.005
    risk_amount = equity * risk_pct
    
    # Calculate stop distance
    stop_distance = abs(signal_price - stop_loss)
    if stop_distance <= 0.01:
        stop_distance = signal_price * 0.02
        
    # Raw quantity
    qty = risk_amount / stop_distance
    
    # Cap position size at max 15% of equity
    max_position_value = equity * 0.15
    capped_qty = max_position_value / signal_price
    
    final_qty = min(qty, capped_qty)
    final_qty = int(np.round(final_qty))
    if final_qty < 1:
        final_qty = 1
        
    # Determine side: Target above entry -> Buy (Long), else Sell (Short)
    side = "buy" if target > signal_price else "sell"
    
    order_id = "SIMULATED_ORDER"
    order_status = "filled"
    alpaca_success = False
    
    if alpaca_active:
        try:
            status_code, res = place_order(ticker, final_qty, side, "market")
            if status_code in [200, 201] or res.get("status") == "success":
                alpaca_success = True
                order_id = res.get("order", {}).get("id", "N/A")
                order_status = "placed/filled"
            else:
                order_status = f"failed: {res.get('message', 'API Error')}"
        except Exception as e:
            order_status = f"failed: {e}"
    else:
        alpaca_success = True
        
    # Write to local logs
    log_event(
        f"[INFO] execute_signal: {side.upper()} {final_qty} {ticker} @ ${signal_price:.2f}. "
        f"Stop: ${stop_loss:.2f} | Target: ${target:.2f} | Category: {category} | "
        f"Risk Amount: ${risk_amount:.2f} ({(risk_pct*100):.1f}%) | "
        f"Status: {order_status} | OrderID: {order_id}"
    )
    
    # Also write to execution_logs.json for the Bloomberg Terminal ALGO tab!
    try:
        from execution_algo import ExecutionAlgoManager
        manager = ExecutionAlgoManager()
        log_entry = {
            "execution_id": f"SIG_{int(pd.Timestamp.now().timestamp())}",
            "ticker": ticker,
            "side": side.upper(),
            "total_qty": final_qty,
            "algo_type": f"SIG-{category}",
            "start_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Completed" if alpaca_success else "Failed",
            "filled_qty": final_qty if alpaca_success else 0,
            "average_price": float(signal_price),
            "slices": [
                {
                    "slice_index": 1,
                    "qty": final_qty,
                    "price": float(signal_price),
                    "status": "filled" if alpaca_success else "failed",
                    "order_id": order_id,
                    "timestamp": pd.Timestamp.now().strftime("%H:%M:%S")
                }
            ]
        }
        manager.add_log(log_entry)
    except Exception as e:
        print(f"Error logging to execution_logs.json: {e}")
        
    # Compile output string
    report = [
        f"=== Falcone Capital Signal Execution: {ticker} ===",
        f"• Aktion: {side.upper()}",
        f"• Menge: {final_qty} Shares (Risiko-Kapital: ${risk_amount:,.2f} bei {risk_pct*100:.2f}% Risiko)",
        f"• Limit/Market Einstieg: ${signal_price:.2f}",
        f"• Stop-Loss: ${stop_loss:.2f} (Distanz: ${stop_distance:.2f})",
        f"• Profit-Target: ${target:.2f}",
        f"• Broker-Status: {order_status.upper()}",
        f"• Order-ID: {order_id}",
        f"• Kontotyp: {'LIVE/PAPER ALPACA' if alpaca_active else 'SIMULATED DEMO'}"
    ]
    return "\n".join(report)

if __name__ == "__main__":
    mcp.run()
