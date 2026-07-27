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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure parent directory is in path to load local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alpaca_trader import get_alpaca_credentials, get_positions, get_account_info, place_order, is_alpaca_configured
from synthetic_swap_builder import execute_synthetic_swap

# Initialize FastMCP Server v2.0.0
mcp = FastMCP("falcone-capital-engine")

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
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def check_ticker_vpei(ticker: str, multiplier: float) -> Optional[dict]:
    try:
        t = yf.Ticker(ticker)
        # Fetch 5-day, 5-minute historical data for U-curve and VPEI profile
        df = t.history(period="5d", interval="5m")
        if df.empty or len(df) < 20:
            return None
        
        # Group by time of day to establish the U-Curve volume profile
        df['time'] = df.index.time
        mean_volumes = df.groupby('time')['Volume'].mean()
        
        # Calculate historical VPEI for each bar to determine a dynamic threshold
        # VPEI = (|Close - Open| / Volume) * mean_volume_for_that_time
        vpeis = []
        for idx, row in df.iterrows():
            vol = row['Volume']
            time_of_day = row['time']
            mu_vol = mean_volumes.get(time_of_day, 1.0)
            if vol > 0:
                vpeis.append((abs(row['Close'] - row['Open']) / vol) * mu_vol)
            else:
                vpeis.append(0.0)
        df['VPEI'] = vpeis
        
        # Latest bar analysis
        latest_bar = df.iloc[-1]
        latest_time = latest_bar['time']
        latest_vol = latest_bar['Volume']
        latest_close = latest_bar['Close']
        latest_open = latest_bar['Open']
        latest_high = latest_bar['High']
        latest_low = latest_bar['Low']
        
        mu_volume = mean_volumes.get(latest_time, df['Volume'].mean())
        if mu_volume <= 0:
            mu_volume = 1.0
            
        latest_vpei = (abs(latest_close - latest_open) / latest_vol) * mu_volume if latest_vol > 0 else 0.0
        
        # Calculate dynamic threshold from preceding historical VPEI values
        historical_vpeis = df['VPEI'].iloc[:-1]
        vpei_mean = historical_vpeis.mean()
        vpei_std = historical_vpeis.std()
        
        # Dynamic critical threshold: mean + 2.5 * std
        threshold = vpei_mean + 2.5 * vpei_std if not pd.isna(vpei_std) else 0.1
        
        is_bullish = latest_close > latest_open
        is_volume_spike = latest_vol > mu_volume * multiplier
        is_vpei_trigger = latest_vpei > threshold and latest_vol < mu_volume * 1.5
        
        if is_bullish and (is_volume_spike or is_vpei_trigger):
            # Calculate Risk and Target
            # SL = Low - (High - Low) * 0.5
            sl = latest_low - (latest_high - latest_low) * 0.5
            risk = latest_close - sl
            if risk <= 0.01:
                risk = latest_close * 0.015
                sl = latest_close - risk
            
            rr_factor = 2.0
            tp = latest_close + (risk * rr_factor)
            
            return {
                "ticker": ticker,
                "close": float(latest_close),
                "open": float(latest_open),
                "volume": int(latest_vol),
                "mu_volume": float(mu_volume),
                "vpei": float(latest_vpei),
                "threshold": float(threshold),
                "sl": float(sl),
                "tp": float(tp),
                "trigger_type": "Volume Spike" if is_volume_spike else "VPEI Mid-Day Drift"
            }
    except Exception:
        pass
    return None

