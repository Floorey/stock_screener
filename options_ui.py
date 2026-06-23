import streamlit as st
import pandas as pd
import os
from datetime import datetime
from options_advisor import (
    suggest_option_strategy,
    get_options_data_for_ticker,
    build_option_screener_df,
    find_featured_trade,
    calculate_cds_metrics
)
from watchlist_manager import load_watchlist

def render_options_tab(get_single_ticker_data, calculate_scores):
    st.markdown('<div class="wl-banner"><h2>🎫 Options-Screener & Stillhalter-Advisor</h2></div>', unsafe_allow_html=True)
    st.markdown("Verbinden Sie Ihre Watchlist-Aktien mit Echtzeit-Optionendaten von Yahoo Finance und erhalten Sie strategische Empfehlungen für das Schreiben von Optionen (Short Puts / Short Calls) oder Kreditabsicherungen (CDS).")

    # Options Parameters
    st.markdown("### ⚙️ Options-Einstellungen")
    opt_col1, opt_col2, opt_col3 = st.columns(3)
    with opt_col1:
        r_rate = st.slider(
            "Risikofreier Zinssatz (%)",
            min_value=0.0,
            max_value=10.0,
            value=4.5,
            step=0.1,
            help="Der US-Leitzins (risk-free rate) für die Black-Scholes-Berechnung von Delta und Gewinnwahrscheinlichkeit.",
            key="opt_r_rate"
        ) / 100.0
    with opt_col2:
        source_choice = st.selectbox(
            "Datenquelle für Ticker auswählen:",
            ["Standard-Watchlist (Downloads)", "Aktuelle App-Watchlist", "CSV-Datei hochladen"],
            help="Bestimmt, welche Tickersymbole und Scores im Options-Screener geladen werden.",
            key="opt_source_choice"
        )
    with opt_col3:
        uploaded_opt_csv = None
        if source_choice == "CSV-Datei hochladen":
            uploaded_opt_csv = st.file_uploader("Fundamentaldaten-CSV hochladen:", type=["csv"], key="opt_csv_uploader")
            
    # Load the data
    df_opt_source = pd.DataFrame()
    
    if source_choice == "Standard-Watchlist (Downloads)":
        dl_path = "C:/Users/lukas/Downloads/watchlist_fundamentals (1).csv"
        if os.path.exists(dl_path):
            try:
                df_opt_source = pd.read_csv(dl_path)
                st.success(f"Erfolgreich geladen: `{dl_path}` ({len(df_opt_source)} Aktien)")
            except Exception as e:
                st.error(f"Fehler beim Laden von `{dl_path}`: {e}")
        else:
            st.warning(f"Die Datei `{dl_path}` wurde im Downloads-Ordner nicht gefunden. Bitte laden Sie sie manuell hoch oder nutzen Sie die App-Watchlist.")
            
    elif source_choice == "Aktuelle App-Watchlist":
        if "watchlist_data_cache" in st.session_state:
            df_opt_source = st.session_state["watchlist_data_cache"]
            st.success(f"Erfolgreich geladen aus App-Watchlist ({len(df_opt_source)} Aktien)")
        else:
            wl_tickers = load_watchlist()
            if wl_tickers:
                st.info("Lade Fundamental-Daten für App-Watchlist...")
                results_wl = []
                for ticker in wl_tickers:
                    data = get_single_ticker_data(ticker, ticker, "Watchlist", {})
                    results_wl.append(data)
                df_opt_source = pd.DataFrame(results_wl)
                if not df_opt_source.empty:
                    df_opt_source = calculate_scores(df_opt_source)
                    st.session_state["watchlist_data_cache"] = df_opt_source
            else:
                st.warning("Ihre App-Watchlist ist leer.")
                
    elif source_choice == "CSV-Datei hochladen":
        if uploaded_opt_csv is not None:
            try:
                df_opt_source = pd.read_csv(uploaded_opt_csv)
                # Check for required columns, calculate if missing
                if "LongScore" not in df_opt_source.columns or "ShortScore" not in df_opt_source.columns:
                    st.info("Scores fehlen in der CSV. Berechne Scores...")
                    if "Price" not in df_opt_source.columns:
                        st.info("Lade Fundamental-Daten für hochgeladene Symbole...")
                        results_csv = []
                        for symbol in df_opt_source["Symbol"].tolist():
                            data = get_single_ticker_data(symbol, symbol, "Uploaded", {})
                            results_csv.append(data)
                        df_opt_source = pd.DataFrame(results_csv)
                    df_opt_source = calculate_scores(df_opt_source)
                st.success(f"Erfolgreich geladen: `{uploaded_opt_csv.name}` ({len(df_opt_source)} Aktien)")
            except Exception as e:
                st.error(f"Fehler beim Parsen der hochgeladenen Datei: {e}")
                
    if not df_opt_source.empty:
        st.markdown("---")
        # Modus Auswahl
        opt_mode = st.radio(
            "Wählen Sie das Options-Tool:",
            ["Standard Stillhalter-Screener", "Synthetischer CDS (Credit Default Swap) Analyzer"],
            horizontal=True,
            help="Der Standard Screener schlägt Stillhalter-Trades (Puts/Calls) vor. Der CDS Analyzer bewertet Ausfallversicherungen (Puts als CDS-Spread).",
            key="opt_mode_select"
        )
        
        # Dropdown to select symbol
        symbols_list = sorted(df_opt_source["Symbol"].dropna().unique().tolist())
        sel_symbol = st.selectbox("Aktie zum Analysieren auswählen:", symbols_list, key="opt_symbol_select")
        
        if sel_symbol:
            row_data = df_opt_source[df_opt_source["Symbol"] == sel_symbol].iloc[0].to_dict()
            current_p = row_data.get("Price")
            
            # --- 1. MODE: SYNTHETIC CDS ANALYZER ---
            if opt_mode == "Synthetischer CDS (Credit Default Swap) Analyzer":
                st.markdown("### 🛡️ Synthetischer Credit Default Swap (CDS) Analyzer")
                st.markdown(
                    "Dieses Tool berechnet synthetische Kreditderivate (CDS) auf Basis von Out-of-the-Money Puts. "
                    "Der Kauf eines OTM Puts entspricht dem Kauf von Kreditschutz (Long CDS). "
                    "Der Verkauf entspricht dem Verkauf von Kreditschutz (Short CDS)."
                )
                
                # Parameters for CDS
                st.markdown("#### ⚙️ CDS-Konfiguration")
                cds_col1, cds_col2 = st.columns(2)
                with cds_col1:
                    protection_level = st.slider(
                        "Kreditereignis-Schwellenwert (Abstand vom Kurs in %):",
                        min_value=5,
                        max_value=40,
                        value=20,
                        step=5,
                        help="Ab welchem Kurssturz das Kreditereignis eintritt. Bestimmt, welche Put-Option als CDS dient.",
                        key="cds_protection_level"
                    )
                with cds_col2:
                    show_term_structure = st.checkbox(
                        "Kredit-Laufzeitkurve scannen (Dauert ca. 2-3 Sekunden)",
                        value=False,
                        help="Lädt Optionsketten für alle Fälligkeiten, um die Fristenstruktur der CDS-Spreads zu visualisieren.",
                        key="cds_show_term"
                    )
                
                # Fetch option dates and chain
                with st.spinner(f"Lade Optionsdaten für {sel_symbol}..."):
                    dates, chain_data = get_options_data_for_ticker(sel_symbol)
                    
                if not dates:
                    st.error(f"Keine Optionsdaten für {sel_symbol} verfügbar.")
                else:
                    selected_expiry = st.selectbox(
                        "Laufzeit für detaillierte CDS-Bewertung:",
                        dates,
                        index=dates.index(chain_data["expiry"]) if chain_data.get("expiry") in dates else 0,
                        key="cds_expiry_select"
                    )
                    
                    if selected_expiry != chain_data.get("expiry"):
                        with st.spinner(f"Lade Optionsdaten für {selected_expiry}..."):
                            _, chain_data = get_options_data_for_ticker(sel_symbol, selected_expiry)
                            
                    if not current_p or pd.isna(current_p):
                        current_p = chain_data["calls"]["strike"].median()
                        
                    today = datetime.now().date()
                    expiry_dt = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
                    days = max((expiry_dt - today).days, 1)
                    
                    if chain_data and "puts" in chain_data:
                        puts_df = chain_data["puts"]
                        
                        # Find the put closest to the target strike
                        target_strike = current_p * (1.0 - protection_level / 100.0)
                        puts_df["strike_diff"] = (puts_df["strike"] - target_strike).abs()
                        best_put = puts_df.sort_values("strike_diff").iloc[0].to_dict()
                        
                        strike_val = best_put["strike"]
                        bid_val = best_put["bid"]
                        ask_val = best_put["ask"]
                        iv_val = best_put["impliedVolatility"]
                        
                        # Calculate CDS Metrics
                        cds_metrics = calculate_cds_metrics(current_p, strike_val, bid_val, ask_val, days, r_rate, iv_val)
                        
                        st.markdown(f"### 📑 CDS-Bewertungsblatt für **{sel_symbol}**")
                        st.markdown(f"**Referenzschuldner:** {row_data.get('Company', sel_symbol)} | **Laufzeit:** {selected_expiry} ({days} Tage)")
                        
                        # Layout Cards
                        cds_c1, cds_c2, cds_c3 = st.columns(3)
                        
                        with cds_c1:
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 8px; padding: 1rem; border: 1px solid #374151; height: 100%;">
                                <span style="font-size: 0.85rem; color: #9ca3af;">CDS Transaktionsdetails</span>
                                <h4 style="margin: 0.2rem 0; color: #3b82f6;">Referenzkontrakt</h4>
                                <ul style="margin: 0.4rem 0 0 0; padding-left: 1.1rem; font-size: 0.9rem; color: #f3f4f6;">
                                    <li>Aktienkurs: ${current_p:.2f}</li>
                                    <li>CDS Strike: ${strike_val:.2f}</li>
                                    <li>Schutzniveau: -{((current_p - strike_val)/current_p)*100:.1f}% OTM</li>
                                    <li>Kreditereignis bei: Kurs < ${strike_val:.2f}</li>
                                </ul>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with cds_c2:
                            mid_spread = cds_metrics["spread_mid"]
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 8px; padding: 1rem; border: 1px solid #374151; height: 100%;">
                                <span style="font-size: 0.85rem; color: #9ca3af;">Synthetischer CDS Spread</span>
                                <h4 style="margin: 0.2rem 0; color: #f59e0b;">{mid_spread:.0f} bps</h4>
                                <ul style="margin: 0.4rem 0 0 0; padding-left: 1.1rem; font-size: 0.9rem; color: #f3f4f6;">
                                    <li>Verkauf (Bid): {cds_metrics['cds_sell_bps']:.0f} bps</li>
                                    <li>Einkauf (Ask): {cds_metrics['cds_buy_bps']:.0f} bps</li>
                                    <li>Bewertung: {cds_metrics['rating_color']} {cds_metrics['rating']}</li>
                                </ul>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with cds_c3:
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 8px; padding: 1rem; border: 1px solid #374151; height: 100%;">
                                <span style="font-size: 0.85rem; color: #9ca3af;">Ausfallwahrscheinlichkeit</span>
                                <h4 style="margin: 0.2rem 0; color: #ef4444;">{cds_metrics['implied_pd_pct']:.2f}%</h4>
                                <ul style="margin: 0.4rem 0 0 0; padding-left: 1.1rem; font-size: 0.9rem; color: #f3f4f6;">
                                    <li>IV (Volatilität): {iv_val*100:.1f}%</li>
                                    <li>Delta (BS): {best_put['delta']:.2f}</li>
                                    <li>Zinssatz (Leitzins): {r_rate*100:.1f}%</li>
                                </ul>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        # CDS Execution Guide
                        st.markdown("<br>#### 🛠️ CDS-Handelsanleitung (Implementation Guide)")
                        
                        exec_col1, exec_col2 = st.columns(2)
                        
                        with exec_col1:
                            st.markdown(f"""
                            <div style="background-color: rgba(16, 185, 129, 0.08); border-left: 5px solid #10b981; border-radius: 8px; padding: 1.2rem; height: 100%;">
                                <h4 style="margin: 0 0 0.5rem 0; color: #10b981;">🛡️ CDS Verkaufen (Short CDS / Schutz verkaufen)</h4>
                                <p style="font-size: 0.9rem; color: #e5e7eb; line-height: 1.5; margin-bottom: 0;">
                                    Du übernimmst das Kreditrisiko und verdienst die Prämie.
                                    <br><b>Aktion:</b> Verkaufe 1 Kontrakt des Puts: <b>Strike ${strike_val:.2f}</b>.
                                    <br><b>Sofort-Einnahme:</b> ${bid_val*100:.2f}
                                    <br><b>Rendite auf besichertes Kapital:</b> {((bid_val/strike_val)*100):.2f}% (<b>{((bid_val/strike_val)*100*(365.0/days)):.1f}% p.a.</b>)
                                    <br><b>Maximales Risiko:</b> ${strike_val*100:.2f} (wenn Aktie gegen $0 stürzt).
                                </p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with exec_col2:
                            st.markdown(f"""
                            <div style="background-color: rgba(239, 68, 68, 0.08); border-left: 5px solid #ef4444; border-radius: 8px; padding: 1.2rem; height: 100%;">
                                <h4 style="margin: 0 0 0.5rem 0; color: #ef4444;">🛡️ CDS Kaufen (Long CDS / Schutz kaufen)</h4>
                                <p style="font-size: 0.9rem; color: #e5e7eb; line-height: 1.5; margin-bottom: 0;">
                                    Du sicherst dich gegen ein Ausfallereignis der Aktie ab.
                                    <br><b>Aktion:</b> Kaufe 1 Kontrakt des Puts: <b>Strike ${strike_val:.2f}</b>.
                                    <br><b>Kosten (Absicherungsgebühr):</b> ${ask_val*100:.2f}
                                    <br><b>Schutzwirkung:</b> Fällt der Kurs unter ${strike_val:.2f}, gleicht die Option jeden Dollar Kursverlust darunter 1:1 aus.
                                </p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        # Risikobegrenzung info
                        st.markdown(f"""
                        <div style="background-color: rgba(245, 158, 11, 0.08); border-left: 5px solid #f59e0b; border-radius: 6px; padding: 1rem; margin-top: 1rem;">
                            <span style="color: #f59e0b; font-weight: bold;">💡 Tipp: Risikolimitierter Kreditschutz (Credit Spread)</span><br>
                            <span style="font-size: 0.9rem; color: #e5e7eb;">
                                Statt des unbegrenzten Risikos beim Short Put, verkaufe einen <b>Put Credit Spread</b>. 
                                Verkaufe den Put mit Strike <b>${strike_val:.2f}</b> (erhalte ${bid_val:.2f}) und kaufe gleichzeitig einen tieferen Schutz-Put mit Strike <b>${(strike_val*0.9):.2f}</b> (zahle ca. ${best_put.get('lastPrice', 0.0)*0.5:.2f}). 
                                Dein Verlustrisiko ist dadurch fest auf die Differenz der Strikes begrenzt.
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Term Structure section
                        if show_term_structure:
                            st.markdown("<br>### 📈 CDS-Laufzeitkurve (Term Structure Curve)")
                            st.markdown("Verlauf der CDS-Spreads (Verkauf in bps p.a.) und der Ausfallwahrscheinlichkeiten über verschiedene Laufzeiten:")
                            
                            term_data = []
                            for d in dates[:4]:
                                today_dt = datetime.now().date()
                                exp_date = datetime.strptime(d, "%Y-%m-%d").date()
                                d_days = max((exp_date - today_dt).days, 1)
                                
                                _, d_chain = get_options_data_for_ticker(sel_symbol, d)
                                if d_chain and "puts" in d_chain:
                                    p_df = d_chain["puts"]
                                    if not p_df.empty:
                                        p_df["strike_diff"] = (p_df["strike"] - target_strike).abs()
                                        d_best = p_df.sort_values("strike_diff").iloc[0]
                                        
                                        d_strike = d_best["strike"]
                                        d_bid = d_best["bid"]
                                        d_ask = d_best["ask"]
                                        d_iv = d_best["impliedVolatility"]
                                        
                                        d_metrics = calculate_cds_metrics(current_p, d_strike, d_bid, d_ask, d_days, r_rate, d_iv)
                                        
                                        term_data.append({
                                            "Laufzeit": d,
                                            "Tage": d_days,
                                            "Strike ($)": d_strike,
                                            "OTM Abstand (%)": ((current_p - d_strike)/current_p)*100,
                                            "CDS Verkauf (bps)": d_metrics["cds_sell_bps"],
                                            "CDS Einkauf (bps)": d_metrics["cds_buy_bps"],
                                            "Ausfallwahrsch. (%)": d_metrics["implied_pd_pct"]
                                        })
                                        
                            if term_data:
                                df_term = pd.DataFrame(term_data)
                                format_term = {
                                    "Strike ($)": "${:.2f}",
                                    "OTM Abstand (%)": "{:.1f}%",
                                    "CDS Verkauf (bps)": "{:.0f} bps",
                                    "CDS Einkauf (bps)": "{:.0f} bps",
                                    "Ausfallwahrsch. (%)": "{:.2f}%"
                                }
                                st.dataframe(
                                    df_term.style.format(format_term),
                                    use_container_width=True,
                                    hide_index=True
                                )
                                
            # --- 2. MODE: STANDARD OPTION SCREENER ---
            else:
                # Suggest Option strategy based on fundamentals
                strat_info = suggest_option_strategy(row_data)
                
                # Fetch option dates and chain
                with st.spinner(f"Lade Optionsdaten für {sel_symbol} von Yahoo Finance..."):
                    dates, chain_data = get_options_data_for_ticker(sel_symbol)
                    
                if not dates:
                    st.error(f"Für {sel_symbol} konnten keine Optionsdaten gefunden werden (z.B. keine Optionen verfügbar oder Yahoo Finance Block).")
                else:
                    selected_expiry = st.selectbox(
                        "Verfallsdatum (Expiration Date):",
                        dates,
                        index=dates.index(chain_data["expiry"]) if chain_data.get("expiry") in dates else 0,
                        key="opt_expiry_select"
                    )
                    
                    if selected_expiry != chain_data.get("expiry"):
                        with st.spinner(f"Lade Optionsdaten für Verfallsdatum {selected_expiry}..."):
                            _, chain_data = get_options_data_for_ticker(sel_symbol, selected_expiry)
                            
                    if chain_data and "calls" in chain_data and "puts" in chain_data:
                        today = datetime.now().date()
                        expiry_dt = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
                        days_to_expiry = max((expiry_dt - today).days, 1)
                        
                        st.markdown(f"### 📈 Analyse für **{sel_symbol}** am Verfallstag **{selected_expiry}** ({days_to_expiry} Tage bis Verfall)")
                        
                        # Columns for Strategy Recommendation
                        rec_col1, rec_col2 = st.columns([1, 2])
                        
                        with rec_col1:
                            if not current_p or pd.isna(current_p):
                                current_p = chain_data["calls"]["strike"].median()
                                
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 12px; padding: 1.5rem; border: 1px solid #374151; height: 100%;">
                                <span style="font-size: 0.9rem; color: #9ca3af;">{sel_symbol} Aktienkurs</span>
                                <h2 style="margin: 0.2rem 0; color: #3b82f6;">${current_p:.2f}</h2>
                                <hr style="border-color: #374151; margin: 0.8rem 0;">
                                <div style="display: flex; justify-content: space-between;">
                                    <span>Long Score:</span>
                                    <span style="font-weight: bold; color: #10b981;">{row_data.get('LongScore', 0)}/7</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 0.4rem;">
                                    <span>Short Score:</span>
                                    <span style="font-weight: bold; color: #ef4444;">{row_data.get('ShortScore', 0)}/7</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 0.4rem;">
                                    <span>KGV (P/E):</span>
                                    <span>{row_data.get('PE', 'N/A')}</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 0.4rem;">
                                    <span>D/E Ratio:</span>
                                    <span>{f"{row_data.get('DebtToEquity', 0):.2f}" if row_data.get('DebtToEquity') is not None else 'N/A'}</span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with rec_col2:
                            strat_color = "#10b981" if "Put" in strat_info["Strategy"] else ("#ef4444" if "Call" in strat_info["Strategy"] else "#9ca3af")
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 12px; padding: 1.5rem; border: 1px solid #374151; height: 100%;">
                                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                                    <span style="font-size: 1.5rem;">{strat_info['Icon']}</span>
                                    <h3 style="margin: 0; color: {strat_color};">{strat_info['Strategy']}</h3>
                                </div>
                                <h5 style="color: #f3f4f6; margin-top: 0.5rem;">Strategie-Begründung:</h5>
                                <p style="color: #9ca3af; font-size: 0.95rem; line-height: 1.4; margin-bottom: 0;">
                                    {strat_info['Explanation']}
                                </p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        # Find Featured Trade Recommendations
                        st.markdown("#### ✨ Empfohlene Trade-Kandidaten (Konservativer Ansatz)")
                        
                        feat_put = find_featured_trade(sel_symbol, current_p, chain_data["puts"], days_to_expiry, r_rate, "put")
                        feat_call = find_featured_trade(sel_symbol, current_p, chain_data["calls"], days_to_expiry, r_rate, "call")
                        
                        f_col1, f_col2 = st.columns(2)
                        
                        with f_col1:
                            if feat_put:
                                st.markdown(f"""
                                <div style="background-color: rgba(16, 185, 129, 0.08); border-left: 5px solid #10b981; border-radius: 8px; padding: 1.2rem; height: 100%;">
                                    <h4 style="margin: 0 0 0.5rem 0; color: #10b981;">🟢 Empfohlener Short Put</h4>
                                    <ul style="margin: 0; padding-left: 1.2rem; color: #e5e7eb; line-height: 1.6;">
                                        <li><b>Strike Price:</b> ${feat_put['strike']:.2f} (<span style="color: #10b981;">-{feat_put['distance_pct']:.1f}% OTM</span>)</li>
                                        <li><b>Prämie (Geldkurs):</b> ${feat_put['bid']:.2f} / Kontrakt: <b>${feat_put['bid']*100:.2f}</b></li>
                                        <li><b>Implizierte Volatilität (IV):</b> {feat_put['impliedVolatility']*100:.1f}%</li>
                                        <li><b>Delta:</b> {feat_put['delta']:.2f}</li>
                                        <li><b>Wahrscheinlichkeit OTM:</b> {feat_put['prob_otm_pct']:.1f}%</li>
                                        <li><b>Rendite bei Verfall:</b> {feat_put['yield_pct']:.2f}% (<b>{feat_put['annualized_yield_pct']:.1f}% p.a.</b>)</li>
                                    </ul>
                                    <p style="font-size: 0.8rem; color: #9ca3af; margin-top: 0.8rem; line-height: 1.3;">
                                        <i>Erklärung: Sie verkaufen die Option und nehmen ${feat_put['bid']*100:.2f} Prämie ein. Fällt {sel_symbol} bis zum {selected_expiry} nicht unter ${feat_put['strike']:.2f}, behalten Sie die volle Prämie. Falls doch, müssen Sie 100 Aktien je Kontrakt zum Preis von ${feat_put['strike']:.2f} kaufen (effektiver Kaufkurs: ${(feat_put['strike'] - feat_put['bid']):.2f}).</i>
                                    </p>
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                st.info("Keine passenden Put-Optionen gefunden.")
                                
                        with f_col2:
                            if feat_call:
                                st.markdown(f"""
                                <div style="background-color: rgba(239, 68, 68, 0.08); border-left: 5px solid #ef4444; border-radius: 8px; padding: 1.2rem; height: 100%;">
                                    <h4 style="margin: 0 0 0.5rem 0; color: #ef4444;">🔴 Empfohlener Short Call / Covered Call</h4>
                                    <ul style="margin: 0; padding-left: 1.2rem; color: #e5e7eb; line-height: 1.6;">
                                        <li><b>Strike Price:</b> ${feat_call['strike']:.2f} (<span style="color: #ef4444;">+{feat_call['distance_pct']:.1f}% OTM</span>)</li>
                                        <li><b>Prämie (Geldkurs):</b> ${feat_call['bid']:.2f} / Kontrakt: <b>${feat_call['bid']*100:.2f}</b></li>
                                        <li><b>Implizierte Volatilität (IV):</b> {feat_call['impliedVolatility']*100:.1f}%</li>
                                        <li><b>Delta:</b> {feat_call['delta']:.2f}</li>
                                        <li><b>Wahrscheinlichkeit OTM:</b> {feat_call['prob_otm_pct']:.1f}%</li>
                                        <li><b>Rendite bei Verfall:</b> {feat_call['yield_pct']:.2f}% (<b>{feat_call['annualized_yield_pct']:.1f}% p.a.</b>)</li>
                                    </ul>
                                    <p style="font-size: 0.8rem; color: #9ca3af; margin-top: 0.8rem; line-height: 1.3;">
                                        <i>Erklärung: Sie verkaufen die Option und nehmen ${feat_call['bid']*100:.2f} Prämie ein. Steigt {sel_symbol} bis zum {selected_expiry} nicht über ${feat_call['strike']:.2f}, behalten Sie die volle Prämie. Falls Sie die Aktie besitzen, wird diese bei einem Kursanstieg über ${feat_call['strike']:.2f} zu diesem Preis verkauft.</i>
                                    </p>
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                st.info("Keine passenden Call-Optionen gefunden.")
                                
                        # Interactive Option Chain Tables
                        st.markdown("<br>#### 📋 Vollständige Optionskette (Out-of-the-Money)")
                        
                        enriched_puts = build_option_screener_df(sel_symbol, current_p, chain_data["puts"], days_to_expiry, r_rate, "put")
                        enriched_calls = build_option_screener_df(sel_symbol, current_p, chain_data["calls"], days_to_expiry, r_rate, "call")
                        
                        tab_puts_det, tab_calls_det = st.tabs(["🟢 Put-Optionen (Stillhalter-Puts)", "🔴 Call-Optionen (Covered Calls)"])
                        
                        format_dict = {
                            "strike": "${:.2f}",
                            "bid": "${:.2f}",
                            "ask": "${:.2f}",
                            "mid": "${:.2f}",
                            "distance_pct": "{:.1f}%",
                            "impliedVolatility": "{:.1f}%",
                            "delta": "{:.2f}",
                            "prob_otm_pct": "{:.1f}%",
                            "yield_pct": "{:.2f}%",
                            "annualized_yield_pct": "{:.1f}%"
                        }
                        
                        cols_to_display = [
                            "strike", "distance_pct", "bid", "ask", "mid", "volume", 
                            "openInterest", "impliedVolatility", "delta", "prob_otm_pct", 
                            "yield_pct", "annualized_yield_pct"
                        ]
                        
                        cols_rename = {
                            "strike": "Strike Price",
                            "distance_pct": "OTM Abstand (%)",
                            "bid": "Bid (Geld)",
                            "ask": "Ask (Brief)",
                            "mid": "Mid Price",
                            "volume": "Volumen",
                            "openInterest": "Open Interest",
                            "impliedVolatility": "IV (%)",
                            "delta": "Delta (BS)",
                            "prob_otm_pct": "Wahrsch. OTM (%)",
                            "yield_pct": "Rendite (%)",
                            "annualized_yield_pct": "Rendite p.a. (%)"
                        }
                        
                        with tab_puts_det:
                            if enriched_puts.empty:
                                st.info("Keine passenden OTM-Puts gefunden.")
                            else:
                                disp_puts = enriched_puts.copy()
                                disp_puts["impliedVolatility"] = disp_puts["impliedVolatility"] * 100.0
                                st.dataframe(
                                    disp_puts[cols_to_display].rename(columns=cols_rename).style.format(format_dict),
                                    use_container_width=True,
                                    hide_index=True
                                )
                                
                        with tab_calls_det:
                            if enriched_calls.empty:
                                st.info("Keine passenden OTM-Calls gefunden.")
                            else:
                                disp_calls = enriched_calls.copy()
                                disp_calls["impliedVolatility"] = disp_calls["impliedVolatility"] * 100.0
                                st.dataframe(
                                    disp_calls[cols_to_display].rename(columns=cols_rename).style.format(format_dict),
                                    use_container_width=True,
                                    hide_index=True
                                )
