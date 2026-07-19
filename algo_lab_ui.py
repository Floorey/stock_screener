import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import yfinance as yf
import os
import time
from datetime import datetime
from execution_algo import ExecutionAlgoManager
from arbitrage_lab import StatisticalArbitrageLab, calculate_black_scholes_delta, calculate_greeks, norm
from alpaca_trader import is_alpaca_configured, get_account_info, place_order, get_positions
from watchlist_manager import load_watchlist

def render_algo_lab_tab():
    st.markdown('<div class="wl-banner"><h2>🔬 Quantitative Algo-Trading & Execution Lab</h2></div>', unsafe_allow_html=True)
    st.markdown("Testen Sie quantitative Handelsstrategien (Arbitrage, Paare) und führen Sie Orders kontrolliert mit Ausführungsalgorithmen aus.")
    
    # Sub-tabs inside Algo Lab
    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
        "🤖 Algorithmic Execution (OMS)",
        "📈 Statistical Arbitrage (Pairs)",
        "🎫 Option Delta-Hedging & Volatility Lab",
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
                    order_res = place_order(
                        symbol=exec_ticker,
                        qty=slice_qty,
                        side=exec_side.lower(),
                        order_type="market"
                    )
                    if order_res.get("status") == "success":
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
        
        # Pair Suitability Test Expander
        with st.expander("🔍 Paar-Eignungsrechner (StatArb Suitability Test)", expanded=False):
            st.markdown("### Prüfen Sie, ob ein Paar für Statistical Arbitrage geeignet ist")
            st.write("Dieser Rechner analysiert Korrelation, Halbwertszeit der Mean Reversion und Cointegration über das letzte Jahr.")
            
            c_col1, c_col2, c_col3 = st.columns(3)
            with c_col1:
                test_ticker_a = st.text_input("Test Asset A", value="KO", key="test_t_a").upper().strip()
            with c_col2:
                test_ticker_b = st.text_input("Test Asset B", value="PEP", key="test_t_b").upper().strip()
            with c_col3:
                test_period = st.selectbox("Historischer Test-Zeitraum", ["90d", "180d", "1y", "2y"], index=2, key="test_per")
                
            if st.button("⚖️ Eignung testen", key="test_suitability_btn"):
                with st.spinner("Analysiere mathematische Paareigenschaften..."):
                    res = StatisticalArbitrageLab.calculate_pair_suitability(test_ticker_a, test_ticker_b, test_period)
                    if res.get("status") == "error":
                        st.error(res.get("message"))
                    else:
                        st.markdown("---")
                        st.markdown(f"#### Analyse-Ergebnis für {test_ticker_a} & {test_ticker_b}")
                        
                        score = res["score"]
                        rec_color = res["recommendation_color"]
                        details = res["details"]
                        
                        col_s1, col_s2 = st.columns([1, 2])
                        with col_s1:
                            st.metric("Hedge-Fund Eignungs-Score", f"{score}/100", delta=rec_color, delta_color="normal")
                        with col_s2:
                            st.info(details)
                            
                        # KPI metrics
                        col_k1, col_k2, col_k3 = st.columns(3)
                        with col_k1:
                            st.metric("Pearson Korrelation (R)", f"{res['correlation']:.3f}", help="Je näher an 1, desto besser laufen die Assets parallel.")
                        with col_k2:
                            st.metric("Mean-Crossing Frequenz (p.a.)", f"{res['normalized_crossings_annual']:.1f} Mal", help="Wie oft der Spread pro Jahr seinen Mittelwert kreuzt. Höher = mehr Trading-Chancen.")
                        with col_k3:
                            hl_val = f"{res['half_life']:.1f} Tage" if res['half_life'] < 300 else "Keine Rückkehr"
                            st.metric("Halbwertszeit (Mean Reversion)", hl_val, help="Wie viele Tage der Spread im Schnitt braucht, um die Hälfte einer Abweichung auszugleichen. Ideal sind 2-25 Tage.")
                            
                        if res["statsmodels_available"]:
                            st.write(f"🔬 **Engle-Granger Cointegration p-Wert:** `{res['coint_p']:.4f}` (p < 0.05 gilt als statistisch signifikant cointegriert)")
                        else:
                            st.caption("Hinweis: Cointegration p-Wert wurde über Mean-Reversion Halbwertszeit approximiert (statsmodels nicht geladen).")
                            
        st.markdown("---")
        
        pair_col1, pair_col2, pair_col3 = st.columns(3)
        with pair_col1:
            ticker_a = st.text_input("Asset A (z.B. KO / Gold)", value="KO").upper().strip()
            rolling_window = st.slider("Mittelwert-Fenster (Tage)", min_value=5, max_value=60, value=20)
        with pair_col2:
            ticker_b = st.text_input("Asset B (z.B. PEP / Silber)", value="PEP").upper().strip()
            entry_threshold = st.slider("Entry Z-Score Schwelle", min_value=1.0, max_value=3.5, value=2.0, step=0.1)
        with pair_col3:
            pairs_period = st.selectbox("Historischer Zeitraum", ["30d", "60d", "90d", "180d", "1y"], index=2)
            
        # Initialize session state for pairs
        if "pairs_df" not in st.session_state:
            st.session_state["pairs_df"] = None
            st.session_state["pairs_ticker_a"] = ""
            st.session_state["pairs_ticker_b"] = ""
            
        run_pairs = st.button("🔍 Spread-Analyse durchführen", key="run_pairs_btn")
        
        if run_pairs:
            with st.spinner(f"Lade historische Daten für {ticker_a} und {ticker_b}..."):
                try:
                    df_pair = StatisticalArbitrageLab.fetch_pairs_data(ticker_a, ticker_b, pairs_period)
                    if df_pair.empty:
                        st.error("Keine ausreichenden Daten gefunden.")
                    else:
                        df_pair = StatisticalArbitrageLab.calculate_pairs_metrics(df_pair, rolling_window)
                        st.session_state["pairs_df"] = df_pair
                        st.session_state["pairs_ticker_a"] = ticker_a
                        st.session_state["pairs_ticker_b"] = ticker_b
                        st.session_state["pairs_corr"] = df_pair["Price_A"].corr(df_pair["Price_B"])
                        st.session_state["pairs_current_a"] = df_pair["Price_A"].iloc[-1]
                        st.session_state["pairs_current_b"] = df_pair["Price_B"].iloc[-1]
                        st.session_state["pairs_current_z"] = df_pair["Z_Score"].iloc[-1]
                        st.session_state["pairs_current_hr"] = df_pair["Hedge_Ratio"].iloc[-1]
                except Exception as e:
                    st.error(f"Fehler bei der Paaranalyse: {e}")
                    st.session_state["pairs_df"] = None
                    
        # Render if analyzed results exist and match current input tickers
        if st.session_state["pairs_df"] is not None and st.session_state["pairs_ticker_a"] == ticker_a and st.session_state["pairs_ticker_b"] == ticker_b:
            df_pair = st.session_state["pairs_df"]
            corr = st.session_state["pairs_corr"]
            current_a = st.session_state["pairs_current_a"]
            current_b = st.session_state["pairs_current_b"]
            current_z = st.session_state["pairs_current_z"]
            current_hr = st.session_state["pairs_current_hr"]
            
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
                            
                            # Register active pair
                            if res_a.get("status") == "success" or res_b.get("status") == "success":
                                from pairs_tracker import register_pair
                                register_pair(ticker_a, ticker_b, -qty_a, qty_b, current_hr, current_z, rolling_window, pairs_period)
                                st.info("Arbitrage-Paar erfolgreich im Tracker registriert.")
                elif current_z < -entry_threshold:
                    if st.button(f"🚀 Buy-Spread Trade platzieren (Long A / Short B)", type="primary"):
                        with st.spinner("Sende Arbitrage-Legs..."):
                            # Buy A, Sell B
                            res_a = place_order(ticker_a, qty_a, "buy", "market")
                            res_b = place_order(ticker_b, qty_b, "sell", "market")
                            st.success(f"Orders platziert! Ticker {ticker_a} (Long): {res_a.get('status')} | Ticker {ticker_b} (Short): {res_b.get('status')}")
                            
                            # Register active pair
                            if res_a.get("status") == "success" or res_b.get("status") == "success":
                                from pairs_tracker import register_pair
                                register_pair(ticker_a, ticker_b, qty_a, -qty_b, current_hr, current_z, rolling_window, pairs_period)
                                st.info("Arbitrage-Paar erfolgreich im Tracker registriert.")
                else:
                    st.info("Der Z-Score liegt aktuell im neutralen Bereich. Kein unmittelbares Handels-Setup.")


    # -------------------------------------------------------------------------
    # SUB-TAB 3: OPTION DELTA-HEDGING & VOLATILITY LAB
    # -------------------------------------------------------------------------
    with sub_tab3:
        st.subheader("Option Delta-Hedging & Volatility Lab")
        st.write("Absicherung von Richtungsrisiken (Delta-Hedged Optionsportfolios) und statistisches Volatilitätstrading (Gamma-Scalping) mit US-Optionen.")
        
        opt_lab_tab1, opt_lab_tab2, opt_lab_tab3 = st.tabs([
            "🎯 Reines Delta-Hedging",
            "🌀 Gamma Scalping Simulator",
            "📊 Execution & Spread Analyzer"
        ])
        
        # ---------------------------------------------------------------------
        # Tab 3.1: Reines Delta-Hedging
        # ---------------------------------------------------------------------
        with opt_lab_tab1:
            st.write("### 🎯 Reines Option Delta-Hedging")
            st.write("Neutralisieren Sie das Richtungsrisiko (Delta) einer reinen Long- oder Short-Optionen-Position durch dynamisches Kaufen oder Leerverkaufen der zugrunde liegenden Aktie.")
            
            dh_col1, dh_col2, dh_col3 = st.columns(3)
            with dh_col1:
                dh_ticker = st.text_input("Underlying Aktie (z.B. MSTR, TSLA)", value="MSTR", key="dh_ticker_input").upper().strip()
                dh_contracts = st.number_input("Anzahl Kontrakte", min_value=1, value=10, step=1, key="dh_contracts_input")
                dh_opt_type = st.selectbox("Optionstyp", ["Call", "Put"], key="dh_opt_type_input")
            with dh_col2:
                dh_strike = st.number_input("Option Strike Price ($)", min_value=1.0, value=100.0, step=1.0, key="dh_strike_input")
                dh_iv = st.slider("Implied Volatility (IV %)", min_value=5.0, max_value=250.0, value=80.0, step=1.0, key="dh_iv_input") / 100.0
                dh_pos_type = st.selectbox("Position", ["Long", "Short"], key="dh_pos_type_input")
            with dh_col3:
                dh_days = st.number_input("Restlaufzeit (Tage)", min_value=1, value=30, step=1, key="dh_days_input")
                dh_r = st.slider("Risikofreier Zins (r %)", min_value=0.0, max_value=10.0, value=4.0, step=0.1, key="dh_r_input") / 100.0
            
            run_dh = st.button("📊 Delta-Hedge berechnen", key="run_dh_btn")
            
            if run_dh or dh_ticker:
                with st.spinner(f"Hole aktuellen Kurs für {dh_ticker}..."):
                    try:
                        tk = yf.Ticker(dh_ticker)
                        hist = tk.history(period="1d")
                        if hist.empty:
                            dh_s = 100.0
                        else:
                            dh_s = float(hist["Close"].iloc[-1])
                            
                        T_years = dh_days / 365.0
                        greeks = calculate_greeks(dh_s, dh_strike, T_years, dh_r, dh_iv, dh_opt_type.lower())
                        
                        # Position multiplier
                        pos_mult = 1.0 if dh_pos_type == "Long" else -1.0
                        
                        # Greeks metrics
                        opt_delta = greeks["delta"]
                        pos_delta = opt_delta * 100 * dh_contracts * pos_mult
                        pos_gamma = greeks["gamma"] * 100 * dh_contracts * pos_mult
                        pos_theta = greeks["theta"] * 100 * dh_contracts * pos_mult
                        pos_vega = greeks["vega"] * 100 * dh_contracts * pos_mult
                        
                        # Target stock shares to hold (to make combined delta = 0)
                        shares_to_hold_round = int(np.round(-pos_delta))
                        
                        st.markdown("### 🦇 Griechische Kennzahlen & Absicherungsbedarf")
                        
                        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                        with m_col1:
                            st.metric("Option Delta (Δ)", f"{opt_delta:.4f}", help="Sensitivität der Option gegenüber $1 Kursbewegung.")
                        with m_col2:
                            st.metric("Position Delta (Δ_pos)", f"{pos_delta:.2f}", help="Kombiniertes Delta der Optionsposition (Einheiten der Aktie).")
                        with m_col3:
                            st.metric("Hedge-Zielposition", f"{shares_to_hold_round} Shares", help="Ziel-Aktienbestand für Delta-Neutralität.")
                        with m_col4:
                            st.metric("Position Gamma (Γ_pos)", f"{pos_gamma:.4f}", help="Veränderung des Positionsdeltas bei $1 Kursbewegung.")
                            
                        if shares_to_hold_round < 0:
                            rec_text = f"**{abs(shares_to_hold_round)} Aktien leerverkaufen (Short)**"
                        elif shares_to_hold_round > 0:
                            rec_text = f"**{abs(shares_to_hold_round)} Aktien kaufen (Long)**"
                        else:
                            rec_text = "**Keine Aktien benötigt (Bereits delta-neutral)**"
                            
                        st.write(f"Um Ihre {dh_pos_type}-{dh_opt_type}-Position ({dh_contracts} Kontrakte) delta-neutral abzusichern, müssen Sie aktuell {rec_text} von **{dh_ticker}** bei einem Kurs von **${dh_s:.2f}** halten.")
                        
                        # Risk Profile Chart
                        prices = np.linspace(dh_s * 0.8, dh_s * 1.2, 50)
                        deltas = [calculate_black_scholes_delta(p, dh_strike, T_years, dh_r, dh_iv, dh_opt_type.lower()) * 100 * dh_contracts * pos_mult for p in prices]
                        combined_deltas = [d + shares_to_hold_round for d in deltas]
                        
                        fig, ax = plt.subplots(figsize=(10, 4))
                        fig.patch.set_facecolor('#0f172a')
                        ax.set_facecolor('#1e293b')
                        ax.tick_params(colors='#94a3b8')
                        ax.xaxis.label.set_color('#94a3b8')
                        ax.yaxis.label.set_color('#94a3b8')
                        ax.title.set_color('#f8fafc')
                        ax.grid(True, color='#334155', linestyle=':')
                        
                        ax.plot(prices, combined_deltas, color="#00ffcc", linewidth=2.5, label="Kombiniertes Delta (Hedged)")
                        ax.plot(prices, deltas, color="#a855f7", linestyle="--", alpha=0.6, label="Unhedged Positions-Delta")
                        ax.axvline(dh_s, color="#f43f5e", linestyle="--", label="Aktueller Kurs")
                        ax.axhline(0, color="#f8fafc", linestyle=":", alpha=0.5)
                        ax.set_ylabel("Gesamt-Delta (Δ)")
                        ax.set_xlabel(f"Aktienpreis ({dh_ticker})")
                        ax.set_title("Hedge-Sensitivität (Gamma-Kurve: Delta-Shift bei Kursbewegungen)")
                        ax.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                        st.pyplot(fig)
                        
                        # Live Execution Panel
                        st.markdown("### 🚀 Delta-Hedge Ausführen")
                        if not is_alpaca_configured():
                            st.warning("Alpaca ist nicht konfiguriert. Hedge-Ausführung deaktiviert.")
                        else:
                            st.info("🟢 Alpaca-Verbindung bereit.")
                            
                            # Fetch existing position to check if we already hold some shares
                            existing_qty = 0
                            positions = get_positions()
                            if positions:
                                for pos in positions:
                                    if pos.get("symbol") == dh_ticker:
                                        existing_qty = int(pos.get("qty"))
                                        break
                                        
                            st.write(f"Aktueller Bestand an {dh_ticker}-Aktien im Alpaca Depot: **{existing_qty}** Shares.")
                            diff_shares = shares_to_hold_round - existing_qty
                            
                            if diff_shares != 0:
                                action_str = f"{abs(diff_shares)} Aktien KAUFEN (Hedge-Reduktion)" if diff_shares > 0 else f"{abs(diff_shares)} Aktien LEERVERKAUFEN"
                                st.write(f"Differenz zum Ziel-Hedge: **{action_str}**")
                                
                                confirm_hedge = st.checkbox("Hedge-Order über Alpaca ausführen", value=False, key="dh_confirm_hedge")
                                if st.button("🚀 Hedge-Order an Alpaca senden", key="dh_hedge_exec_btn"):
                                    if not confirm_hedge:
                                        st.error("Bitte bestätigen Sie die Orderausführung.")
                                    else:
                                        side = "buy" if diff_shares > 0 else "sell"
                                        res = place_order(dh_ticker, abs(diff_shares), side, "market")
                                        if res.get("status") == "success":
                                            st.success(f"Erfolgreich! Hedge-Order übergeben. ID: {res.get('order', {}).get('id')}")
                                        else:
                                            st.error(f"Fehler bei Ausführung: {res.get('message')}")
                            else:
                                st.success("Ihr Portfolio ist bezüglich dieses Assets bereits perfekt delta-neutral abgesichert!")
                    except Exception as e:
                        st.error(f"Fehler bei Berechnungen: {e}")
                        
        # ---------------------------------------------------------------------
        # Tab 3.2: Gamma Scalping Simulator
        # ---------------------------------------------------------------------
        with opt_lab_tab2:
            st.write("### 🌀 Volatility Arbitrage (Gamma Scalping)")
            st.write("Kaufen Sie einen Long Straddle oder Strangle (Long Volatilität) und nutzen Sie die Kursbewegungen, um durch kontinuierliches Rebalancing (tief kaufen, hoch verkaufen) Gewinne zu erzielen, die den Zeitwertverfall (Theta) kompensieren.")
            
            # Helper to calculate BS price inside UI
            def calculate_bs_price(S, K, T, r, sigma, option_type="call"):
                if T <= 0:
                    return max(0.0, S - K) if option_type.lower() == "call" else max(0.0, K - S)
                d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
                d2 = d1 - sigma * np.sqrt(T)
                if option_type.lower() == "call":
                    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
                else:
                    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            
            gs_col1, gs_col2, gs_col3 = st.columns(3)
            with gs_col1:
                gs_ticker = st.text_input("Underlying Ticker", value="MSTR", key="gs_ticker_input").upper().strip()
                gs_strategy = st.selectbox("Strategie", ["Long Straddle (Call + Put @ Strike)", "Long Strangle (Call @ +5%, Put @ -5%)"], key="gs_strat_input")
                gs_contracts = st.number_input("Anzahl Kontrakte", min_value=1, value=10, step=1, key="gs_contracts_input")
            with gs_col2:
                gs_stock_px = st.number_input("Aktueller Aktienkurs ($)", min_value=1.0, value=100.0, step=1.0, key="gs_px_input")
                gs_iv = st.slider("Implizierte Volatilität (IV %)", min_value=10.0, max_value=250.0, value=100.0, step=5.0, key="gs_iv_input") / 100.0
                gs_path_type = st.selectbox("Simulierter Preispfad", ["Oszillierend (Seitwärts/Fluctuating)", "Aufwärtstrend + Rauschen", "Abwärtstrend + Rauschen"], key="gs_path_input")
            with gs_col3:
                gs_days = st.number_input("Laufzeit Optionen (Tage)", min_value=5, value=20, step=1, key="gs_days_input")
                gs_r = st.slider("Risikofreier Zins (r %)", min_value=0.0, max_value=10.0, value=4.0, step=0.1, key="gs_r_input") / 100.0
                
            run_sim = st.button("🌀 Gamma Scalping Simulation starten", key="run_gs_sim_btn")
            
            if run_sim:
                st.markdown("### 📈 Simulationsergebnisse (Täglicher Rebalancing-Pfad)")
                
                # Determine strikes
                if "Straddle" in gs_strategy:
                    strike_call = gs_stock_px
                    strike_put = gs_stock_px
                else:
                    strike_call = np.round(gs_stock_px * 1.05, 2)
                    strike_put = np.round(gs_stock_px * 0.95, 2)
                
                # Generate price path over 10 steps (representing 10 half-days, or 5 days total, dt = 0.5 days)
                steps = 11
                dt_days = 0.5
                dt_years = dt_days / 365.0
                
                # Random seed for reproducibility of current run but varying
                np.random.seed(int(time.time()) % 1000)
                
                prices = [gs_stock_px]
                sigma_step = gs_iv * np.sqrt(dt_years)
                
                for idx in range(1, steps):
                    if "Oszillierend" in gs_path_type:
                        phase = idx * np.pi / 2.5
                        p_change = 1.5 * sigma_step * np.sin(phase) + np.random.normal(0, 0.4 * sigma_step)
                        prices.append(np.round(gs_stock_px * (1.0 + p_change), 2))
                    elif "Aufwärts" in gs_path_type:
                        p_change = 0.5 * sigma_step * idx + np.random.normal(0, 0.4 * sigma_step)
                        prices.append(np.round(gs_stock_px * (1.0 + p_change), 2))
                    else: # Downward
                        p_change = -0.5 * sigma_step * idx + np.random.normal(0, 0.4 * sigma_step)
                        prices.append(np.round(gs_stock_px * (1.0 + p_change), 2))
                
                # Track simulation variables
                sim_records = []
                
                # Step 0 setup
                s_0 = prices[0]
                t_0 = gs_days / 365.0
                
                call_px_0 = calculate_bs_price(s_0, strike_call, t_0, gs_r, gs_iv, "call")
                put_px_0 = calculate_bs_price(s_0, strike_put, t_0, gs_r, gs_iv, "put")
                opt_val_0 = (call_px_0 + put_px_0) * 100 * gs_contracts
                
                call_d_0 = calculate_black_scholes_delta(s_0, strike_call, t_0, gs_r, gs_iv, "call")
                put_d_0 = calculate_black_scholes_delta(s_0, strike_put, t_0, gs_r, gs_iv, "put")
                net_d_0 = (call_d_0 + put_d_0) * 100 * gs_contracts
                
                # Initial Stock position to hedge delta
                stock_qty_0 = -int(np.round(net_d_0))
                stock_val_0 = stock_qty_0 * s_0
                
                # Initial Capital setup: we assume we start with 0 cash net, so Cash = -OptionVal - StockVal
                cash_0 = -opt_val_0 - stock_val_0
                
                sim_records.append({
                    "Schritt": 0,
                    "Tag": 0.0,
                    "Aktienkurs ($)": s_0,
                    "Call Preis ($)": call_px_0,
                    "Put Preis ($)": put_px_0,
                    "Netto Delta": net_d_0,
                    "Aktien-Bestand": stock_qty_0,
                    "Aktion": "Setup",
                    "Aktion Menge": 0,
                    "Option Wert ($)": opt_val_0,
                    "Aktien Wert ($)": stock_val_0,
                    "Cash ($)": cash_0,
                    "Depot-Wert ($)": 0.0,
                    "Netto P&L ($)": 0.0
                })
                
                # Loop through steps
                stock_qty_prev = stock_qty_0
                cash_prev = cash_0
                
                for idx in range(1, steps):
                    s_i = prices[idx]
                    t_i = max(0.001, (gs_days - idx * dt_days) / 365.0)
                    tag_i = idx * dt_days
                    
                    call_px_i = calculate_bs_price(s_i, strike_call, t_i, gs_r, gs_iv, "call")
                    put_px_i = calculate_bs_price(s_i, strike_put, t_i, gs_r, gs_iv, "put")
                    opt_val_i = (call_px_i + put_px_i) * 100 * gs_contracts
                    
                    call_d_i = calculate_black_scholes_delta(s_i, strike_call, t_i, gs_r, gs_iv, "call")
                    put_d_i = calculate_black_scholes_delta(s_i, strike_put, t_i, gs_r, gs_iv, "put")
                    net_d_i = (call_d_i + put_d_i) * 100 * gs_contracts
                    
                    # Target Stock Qty
                    stock_qty_target = -int(np.round(net_d_i))
                    trade_qty = stock_qty_target - stock_qty_prev
                    
                    if trade_qty > 0:
                        action_str = "Kauf"
                        cash_i = cash_prev - (trade_qty * s_i)
                    elif trade_qty < 0:
                        action_str = "Verkauf"
                        cash_i = cash_prev + (abs(trade_qty) * s_i)
                    else:
                        action_str = "Hold"
                        cash_i = cash_prev
                        
                    stock_val_i = stock_qty_target * s_i
                    portfolio_val_i = opt_val_i + stock_val_i + cash_i
                    
                    # Log record
                    sim_records.append({
                        "Schritt": idx,
                        "Tag": tag_i,
                        "Aktienkurs ($)": s_i,
                        "Call Preis ($)": call_px_i,
                        "Put Preis ($)": put_px_i,
                        "Netto Delta": net_d_i,
                        "Aktien-Bestand": stock_qty_target,
                        "Aktion": action_str,
                        "Aktion Menge": abs(trade_qty),
                        "Option Wert ($)": opt_val_i,
                        "Aktien Wert ($)": stock_val_i,
                        "Cash ($)": cash_i,
                        "Depot-Wert ($)": portfolio_val_i,
                        "Netto P&L ($)": portfolio_val_i
                    })
                    
                    # Update state
                    stock_qty_prev = stock_qty_target
                    cash_prev = cash_i
                
                df_sim = pd.DataFrame(sim_records)
                
                # Show key metrics of simulation
                final_row = df_sim.iloc[-1]
                initial_opt_cost = df_sim.iloc[0]["Option Wert ($)"]
                final_opt_val = final_row["Option Wert ($)"]
                total_theta_cost = initial_opt_cost - final_opt_val
                scalping_pnl = final_row["Netto P&L ($)"] + total_theta_cost
                
                kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
                with kpi_col1:
                    st.metric("Netto P&L (Ergebnis)", f"${final_row['Netto P&L ($)']:+,.2f}", 
                              delta="Gewinn" if final_row['Netto P&L ($)'] > 0 else "Verlust")
                with kpi_col2:
                    st.metric("Scalping-Gewinn (Gamma)", f"${scalping_pnl:,.2f}", 
                              help="Realisierter Gewinn aus den Aktien-Hedge-Transaktionen (Kauf im Tief, Verkauf im Hoch).")
                with kpi_col3:
                    st.metric("Options-Wertverlust (Theta)", f"-${total_theta_cost:,.2f}", 
                              help="Zeitwertverlust der Call- und Put-Optionen über den Simulationszeitraum.")
                with kpi_col4:
                    performance_ratio = (scalping_pnl / total_theta_cost) * 100 if total_theta_cost > 0 else 0
                    st.metric("Theta-Deckungsgrad (%)", f"{performance_ratio:.1f}%", 
                              help="Wie viel Prozent des Options-Wertverlusts durch das Gamma-Scalping wieder eingespielt wurden. >100% bedeutet profitabel.")
                
                # Show dynamic plot
                fig, (ax_p, ax_pl) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
                fig.patch.set_facecolor('#0f172a')
                
                for ax in [ax_p, ax_pl]:
                    ax.set_facecolor('#1e293b')
                    ax.tick_params(colors='#94a3b8')
                    ax.xaxis.label.set_color('#94a3b8')
                    ax.yaxis.label.set_color('#94a3b8')
                    ax.title.set_color('#f8fafc')
                    ax.grid(True, color='#334155', linestyle=':')
                
                # Chart 1: Stock Price path
                ax_p.plot(df_sim["Tag"], df_sim["Aktienkurs ($)"], marker="o", color="#38bdf8", linewidth=2, label="Aktienkurs ($)")
                ax_p.axhline(gs_stock_px, color="#ef4444", linestyle="--", label="Strike Price (ATM)")
                ax_p.set_ylabel("Aktienkurs ($)")
                ax_p.set_title(f"Simulierter Kursverlauf für {gs_ticker} (IV: {gs_iv*100:.0f}%)")
                ax_p.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                
                # Chart 2: Cumulative P&L and Scalping vs Theta
                opt_decay_cum = [df_sim.iloc[0]["Option Wert ($)"] - row["Option Wert ($)"] for idx, row in df_sim.iterrows()]
                scalp_cum = [row["Netto P&L ($)"] + opt_decay_cum[idx] for idx, row in df_sim.iterrows()]
                
                ax_pl.plot(df_sim["Tag"], df_sim["Netto P&L ($)"], marker="s", color="#22c55e" if final_row["Netto P&L ($)"] >= 0 else "#ef4444", linewidth=2.5, label="Netto Portfolio P&L")
                ax_pl.bar(df_sim["Tag"], [-x for x in opt_decay_cum], color="#f43f5e", alpha=0.4, width=0.2, label="Kumulativer Theta-Verlust")
                ax_pl.plot(df_sim["Tag"], scalp_cum, color="#a855f7", linestyle=":", label="Kumulativer Scalping-Gewinn")
                ax_pl.set_xlabel("Tag")
                ax_pl.set_ylabel("P&L ($)")
                ax_pl.set_title("P&L-Zerlegung: Gamma-Gewinn vs. Theta-Verfall")
                ax_pl.legend(facecolor='#1e293b', labelcolor='#f8fafc')
                
                st.pyplot(fig)
                
                # Table details of the steps
                st.markdown("### 📋 Transaktionsprotokoll")
                
                display_df = df_sim.copy()
                display_df["Preisschritt"] = display_df["Schritt"].apply(lambda s: f"Schritt {s}")
                display_df["Aktienkurs ($)"] = display_df["Aktienkurs ($)"].apply(lambda x: f"${x:.2f}")
                display_df["Netto Delta"] = display_df["Netto Delta"].apply(lambda x: f"{x:.2f}")
                display_df["Aktion Info"] = display_df.apply(lambda r: f"{r['Aktion']} {r['Aktion Menge']} Shares" if r["Aktion"] in ["Kauf", "Verkauf"] else r["Aktion"], axis=1)
                display_df["Option Wert ($)"] = display_df["Option Wert ($)"].apply(lambda x: f"${x:,.2f}")
                display_df["Depot-Wert ($)"] = display_df["Depot-Wert ($)"].apply(lambda x: f"${x:,.2f}")
                display_df["Netto P&L ($)"] = display_df["Netto P&L ($)"].apply(lambda x: f"${x:,.2f}")
                
                st.dataframe(display_df[["Preisschritt", "Tag", "Aktienkurs ($)", "Netto Delta", "Aktien-Bestand", "Aktion Info", "Option Wert ($)", "Depot-Wert ($)", "Netto P&L ($)"]], hide_index=True, use_container_width=True)
                
        # ---------------------------------------------------------------------
        # Tab 3.3: Execution & Spread Analyzer
        # ---------------------------------------------------------------------
        with opt_lab_tab3:
            st.write("### 📊 Execution & Spread Analyzer")
            st.write("Visualisierung des aktuellen Geld-Brief-Spreads (Bid-Ask Spread) von US-Optionen und Simulation von limitierten Orders innerhalb des Spreads (Mid-Price Orders) zur Reduzierung von Slippage.")
            
            ea_ticker = st.text_input("Ticker Symbol für Optionsanalyse", value="MSTR", key="ea_ticker_input").upper().strip()
            
            options_loaded = False
            expiries = []
            
            if ea_ticker:
                with st.spinner(f"Lade Optionskette für {ea_ticker}..."):
                    try:
                        tk = yf.Ticker(ea_ticker)
                        expiries = list(tk.options)
                        if expiries:
                            options_loaded = True
                    except Exception:
                        options_loaded = False
                        
            if options_loaded:
                st.success(f"🟢 {len(expiries)} Options-Verfallstage für {ea_ticker} geladen.")
                sel_ea_expiry = st.selectbox("Ablaufdatum (Expiry) wählen", expiries, key="ea_expiry_sel")
                
                try:
                    chain = tk.option_chain(sel_ea_expiry)
                    calls_orig = chain.calls
                    puts_orig = chain.puts
                    
                    hist = tk.history(period="1d")
                    stock_price = float(hist["Close"].iloc[-1]) if not hist.empty else 100.0
                    
                    # Filter strikes close to ATM
                    calls = calls_orig[(calls_orig["strike"] >= stock_price * 0.8) & (calls_orig["strike"] <= stock_price * 1.2)].copy()
                    puts = puts_orig[(puts_orig["strike"] >= stock_price * 0.8) & (puts_orig["strike"] <= stock_price * 1.2)].copy()
                    
                    for df_opt in [calls, puts]:
                        df_opt["bid"] = df_opt["bid"].fillna(df_opt["lastPrice"] * 0.95).replace(0.0, df_opt["lastPrice"] * 0.95)
                        df_opt["ask"] = df_opt["ask"].fillna(df_opt["lastPrice"] * 1.05).replace(0.0, df_opt["lastPrice"] * 1.05)
                        df_opt["Spread_USD"] = df_opt["ask"] - df_opt["bid"]
                        df_opt["Mid_Price"] = (df_opt["ask"] + df_opt["bid"]) / 2.0
                        df_opt["Spread_Pct"] = (df_opt["Spread_USD"] / df_opt["Mid_Price"]) * 100
                        df_opt["impliedVolatility"] = df_opt["impliedVolatility"] * 100.0
                except Exception as e:
                    st.warning(f"Fehler beim Parsen der Live-Optionsdaten: {e}. Verwende simulierte Standard-Daten.")
                    options_loaded = False
            
            if not options_loaded:
                st.info("💡 Verwende realistische simulierte Optionsdaten für Analyse, da keine Live-Daten geladen werden konnten.")
                stock_price = 100.0
                sel_ea_expiry = "30-Tage Expiry (Mock)"
                
                strikes = np.arange(80.0, 122.5, 2.5)
                mock_calls = []
                mock_puts = []
                
                mock_T = 30.0 / 365.0
                mock_r = 0.04
                mock_iv = 0.80
                
                for k in strikes:
                    call_px = calculate_bs_price(stock_price, k, mock_T, mock_r, mock_iv, "call")
                    put_px = calculate_bs_price(stock_price, k, mock_T, mock_r, mock_iv, "put")
                    
                    dist = abs(k - stock_price)
                    spread = 0.10 + 0.05 * dist + 0.005 * dist**2
                    
                    call_bid = max(0.01, np.round(call_px - spread/2.0, 2))
                    call_ask = np.round(call_px + spread/2.0, 2)
                    
                    put_bid = max(0.01, np.round(put_px - spread/2.0, 2))
                    put_ask = np.round(put_px + spread/2.0, 2)
                    
                    smile_iv = mock_iv + 0.02 * (k - stock_price)**2 / stock_price
                    if k < stock_price:
                        smile_iv += 0.005 * (stock_price - k)
                        
                    mock_calls.append({
                        "contractSymbol": f"{ea_ticker}260821C{int(k*1000):08d}",
                        "strike": k,
                        "bid": call_bid,
                        "ask": call_ask,
                        "Spread_USD": call_ask - call_bid,
                        "Mid_Price": (call_ask + call_bid) / 2.0,
                        "Spread_Pct": ((call_ask - call_bid) / ((call_ask + call_bid)/2.0)) * 100.0,
                        "impliedVolatility": smile_iv * 100.0,
                        "volume": int(1000 / (1.0 + 0.1 * dist)),
                        "openInterest": int(5000 / (1.0 + 0.05 * dist))
                    })
                    
                    mock_puts.append({
                        "contractSymbol": f"{ea_ticker}260821P{int(k*1000):08d}",
                        "strike": k,
                        "bid": put_bid,
                        "ask": put_ask,
                        "Spread_USD": put_ask - put_bid,
                        "Mid_Price": (put_ask + put_bid) / 2.0,
                        "Spread_Pct": ((put_ask - put_bid) / ((put_ask + put_bid)/2.0)) * 100.0,
                        "impliedVolatility": smile_iv * 100.0,
                        "volume": int(800 / (1.0 + 0.15 * dist)),
                        "openInterest": int(4000 / (1.0 + 0.08 * dist))
                    })
                    
                calls = pd.DataFrame(mock_calls)
                puts = pd.DataFrame(mock_puts)
            
            # Options Visualizations
            st.markdown(f"### 📊 Spread-Überwachung vs. Implizierte Volatilität (Smile)")
            st.write(f"Aktueller Kurs der Aktie: **${stock_price:.2f}** | Expiry: **{sel_ea_expiry}**")
            
            ea_opt_type = st.radio("Optionstyp für Diagramm", ["Calls", "Puts"], horizontal=True, key="ea_opt_type_chart")
            df_chart = calls if ea_opt_type == "Calls" else puts
            
            # Dual Axis Plot: Bid-Ask Spread ($) and Implied Volatility (%)
            fig, ax_sp = plt.subplots(figsize=(10, 4.5))
            fig.patch.set_facecolor('#0f172a')
            ax_sp.set_facecolor('#1e293b')
            ax_sp.tick_params(colors='#94a3b8')
            ax_sp.xaxis.label.set_color('#94a3b8')
            ax_sp.yaxis.label.set_color('#38bdf8')
            ax_sp.title.set_color('#f8fafc')
            ax_sp.grid(True, color='#334155', linestyle=':')
            
            # Spread line
            ax_sp.plot(df_chart["strike"], df_chart["Spread_USD"], color="#38bdf8", marker="o", linewidth=2, label="Bid-Ask Spread ($)")
            ax_sp.set_ylabel("Geld-Brief-Spread ($)", color="#38bdf8")
            ax_sp.axvline(stock_price, color="#ef4444", linestyle="--", label="Aktienkurs (ATM)")
            
            # IV line on secondary axis
            ax_iv = ax_sp.twinx()
            ax_iv.tick_params(colors='#94a3b8')
            ax_iv.yaxis.label.set_color('#a855f7')
            ax_iv.plot(df_chart["strike"], df_chart["impliedVolatility"], color="#a855f7", marker="s", linestyle="--", linewidth=1.5, label="Implizierte Volatilität (IV %)")
            ax_iv.set_ylabel("Implizierte Volatilität (IV %)", color="#a855f7")
            
            # Legends combined
            lines1, labels1 = ax_sp.get_legend_handles_labels()
            lines2, labels2 = ax_iv.get_legend_handles_labels()
            ax_sp.legend(lines1 + lines2, labels1 + labels2, loc="upper center", facecolor='#1e293b', labelcolor='#f8fafc')
            
            ax_sp.set_xlabel("Basispreis (Strike)")
            st.pyplot(fig)
            
            # Table View
            with st.expander("📋 Tabelle der Optionsdaten anzeigen"):
                st.write(f"#### {ea_opt_type} Kette")
                formatted_table = df_chart.copy()
                formatted_table["Strike"] = formatted_table["strike"].apply(lambda x: f"${x:.2f}")
                formatted_table["Bid"] = formatted_table["bid"].apply(lambda x: f"${x:.2f}")
                formatted_table["Ask"] = formatted_table["ask"].apply(lambda x: f"${x:.2f}")
                formatted_table["Mid-Price"] = formatted_table["Mid_Price"].apply(lambda x: f"${x:.2f}")
                formatted_table["Spread ($)"] = formatted_table["Spread_USD"].apply(lambda x: f"${x:.2f}")
                formatted_table["Spread (%)"] = formatted_table["Spread_Pct"].apply(lambda x: f"{x:.1f}%")
                formatted_table["IV (%)"] = formatted_table["impliedVolatility"].apply(lambda x: f"{x:.1f}%")
                
                st.dataframe(
                    formatted_table[["contractSymbol", "Strike", "Bid", "Ask", "Mid-Price", "Spread ($)", "Spread (%)", "IV (%)", "volume", "openInterest"]],
                    hide_index=True,
                    use_container_width=True
                )
            
            # Order-Typen-Test Simulator
            st.markdown("---")
            st.markdown("### 🎛️ Order-Typen-Test & Slippage-Minimierung")
            st.write("Vergleichen Sie die Ausführungsrate und Slippage-Kosten einer aggressiven Market-Order mit einer geduldigen Mid-Price Limit-Order.")
            
            test_contract_symbol = st.selectbox(
                "Options-Kontrakt für Test wählen",
                options=df_chart["contractSymbol"].tolist(),
                key="ea_test_contract_sel"
            )
            
            con_row = df_chart[df_chart["contractSymbol"] == test_contract_symbol].iloc[0]
            c_bid = con_row["bid"]
            c_ask = con_row["ask"]
            c_mid = con_row["Mid_Price"]
            c_spread = con_row["Spread_USD"]
            c_iv_val = con_row["impliedVolatility"] / 100.0
            
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.markdown(f"""
                <div style="background-color: #1e293b; border-radius: 8px; padding: 1rem; border: 1px solid #334155;">
                    <h4>Kontrakt: {test_contract_symbol}</h4>
                    <ul>
                        <li><b>Bid (Geld):</b> ${c_bid:.2f}</li>
                        <li><b>Ask (Brief):</b> ${c_ask:.2f}</li>
                        <li><b>Mittelpreis (Mid):</b> ${c_mid:.2f}</li>
                        <li><b>Spread:</b> ${c_spread:.2f} ({(c_spread/c_mid*100):.1f}%)</li>
                        <li><b>Implizierte Volatilität (IV):</b> {(c_iv_val*100):.1f}%</li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)
            with col_t2:
                ea_side = st.selectbox("Transaktion", ["Kauf (Buy)", "Verkauf (Sell)"], key="ea_side_input")
                ea_qty = st.number_input("Menge (Kontrakte)", min_value=1, value=5, step=1, key="ea_qty_input")
                ea_wait = st.slider("Wartezeit Limit-Order (Minuten)", min_value=1, max_value=60, value=10, key="ea_wait_input")
                
            run_order_test = st.button("🧪 Order-Typen-Test starten (Monte Carlo Simulation)", key="run_ea_order_test_btn")
            
            if run_order_test:
                sigma_opt = c_mid * c_iv_val * np.sqrt(ea_wait / 525600.0)
                half_spread = c_spread / 2.0
                
                if sigma_opt <= 0:
                    d = 99.0
                else:
                    d = half_spread / sigma_opt
                
                p_fill = 2.0 * (1.0 - norm.cdf(d))
                p_fill = max(0.05, min(0.99, p_fill))
                
                st.write(f"Berechnete theoretische Fill-Wahrscheinlichkeit der Mid-Order: **{p_fill*100:.1f}%**")
                
                trials = 100
                fills = 0
                
                progress_bar = st.progress(0.0)
                
                for i in range(trials):
                    rand_val = np.random.rand()
                    if rand_val <= p_fill:
                        fills += 1
                    if i % 10 == 0:
                        progress_bar.progress((i + 1) / trials)
                        time.sleep(0.02)
                
                progress_bar.progress(1.0)
                
                saving_per_contract = c_spread / 2.0
                total_saving_if_filled = saving_per_contract * 100.0 * ea_qty
                
                realized_saving = fills * saving_per_contract * 100.0 * ea_qty / 100.0
                
                st.markdown("### 📊 Test-Ergebnis (100 simulierte Orders)")
                
                k_col1, k_col2, k_col3 = st.columns(3)
                with k_col1:
                    st.metric("Ausführungsrate (Fills)", f"{fills} / 100 Fills", 
                              help="Anzahl der Limit-Orders, die innerhalb der Wartezeit gefüllt wurden.")
                with k_col2:
                    st.metric("Erzielte Ersparnis (Slippage)", f"${realized_saving:,.2f}", 
                              help=f"Erzielte Kostenersparnis gegenüber einer Market-Order. Ein Einzeleffekt von ${saving_per_contract*100:.2f} pro gefülltem Kontrakt.")
                with k_col3:
                    potential_saving = total_saving_if_filled
                    st.metric("Max. Potenzial bei 100% Fill", f"${potential_saving:,.2f}",
                              help="Mögliche maximale Ersparnis, wenn alle Orders gefüllt worden wären.")
                
                fig_bar, ax_bar = plt.subplots(figsize=(6, 3))
                fig_bar.patch.set_facecolor('#0f172a')
                ax_bar.set_facecolor('#1e293b')
                ax_bar.tick_params(colors='#94a3b8')
                ax_bar.title.set_color('#f8fafc')
                
                categories = ["Gefüllt (Mid-Price)", "Nicht gefüllt (Fallback)"]
                values = [fills, 100 - fills]
                colors = ["#22c55e", "#ef4444"]
                
                bars = ax_bar.barh(categories, values, color=colors, height=0.5)
                ax_bar.set_xlim(0, 100)
                ax_bar.set_xlabel("Häufigkeit in %", color="#94a3b8")
                ax_bar.set_title("Order-Ausführungsverteilung im Spread-Band")
                
                for bar in bars:
                    width = bar.get_width()
                    ax_bar.text(width + 2, bar.get_y() + bar.get_height()/2, f"{width}%", 
                                va='center', ha='left', color='#f8fafc', fontweight='bold')
                
                st.pyplot(fig_bar)
                
                st.info(f"💡 **Fazit für Trader:** Durch Platzierung von Mid-Price Limit-Orders statt Market-Orders haben Sie im Schnitt **${realized_saving/ea_qty:,.2f} pro Kontrakt** an Slippage-Kosten eingespart. Bei den {100 - fills}% nicht ausgeführten Orders mussten Sie am Ende der {ea_wait} Minuten auf eine aggressive Market-Order ausweichen, um den Einstieg zu erzwingen, was dort zu den vollen Slippage-Kosten von ${c_spread*100:.2f} führte. Die Simulation zeigt: Geduld im Spread spart signifikant Kapital!")

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