@mcp.tool(name="scan_markets", description="Scannt parallel das gesamte definierte Universum (Top 30 Nasdaq Large Caps & Top 30 Russell Small/Mid Caps) auf Volumen-Spikes und VPEI-Drifts.")
def scan_markets(multiplier: float = 3.0) -> str:
    """
    Scannt parallel das gesamte definierte Universum (Top 30 Nasdaq Large Caps & Top 30 Russell Small/Mid Caps) auf Volumen-Spikes und VPEI-Drifts.
    
    :param multiplier: Volumen-Schwellenwert-Faktor (Standard: 3.0)
    """
    tickers = NASDAQ_TICKERS + RUSSELL_TICKERS
    signals = []
    
    # Run parallel scanning with ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_ticker_vpei, ticker, multiplier): ticker for ticker in tickers}
        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    signals.append(res)
            except Exception as e:
                log_event(f"[ERROR] Scan failed for {futures[future]}: {e}")
                
    if not signals:
        msg = f"=== Market Scan Completed ===\nVol-Faktor: {multiplier}x\nEs wurden keine Volumen-Spikes oder VPEI-Signale im Universum gefunden."
        log_event(f"[INFO] scan_markets: Completed. No signals found.")
        return msg
        
    signals.sort(key=lambda x: x["vpei"], reverse=True)
    
    lines = [f"=== Falcone VPEI Signals Detected ({len(signals)} tickers) ==="]
    for s in signals:
        category = "NASDAQ" if s["ticker"] in NASDAQ_TICKERS else "RUSSELL"
        lines.append(
            f"• {s['ticker']} ({category}) | Kurs: ${s['close']:.2f} | "
            f"Typ: {s['trigger_type']} | VPEI: {s['vpei']:.4f} (Limit: {s['threshold']:.4f}) | "
            f"Vol: {s['volume']} (Schnitt: {s['mu_volume']:.1f}) | "
            f"Stop-Loss: ${s['sl']:.2f} | Target: ${s['tp']:.2f}"
        )
        
    log_event(f"[INFO] scan_markets: Completed. Found {len(signals)} signals.")
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
        
    # Determine side/direction: Target above entry -> Buy (Long), else Sell (Short)
    direction = "long" if target > signal_price else "short"
    side = "BUY" if direction == "long" else "SELL"
    
    # Standard options contract = 100 shares. Round final_qty to options contract count.
    option_qty = int(np.round(final_qty / 100.0))
    if option_qty < 1:
        option_qty = 1
        
    order_id = "SIMULATED_ORDER"
    order_status = "filled"
    alpaca_success = False
    
    if alpaca_active:
        try:
            success = execute_synthetic_swap(ticker, direction, option_qty)
            if success:
                alpaca_success = True
                order_id = f"SYN-{ticker}-{direction.upper()}-{option_qty}"
                order_status = "placed/filled"
            else:
                order_status = "failed: leg execution incomplete or failed"
        except Exception as e:
            order_status = f"failed: {e}"
    else:
        alpaca_success = True
        order_id = f"SIM-SYN-{ticker}-{direction.upper()}-{option_qty}"
        
    # Write to local logs
    log_event(
        f"[INFO] execute_signal (Synthetic Swap): {direction.upper()} {option_qty} contract(s) ({option_qty * 100} shares eq) {ticker} @ ${signal_price:.2f}. "
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
            "side": side,
            "total_qty": option_qty * 100,
            "algo_type": f"SYN-{category}",
            "start_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Completed" if alpaca_success else "Failed",
            "filled_qty": option_qty * 100 if alpaca_success else 0,
            "average_price": float(signal_price),
            "slices": [
                {
                    "slice_index": 1,
                    "qty": option_qty * 100,
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
        f"=== Falcone Capital Signal Execution (Synthetic Swap Option): {ticker} ===",
        f"• Richtung: {direction.upper()} (Synthetic Swap)",
        f"• Menge: {option_qty} Contract(s) (= {option_qty * 100} Shares Exposure)",
        f"• Basiswert-Einstieg: ${signal_price:.2f}",
        f"• Stop-Loss: ${stop_loss:.2f} (Distanz: ${stop_distance:.2f})",
        f"• Profit-Target: ${target:.2f}",
        f"• Broker-Status: {order_status.upper()}",
        f"• Order-ID: {order_id}",
        f"• Kontotyp: {'LIVE/PAPER ALPACA' if alpaca_active else 'SIMULATED DEMO'}"
    ]
    return "\n".join(report)

if __name__ == "__main__":
    # Custom argument parsing to handle logging parameters before FastMCP/Click sees them
    log_level = "INFO"
    log_file = None
    new_args = []
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--log-level" and i + 1 < len(sys.argv):
            log_level = sys.argv[i+1].upper()
            i += 2
        elif arg == "--log-file" and i + 1 < len(sys.argv):
            log_file = sys.argv[i+1]
            i += 2
        else:
            new_args.append(arg)
            i += 1
    sys.argv = [sys.argv[0]] + new_args

    if log_file:
        import logging
        numeric_level = getattr(logging, log_level, logging.INFO)
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        logging.basicConfig(filename=log_file, level=numeric_level,
                            format='[%(asctime)s] [%(levelname)s] %(message)s')
        logging.info(f"Falcone Capital Engine MCP Server started with log level {log_level}")

    mcp.run()
