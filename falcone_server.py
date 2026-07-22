import os
import sys
import requests
from typing import Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Ensure parent directory is in the path to load local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alpaca_trader import get_alpaca_credentials, get_alpaca_headers, is_alpaca_configured

# Create FastMCP server instance
mcp = FastMCP("falcone-capital-engine")

@mcp.tool(name="analyze_volume_spike", description="Analysiert den aktuellen Tick- oder Kerzen-Stream auf institutionelle Volumen-Spikes und berechnet optimale Stop-Loss/Target-Zonen.")
def analyze_volume_spike(ticker: str, multiplier: float = 3.0) -> str:
    """
    Analysiert den aktuellen Tick- oder Kerzen-Stream auf institutionelle Volumen-Spikes und berechnet optimale Stop-Loss/Target-Zonen.
    
    :param ticker: Das Handelssymbol (z. B. GOOGL, MU)
    :param multiplier: Faktor über dem gleitenden Volumen-Durchschnitt (Standard: 3.0)
    """
    ticker = ticker.upper().strip()
    
    if not is_alpaca_configured():
        return "Alpaca API Keys sind nicht konfiguriert. Bitte in der .env-Datei oder Umgebungsvariablen eintragen."
        
    api_key, secret_key, _ = get_alpaca_credentials()
    
    # We fetch stock bars for the given ticker. 
    # Using the Alpaca Data API for stock bars: https://data.alpaca.markets/v2/stocks/bars
    url = f"https://data.alpaca.markets/v2/stocks/bars"
    headers = {
        "APCA-API-KEY-ID": api_key or "",
        "APCA-API-SECRET-KEY": secret_key or "",
        "Content-Type": "application/json"
    }
    
    # We want intraday bars (e.g. 5Min) to analyze the recent volume stream.
    # We fetch 100 bars.
    params = {
        "symbols": ticker,
        "timeframe": "5Min",
        "limit": 100,
        "adjustment": "raw"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            return f"Fehler beim Abrufen der Marktdaten von Alpaca (Status {response.status_code}): {response.text}"
            
        data = response.json()
        bars_dict = data.get("bars", {})
        bars = bars_dict.get(ticker, [])
        
        if not bars:
            # Let's try 1Day timeframe as fallback if 5Min is empty
            params["timeframe"] = "1Day"
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                bars = data.get("bars", {}).get(ticker, [])
                
        if not bars:
            return f"Keine Kursdaten für das Symbol {ticker} gefunden."
            
        # Analyze spikes. A spike is defined when a bar's volume is > multiplier * avg_volume of the preceding bars.
        if len(bars) < 10:
            return f"Nicht genügend historische Daten für {ticker} vorhanden (mindestens 10 Balken benötigt, gefunden: {len(bars)})."
            
        spikes = []
        lookback = min(20, len(bars) - 5)
        for i in range(len(bars) - lookback, len(bars)):
            preceding_bars = bars[max(0, i-20):i]
            if not preceding_bars:
                continue
            avg_volume = sum(b["v"] for b in preceding_bars) / len(preceding_bars)
            
            current_bar = bars[i]
            volume = current_bar["v"]
            
            if avg_volume > 0:
                ratio = volume / avg_volume
                if ratio >= multiplier:
                    spikes.append({
                        "index": i,
                        "bar": current_bar,
                        "ratio": ratio,
                        "avg_volume": avg_volume
                    })
                    
        if not spikes:
            # Find the maximum ratio in range to give useful feedback
            max_ratio = 0.0
            for i in range(len(bars) - lookback, len(bars)):
                preceding_bars = bars[max(0, i-20):i]
                if not preceding_bars:
                    continue
                avg_volume = sum(b["v"] for b in preceding_bars) / len(preceding_bars)
                if avg_volume > 0:
                    ratio = bars[i]["v"] / avg_volume
                    if ratio > max_ratio:
                        max_ratio = ratio
                        
            return (
                f"=== Falcone Capital Volume Analysis: {ticker} ===\n"
                f"Es wurden keine Volumen-Spikes mit dem Faktor >= {multiplier}x in den letzten {lookback} Kerzen (5Min) gefunden.\n"
                f"Der höchste gemessene Volumen-Faktor in diesem Zeitraum war: {max_ratio:.2f}x."
            )
            
        # Get the most recent spike
        latest_spike = spikes[-1]
        spike_bar = latest_spike["bar"]
        ratio = latest_spike["ratio"]
        avg_vol = latest_spike["avg_volume"]
        
        # Calculate levels
        entry = spike_bar["c"]
        high = spike_bar["h"]
        low = spike_bar["l"]
        volume = spike_bar["v"]
        timestamp = spike_bar["t"]
        
        # Stop loss & Risk
        risk = entry - low
        if risk <= 0.01:
            risk = entry * 0.015
            
        stop_loss = low - (risk * 0.05)
        
        # Targets
        target_1 = entry + (1.5 * risk)
        target_2 = entry + (2.0 * risk)
        target_3 = entry + (3.0 * risk)
        
        # Format the result nicely
        report = []
        report.append(f"=== Falcone Capital Volume Analysis: {ticker} ===")
        report.append(f"VOLUMEN-SPIKE DETEKTIERT! 🚨")
        report.append(f"• Zeitpunkt (UTC): {timestamp}")
        report.append(f"• Volumen: {volume:,} (Faktor: {ratio:.2f}x über gleitendem Durchschnitt von {int(avg_vol):,})")
        report.append(f"• Kerzen-Range: High ${high:.2f} | Low ${low:.2f} | Close ${entry:.2f}")
        report.append("")
        report.append("--- Risiko- & Target-Zonen ---")
        report.append(f"• Einstieg (Close-Trigger): ${entry:.2f}")
        report.append(f"• Stop-Loss (Unter Spike-Low): ${stop_loss:.2f} (-{((entry-stop_loss)/entry)*100:.2f}%)")
        report.append(f"• Target 1 (RRR 1.5): ${target_1:.2f} (+{((target_1-entry)/entry)*100:.2f}%)")
        report.append(f"• Target 2 (RRR 2.0): ${target_2:.2f} (+{((target_2-entry)/entry)*100:.2f}%)")
        report.append(f"• Target 3 (RRR 3.0): ${target_3:.2f} (+{((target_3-entry)/entry)*100:.2f}%)")
        report.append("")
        report.append(f"Hinweis: Institutionelle Käufer stützen in der Regel das Tief des Spike-Balkens (${low:.2f}). Ein Unterschreiten des Stop-Loss storniert das bullische Setup.")
        
        return "\n".join(report)
        
    except Exception as e:
        return f"Fehler während der Volumen-Analyse: {str(e)}"

if __name__ == "__main__":
    mcp.run()
