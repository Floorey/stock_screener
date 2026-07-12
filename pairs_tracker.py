import os
import json
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from alpaca_trader import place_order, get_positions, is_alpaca_configured
from arbitrage_lab import StatisticalArbitrageLab

PAIRS_FILE = os.path.join(os.path.dirname(__file__), "active_pairs.json")

def load_active_pairs() -> list:
    if not os.path.exists(PAIRS_FILE):
        return []
    try:
        with open(PAIRS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_active_pairs(pairs: list):
    try:
        with open(PAIRS_FILE, "w", encoding="utf-8") as f:
            json.dump(pairs, f, indent=4)
    except Exception as e:
        print(f"Error saving active pairs: {e}")

def register_pair(ticker_a: str, ticker_b: str, qty_a: int, qty_b: int, hedge_ratio: float, entry_z: float, window: int, period: str):
    pairs = load_active_pairs()
    
    # Remove existing pair for the same tickers if present to avoid duplicates
    pairs = [p for p in pairs if not (p["ticker_a"] == ticker_a and p["ticker_b"] == ticker_b)]
    
    pairs.append({
        "pair_id": f"PAIR_{ticker_a}_{ticker_b}_{int(time.time())}",
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "qty_a": qty_a,
        "qty_b": qty_b,
        "entry_z": entry_z,
        "entry_hr": hedge_ratio,
        "window": window,
        "period": period,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_active_pairs(pairs)

def delete_pair(pair_id: str):
    pairs = load_active_pairs()
    pairs = [p for p in pairs if p["pair_id"] != pair_id]
    save_active_pairs(pairs)

def get_pair_realtime_metrics(pair: dict, live_positions: list) -> dict:
    """
    Computes real-time prices, Z-score, and target exit prices for an active pair.
    """
    ticker_a = pair["ticker_a"]
    ticker_b = pair["ticker_b"]
    window = pair["window"]
    period = pair["period"]
    
    # Check if positions are in live_positions
    pos_symbols = {p["symbol"]: float(p["qty"]) for p in live_positions}
    
    has_a = ticker_a in pos_symbols
    has_b = ticker_b in pos_symbols
    
    actual_qty_a = pos_symbols.get(ticker_a, 0.0)
    actual_qty_b = pos_symbols.get(ticker_b, 0.0)
    
    # If positions are closed or quantities don't match signs, we flag it
    is_active = has_a and has_b and (actual_qty_a * pair["qty_a"] > 0) and (actual_qty_b * pair["qty_b"] > 0)
    
    # Get live prices
    price_a = 0.0
    price_b = 0.0
    try:
        ta = yf.Ticker(ticker_a)
        tb = yf.Ticker(ticker_b)
        hist_a = ta.history(period="1d")
        hist_b = tb.history(period="1d")
        if not hist_a.empty:
            price_a = float(hist_a["Close"].iloc[-1])
        if not hist_b.empty:
            price_b = float(hist_b["Close"].iloc[-1])
    except Exception:
        pass
        
    # Calculate current Z-Score and spread mean
    current_z = 0.0
    target_price_a = 0.0
    target_price_b = 0.0
    hr = pair["entry_hr"]
    
    try:
        df = StatisticalArbitrageLab.fetch_pairs_data(ticker_a, ticker_b, period)
        if not df.empty:
            df = StatisticalArbitrageLab.calculate_pairs_metrics(df, window)
            # Add today's live price to the series for the most up-to-date calculation
            if price_a > 0 and price_b > 0:
                new_row = pd.DataFrame({"Price_A": [price_a], "Price_B": [price_b]}, index=[pd.Timestamp.now().floor('D')])
                df = pd.concat([df, new_row]).drop_duplicates()
                df = StatisticalArbitrageLab.calculate_pairs_metrics(df, window)
                
            current_z = float(df["Z_Score"].iloc[-1])
            spread_mean = float(df["Spread_Mean"].iloc[-1])
            hr = float(df["Hedge_Ratio"].iloc[-1]) # latest hedge ratio
            
            # Target exit: Spread = Spread_Mean (i.e. Z-Score = 0)
            # Price_A - hr * Price_B = spread_mean
            if price_b > 0:
                target_price_a = spread_mean + hr * price_b
            if hr != 0:
                target_price_b = (price_a - spread_mean) / hr
    except Exception as e:
        print(f"Error calculating real-time metrics for pair {ticker_a}/{ticker_b}: {e}")
        
    return {
        "pair_id": pair["pair_id"],
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "qty_a": actual_qty_a if has_a else pair["qty_a"],
        "qty_b": actual_qty_b if has_b else pair["qty_b"],
        "price_a": price_a,
        "price_b": price_b,
        "current_hr": hr,
        "current_z": current_z,
        "target_price_a": target_price_a,
        "target_price_b": target_price_b,
        "is_active": is_active,
        "timestamp": pair["timestamp"]
    }

def rebalance_pair_trade(pair_id: str) -> dict:
    """
    Re-estimates the hedge ratio and rebalances Asset B to match the new ratio.
    """
    pairs = load_active_pairs()
    target_pair = None
    for p in pairs:
        if p["pair_id"] == pair_id:
            target_pair = p
            break
            
    if not target_pair:
        return {"status": "error", "message": "Paar in aktiven Positionen nicht gefunden."}
        
    ticker_a = target_pair["ticker_a"]
    ticker_b = target_pair["ticker_b"]
    qty_a = target_pair["qty_a"]
    window = target_pair["window"]
    period = target_pair["period"]
    
    try:
        # 1. Fetch latest data to find new hedge ratio
        df = StatisticalArbitrageLab.fetch_pairs_data(ticker_a, ticker_b, period)
        if df.empty:
            return {"status": "error", "message": "Historische Daten konnten nicht geladen werden."}
            
        df = StatisticalArbitrageLab.calculate_pairs_metrics(df, window)
        new_hr = float(df["Hedge_Ratio"].iloc[-1])
        
        # 2. Get current live position details
        live_positions = get_positions()
        live_qtys = {p["symbol"]: float(p["qty"]) for p in live_positions}
        
        if ticker_a not in live_qtys:
            return {"status": "error", "message": f"Keine aktive Position für {ticker_a} gefunden."}
            
        current_qty_a = live_qtys[ticker_a]
        current_qty_b = live_qtys.get(ticker_b, 0.0)
        
        # 3. Calculate target Qty for Asset B based on current A quantity
        # E.g. If we are Long A (+10) and Short B (ratio is 1.2), target B is -12
        # Target Qty B = -sign(Qty A) * round(abs(Qty A) * new_hr)
        target_qty_b = -np.sign(current_qty_a) * np.round(abs(current_qty_a) * new_hr)
        target_qty_b = int(target_qty_b)
        
        diff_qty = target_qty_b - current_qty_b
        
        if diff_qty == 0:
            # Ratio is already correct, just update metadata
            target_pair["qty_a"] = int(current_qty_a)
            target_pair["qty_b"] = int(current_qty_b)
            target_pair["entry_hr"] = new_hr
            save_active_pairs(pairs)
            return {"status": "success", "message": f"Hedge-Verhältnis ({new_hr:.3f}) ist bereits korrekt ausgeglichen."}
            
        # 4. Place order for diff
        side = "buy" if diff_qty > 0 else "sell"
        order_res = place_order(ticker_b, abs(diff_qty), side, "market")
        
        if order_res.get("status") == "success":
            # Update pair settings
            target_pair["qty_a"] = int(current_qty_a)
            target_pair["qty_b"] = int(target_qty_b)
            target_pair["entry_hr"] = new_hr
            save_active_pairs(pairs)
            return {"status": "success", "message": f"Hedge rebalanciert! {abs(diff_qty)} Shares von {ticker_b} ({side}) geordert. Neues Verhältnis: {new_hr:.3f}."}
        else:
            return {"status": "error", "message": f"Fehler bei Rebalancing-Order für {ticker_b}: {order_res.get('message')}"}
    except Exception as e:
        return {"status": "error", "message": f"Rebalancing fehlgeschlagen: {str(e)}"}

def close_pair_trade(pair_id: str) -> dict:
    """
    Closes both leg positions at Alpaca and deletes the tracker file entry.
    """
    pairs = load_active_pairs()
    target_pair = None
    for p in pairs:
        if p["pair_id"] == pair_id:
            target_pair = p
            break
            
    if not target_pair:
        return {"status": "error", "message": "Paar in aktiven Positionen nicht gefunden."}
        
    ticker_a = target_pair["ticker_a"]
    ticker_b = target_pair["ticker_b"]
    
    try:
        # Get current live position details
        live_positions = get_positions()
        live_qtys = {p["symbol"]: float(p["qty"]) for p in live_positions}
        
        qty_a = live_qtys.get(ticker_a, 0.0)
        qty_b = live_qtys.get(ticker_b, 0.0)
        
        # Close Leg A
        res_a_msg = "Keine Position"
        if qty_a != 0:
            side_a = "sell" if qty_a > 0 else "buy"
            order_a = place_order(ticker_a, abs(qty_a), side_a, "market")
            res_a_msg = order_a.get("status")
            
        # Close Leg B
        res_b_msg = "Keine Position"
        if qty_b != 0:
            side_b = "sell" if qty_b > 0 else "buy"
            order_b = place_order(ticker_b, abs(qty_b), side_b, "market")
            res_b_msg = order_b.get("status")
            
        # Delete tracker entry
        delete_pair(pair_id)
        
        return {
            "status": "success", 
            "message": f"Paar geschlossen! Ticker {ticker_a} (Glattstellung): {res_a_msg} | Ticker {ticker_b} (Glattstellung): {res_b_msg}"
        }
    except Exception as e:
        return {"status": "error", "message": f"Fehler beim Schließen des Paares: {str(e)}"}

def render_pairs_tracker_widget(live_positions: list):
    import streamlit as st
    
    st.markdown("---")
    st.markdown('<div class="wl-banner"><h3>📊 StatArb Pairs Trading Tracker</h3></div>', unsafe_allow_html=True)
    
    active_pairs = load_active_pairs()
    if not active_pairs:
        st.info("Keine aktiven Statistical Arbitrage-Paare im Tracker registriert.")
        return
        
    st.write("Verfolgen Sie Ihre aktiven StatArb Trades, rebalancieren Sie das Hedge-Verhältnis oder schließen Sie beide Legs zeitgleich.")
    
    # Calculate live metrics for each pair
    pairs_data = []
    for pair in active_pairs:
        with st.spinner(f"Lade Live-Metriken für {pair['ticker_a']}/{pair['ticker_b']}..."):
            metrics = get_pair_realtime_metrics(pair, live_positions)
            pairs_data.append(metrics)
            
    # Display table/interface for each pair
    for p in pairs_data:
        ticker_a = p["ticker_a"]
        ticker_b = p["ticker_b"]
        qty_a = p["qty_a"]
        qty_b = p["qty_b"]
        
        # Color coding state
        badge = "🟢 AKTIV" if p["is_active"] else "🔴 INAKTIV (Abweichung im Depot)"
        
        st.markdown(f"#### ⚖️ Paar: **{ticker_a}** vs **{ticker_b}** ({badge})")
        
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        with col_m1:
            st.metric(f"Menge {ticker_a}", f"{qty_a:.0f} Shares")
            st.metric(f"Akt. Kurs {ticker_a}", f"${p['price_a']:.2f}")
        with col_m2:
            st.metric(f"Menge {ticker_b}", f"{qty_b:.0f} Shares")
            st.metric(f"Akt. Kurs {ticker_b}", f"${p['price_b']:.2f}")
        with col_m3:
            st.metric("Aktueller Z-Score", f"{p['current_z']:.2f}")
            st.metric("Hedge-Faktor (HR)", f"{p['current_hr']:.3f}")
        with col_m4:
            st.metric(f"Ziel-Exit {ticker_a}", f"${p['target_price_a']:.2f}", help="Erwarteter Preis bei Z-Score = 0 (sofern B konstant bleibt)")
        with col_m5:
            st.metric(f"Ziel-Exit {ticker_b}", f"${p['target_price_b']:.2f}", help="Erwarteter Preis bei Z-Score = 0 (sofern A konstant bleibt)")
            
        # Rebalance & Close buttons
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
        with btn_col1:
            # Rebalance Button
            if st.button("🔄 Hedge rebalancieren", key=f"reb_btn_{p['pair_id']}", help="Errechnet das optimale Hedge-Verhältnis neu und gleicht die Menge des zweiten Stocks (Asset B) an."):
                with st.spinner("Rebalanciere Paar..."):
                    res = rebalance_pair_trade(p["pair_id"])
                    if res.get("status") == "success":
                        st.success(res.get("message"))
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(res.get("message"))
        with btn_col2:
            # Close Button
            if st.button("🚪 Paar glattstellen", key=f"close_pair_btn_{p['pair_id']}", type="secondary", help="Schließt die Positionen beider Aktien zeitgleich am Markt und entfernt das Paar aus dem Tracker."):
                with st.spinner("Glattstellung läuft..."):
                    res = close_pair_trade(p["pair_id"])
                    if res.get("status") == "success":
                        st.success(res.get("message"))
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(res.get("message"))
        st.markdown("---")
