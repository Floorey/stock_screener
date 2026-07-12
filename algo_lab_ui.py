import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import time
from datetime import datetime
from execution_algo import ExecutionAlgoManager
from arbitrage_lab import StatisticalArbitrageLab, calculate_black_scholes_delta, calculate_greeks
from alpaca_trader import is_alpaca_configured, get_account_info, place_order, get_positions
from watchlist_manager import load_watchlist

def render_algo_lab_tab():
    st.markdown('<div class="wl-banner"><h2>🔬 Quantitative Algo-Trading & Execution Lab</h2></div>', unsafe_allow_html=True)
    st.markdown("Testen Sie quantitative Handelsstrategien (Arbitrage, Paare) und führen Sie Orders kontrolliert mit Ausführungsalgorithmen aus.")
    
    # Sub-tabs inside Algo Lab
    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
        "🤖 Algorithmic Execution (OMS)",
        "📈 Statistical Arbitrage (Pairs)",
        "🎫 Convertible Arbitrage & Delta Hedging",
        "⚖️ Long/Short Equity Basket"
    ])
    
    # -------------------------------------------------------------------------
    # SUB-TAB 1: ALGORITHMIC EXECUTION (OMS)
    # -------------------------------------------------------------------------
    with sub_tab1:
        st.subheader("Order Execution Algorithms (TWAP / VWAP)")
        st.write("Verteilen Sie große Orders über die Zeit, um Marktimpakt und Slippage zu minimieren.")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            exec_ticker = st.text_input("Ticker Symbol", value="AAPL").upper().strip()
            exec_side = st.selectbox("Aktion", ["BUY", "SELL"])
        with col2:
            exec_qty = st.number_input("Gesamtmenge (Shares)", min_value=1, value=100, step=1)
            exec_algo = st.selectbox("Algorithmus", ["TWAP", "VWAP"])
        with col3:
            exec_slices = st.slider("Anzahl Slices / Intervalle", min_value=2, max_value=20, value=5)
            exec_sec = st.slider("Intervall (Sekunden)", min_value=2, max_value=60, value=5)
            
        manager = ExecutionAlgoManager()
        
        # Calculate & Show preview of the schedule
        if exec_algo == "TWAP":
            schedule = manager.calculate_twap_schedule(exec_qty, exec_slices)
        else:
            schedule = manager.calculate_vwap_schedule(exec_qty, exec_slices)
            
        st.markdown("### 📋 Geplante Ausführungstransaktionen")
        preview_data = []
        for i, q in enumerate(schedule):
            preview_data.append({
                "Slice ID": f"Slice {i+1}",
                "Anteilige Menge (Shares)": q,
                "Gewichtung": f"{(q / exec_qty * 100):.1f}%",
                "Verzögerung nach Start": f"{i * exec_sec} Sek."
            })
        st.table(pd.DataFrame(preview_data))
        
        col_exec_btn, col_empty = st.columns([1, 2])
        with col_exec_btn:
            start_exec = st.button("🚀 Ausführung starten", use_container_width=True)
            
        if start_exec:
            st.info(f"Starte {exec_algo} Orderausführung für {exec_qty} Anteile von {exec_ticker}...")
            
            # Execution container with progress
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            log_container = st.container()
            
            total_filled = 0
            total_cost = 0.0
            
            execution_id = f"EXE_{int(time.time())}"
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = {
                "execution_id": execution_id,
                "ticker": exec_ticker,
                "side": exec_side,
                "total_qty": exec_qty,
                "algo_type": exec_algo,
                "start_time": start_time,
                "status": "Running",
                "filled_qty": 0,
                "average_price": 0.0,
                "slices": []
            }
            manager.add_log(log_entry)
            
            for idx, slice_qty in enumerate(schedule):
                # Retrieve price proxy
                price = 100.0
                try:
                    import yfinance as yf
                    tk = yf.Ticker(exec_ticker)
                    hist = tk.history(period="1d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
                except Exception:
                    pass
                
                # Mock or Alpaca order execution
                order_id = "MOCK_ORDER"
                status = "filled"
                
                # Place real Alpaca order if configured
                if is_alpaca_configured():
                    status_code, order_res = place_order(
                        symbol=exec_ticker,
                        qty=slice_qty,
                        side=exec_side.lower(),
                        order_type="market"
                    )
                    if status_code in [200, 201] or order_res.get("status") == "success":
                        order_id = order_res.get("order", {}).get("id", "N/A")
                        status = "filled"
                    else:
                        status = f"failed: {order_res.get('message', 'Unbekannter Fehler')}"
                else:
                    # Simulated execution with a small slippage
                    slippage = np.random.normal(0, 0.0005) * price
                    price = price + abs(slippage) if exec_side == "BUY" else price - abs(slippage)
                    
                if "failed" not in status:
                    total_filled += slice_qty
                    total_cost += price * slice_qty
                    avg_p = total_cost / total_filled
                else:
                    price = 0.0
                    avg_p = total_cost / total_filled if total_filled > 0 else 0.0
                    
                slice_log = {
                    "slice_index": idx + 1,
                    "qty": slice_qty,
                    "price": price,
                    "status": status,
                    "order_id": order_id,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
                
                # Update status
                progress_val = float(idx + 1) / len(schedule)
                progress_bar.progress(progress_val)
                status_text.write(f"Ausgeführt {total_filled}/{exec_qty} Shares ({progress_val*100:.1f}%) | Durchschnittspreis: ${avg_p:.2f}")
                
                with log_container:
                    if "failed" in status:
                        st.error(f"🔴 Slice {idx+1} ({slice_qty} shares) FEHLGESCHLAGEN: {status}")
                    else:
                        st.success(f"🟢 Slice {idx+1} ({slice_qty} shares) ausgeführt für **${price:.2f}** | Zeit: {slice_log['timestamp']}")
                        
                # Update log file
                logs = manager.get_logs()
                for log in logs:
                    if log["execution_id"] == execution_id:
                        log["filled_qty"] = total_filled
                        log["average_price"] = avg_p
                        log["slices"].append(slice_log)
                        if total_filled >= exec_qty:
                            log["status"] = "Completed"
                            log["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        elif idx == len(schedule) - 1:
                            log["status"] = "Partial"
                            log["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        break
                
                with open(manager.log_file, "w", encoding="utf-8") as f:
                    import json
                    json.dump(logs, f, indent=4)
                    
                if idx < len(schedule) - 1:
                    time.sleep(exec_sec)
                    
            st.success(f"Execution {exec_algo} abgeschlossen! {total_filled} Shares von {exec_ticker} platziert.")
            
        # Historic Execution Log Table
        st.markdown("---")
        st.markdown("### 📜 Ausführungsprotokoll (OMS Historie)")
        past_logs = manager.get_logs()
        if not past_logs:
            st.info("Keine aufgezeichneten Ausführungsaufträge vorhanden.")
        else:
            flat_logs = []
            for log in reversed(past_logs):
                flat_logs.append({
                    "ID": log["execution_id"],
                    "Ticker": log["ticker"],
                    "Aktion": log["side"],
                    "Menge": log["total_qty"],
                    "Ausgeführt": log["filled_qty"],
                    "Typ": log["algo_type"],
                    "Ø Preis": f"${log['average_price']:.2f}",
                    "Status": log["status"],
                    "Startzeit": log["start_time"]
                })
            st.dataframe(pd.DataFrame(flat_logs), hide_index=True, use_container_width=True)

    # -------------------------------------------------------------------------
    # SUB-TAB 2: STATISTICAL ARBITRAGE (PAIRS TRADING)
    # -------------------------------------------------------------------------
    with sub_tab2:
        st.subheader("Statistical Arbitrage Lab (Pairs Trading)")
        st.write("Identifizieren Sie überkaufte/überverkaufte Spreads korrelierter Asset-Paare und handeln Sie deren Mittelwertrückkehr (Mean Reversion).")
        
        pair_col1, pair_col2, pair_col3 = st.columns(3)
        with pair_col1:
            ticker_a = st.text_input("Asset A (z.B. KO / Gold)", value="KO").upper().strip()
            rolling_window = st.slider("Mittelwert-Fenster (Tage)", min_value=5, max_value=60, value=20)
        with pair_col2:
            ticker_b = st.text_input("Asset B (z.B. PEP / Silber)", value="PEP").upper().strip()
            entry_threshold = st.slider("Entry Z-Score Schwelle", min_value=1.0, max_value=3.5, value=2.0, step=0.1)
        with pair_col3:
            pairs_period = st.selectbox("Historischer Zeitraum", ["30d", "60d", "90d", "180d", "1y"], index=2)
            
        run_pairs = st.button("🔍 Spread-Analyse durchführen", key="run_pairs_btn")
        
        if run_pairs:
            with st.spinner(f"Lade historische Daten für {ticker_a} und {ticker_b}..."):
                try:
                    df_pair = StatisticalArbitrageLab.fetch_pairs_data(ticker_a, ticker_b, pairs_period)
                    if df_pair.empty:
                        st.error("Keine ausreichenden Daten gefunden.")
                    else:
                        df_pair = StatisticalArbitrageLab.calculate_pairs_metrics(df_pair, rolling_window)
                        
                        # Correlation
                        corr = df_pair["Price_A"].corr(df_pair["Price_B"])
                        current_a = df_pair["Price_A"].iloc[-1]
                        current_b = df_pair["Price_B"].iloc[-1]
                        current_z = df_pair["Z_Score"].iloc[-1]
                        current_hr = df_pair["Hedge_Ratio"].iloc[-1]
                        
                        st.markdown("### 📊 Paar-Statistiken")
                        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                        with stat_col1:
                            st.metric(f"Preis {ticker_a}", f"${current_a:.2f}")
                        with stat_col2:
                            st.metric(f"Preis {ticker_b}", f"${current_b:.2f}")
                        with stat_col3:
                            st.metric("Historische Korrelation", f"{corr:.2f}", delta="Gleichlauf" if corr > 0.7 else "Schwach")
                        with stat_col4:
                            # Color coding z-score
                            if current_z > entry_threshold:
                                rec_text = "SHORT SPREAD (Sell A / Buy B)"
                                rec_color = "red"
                            elif current_z < -entry_threshold:
                                rec_text = "BUY SPREAD (Buy A / Sell B)"
                                rec_color = "green"
                            else:
                                rec_text = "KEIN SIGNAL (Mean-Neutral)"
                                rec_color = "gray"
                            
                            st.metric("Aktueller Z-Score", f"{current_z:.2f}", delta=rec_text, delta_color="normal" if "BUY" in rec_text else ("inverse" if "SHORT" in rec_text else "off"))
                        
                        # Plot Spread & Z-Score
                        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
                        fig.patch.set_facecolor('#0f172a')
                        
                        for ax in [ax1, ax2]:
                            ax.set_facecolor('#1e293b')
                            ax.tick_params(colors='#94a3b8')
                            ax.xaxis.label.set_color('#94a3b8')
                            ax.yaxis.label.set_color('#94a3b8')
                            ax.title.set_color('#f8fafc')
                            ax.grid(True, color='#334155', linestyle=':')
                            
                        # Chart 1: Spread
                        ax1.plot(df_pair.index, df_pair["Spread"], label="Spread (A - Ratio*B)", color="#38bdf8", linewidth=2)
                        ax1.plot(df_pair.index, df_pair["Spread_Mean"], label="Mittelwert", color="#f43f5e", linestyle="--")
                        ax1.set_title(f"Historischer Spread zwischen {ticker_a} und {ticker_b}")
                        ax1.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                        
                        # Chart 2: Z-Score
                        ax2.plot(df_pair.index, df_pair["Z_Score"], label="Z-Score", color="#a855f7", linewidth=2)
                        ax2.axhline(entry_threshold, color="#ef4444", linestyle=":", label="Short Threshold")
                        ax2.axhline(-entry_threshold, color="#22c55e", linestyle=":", label="Buy Threshold")
                        ax2.axhline(0, color="#94a3b8", linestyle="-.")
                        ax2.set_title("Z-Score Abweichungsindikator")
                        ax2.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                        
                        st.pyplot(fig)
                        
                        # Execution section
                        st.markdown("### ⚡ Live Arbitrage Order-Cockpit")
                        st.write(f"Empfohlener Hedge-Faktor: **1 Share von {ticker_a}** erfordert **{current_hr:.3f} Shares von {ticker_b}** für ein neutrales Spread-Exposure.")
                        
                        mult = st.number_input("Multiplikator (Menge für Asset A)", min_value=1, value=10, step=1)
                        qty_a = mult
                        qty_b = int(np.round(mult * current_hr))
                        
                        exec_col1, exec_col2 = st.columns(2)
                        with exec_col1:
                            st.write(f"🛒 **Kauf-Leg:** {qty_a} Shares von {ticker_a} (Wert: ${qty_a * current_a:,.2f})")
                        with exec_col2:
                            st.write(f"📉 **Short-Leg:** {qty_b} Shares von {ticker_b} (Wert: ${qty_b * current_b:,.2f})")
                            
                        if not is_alpaca_configured():
                            st.warning("Alpaca ist nicht konfiguriert. Arbitrage-Ausführung deaktiviert.")
                        else:
                            st.success("🟢 Alpaca-Konto verbunden. Trades können platziert werden.")
                            
                            if current_z > entry_threshold:
                                if st.button(f"🚀 Short-Spread Trade platzieren (Short A / Long B)", type="primary"):
                                    with st.spinner("Sende Arbitrage-Legs..."):
                                        # Sell A, Buy B
                                        res_a = place_order(ticker_a, qty_a, "sell", "market")
                                        res_b = place_order(ticker_b, qty_b, "buy", "market")
                                        st.success(f"Orders platziert! Ticker {ticker_a} (Short): {res_a.get('status')} | Ticker {ticker_b} (Long): {res_b.get('status')}")
                            elif current_z < -entry_threshold:
                                if st.button(f"🚀 Buy-Spread Trade platzieren (Long A / Short B)", type="primary"):
                                    with st.spinner("Sende Arbitrage-Legs..."):
                                        # Buy A, Sell B
                                        res_a = place_order(ticker_a, qty_a, "buy", "market")
                                        res_b = place_order(ticker_b, qty_b, "sell", "market")
                                        st.success(f"Orders platziert! Ticker {ticker_a} (Long): {res_a.get('status')} | Ticker {ticker_b} (Short): {res_b.get('status')}")
                            else:
                                st.info("Der Z-Score liegt aktuell im neutralen Bereich. Kein unmittelbares Handels-Setup.")
                except Exception as e:
                    st.error(f"Fehler bei der Paaranalyse: {e}")

    # -------------------------------------------------------------------------
    # SUB-TAB 3: CONVERTIBLE ARBITRAGE & DELTA HEDGING
    # -------------------------------------------------------------------------
    with sub_tab3:
        st.subheader("Convertible Arbitrage Lab (Option Delta-Hedging)")
        st.write("Neutralisieren Sie das Richtungsrisiko (Delta) einer Long-Option / Wandelanleihe durch dynamischen Leerverkauf der zugrunde liegenden Aktie.")
        
        ca_col1, ca_col2, ca_col3 = st.columns(3)
        with ca_col1:
            ca_ticker = st.text_input("Underlying Aktie (z.B. MSTR, TSLA)", value="MSTR", key="ca_ticker_input").upper().strip()
            ca_contracts = st.number_input("Anzahl Call Kontrakte (Long)", min_value=1, value=10, step=1)
        with ca_col2:
            ca_strike = st.number_input("Option Strike Price ($)", min_value=1.0, value=100.0, step=1.0)
            ca_iv = st.slider("Implied Volatility (IV %)", min_value=5.0, max_value=250.0, value=80.0, step=1.0) / 100.0
        with ca_col3:
            ca_days = st.number_input("Restlaufzeit (Tage)", min_value=1, value=30, step=1)
            ca_r = st.slider("Risikofreier Zins (r %)", min_value=0.0, max_value=10.0, value=4.0, step=0.1) / 100.0

        run_ca = st.button("📊 Delta-Hedge berechnen", key="run_ca_btn")
        
        if run_ca or ca_ticker:
            with st.spinner(f"Hole aktuellen Kurs für {ca_ticker}..."):
                try:
                    tk = yf.Ticker(ca_ticker)
                    hist = tk.history(period="1d")
                    if hist.empty:
                        ca_s = 100.77
                    else:
                        ca_s = float(hist["Close"].iloc[-1])
                        
                    T_years = ca_days / 365.0
                    greeks = calculate_greeks(ca_s, ca_strike, T_years, ca_r, ca_iv)
                    
                    st.markdown("### 🦇 Griechische Kennzahlen & Absicherungs-Bedarf")
                    
                    # Target shares to short
                    shares_to_short = int(np.round(greeks["delta"] * 100 * ca_contracts))
                    
                    cag_col1, cag_col2, cag_col3, cag_col4 = st.columns(4)
                    with cag_col1:
                        st.metric("Aktienkurs (Live)", f"${ca_s:.2f}")
                    with cag_col2:
                        st.metric("Option Delta (Δ)", f"{greeks['delta']:.4f}", help="Sensitivität gegenüber dem Aktienpreis.")
                    with cag_col3:
                        st.metric("Hedge-Short-Volumen", f"{shares_to_short} Shares", help="Anzahl der leerzuverkaufenden Aktien für Delta-Neutralität.")
                    with cag_col4:
                        st.metric("Option Gamma (Γ)", f"{greeks['gamma']:.4f}", help="Veränderung des Delta bei 1$ Kursbewegung.")
                        
                    st.write(f"Um Ihre Long-Call-Position ({ca_contracts} Kontrakte = 1.000 Basisaktien nominal) delta-neutral abzusichern, müssen Sie exakt **{shares_to_short} Aktien** von **{ca_ticker} leerverkaufen**.")
                    
                    # Risk Profile Chart
                    prices = np.linspace(ca_s * 0.8, ca_s * 1.2, 50)
                    deltas = [calculate_black_scholes_delta(p, ca_strike, T_years, ca_r, ca_iv) for p in prices]
                    
                    fig, ax = plt.subplots(figsize=(10, 4))
                    fig.patch.set_facecolor('#0f172a')
                    ax.set_facecolor('#1e293b')
                    ax.tick_params(colors='#94a3b8')
                    ax.xaxis.label.set_color('#94a3b8')
                    ax.yaxis.label.set_color('#94a3b8')
                    ax.title.set_color('#f8fafc')
                    ax.grid(True, color='#334155', linestyle=':')
                    
                    ax.plot(prices, deltas, color="#00ffcc", linewidth=2.5, label="Dynamisches Delta")
                    ax.axvline(ca_s, color="#f43f5e", linestyle="--", label="Aktueller Kurs")
                    ax.axhline(greeks["delta"], color="#a855f7", linestyle=":")
                    ax.set_ylabel("Delta (Δ)")
                    ax.set_xlabel(f"Aktienpreis ({ca_ticker})")
                    ax.set_title("Hedge-Sensitivität (Gamma-Kurve: Delta-Shift)")
                    ax.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                    st.pyplot(fig)
                    
                    # Live Execution Panel
                    st.markdown("### 🚀 Delta-Hedge Ausführen")
                    if not is_alpaca_configured():
                        st.warning("Alpaca ist nicht konfiguriert. Hedge-Ausführung deaktiviert.")
                    else:
                        st.info("🟢 Alpaca-Verbindung bereit.")
                        
                        # Fetch existing position to check if we already shorted some shares
                        existing_qty = 0
                        positions = get_positions()
                        if positions:
                            for pos in positions:
                                if pos.get("symbol") == ca_ticker:
                                    existing_qty = int(pos.get("qty"))
                                    break
                                    
                        st.write(f"Aktueller Bestand an {ca_ticker}-Aktien im Alpaca Depot: **{existing_qty}** Shares.")
                        diff_shares = -shares_to_short - existing_qty
                        
                        if diff_shares != 0:
                            action_str = f"{abs(diff_shares)} Aktien LEERVERKAUFEN" if diff_shares < 0 else f"{abs(diff_shares)} Aktien KAUFEN (Hedge-Reduktion)"
                            st.write(f"Differenz zum Ziel-Hedge: **{action_str}**")
                            
                            confirm_hedge = st.checkbox("Hedge-Order über Alpaca ausführen", value=False)
                            if st.button("🚀 Hedge-Order an Alpaca senden", key="ca_hedge_exec_btn"):
                                if not confirm_hedge:
                                    st.error("Bitte bestätigen Sie die Orderausführung.")
                                else:
                                    side = "sell" if diff_shares < 0 else "buy"
                                    code, res = place_order(ca_ticker, abs(diff_shares), side, "market")
                                    if code in [200, 201] or res.get("status") == "success":
                                        st.success(f"Erfolgreich! Hedge-Order übergeben. ID: {res.get('order', {}).get('id')}")
                                    else:
                                        st.error(f"Fehler bei Ausführung: {res.get('message')}")
                        else:
                            st.success("Ihr Portfolio ist bezüglich dieses Assets bereits perfekt delta-neutral abgesichert!")
                except Exception as e:
                    st.error(f"Fehler bei Berechnungen: {e}")

    # -------------------------------------------------------------------------
    # SUB-TAB 4: LONG/SHORT EQUITY BASKET
    # -------------------------------------------------------------------------
    with sub_tab4:
        st.subheader("Long/Short Equity Basket Strategy")
        st.write("Bauen Sie ein marktneutrales Portfolio aus unterbewerteten Long-Kandidaten und überbewerteten Short-Kandidaten auf.")
        
        # Load screener cache to see if we have results
        import json
        cache_path = os.path.join(os.path.dirname(__file__), "screener_cache.json")
        
        if not os.path.exists(cache_path):
            st.warning("Keine Screener-Daten gefunden. Bitte führen Sie zuerst im ersten Tab 'Screener Dashboard' einen Scan durch.")
        else:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    
                df_cache = pd.DataFrame(cache_data.get("results", []))
                if df_cache.empty:
                    st.warning("Keine gültigen Aktien-Scoringdaten gefunden.")
                else:
                    # Sort candidates
                    longs = df_cache.sort_values(by="long_score", ascending=False).head(5)
                    shorts = df_cache.sort_values(by="short_score", ascending=False).head(5)
                    
                    st.markdown("### 🏆 Top Long- & Short-Kandidaten (System-Scoring)")
                    
                    ls_col1, ls_col2 = st.columns(2)
                    with ls_col1:
                        st.markdown("<div class='long-banner'><b>🟢 Long-Portfolio (Top Fundamental-Scores)</b></div>", unsafe_allow_html=True)
                        st.dataframe(longs[["ticker", "name", "long_score", "pe", "debt_equity", "tradable"]], hide_index=True)
                    with ls_col2:
                        st.markdown("<div class='short-banner'><b>🔴 Short-Portfolio (Top Verschuldung & Cash-Burn)</b></div>", unsafe_allow_html=True)
                        st.dataframe(shorts[["ticker", "name", "short_score", "pe", "debt_equity", "shortable"]], hide_index=True)
                        
                    # Target Capital Allocation
                    basket_cap = st.number_input("Zielkapital pro Leg ($)", min_value=1000, value=10000, step=1000)
                    
                    st.markdown("### ⚖️ Portfolio-Allokation (Marktneutral-Gewichtung)")
                    st.write("Jedes Asset wird mit gleichem Gewicht im Long- bzw. Short-Korb alloziert. Das Netto-Beta des Korbs wird nahe 0 balanciert.")
                    
                    # Calculate weights
                    long_weight = 1.0 / len(longs)
                    short_weight = -1.0 / len(shorts)
                    
                    ls_preview = []
                    for idx, row in longs.iterrows():
                        px = row.get("price", 100.0) or 100.0
                        shares = int(np.round((basket_cap * long_weight) / px))
                        ls_preview.append({
                            "Typ": "Long",
                            "Ticker": row["ticker"],
                            "Name": row["name"],
                            "Preis": f"${px:.2f}",
                            "Gewicht": f"{(long_weight * 50):.1f}%", # scaled to total portfolio
                            "Menge": shares,
                            "Kosten (USD)": f"${(shares * px):,.2f}",
                            "Beta": row.get("beta", 1.0) or 1.0
                        })
                    for idx, row in shorts.iterrows():
                        px = row.get("price", 100.0) or 100.0
                        shares = int(np.round((basket_cap * abs(short_weight)) / px))
                        ls_preview.append({
                            "Typ": "Short",
                            "Ticker": row["ticker"],
                            "Name": row["name"],
                            "Preis": f"${px:.2f}",
                            "Gewicht": f"{(short_weight * 50):.1f}%",
                            "Menge": shares,
                            "Kosten (USD)": f"${(shares * px):,.2f}",
                            "Beta": row.get("beta", 1.0) or 1.0
                        })
                        
                    df_ls = pd.DataFrame(ls_preview)
                    st.dataframe(df_ls, hide_index=True, use_container_width=True)
                    
                    # Compute aggregate statistics
                    total_long_val = sum(float(x["Kosten (USD)"].replace("$","").replace(",","")) for x in ls_preview if x["Typ"] == "Long")
                    total_short_val = sum(float(x["Kosten (USD)"].replace("$","").replace(",","")) for x in ls_preview if x["Typ"] == "Short")
                    
                    # Beta calculation
                    betas = [float(x["Beta"]) for x in ls_preview]
                    weights = [float(x["Gewicht"].replace("%","")) / 100.0 for x in ls_preview]
                    net_beta = sum(b * w for b, w in zip(betas, weights))
                    
                    stat_col1, stat_col2, stat_col3 = st.columns(3)
                    with stat_col1:
                        st.metric("Netto Exposure (USD)", f"${(total_long_val - total_short_val):,.2f}")
                    with stat_col2:
                        st.metric("Brutto Exposure (USD)", f"${(total_long_val + total_short_val):,.2f}")
                    with stat_col3:
                        st.metric("Netto Portfolio Beta", f"{net_beta:.3f}", help="Ziel für Marktneutralität liegt bei 0.0.")
                        
                    # Execution
                    st.markdown("### 🚀 Basket Trade über Alpaca ausführen")
                    if not is_alpaca_configured():
                        st.warning("Alpaca ist nicht konfiguriert. Basket Execution deaktiviert.")
                    else:
                        confirm_basket = st.checkbox("Ich bestätige, dass ich diesen Long/Short-Korb als Basket über Alpaca handeln will.", value=False)
                        
                        if st.button("🚀 Long/Short Basket an Alpaca senden"):
                            if not confirm_basket:
                                st.error("Bitte bestätigen Sie die Ausführung des Baskets.")
                            else:
                                with st.spinner("Sende Basket-Orders..."):
                                    responses = []
                                    success = 0
                                    for trade in ls_preview:
                                        side = "buy" if trade["Typ"] == "Long" else "sell"
                                        res = place_order(trade["Ticker"], trade["Menge"], side, "market")
                                        if res.get("status") == "success":
                                            success += 1
                                        responses.append((trade["Ticker"], side, res))
                                        
                                    if success == len(ls_preview):
                                        st.success(f"🔥 Basket erfolgreich ausgeführt! Alle {success} Orders an Alpaca übermittelt.")
                                    else:
                                        st.warning(f"Basket teilweise ausgeführt ({success}/{len(ls_preview)} Orders erfolgreich).")
                                    
                                    for t, side, res in responses:
                                        if res.get("status") == "success":
                                            st.success(f"🟢 **{t}** ({side}): Platziert! ID: {res['order']['id']}")
                                        else:
                                            st.error(f"🔴 **{t}** ({side}): Fehler: {res.get('message')}")
            except Exception as e:
                st.error(f"Fehler beim Laden des Screener-Caches: {e}")
