import streamlit as st
import pandas as pd
import os
import sys
import io
import yfinance as yf
from screener import run_screener, get_single_ticker_data, calculate_scores
from pdf_analyzer import (
    extract_text_from_pdf,
    search_keywords_in_pdf,
    scan_for_financial_metrics,
    fetch_sec_filings,
    download_and_parse_filing
)
from watchlist_manager import load_watchlist, add_to_watchlist, remove_from_watchlist
from macro_fetcher import fetch_macro_futures, search_polymarket_markets, fetch_company_news, fetch_wsb_trending
from report_generator import generate_pdf_report
from options_ui import render_options_tab
from datetime import datetime
from alpaca_trader import (
    is_alpaca_configured,
    get_account_info,
    get_positions,
    get_open_orders,
    place_order,
    cancel_order,
    cancel_all_orders,
    verify_alpaca_connection,
    get_alpaca_credentials
)

# Reconfigure encoding to avoid Windows encoding crashes
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")

# Set Page Config
st.set_page_config(
    page_title="Fundamental Stock Screener & Watchlist",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Design & Aesthetics
st.markdown("""
<style>
    /* Main container styling */
    .reportview-container {
        background: #0e1117;
    }
    
    /* Header Styling */
    .main-header {
        font-family: 'Outfit', 'Inter', sans-serif;
        font-size: 2.8rem;
        font-weight: 700;
        background: linear-gradient(90deg, #3b82f6, #10b981, #8b5cf6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subheader {
        font-size: 1.1rem;
        color: #9ca3af;
        margin-bottom: 2rem;
    }
    
    /* Card design */
    .metric-card {
        background-color: #1f2937;
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #374151;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        transition: transform 0.2s, border-color 0.2s;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: #4b5563;
    }
    
    /* Highlight banners */
    .long-banner {
        background-color: rgba(16, 185, 129, 0.1);
        border-left: 5px solid #10b981;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    .short-banner {
        background-color: rgba(239, 68, 68, 0.1);
        border-left: 5px solid #ef4444;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    /* Watchlist banner */
    .wl-banner {
        background-color: rgba(245, 158, 11, 0.1);
        border-left: 5px solid #f59e0b;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    /* Custom buttons */
    .stButton>button {
        background: linear-gradient(90deg, #2563eb, #10b981);
        color: white;
        border: none;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        border-radius: 8px;
        transition: opacity 0.2s;
    }
    
    .stButton>button:hover {
        opacity: 0.9;
    }
</style>
""", unsafe_allow_html=True)

# App Title
st.markdown('<h1 class="main-header">📊 Stock Screener & Watchlist</h1>', unsafe_allow_html=True)
st.markdown('<p class="subheader">Scannen Sie Fundamental-Daten über Yahoo Finance und verwalten Sie Watchlists für Ihr Quantlib Tool</p>', unsafe_allow_html=True)

# Sidebar Configuration
st.sidebar.image("https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&q=80&w=400", use_column_width=True)
st.sidebar.markdown("### ⚙️ Scan-Einstellungen")

# Index Selection
index_choice = st.sidebar.selectbox(
    "Index auswählen",
    ["Dow Jones", "S&P 500", "NASDAQ 100", "Russell 2000"],
    help="Index, dessen Aktien gescreent werden sollen."
)

# Limit sliders
limit_tickers = st.sidebar.slider(
    "Aktien-Limit beim Scannen",
    min_value=5,
    max_value=250,
    value=30,
    step=5,
    help="Begrenzt die Anzahl der geladenen Aktien (Beschleunigt das Testen)."
)

# Expandable Alpaca integration (completely optional)
with st.sidebar.expander("🦙 Alpaca Integration (Optional)", expanded=False):
    st.markdown("<small>Falls Sie Handelsberechtigung/Leihbarkeit über Alpaca filtern möchten:</small>", unsafe_allow_html=True)
    alpaca_key = st.text_input("Alpaca API Key ID", value=os.getenv("ALPACA_API_KEY", ""), type="password")
    alpaca_secret = st.text_input("Alpaca API Secret Key", value=os.getenv("ALPACA_SECRET_KEY", ""), type="password")
    alpaca_url = st.text_input("Alpaca API Base URL", value=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))

    # Update environment variables based on inputs
    if alpaca_key:
        os.environ["ALPACA_API_KEY"] = alpaca_key.strip()
    if alpaca_secret:
        os.environ["ALPACA_SECRET_KEY"] = alpaca_secret.strip()
    if alpaca_url:
        os.environ["ALPACA_BASE_URL"] = alpaca_url.strip()

    # Visual connection status check
    if os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_SECRET_KEY"):
        is_ok, status_msg = verify_alpaca_connection()
        if is_ok:
            st.success(f"🟢 Alpaca {status_msg}")
        else:
            st.error(f"🔴 {status_msg}")

# Trigger scan button
start_scan = st.sidebar.button("🔍 Screener starten")

# Sidebar Macro Section
st.sidebar.markdown("---")
st.sidebar.markdown("### 🌍 Globale Makro-Märkte")
if st.sidebar.button("🔄 Makro-Daten aktualisieren") or "macro_futures_df" not in st.session_state:
    try:
        st.session_state["macro_futures_df"] = fetch_macro_futures()
    except Exception as e:
        pass

if "macro_futures_df" in st.session_state and not st.session_state["macro_futures_df"].empty:
    m_df = st.session_state["macro_futures_df"]
    st.sidebar.dataframe(
        m_df[["Name", "Kurs", "Änderung %"]],
        hide_index=True,
        use_container_width=True
    )

# Initialize Tabs
tab1, tab_wl, tab_opt, tab2, tab_trade, tab_strat, tab3 = st.tabs([
    "🎯 Screener Dashboard", 
    "⭐ Watchlist Manager", 
    "🎫 Options-Screener",
    "📈 Einzelwert-Analyse", 
    "💼 Alpaca Trading",
    "⚡ Strategie-Desk (Option A)",
    "📄 PDF Finanzbericht Analyzer"
])

# ----------------------------------------------------
# TAB 1: SCREENER DASHBOARD
# ----------------------------------------------------
with tab1:
    # Global Macro Indicator Banner
    if "macro_futures_df" in st.session_state and not st.session_state["macro_futures_df"].empty:
        m_df = st.session_state["macro_futures_df"]
        cols_ind = st.columns(4)
        indicators = ["S&P 500 Futures", "Nasdaq 100 Futures", "VIX Volatilitätsindex", "Rohöl Futures (WTI)"]
        for i, ind_name in enumerate(indicators):
            if i < len(cols_ind):
                ind_row = m_df[m_df["Name"] == ind_name]
                if not ind_row.empty:
                    row_data = ind_row.iloc[0]
                    with cols_ind[i]:
                        raw_val = row_data["Raw_Change_Pct"]
                        is_positive = raw_val >= 0
                        color_symbol = "🟢" if is_positive else "🔴"
                        if "VIX" in ind_name:
                            color_symbol = "🟢" if not is_positive else "🔴"
                        st.markdown(f"""
                        <div style="background-color: #1f2937; border-radius: 8px; padding: 0.8rem; border: 1px solid #374151; text-align: center;">
                            <span style="font-size: 0.8rem; color: #9ca3af;">{ind_name}</span>
                            <h4 style="margin: 0.2rem 0; color: #f3f4f6;">{row_data["Kurs"]}</h4>
                            <span style="font-size: 0.8rem;">{color_symbol} {row_data["Änderung %"]}</span>
                        </div>
                        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    if start_scan:
        st.markdown(f"### Scanne {limit_tickers} Aktien aus dem **{index_choice}**...")
        
        # Loader spinner
        with st.spinner("Lade Fundamentaldaten von Yahoo Finance. Bitte warten..."):
            try:
                # Run the core screener
                df_results = run_screener(index_name=index_choice, limit=limit_tickers, max_workers=15)
                
                # Fetch WSB trending data
                try:
                    wsb_data = fetch_wsb_trending()
                    st.session_state["wsb_data"] = wsb_data
                except Exception:
                    st.session_state["wsb_data"] = {}
                
                if df_results.empty:
                    st.error("Es konnten keine Daten geladen werden. Bitte versuchen Sie es erneut.")
                else:
                    # Save results to session state
                    st.session_state["screener_results"] = df_results
                    st.success("Screener-Lauf erfolgreich abgeschlossen!")
            except Exception as e:
                st.error(f"Fehler bei der Ausführung des Screeners: {e}")

    # Display results if in session state
    if "screener_results" in st.session_state:
        df = st.session_state["screener_results"]
        wsb_dict = st.session_state.get("wsb_data", {})
        
        # High Level Metric Cards
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <span style="font-size: 0.9rem; color: #9ca3af;">Gescannte Aktien</span>
                <h2 style="margin: 0.5rem 0; color: #3b82f6;">{len(df)}</h2>
                <span style="font-size: 0.8rem; color: #10b981;">{index_choice}</span>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            avg_pe = df["PE"].mean()
            st.markdown(f"""
            <div class="metric-card">
                <span style="font-size: 0.9rem; color: #9ca3af;">Durchschnitts-KGV</span>
                <h2 style="margin: 0.5rem 0; color: #10b981;">{f"{avg_pe:.1f}" if not pd.isna(avg_pe) else "N/A"}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">({index_choice} Schnitt)</span>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            # Count positive earnings vs negative
            pos_earnings = (df["PE"] > 0).sum()
            st.markdown(f"""
            <div class="metric-card">
                <span style="font-size: 0.9rem; color: #9ca3af;">Profitabel (Pos. EPS)</span>
                <h2 style="margin: 0.5rem 0; color: #8b5cf6;">{pos_earnings}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">({(pos_earnings/len(df)*100):.1f}% der Aktien)</span>
            </div>
            """, unsafe_allow_html=True)
        with col4:
            # High long scores
            high_long = (df["LongScore"] >= 4).sum()
            st.markdown(f"""
            <div class="metric-card">
                <span style="font-size: 0.9rem; color: #9ca3af;">Top-Long Kandidaten</span>
                <h2 style="margin: 0.5rem 0; color: #f59e0b;">{high_long}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">(Score >= 4)</span>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Side-by-side Top Candidates
        col_long, col_short = st.columns(2)
        
        with col_long:
            st.markdown('<div class="long-banner"><h3>🟢 Top Long Kandidaten (Qualität & Value)</h3></div>', unsafe_allow_html=True)
            long_df = df.sort_values(by=["LongScore", "PE"], ascending=[False, True])
            st.dataframe(
                long_df[["Symbol", "Company", "LongScore", "PE", "DebtToEquity", "CurrentRatio", "ROE"]].head(10),
                use_container_width=True
            )
            
        with col_short:
            st.markdown('<div class="short-banner"><h3>🔴 Top Short Kandidaten (Distress & Cash-Burn)</h3></div>', unsafe_allow_html=True)
            short_df = df.sort_values(by=["ShortScore", "CurrentRatio"], ascending=[False, True])
            
            # Format short interest and add squeeze risk indicator
            short_df_display = short_df.copy()
            if "ShortInterestPercent" in short_df_display.columns:
                short_df_display["Short Interest"] = short_df_display["ShortInterestPercent"].apply(
                    lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
                )
                def determine_risk(row_item):
                    val = row_item.get("ShortInterestPercent")
                    symbol = row_item.get("Symbol")
                    is_wsb_trending = symbol in wsb_dict
                    
                    if pd.isna(val):
                        if is_wsb_trending:
                            return "⚡ MITTEL (WSB aktiv)"
                        return "N/A"
                    # High short interest + WSB trending = EXTREMELY HIGH SQUEEZE RISK!
                    if val >= 0.15 and is_wsb_trending:
                        return "🚨 EXTREM (Squeeze! WSB-Trend!)"
                    if val >= 0.15:
                        return "⚠️ HOCH (Squeeze-Gefahr!)"
                    if is_wsb_trending or val >= 0.08:
                        return "⚡ MITTEL (WSB aktiv)" if is_wsb_trending else "⚡ MITTEL"
                    return "🟢 GERING"
                
                short_df_display["Squeeze-Risiko"] = short_df_display.apply(determine_risk, axis=1)
                short_df_display["WSB Mentions"] = short_df_display["Symbol"].apply(lambda s: wsb_dict.get(s, {}).get("mentions", 0))
                cols_to_show = ["Symbol", "Company", "ShortScore", "Short Interest", "WSB Mentions", "Squeeze-Risiko", "PE", "DebtToEquity", "CurrentRatio", "FCF"]
            else:
                cols_to_show = ["Symbol", "Company", "ShortScore", "PE", "DebtToEquity", "CurrentRatio", "FCF"]
                
            st.dataframe(
                short_df_display[cols_to_show].head(10),
                use_container_width=True
            )
            
        # Detailed Raw Data Table
        st.markdown("### 📋 Alle gescreenten Aktien im Detail")
        
        # Search & Filter
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            search_query = st.text_input("Nach Symbol oder Firma suchen", "")
        with filter_col2:
            sector_choices = ["Alle"] + sorted(df["Sector"].dropna().unique().tolist())
            sector_choice = st.selectbox("Sektor filtern", sector_choices)
            
        filtered_df = df.copy()
        if wsb_dict:
            filtered_df["WSB-Mentions"] = filtered_df["Symbol"].apply(lambda s: wsb_dict.get(s, {}).get("mentions", 0))
            filtered_df["WSB-Rank"] = filtered_df["Symbol"].apply(lambda s: wsb_dict.get(s, {}).get("rank", "N/A"))
            filtered_df["WSB-Trending"] = filtered_df["WSB-Rank"].apply(lambda r: "🔥 JA" if r != "N/A" else "🟢 NEIN")
        if search_query:
            filtered_df = filtered_df[
                filtered_df["Symbol"].str.contains(search_query, case=False) | 
                filtered_df["Company"].str.contains(search_query, case=False)
            ]
        if sector_choice != "Alle":
            filtered_df = filtered_df[filtered_df["Sector"] == sector_choice]
            
        st.dataframe(filtered_df, use_container_width=True)
        
        # Watchlist actions
        st.markdown("---")
        st.markdown("### ⭐ Aktien zur Watchlist hinzufügen")
        
        wl_col1, wl_col2 = st.columns([3, 1])
        with wl_col1:
            add_symbols = st.multiselect(
                "Wählen Sie Ticker zum Hinzufügen aus:",
                options=sorted(filtered_df["Symbol"].tolist()),
                help="Wählen Sie Ticker aus der Liste aus, um sie in Ihre Watchlist aufzunehmen."
            )
        with wl_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Hinzufügen") and add_symbols:
                added_count = 0
                for s in add_symbols:
                    if add_to_watchlist(s):
                        added_count += 1
                if added_count > 0:
                    st.success(f"{added_count} neue Aktie(n) zur Watchlist hinzugefügt!")
                else:
                    st.warning("Ausgewählte Aktie(n) sind bereits in der Watchlist.")
        
        # CSV and Excel Downloads
        st.markdown("<br>", unsafe_allow_html=True)
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Gesamtes Screen-Ergebnis als CSV herunterladen",
            data=csv,
            file_name=f"screener_{index_choice.replace(' ', '_').lower()}.csv",
            mime="text/csv"
        )
    else:
        st.info("Bitte klicken Sie in der linken Seitenleiste auf **Screener starten**, um Fundamental-Daten zu laden.")

# ----------------------------------------------------
# TAB WL: WATCHLIST MANAGER
# ----------------------------------------------------
with tab_wl:
    st.markdown('<div class="wl-banner"><h2>⭐ Watchlist Manager (für Quantlib)</h2></div>', unsafe_allow_html=True)
    st.markdown("Verwalten Sie Ihre Watchlist und exportieren Sie die Daten strukturiert für Ihr **Quantlib Tool**.")
    
    watchlist_tickers = load_watchlist()
    
    if not watchlist_tickers:
        st.info("Ihre Watchlist ist zurzeit leer. Scannen Sie Indizes im **Screener Dashboard** und fügen Sie dort Aktien hinzu.")
    else:
        st.markdown(f"Aktuelle Watchlist enthält **{len(watchlist_tickers)}** Aktien: `{', '.join(watchlist_tickers)}`")
        
        # Watchlist refresh trigger
        load_wl_data = st.button("🔄 Watchlist-Fundamental-Daten abrufen/aktualisieren")
        
        if load_wl_data or "watchlist_data_cache" in st.session_state:
            # Only download if triggered or not in cache
            if load_wl_data or "watchlist_data_cache" not in st.session_state:
                with st.spinner("Lade Fundamental-Daten für Watchlist-Aktien herunter..."):
                    results = []
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        futures = {
                            executor.submit(get_single_ticker_data, ticker, ticker, "Watchlist", {}): ticker
                            for ticker in watchlist_tickers
                        }
                        for future in as_completed(futures):
                            try:
                                data = future.result()
                                results.append(data)
                            except Exception as e:
                                pass
                    wl_df = pd.DataFrame(results)
                    if not wl_df.empty:
                        wl_df = calculate_scores(wl_df)
                        # Reorder columns to put scores first
                        cols = ["Symbol", "Company", "LongScore", "ShortScore", "Price", "Sector", "Industry"]
                        other_cols = [c for c in wl_df.columns if c not in cols and c not in ["Tradable", "Shortable", "EasyToBorrow"]]
                        wl_df = wl_df[cols + other_cols]
                        st.session_state["watchlist_data_cache"] = wl_df
            
            if "watchlist_data_cache" in st.session_state:
                wl_cached_df = st.session_state["watchlist_data_cache"]
                # Sync cache with current watchlist (if items were removed)
                wl_cached_df = wl_cached_df[wl_cached_df["Symbol"].isin(watchlist_tickers)]
                
                st.dataframe(wl_cached_df, use_container_width=True)
                
                # Exporters
                st.markdown("### 📥 Watchlist exportieren")
                exp_col1, exp_col2 = st.columns(2)
                with exp_col1:
                    # Full data CSV
                    csv_full = wl_cached_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "📥 Komplette Watchlist-Fundamentaldaten (CSV)",
                        data=csv_full,
                        file_name="watchlist_fundamentals.csv",
                        mime="text/csv",
                        help="Exportiert alle Fundamental-Kennzahlen inklusive Long/Short-Scores."
                    )
                with exp_col2:
                    # Simple ticker list CSV (perfect for Quantlib input)
                    ticker_csv = "\n".join(watchlist_tickers).encode('utf-8')
                    st.download_button(
                        "📥 Reines Ticker-Verzeichnis für Quantlib (CSV)",
                        data=ticker_csv,
                        file_name="quantlib_watchlist_tickers.csv",
                        mime="text/plain",
                        help="Exportiert nur die Ticker-Symbole (Zeile für Zeile). Ideal zum Einlesen in quantitative Skripte."
                    )
        
        # Remove tickers section
        st.markdown("---")
        st.markdown("### ❌ Aktien aus Watchlist entfernen")
        to_remove = st.multiselect(
            "Wählen Sie zu entfernende Aktien aus:",
            options=watchlist_tickers
        )
        if st.button("❌ Ausgewählte entfernen") and to_remove:
            for t in to_remove:
                remove_from_watchlist(t)
            # Clean cache if present
            if "watchlist_data_cache" in st.session_state:
                st.session_state["watchlist_data_cache"] = st.session_state["watchlist_data_cache"][
                    ~st.session_state["watchlist_data_cache"]["Symbol"].isin(to_remove)
                ]
            st.success(f"{len(to_remove)} Aktie(n) erfolgreich entfernt.")
            st.rerun()
            
        # Import watchlist
        st.markdown("---")
        st.markdown("### 📥 Watchlist importieren")
        uploaded_wl = st.file_uploader(
            "Laden Sie eine Ticker-Liste (.txt oder .csv) hoch (Zeilen- oder Komma-separiert):",
            type=["txt", "csv"],
            key="watchlist_uploader"
        )
        if uploaded_wl is not None:
            content_bytes = uploaded_wl.read()
            content_str = content_bytes.decode("utf-8")
            # Split by comma or newline
            imported_tickers = [line.strip().upper() for line in content_str.replace(",", "\n").split("\n") if line.strip()]
            added = 0
            for t in imported_tickers:
                if add_to_watchlist(t):
                    added += 1
            if added > 0:
                st.success(f"{added} Ticker erfolgreich aus Datei importiert!")
                st.rerun()
            else:
                st.warning("Keine neuen Ticker importiert (bereits in der Liste vorhanden).")


# ----------------------------------------------------
# TAB OPT: OPTIONS SCREENER
# ----------------------------------------------------
with tab_opt:
    render_options_tab(get_single_ticker_data, calculate_scores)


# ----------------------------------------------------
# TAB 2: INDIVIDUAL STOCK ANALYZER
# ----------------------------------------------------
with tab2:
    st.markdown("### 📈 Detaillierte Einzelwert-Analyse")
    
    # Auto-fill suggestions from screener or watchlist
    available_symbols = set()
    if "screener_results" in st.session_state:
        available_symbols.update(st.session_state["screener_results"]["Symbol"].tolist())
    available_symbols.update(watchlist_tickers)
    # Option 2: CLO-ETFs
    available_symbols.update(["JAAA", "JBBB", "CLOI", "RAAA", "RAAR"])
    
    search_symbol = st.selectbox(
        "Wählen Sie ein Symbol aus Ihren aktiven Scans/Watchlists:",
        options=[""] + sorted(list(available_symbols)),
        index=0
    )
    
    manual_symbol = st.text_input("Oder geben Sie manuell ein US-Ticker-Symbol ein (z.B. TSLA):", value="")
    
    target_symbol = manual_symbol.strip().upper() if manual_symbol else search_symbol
    
    if target_symbol:
        with st.spinner(f"Lade Fundamentaldaten für {target_symbol}..."):
            try:
                # Load yfinance Ticker details
                ticker = yf.Ticker(target_symbol)
                info = ticker.info
                
                if info and len(info) > 5:
                    company_name = info.get("longName", target_symbol)
                    
                    st.markdown(f"## {company_name} ({target_symbol})")
                    st.markdown(f"**Sektor:** {info.get('sector', 'N/A')} | **Branche:** {info.get('industry', 'N/A')}")
                    
                    # Quick action to add/remove watchlist
                    if target_symbol in watchlist_tickers:
                        if st.button("⭐ Aus Watchlist entfernen"):
                            remove_from_watchlist(target_symbol)
                            st.success(f"{target_symbol} aus der Watchlist entfernt.")
                            st.rerun()
                    else:
                        if st.button("⭐ Zur Watchlist hinzufügen"):
                            add_to_watchlist(target_symbol)
                            st.success(f"{target_symbol} zur Watchlist hinzugefügt.")
                            st.rerun()
                    
                    # Squeeze risk calculation for detailed view
                    short_float = info.get('shortPercentOfFloat')
                    if short_float is not None:
                        sf_str = f"{short_float*100:.2f}%"
                        if short_float >= 0.15:
                            squeeze_risk = "⚠️ HOCH (Squeeze-Gefahr!)"
                        elif short_float >= 0.08:
                            squeeze_risk = "⚡ MITTEL"
                        else:
                            squeeze_risk = "🟢 GERING"
                    else:
                        sf_str = "N/A"
                        squeeze_risk = "N/A"
                    
                    beta = info.get('beta')
                    beta_str = f"{beta:.2f}" if beta is not None else "N/A"

                    is_etf = (info.get("quoteType") == "ETF") or (target_symbol in ["JAAA", "JBBB", "CLOI", "RAAA", "RAAR"])
                    
                    # Layout card metrics
                    col1, col2, col3 = st.columns(3)
                    if is_etf:
                        with col1:
                            st.metric("Aktueller Kurs", f"${info.get('currentPrice', info.get('previousClose', 0.0)):.2f}")
                            st.metric("NAV (Nettoinventarwert)", f"${info.get('navPrice', 0.0):.2f}" if info.get('navPrice') else "N/A")
                            st.metric("Dividendenrendite (Yield)", f"{(info.get('yield', 0)*100):.2f}%" if info.get('yield') else "N/A")
                        with col2:
                            st.metric("Kostenquote (Expense Ratio)", f"{info.get('netExpenseRatio', 'N/A')}%" if info.get('netExpenseRatio') is not None else "N/A")
                            assets_val = info.get('totalAssets') or info.get('netAssets')
                            st.metric("Fondsvolumen (Assets)", f"${assets_val:,}" if assets_val else "N/A")
                            st.metric("Fonds-Kategorie", info.get('category', 'N/A'))
                        with col3:
                            st.metric("Fonds-Anbieter (Family)", info.get('fundFamily', 'N/A'))
                            st.metric("Beta (3 Jahre)", f"{info.get('beta3Year', 'N/A')}")
                            st.metric("YTD Performance", f"{(info.get('ytdReturn', 0)*100):.2f}%" if info.get('ytdReturn') else "N/A")
                    else:
                        with col1:
                            st.metric("Aktueller Kurs", f"${info.get('currentPrice', info.get('previousClose', 0.0)):.2f}")
                            st.metric("KGV (P/E)", f"{info.get('trailingPE', 'N/A')}")
                            st.metric("KGV Vorwärts (Forward P/E)", f"{info.get('forwardPE', 'N/A')}")
                            st.metric("Short Interest", sf_str)
                        with col2:
                            st.metric("KBV (P/B)", f"{info.get('priceToBook', 'N/A')}")
                            de_ratio = info.get("debtToEquity")
                            st.metric("Debt-to-Equity", f"{de_ratio/100:.2f}" if de_ratio is not None else "N/A")
                            st.metric("Current Ratio", f"{info.get('currentRatio', 'N/A')}")
                            st.metric("Squeeze-Risiko", squeeze_risk)
                        with col3:
                            st.metric("Free Cash Flow", f"${info.get('freeCashflow', 0):,}" if info.get('freeCashflow') else "N/A")
                            st.metric("ROE", f"{(info.get('returnOnEquity', 0)*100):.2f}%" if info.get('returnOnEquity') else "N/A")
                            st.metric("Umsatzwachstum (YoY)", f"{(info.get('revenueGrowth', 0)*100):.2f}%" if info.get('revenueGrowth') else "N/A")
                            st.metric("Beta-Faktor (Risiko)", beta_str)
                    
                    # --- ALPACA QUICK TRADE INTERFACE ---
                    if is_alpaca_configured():
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown('<div style="background-color: #1f2937; border-radius: 12px; padding: 1.5rem; border: 1px solid #374151;">'
                                    '<h3 style="margin-top: 0; color: #3b82f6;">🦙 Alpaca Schnell-Handel</h3>'
                                    'Handeln Sie diesen Wert direkt über Ihr Alpaca-Konto.</div>', unsafe_allow_html=True)
                        
                        trade_col1, trade_col2, trade_col3 = st.columns([1, 1, 2])
                        with trade_col1:
                            trade_qty = st.number_input(
                                "Stückzahl", 
                                min_value=0.01, 
                                value=1.0, 
                                step=1.0, 
                                key=f"trade_qty_{target_symbol}"
                            )
                        with trade_col2:
                            trade_type = st.selectbox(
                                "Order-Typ", 
                                ["Market", "Limit"], 
                                key=f"trade_type_{target_symbol}"
                            )
                            trade_limit_price = None
                            if trade_type == "Limit":
                                current_p = info.get('currentPrice') or info.get('previousClose', 0.0)
                                trade_limit_price = st.number_input(
                                    "Limit-Preis ($)", 
                                    min_value=0.01, 
                                    value=float(current_p) if current_p else 10.0, 
                                    step=0.01, 
                                    key=f"trade_limit_{target_symbol}"
                                )
                        with trade_col3:
                            st.markdown("<br>", unsafe_allow_html=True)
                            buy_btn, sell_btn = st.columns(2)
                            with buy_btn:
                                if st.button("🟢 Kaufen (Buy)", key=f"buy_btn_action_{target_symbol}", use_container_width=True):
                                    with st.spinner("Übermittle Kauforder..."):
                                        res = place_order(
                                            symbol=target_symbol,
                                            qty=trade_qty,
                                            side="buy",
                                            order_type=trade_type.lower(),
                                            limit_price=trade_limit_price
                                        )
                                        if res.get("status") == "success":
                                            ord_info = res.get("order", {})
                                            st.success(f"Kauforder erfolgreich platziert: {trade_qty} {target_symbol} ({ord_info.get('status')})")
                                        else:
                                            st.error(f"Fehler: {res.get('message')}")
                            with sell_btn:
                                if st.button("🔴 Verkaufen (Sell)", key=f"sell_btn_action_{target_symbol}", use_container_width=True):
                                    with st.spinner("Übermittle Verkaufsorder..."):
                                        res = place_order(
                                            symbol=target_symbol,
                                            qty=trade_qty,
                                            side="sell",
                                            order_type=trade_type.lower(),
                                            limit_price=trade_limit_price
                                        )
                                        if res.get("status") == "success":
                                            ord_info = res.get("order", {})
                                            st.success(f"Verkaufsorder erfolgreich platziert: {trade_qty} {target_symbol} ({ord_info.get('status')})")
                                        else:
                                            st.error(f"Fehler: {res.get('message')}")
                        st.markdown("---")
                        
                    # WSB Sentiment Section
                    st.markdown("### 🦍 WallStreetBets (Reddit) Sentiment")
                    try:
                        wsb_data_current = fetch_wsb_trending()
                        ticker_wsb = wsb_data_current.get(target_symbol)
                    except Exception:
                        ticker_wsb = None
                        
                    if ticker_wsb:
                        st.markdown(f"""
                        <div style="background-color: rgba(239, 68, 68, 0.15); border-left: 5px solid #ef4444; padding: 1.2rem; border-radius: 8px; margin-bottom: 1.5rem;">
                            <h4 style="margin: 0 0 0.5rem 0; color: #ef4444;">🔥 WallStreetBets Trend-Warnung!</h4>
                            <p style="margin: 0.2rem 0; font-size: 1rem; color: #f3f4f6;">
                                <b>{target_symbol}</b> ist zurzeit ein aktiver <b>Hype-Wert</b> auf r/wallstreetbets!
                            </p>
                            <ul style="margin: 0.5rem 0 0 0; padding-left: 1.2rem; color: #e5e7eb;">
                                <li><b>WSB-Rang:</b> Platz {ticker_wsb['rank']} der meistdiskutierten Aktien</li>
                                <li><b>Erwähnungen (Mentions):</b> {ticker_wsb['mentions']} in den letzten 24h</li>
                                <li><b>Upvotes gesamt:</b> {ticker_wsb['upvotes']}</li>
                                <li><b>Squeeze-Gefahr:</b> Extrem hoch, falls das Short-Interest ebenfalls hoch ist!</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background-color: rgba(16, 185, 129, 0.1); border-left: 5px solid #10b981; padding: 1rem; border-radius: 6px; margin-bottom: 1.5rem;">
                            <span style="color: #10b981; font-weight: bold;">🟢 Keine Hype-Aktivität</span><br>
                            <span style="font-size: 0.9rem; color: #9ca3af;">Dieser Ticker ist zurzeit nicht in den Top-Trends auf r/wallstreetbets gelistet. Geringes Risiko eines retail-getriebenen Short Squeezes.</span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                    # Detailed Information Box
                    st.markdown("### 📝 Unternehmensbeschreibung")
                    st.write(info.get("longBusinessSummary", "Keine Beschreibung verfügbar."))
                    
                    st.markdown("---")
                    
                    # Split into columns for News and Polymarket
                    news_col, poly_col = st.columns(2)
                    
                    with news_col:
                        st.markdown("### 📰 Aktuelle News (Yahoo Finance)")
                        news_items = fetch_company_news(target_symbol)
                        if not news_items:
                            st.info("Keine aktuellen Nachrichten gefunden.")
                        else:
                            for article in news_items:
                                st.markdown(f"""
                                <div style="background-color: #1f2937; border-radius: 8px; padding: 1rem; border: 1px solid #374151; margin-bottom: 0.8rem;">
                                    <span style="font-size: 0.8rem; color: #9ca3af;">{article['Herausgeber']} | {article['Datum']}</span>
                                    <h5 style="margin: 0.4rem 0;"><a href="{article['Link']}" target="_blank" style="color: #60a5fa; text-decoration: none;">{article['Titel']}</a></h5>
                                </div>
                                """, unsafe_allow_html=True)
                                
                    with poly_col:
                        st.markdown("### 🔮 Polymarket Sentiment")
                        # Suggest a keyword based on company name
                        first_word = company_name.split()[0].replace(",", "").replace(".", "").strip()
                        search_term = st.text_input(
                            "Prognosemärkte durchsuchen (Firma, Makro, Fed etc.):",
                            value=first_word,
                            key=f"poly_search_{target_symbol}"
                        )
                        
                        if search_term:
                            with st.spinner(f"Durchsuche Polymarket für '{search_term}'..."):
                                poly_markets = search_polymarket_markets(search_term)
                                
                            if not poly_markets:
                                st.info("Keine aktiven Prognosemärkte gefunden. Versuchen Sie einen allgemeineren Begriff (z.B. Fed, Inflation, US Economy).")
                            else:
                                for m in poly_markets:
                                    st.markdown(f"""
                                    <div style="background-color: #1f2937; border-radius: 8px; padding: 1rem; border: 1px solid #374151; margin-bottom: 0.8rem;">
                                        <span style="font-size: 0.8rem; color: #f59e0b;">Thema: {m['Thema']} (Volumen: {m['Volumen']})</span>
                                        <h6 style="margin: 0.4rem 0; color: #f3f4f6;">{m['Wettfrage']}</h6>
                                        <p style="margin: 0.2rem 0; font-size: 0.9rem; font-weight: bold; color: #10b981;">{m['Wahrscheinlichkeiten']}</p>
                                        <span style="font-size: 0.8rem; color: #9ca3af;">Endet am: {m['Enddatum']} | <a href="{m['Link']}" target="_blank" style="color: #3b82f6; text-decoration: none;">Auf Polymarket ansehen ↗</a></span>
                                    </div>
                                    """, unsafe_allow_html=True)
                    
                    # --- BLACKGATE CAPITAL PDF REPORT GENERATOR ---
                    st.markdown("---")
                    st.markdown("### 📝 Blackgate Capital Investment Research Memo erstellen")
                    st.markdown("Generieren Sie ein professionelles PDF-Investment-Memo für diese Aktie.")
                    
                    memo_col1, memo_col2 = st.columns(2)
                    with memo_col1:
                        analyst_name = st.text_input("Analysten-Name:", value="Lukas", key=f"analyst_name_{target_symbol}")
                        recommendation = st.selectbox(
                            "Empfehlung / Rating:",
                            ["STRONG BUY", "BUY", "HOLD", "SHORT", "STRONG SHORT"],
                            index=1,
                            key=f"rec_{target_symbol}"
                        )
                    with memo_col2:
                        analyst_notes = st.text_area(
                            "Investment-These & Analysten-Notizen (Fließtext):",
                            height=120,
                            placeholder="Schreiben Sie hier Ihre Begründung (Katalysatoren, Argumente für Kauf/Leerverkauf, Risiken)...",
                            key=f"notes_{target_symbol}"
                        )
                        
                    generate_btn = st.button("📄 PDF Memo generieren", key=f"gen_btn_{target_symbol}")
                    if generate_btn:
                        with st.spinner("Erstelle PDF Investment Research Memo..."):
                            try:
                                news_items = fetch_company_news(target_symbol)
                                first_word = company_name.split()[0].replace(",", "").replace(".", "").strip()
                                poly_items = search_polymarket_markets(first_word)
                                
                                # Recalculate scores for this single company info dict
                                if is_etf:
                                    l_score = 0
                                    s_score = 0
                                else:
                                    # Recalculate scores for this single company info dict
                                    row_dict = {
                                        "PE": info.get("trailingPE"),
                                        "PB": info.get("priceToBook"),
                                        "DebtToEquity": info.get("debtToEquity", 0) / 100.0 if info.get("debtToEquity") is not None else None,
                                        "CurrentRatio": info.get("currentRatio"),
                                        "FCF": info.get("freeCashflow"),
                                        "ROE": info.get("returnOnEquity"),
                                        "RevenueGrowth": info.get("revenueGrowth"),
                                        "NetMargin": info.get("profitMargins"),
                                        "EVToRevenue": info.get("enterpriseToRevenue"),
                                        "ShortInterestPercent": info.get("shortPercentOfFloat")
                                    }
                                    df_scores = calculate_scores(pd.DataFrame([row_dict]))
                                    l_score = int(df_scores["LongScore"].iloc[0])
                                    s_score = int(df_scores["ShortScore"].iloc[0])
                                
                                pdf_stream = generate_pdf_report(
                                    symbol=target_symbol,
                                    company_name=company_name,
                                    info=info,
                                    long_score=l_score,
                                    short_score=s_score,
                                    news=news_items,
                                    polymarket=poly_items,
                                    analyst_notes=analyst_notes,
                                    analyst_name=analyst_name,
                                    recommendation=recommendation,
                                    is_etf=is_etf
                                )
                                
                                st.session_state[f"pdf_stream_{target_symbol}"] = pdf_stream.getvalue()
                                st.success("PDF erfolgreich generiert! Klicken Sie unten auf Herunterladen.")
                            except Exception as e:
                                st.error(f"Fehler bei der PDF-Generierung: {e}")
                                
                    if f"pdf_stream_{target_symbol}" in st.session_state:
                        st.download_button(
                            label="📥 PDF Investment Memo herunterladen",
                            data=st.session_state[f"pdf_stream_{target_symbol}"],
                            file_name=f"Blackgate_Research_Memo_{target_symbol}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            key=f"dl_btn_{target_symbol}"
                        )
                else:
                    st.error(f"Keine ausreichenden Daten für Ticker {target_symbol} gefunden. Bitte Ticker prüfen.")
            except Exception as e:
                st.error(f"Fehler beim Abrufen der Einzelwertdaten: {e}")

# ----------------------------------------------------
# TAB TRADE: ALPACA TRADING PORTFOLIO & ORDERS
# ----------------------------------------------------
with tab_trade:
    st.markdown('<div class="wl-banner"><h2>💼 Alpaca Portfolio & Trading Desk</h2></div>', unsafe_allow_html=True)
    
    # Option 2: CLO-ETF Quick Selector
    st.markdown("### 🏷️ CLO-ETF Schnell-Auswahl (Option 2)")
    st.markdown("<small>Wähle einen der CLO-ETFs aus, um ihn direkt im Trading Desk (rechts) zu laden und zu handeln:</small>", unsafe_allow_html=True)
    clo_cols = st.columns(5)
    clo_etfs = [
        ("JAAA", "Janus Henderson AAA CLO ETF"),
        ("JBBB", "Janus Henderson B-BBB CLO ETF"),
        ("CLOI", "VanEck CLO ETF"),
        ("RAAA", "Reckoner Yield Enhanced AAA CLO ETF"),
        ("RAAR", "Reckoner Yield Enhanced AAA CLO Reinvesting ETF")
    ]
    for i, (symbol, name) in enumerate(clo_etfs):
        with clo_cols[i]:
            if st.button(f"Trade {symbol}", key=f"trade_clo_btn_{symbol}", help=name, use_container_width=True):
                st.session_state["trading_desk_symbol"] = symbol
                st.rerun()
    st.markdown("---")
    
    if not is_alpaca_configured():
        st.warning("⚠️ Alpaca API-Schlüssel sind nicht konfiguriert.")
        st.markdown("""
        Um Trading zu aktivieren, tragen Sie bitte Ihre **Alpaca API Keys** in der linken Seitenleiste unter **Alpaca Integration** ein oder hinterlegen Sie diese in der `.env`-Datei:
        ```env
        ALPACA_API_KEY=dein_key_id
        ALPACA_SECRET_KEY=dein_secret_key
        ALPACA_BASE_URL=https://paper-api.alpaca.markets
        ```
        *Hinweis: Verwenden Sie für Tests immer Ihre **Paper Trading Keys**, um echtes Geld zu schützen!*
        """)
    else:
        # Load account information
        with st.spinner("Lade Alpaca-Kontodaten..."):
            acc = get_account_info()
            positions = get_positions()
            open_orders = get_open_orders()
            
        if not acc:
            st.error("Fehler beim Abrufen der Alpaca-Kontodaten. Bitte überprüfen Sie Ihre API-Schlüssel.")
        else:
            # Styled metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <span style="font-size: 0.9rem; color: #9ca3af;">Portfolio-Wert (Equity)</span>
                    <h2 style="margin: 0.5rem 0; color: #3b82f6;">${float(acc.get('equity', 0)):,.2f}</h2>
                    <span style="font-size: 0.8rem; color: #9ca3af;">Konto-Status: {acc.get('status', 'ACTIVE')}</span>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.markdown(f"""
                <div class="metric-card">
                    <span style="font-size: 0.9rem; color: #9ca3af;">Freies Bargeld (Cash)</span>
                    <h2 style="margin: 0.5rem 0; color: #10b981;">${float(acc.get('cash', 0)):,.2f}</h2>
                    <span style="font-size: 0.8rem; color: #9ca3af;">Unverplantes Kapital</span>
                </div>
                """, unsafe_allow_html=True)
            with col3:
                st.markdown(f"""
                <div class="metric-card">
                    <span style="font-size: 0.9rem; color: #9ca3af;">Kaufkraft (Buying Power)</span>
                    <h2 style="margin: 0.5rem 0; color: #8b5cf6;">${float(acc.get('buying_power', 0)):,.2f}</h2>
                    <span style="font-size: 0.8rem; color: #9ca3af;">Hebel-Kaufkraft</span>
                </div>
                """, unsafe_allow_html=True)
            with col4:
                api_key, _, base_url = get_alpaca_credentials()
                account_mode = "LIVE" if "live" in base_url.lower() else "PAPER"
                st.markdown(f"""
                <div class="metric-card">
                    <span style="font-size: 0.9rem; color: #9ca3af;">Handels-Modus</span>
                    <h2 style="margin: 0.5rem 0; color: #f59e0b;">{account_mode}</h2>
                    <span style="font-size: 0.8rem; color: #9ca3af;">Währung: {acc.get('currency', 'USD')}</span>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Divide page into layout: Left side Positions & Orders, Right side Trading Desk
            pos_col, order_desk_col = st.columns([3, 2])
            
            with pos_col:
                st.markdown("### 📈 Offene Positionen")
                if not positions:
                    st.info("Keine offenen Positionen in deinem Alpaca-Portfolio.")
                else:
                    pos_list = []
                    for p in positions:
                        symbol = p.get('symbol')
                        qty = float(p.get('qty', 0))
                        market_value = float(p.get('market_value', 0))
                        cost_basis = float(p.get('cost_basis', 0))
                        avg_entry = float(p.get('avg_entry_price', 0))
                        current_price = float(p.get('current_price', 0))
                        unrealized_pl = float(p.get('unrealized_pl', 0))
                        unrealized_pl_pct = float(p.get('unrealized_plpc', 0)) * 100
                        
                        pos_list.append({
                            "Symbol": symbol,
                            "Menge": qty,
                            "Akt. Kurs": f"${current_price:.2f}",
                            "Durchschn. Einstieg": f"${avg_entry:.2f}",
                            "Marktwert": f"${market_value:.2f}",
                            "Kostenbasis": f"${cost_basis:.2f}",
                            "GuV ($)": unrealized_pl,
                            "GuV (%)": f"{unrealized_pl_pct:.2f}%"
                        })
                    
                    df_pos = pd.DataFrame(pos_list)
                    
                    def highlight_pl(val):
                        # Ensure profit/loss has colors
                        if isinstance(val, (int, float)):
                            color = '#10b981' if val >= 0 else '#ef4444'
                            return f'color: {color}; font-weight: bold;'
                        return ''
                    
                    st.dataframe(
                        df_pos.style.map(highlight_pl, subset=['GuV ($)']),
                        use_container_width=True,
                        hide_index=True
                    )
                
                st.markdown("### ⏳ Offene Orders")
                if not open_orders:
                    st.info("Keine ausstehenden (offenen) Orders.")
                else:
                    order_list = []
                    for o in open_orders:
                        order_list.append({
                            "Symbol": o.get('symbol'),
                            "Aktion": o.get('side').upper(),
                            "Typ": o.get('type').upper(),
                            "Menge": float(o.get('qty', 0)),
                            "Limit-Preis": f"${float(o.get('limit_price', 0)):.2f}" if o.get('limit_price') else "N/A",
                            "TIF": o.get('time_in_force').upper(),
                            "Status": o.get('status').upper(),
                            "Erstellt am": o.get('created_at')[:19].replace('T', ' '),
                            "ID": o.get('id')
                        })
                    
                    df_ord = pd.DataFrame(order_list)
                    st.dataframe(df_ord.drop(columns=["ID"]), use_container_width=True, hide_index=True)
                    
                    # Cancel order form
                    st.markdown("#### Order stornieren")
                    cancel_col1, cancel_col2 = st.columns([3, 1])
                    with cancel_col1:
                        order_to_cancel = st.selectbox(
                            "Wählen Sie eine Order zum Stornieren:",
                            options=[o["ID"] for o in order_list],
                            format_func=lambda x: f"{next(item for item in order_list if item['ID'] == x)['Aktion']} {next(item for item in order_list if item['ID'] == x)['Menge']} {next(item for item in order_list if item['ID'] == x)['Symbol']} (erstellt: {next(item for item in order_list if item['ID'] == x)['Erstellt am']})"
                        )
                    with cancel_col2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("❌ Order abbrechen", use_container_width=True):
                            if cancel_order(order_to_cancel):
                                st.success("Order wurde storniert.")
                                st.rerun()
                            else:
                                st.error("Order konnte nicht storniert werden.")
                                
                    if st.button("🔥 Alle offenen Orders stornieren", use_container_width=True):
                        if cancel_all_orders():
                            st.success("Alle offenen Orders wurden storniert.")
                            st.rerun()
                        else:
                            st.error("Fehler beim Stornieren aller Orders.")
            
            with order_desk_col:
                st.markdown("### 🎛️ Trading Desk")
                
                # Preset symbols from watchlists or portfolio
                suggested_symbols = set()
                suggested_symbols.update([p.get('symbol') for p in positions])
                suggested_symbols.update(watchlist_tickers)
                if "screener_results" in st.session_state:
                    suggested_symbols.update(st.session_state["screener_results"]["Symbol"].tolist())
                # Option 2: CLO-ETFs
                suggested_symbols.update(["JAAA", "JBBB", "CLOI", "RAAA", "RAAR"])
                
                trade_symbol = st.selectbox(
                    "Wertpapier-Symbol",
                    options=sorted(list(suggested_symbols)),
                    key="trading_desk_symbol"
                )
                
                custom_symbol = st.text_input("Anderes Ticker-Symbol eingeben:", "").strip().upper()
                final_trade_symbol = custom_symbol if custom_symbol else trade_symbol
                
                if final_trade_symbol:
                    # Show price estimate via yfinance
                    try:
                        price_ticker = yf.Ticker(final_trade_symbol)
                        current_p = price_ticker.info.get('currentPrice') or price_ticker.info.get('previousClose', 0.0)
                        st.markdown(f"**Geschätzter aktueller Preis:** `${current_p:.2f}` (über Yahoo Finance)")
                    except Exception:
                        current_p = 0.0
                        st.markdown("**Geschätzter aktueller Preis:** `N/A` (yFinance nicht erreichbar)")
                        
                    t_side = st.radio("Transaktionsart", ["Kauf (Buy)", "Verkauf (Sell)"], horizontal=True)
                    t_type = st.selectbox("Order-Typ", ["Market", "Limit"])
                    
                    t_limit_price = None
                    if t_type == "Limit":
                        t_limit_price = st.number_input("Limit Preis ($)", min_value=0.01, value=float(current_p) if current_p else 10.0, step=0.01)
                        
                    t_qty = st.number_input("Stückzahl", min_value=0.01, value=1.0, step=1.0)
                    
                    # Estimate total cost
                    if current_p and t_qty:
                        est_total = current_p * t_qty
                        st.markdown(f"**Geschätzter Gesamtwert:** `${est_total:,.2f}`")
                        
                    # Execute button
                    side_action = "buy" if "Kauf" in t_side else "sell"
                    btn_color = "🟢" if side_action == "buy" else "🔴"
                    
                    if st.button(f"{btn_color} Order an Alpaca übermitteln", use_container_width=True):
                        with st.spinner("Übermittle Order an Alpaca..."):
                            res = place_order(
                                symbol=final_trade_symbol,
                                qty=t_qty,
                                side=side_action,
                                order_type=t_type.lower(),
                                limit_price=t_limit_price
                            )
                            if res.get("status") == "success":
                                ord_data = res.get("order", {})
                                st.success(f"Order erfolgreich übermittelt! ID: {ord_data.get('id', 'N/A')} | Status: {ord_data.get('status', 'N/A')}")
                                st.rerun()
                            else:
                                st.error(f"Fehler beim Übermitteln der Order: {res.get('message')}")


# ----------------------------------------------------
# TAB STRAT: STRATEGY DESK
# ----------------------------------------------------
with tab_strat:
    st.markdown('<div class="wl-banner"><h2>⚡ Blackgate Capital Strategie-Desk (Option A & mehr)</h2></div>', unsafe_allow_html=True)
    st.markdown("Planen und handeln Sie komplexe Optionsstrategien direkt über Ihr Alpaca-Konto. Dieses Desk ermöglicht es Ihnen, vordefinierte Strategien wie den *Synthetischen Short* auf Bonds (Option A) zu strukturieren und auszuführen.")
    
    # Check if Alpaca is configured
    if not is_alpaca_configured():
        st.warning("⚠️ Alpaca API-Schlüssel sind nicht konfiguriert. Sie können Strategien simulieren, aber nicht handeln. Bitte konfigurieren Sie die Schlüssel in der linken Seitenleiste.")
        
    # Strategy selection
    strategy_choice = st.selectbox(
        "Wählen Sie eine Strategie aus:",
        [
            "Option A: Synthetischer Short (Bonds Zinswette)",
            "Covered Call / Buy-Write (Income & Upside)",
            "Cash-Secured Put (Günstiger Einstieg)",
            "Bear Put Spread (Definierter Risiko-Short)"
        ]
    )
    
    # Underlying ticker
    default_ticker = "TLT" if "Option A" in strategy_choice else "AAPL"
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        strat_ticker = st.text_input("Underlying Ticker (z.B. TLT, IEF, AAPL, NVDA):", value=default_ticker, key="strat_ticker_input").strip().upper()
    with col_s2:
        num_contracts = st.number_input("Anzahl Kontrakte (1 Kontrakt = 100 Aktien):", min_value=1, value=1, step=1, key="strat_num_contracts")
        
    # Fetch underlying price and options dates
    underlying_price = 0.0
    expiry_dates = []
    
    if strat_ticker:
        with st.spinner(f"Lade Kursdaten für {strat_ticker}..."):
            try:
                tk = yf.Ticker(strat_ticker)
                info = tk.info
                underlying_price = info.get("currentPrice") or info.get("previousClose") or 0.0
                expiry_dates = list(tk.options)
            except Exception as e:
                st.error(f"Fehler beim Laden von {strat_ticker}: {e}")
                
    if underlying_price > 0:
        st.metric(f"Aktueller Kurs von {strat_ticker}", f"${underlying_price:.2f}")
        
        if not expiry_dates:
            st.error(f"Keine Optionen für {strat_ticker} verfügbar.")
        else:
            col_s3, col_s4 = st.columns(2)
            with col_s3:
                selected_expiry = st.selectbox("Laufzeit (Option Expiration Date):", expiry_dates, key="strat_expiry_select")
            with col_s4:
                # ATM Strike suggestion
                suggested_strike = round(underlying_price)
                strike_price = st.number_input(
                    "Ziel-Strike (ATM / Basispreis):",
                    min_value=0.5,
                    value=float(suggested_strike),
                    step=0.5,
                    help="Der Basispreis für die Hauptkomponente der Strategie.",
                    key="strat_strike_input"
                )
                
            # Expiry details
            today = datetime.now().date()
            expiry_dt = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
            days_to_expiry = max((expiry_dt - today).days, 1)
            st.markdown(f"**Laufzeit:** {selected_expiry} ({days_to_expiry} Tage bis Verfall)")
            
            # Fetch option chain for selected expiry
            if st.button("📊 Optionen simulieren & Preise abrufen", key="strat_simulate_btn"):
                with st.spinner("Lade Optionskette und berechne Preise..."):
                    try:
                        chain = tk.option_chain(selected_expiry)
                        calls_df = chain.calls
                        puts_df = chain.puts
                        
                        # Find ATM / selected strike contracts
                        call_atm = calls_df.iloc[(calls_df['strike'] - strike_price).abs().argsort()[:1]]
                        put_atm = puts_df.iloc[(puts_df['strike'] - strike_price).abs().argsort()[:1]]
                        
                        if call_atm.empty or put_atm.empty:
                            st.error("Der gewählte Strike ist nicht in der Optionskette verfügbar.")
                        else:
                            c_contract = call_atm.iloc[0].to_dict()
                            p_contract = put_atm.iloc[0].to_dict()
                            
                            st.session_state["strat_sim_results"] = {
                                "ticker": strat_ticker,
                                "price": underlying_price,
                                "expiry": selected_expiry,
                                "days": days_to_expiry,
                                "strike": strike_price,
                                "call": c_contract,
                                "put": p_contract,
                                "contracts": num_contracts,
                                "strategy": strategy_choice,
                                "puts_df": puts_df.to_dict(orient="records") # store puts for spread calculation
                            }
                            st.success("Simulation erfolgreich abgeschlossen!")
                    except Exception as e:
                        st.error(f"Fehler beim Laden der Optionskette: {e}")
                        
            # Show simulated details if available
            if "strat_sim_results" in st.session_state:
                sim = st.session_state["strat_sim_results"]
                
                # Check if simulated ticker matches selected ticker to keep it in sync
                if sim["ticker"] == strat_ticker and sim["expiry"] == selected_expiry:
                    st.markdown("### 🔍 Struktur der Optionsstrategie")
                    
                    c_con = sim["call"]
                    p_con = sim["put"]
                    k_val = sim["strike"]
                    cnt = sim["contracts"]
                    
                    c_symbol = c_con.get("contractSymbol", "")
                    p_symbol = p_con.get("contractSymbol", "")
                    
                    c_mid = (c_con.get("bid", 0.0) + c_con.get("ask", 0.0)) / 2.0 or c_con.get("lastPrice", 0.0)
                    p_mid = (p_con.get("bid", 0.0) + p_con.get("ask", 0.0)) / 2.0 or p_con.get("lastPrice", 0.0)
                    
                    legs_data = []
                    
                    if "Option A" in strategy_choice:
                        # Synthetic Short: Long Put + Short Call
                        legs_data = [
                            {
                                "Aktion": "KAUF (Long Put)",
                                "Symbol": p_symbol,
                                "Typ": "Put",
                                "Strike": f"${p_con['strike']:.2f}",
                                "Bid": f"${p_con['bid']:.2f}",
                                "Ask": f"${p_con['ask']:.2f}",
                                "Mitte-Preis": f"${p_mid:.2f}",
                                "Effekt": "Debit (Gezahlte Prämie)",
                                "Kosten/Einnahme": -p_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": p_symbol,
                                    "qty": cnt,
                                    "side": "buy",
                                    "type": "limit",
                                    "limit_price": p_con['ask']
                                }
                            },
                            {
                                "Aktion": "VERKAUF (Short Call)",
                                "Symbol": c_symbol,
                                "Typ": "Call",
                                "Strike": f"${c_con['strike']:.2f}",
                                "Bid": f"${c_con['bid']:.2f}",
                                "Ask": f"${c_con['ask']:.2f}",
                                "Mitte-Preis": f"${c_mid:.2f}",
                                "Effekt": "Credit (Eingenommene Prämie)",
                                "Kosten/Einnahme": c_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": c_symbol,
                                    "qty": cnt,
                                    "side": "sell",
                                    "type": "limit",
                                    "limit_price": c_con['bid']
                                }
                            }
                        ]
                    elif "Covered Call" in strategy_choice:
                        # Covered Call: Long Stock + Short Call
                        legs_data = [
                            {
                                "Aktion": "KAUF (Stock)",
                                "Symbol": strat_ticker,
                                "Typ": "Aktie",
                                "Strike": "N/A",
                                "Bid": "N/A",
                                "Ask": "N/A",
                                "Mitte-Preis": f"${underlying_price:.2f}",
                                "Effekt": "Debit (Kauf Aktien)",
                                "Kosten/Einnahme": -underlying_price * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": strat_ticker,
                                    "qty": cnt * 100,
                                    "side": "buy",
                                    "type": "market",
                                    "limit_price": None
                                }
                            },
                            {
                                "Aktion": "VERKAUF (Short Call)",
                                "Symbol": c_symbol,
                                "Typ": "Call",
                                "Strike": f"${c_con['strike']:.2f}",
                                "Bid": f"${c_con['bid']:.2f}",
                                "Ask": f"${c_con['ask']:.2f}",
                                "Mitte-Preis": f"${c_mid:.2f}",
                                "Effekt": "Credit (Eingenommene Prämie)",
                                "Kosten/Einnahme": c_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": c_symbol,
                                    "qty": cnt,
                                    "side": "sell",
                                    "type": "limit",
                                    "limit_price": c_con['bid']
                                }
                            }
                        ]
                    elif "Cash-Secured Put" in strategy_choice:
                        # Cash-Secured Put: Short Put
                        legs_data = [
                            {
                                "Aktion": "VERKAUF (Short Put)",
                                "Symbol": p_symbol,
                                "Typ": "Put",
                                "Strike": f"${p_con['strike']:.2f}",
                                "Bid": f"${p_con['bid']:.2f}",
                                "Ask": f"${p_con['ask']:.2f}",
                                "Mitte-Preis": f"${p_mid:.2f}",
                                "Effekt": "Credit (Eingenommene Prämie)",
                                "Kosten/Einnahme": p_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": p_symbol,
                                    "qty": cnt,
                                    "side": "sell",
                                    "type": "limit",
                                    "limit_price": p_con['bid']
                                }
                            }
                        ]
                    elif "Bear Put Spread" in strategy_choice:
                        # Bear Put Spread: Long Put ATM + Short Put OTM (e.g. 10% lower)
                        puts_df = pd.DataFrame(sim["puts_df"])
                        otm_strike_target = strike_price * 0.90
                        otm_put = puts_df.iloc[(puts_df['strike'] - otm_strike_target).abs().argsort()[:1]].iloc[0].to_dict()
                        otm_p_symbol = otm_put.get("contractSymbol", "")
                        otm_p_mid = (otm_put.get("bid", 0.0) + otm_put.get("ask", 0.0)) / 2.0 or otm_put.get("lastPrice", 0.0)
                        
                        legs_data = [
                            {
                                "Aktion": "KAUF (Long Put ATM)",
                                "Symbol": p_symbol,
                                "Typ": "Put",
                                "Strike": f"${p_con['strike']:.2f}",
                                "Bid": f"${p_con['bid']:.2f}",
                                "Ask": f"${p_con['ask']:.2f}",
                                "Mitte-Preis": f"${p_mid:.2f}",
                                "Effekt": "Debit (Gezahlte Prämie)",
                                "Kosten/Einnahme": -p_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": p_symbol,
                                    "qty": cnt,
                                    "side": "buy",
                                    "type": "limit",
                                    "limit_price": p_con['ask']
                                }
                            },
                            {
                                "Aktion": "VERKAUF (Short Put OTM)",
                                "Symbol": otm_p_symbol,
                                "Typ": "Put",
                                "Strike": f"${otm_put['strike']:.2f}",
                                "Bid": f"${otm_put['bid']:.2f}",
                                "Ask": f"${otm_put['ask']:.2f}",
                                "Mitte-Preis": f"${otm_p_mid:.2f}",
                                "Effekt": "Credit (Eingenommene Prämie)",
                                "Kosten/Einnahme": otm_p_mid * 100 * cnt,
                                "Alpaca_Action": {
                                    "symbol": otm_p_symbol,
                                    "qty": cnt,
                                    "side": "sell",
                                    "type": "limit",
                                    "limit_price": otm_put['bid']
                                }
                            }
                        ]
                    
                    # Display Table
                    df_legs = pd.DataFrame(legs_data).drop(columns=["Alpaca_Action"])
                    st.table(df_legs)
                    
                    # Calculate Totals
                    total_cash_flow = sum(leg["Kosten/Einnahme"] for leg in legs_data)
                    net_type = "Einnahme (Net Credit)" if total_cash_flow >= 0 else "Kosten (Net Debit)"
                    
                    st.markdown("#### ⚖️ Strategie-Metriken & Zusammenfassung")
                    c_flow_col1, c_flow_col2, c_flow_col3 = st.columns(3)
                    with c_flow_col1:
                        st.metric("Netto Cashflow (Einstieg)", f"${abs(total_cash_flow):,.2f}", delta=net_type, delta_color="normal" if total_cash_flow >= 0 else "inverse")
                    with c_flow_col2:
                        if "Option A" in strategy_choice:
                            st.metric("Gesamt-Delta", "-1.00", help="100% Short-Replikation des Underlyings.")
                        elif "Covered Call" in strategy_choice:
                            st.metric("Gesamt-Delta", "ca. +0.75", help="Aktie (+1.00) minus Call (ca. -0.25)")
                        elif "Cash-Secured Put" in strategy_choice:
                            st.metric("Gesamt-Delta", "ca. +0.20", help="Short Put hat ein positives Delta.")
                        elif "Bear Put Spread" in strategy_choice:
                            st.metric("Gesamt-Delta", "ca. -0.30", help="Differenz der Deltas der Puts.")
                    with c_flow_col3:
                        if "Option A" in strategy_choice:
                            st.metric("Maximales Risiko", "Unbegrenzt", help="Ungedeckelter Call-Short birgt theoretisch unbegrenztes Risiko nach oben. Stop-Loss von 5% über dem Strike einrichten!")
                        elif "Covered Call" in strategy_choice:
                            st.metric("Maximales Risiko", f"${underlying_price * 100 * cnt:,.2f}", help="Maximaler Verlust, falls die Aktie auf 0 fällt.")
                        elif "Cash-Secured Put" in strategy_choice:
                            st.metric("Maximales Risiko", f"${k_val * 100 * cnt:,.2f}", help="Erwerb der Aktie zum Strike-Preis bei Totalverlust.")
                        elif "Bear Put Spread" in strategy_choice:
                            max_spread_loss = abs(total_cash_flow)
                            st.metric("Maximales Risiko (Gedeckelt)", f"${max_spread_loss:,.2f}", help="Begrenzt auf den Net Debit.")
                            
                    # Detailed Strategy Description
                    st.markdown("#### 📝 Trade-Beschreibung & Investment-These")
                    if "Option A" in strategy_choice:
                        st.markdown(f"""
                        **Option A: Synthetischer Short auf US-Anleihen (TLT/IEF)**
                        * **These:** Basierend auf dem Research-Memo `Blackgate_Macro_Memo_Option_A.pdf` zeigen hartnäckige Inflation und steigende US-Staatsverschuldung Aufwärtsdruck auf die Anleiherenditen. Da Anleihekurse mathematisch fallen, wenn die Zinsen steigen, ist der Short-Bond die direkte Wette.
                        * **Mechanik:** Der Kauf des ATM Puts ({p_symbol}) sichert den Kursgewinn bei fallendem Preis. Der zeitgleiche Verkauf des ATM Calls ({c_symbol}) finanziert den Put vollständig (Netto-Einstiegskosten liegen nahe $0.00). 1:1 Partizipation an fallenden Kursen ohne tägliche Borrow-Gebühren (Leihgebühren) oder Short Squeeze Risiken des physischen Leerverkaufs.
                        * **Absicherung (Stop-Loss):** Falls TLT/IEF um mehr als 5% über den Strike-Kurs (${k_val:.2f}) steigt, sollte die Position manuell geschlossen werden, da der ungedeckte Short Call ein unbegrenztes Risiko darstellt.
                        """)
                    elif "Covered Call" in strategy_choice:
                        st.markdown(f"""
                        **Covered Call / Buy-Write**
                        * **These:** Moderate Aufwärtsbewegung oder Seitwärtsphase des Underlyings.
                        * **Mechanik:** Sie erwerben 100 Aktien von {strat_ticker} zum Kurs von ${underlying_price:.2f} und verkaufen zeitgleich eine Call-Option ({c_symbol}) mit Strike ${k_val:.2f}. Die eingenommene Prämie erhöht die Rendite Ihres Aktienbestands.
                        * **Ausgang:** Steigt die Aktie über ${k_val:.2f}, werden Ihre Aktien zum Strike verkauft (Gewinn deckelt bei Strike + Prämie). Bleibt sie darunter, behalten Sie die Aktien und die Prämie.
                        """)
                    elif "Cash-Secured Put" in strategy_choice:
                        st.markdown(f"""
                        **Cash-Secured Put**
                        * **These:** Hohe Qualität der Aktie und Wunsch, zu einem günstigeren Preis einzusteigen.
                        * **Mechanik:** Sie verkaufen eine OTM Put-Option ({p_symbol}) mit Strike ${k_val:.2f}. Sie nehmen sofort die Prämie ein. Fällt die Aktie unter ${k_val:.2f}, kaufen Sie 100 Aktien je Kontrakt zum Strike (Ihr effektiver Einstiegspreis sinkt um die eingenommene Prämie).
                        """)
                    elif "Bear Put Spread" in strategy_choice:
                        st.markdown(f"""
                        **Bear Put Spread**
                        * **These:** Fallende Kurse des Underlyings bei begrenztem Risiko und niedrigeren Einstiegskosten.
                        * **Mechanik:** Sie kaufen den Put ({p_symbol}) und verkaufen einen günstigeren OTM Put. Die Kosten des Trades sinken. 
                        * **Gewinn/Verlust:** Maximaler Verlust ist der Netto-Debit. Maximaler Gewinn ist die Differenz der Strikes abzüglich des Debits.
                        """)
                        
                    # Execution
                    st.markdown("---")
                    st.markdown("### 🚀 Trade ausführen")
                    
                    if not is_alpaca_configured():
                        st.error("Alpaca ist nicht konfiguriert. Ausführung deaktiviert.")
                    else:
                        account_mode = "PAPER"
                        api_key, _, base_url = get_alpaca_credentials()
                        if "live" in base_url.lower():
                            account_mode = "LIVE"
                            st.warning("⚠️ ACHTUNG: Dies ist ein LIVE-Konto. Ein Klick auf den Button führt zu echtem Geldhandel!")
                        else:
                            st.info("🟢 Handel im Alpaca PAPER (Test) Modus.")
                            
                        # Confirm execution checkbox
                        confirm_trade = st.checkbox("Ich bestätige, dass ich diesen Trade auf Alpaca ausführen möchte.", value=False, key="confirm_strat_execution")
                        
                        if st.button("🚀 Strategie-Order an Alpaca senden", key="strat_execute_orders_btn"):
                            if not confirm_trade:
                                st.error("Bitte bestätigen Sie die Ausführung über die Checkbox oben.")
                            else:
                                with st.spinner("Sende Orders an Alpaca..."):
                                    responses = []
                                    success_count = 0
                                    for leg in legs_data:
                                        act = leg["Alpaca_Action"]
                                        res = place_order(
                                            symbol=act["symbol"],
                                            qty=act["qty"],
                                            side=act["side"],
                                            order_type=act["type"],
                                            limit_price=act["limit_price"]
                                        )
                                        responses.append((leg["Aktion"], res))
                                        if res.get("status") == "success":
                                            success_count += 1
                                            
                                    # Show results
                                    if success_count == len(legs_data):
                                        st.success("🔥 Alle Orders der Strategie wurden erfolgreich an Alpaca übermittelt!")
                                    else:
                                        st.warning(f"Einige Orders konnten nicht platziert werden ({success_count}/{len(legs_data)} erfolgreich). Details unten.")
                                        
                                    for title, res in responses:
                                        if res.get("status") == "success":
                                            st.success(f"🟢 **{title}**: Platziert! ID: {res['order']['id']} (Status: {res['order']['status']})")
                                        else:
                                            st.error(f"🔴 **{title}**: Fehler: {res.get('message')}")

# ----------------------------------------------------
# TAB 3: PDF FINANCIAL REPORT ANALYZER
# ----------------------------------------------------
with tab3:
    st.markdown("### 📄 Finanzberichte Einlesen & Analysieren")
    st.markdown("Laden Sie Geschäftsberichte (10-K, 10-Q) automatisch über Yahoo Finance oder laden Sie eine eigene PDF-Datei hoch, um gezielt nach Fundamentaldaten oder Begriffen zu scannen.")
    
    # Selection of source
    report_source = st.radio(
        "Quelle des Finanzberichts",
        ["Yahoo Finance (Automatisch laden)", "Eigene PDF-Datei hochladen (Manuell)"],
        horizontal=True
    )
    
    # Initialize session state variables if they do not exist
    if "pages_data" not in st.session_state:
        st.session_state["pages_data"] = None
    if "loaded_report_name" not in st.session_state:
        st.session_state["loaded_report_name"] = ""
        
    if report_source == "Yahoo Finance (Automatisch laden)":
        st.info("💡 **Hinweis:** SEC-Finanzberichte (10-K, 10-Q) stehen primär für **US-amerikanische Unternehmen** zur Verfügung. Für europäische oder asiatische Aktien (wie z.B. SAP, ASML, BMW) verwenden Sie bitte die manuelle PDF-Upload-Option.")
        
        # Get active symbols from watchlists/screener
        available_symbols = set()
        if "screener_results" in st.session_state:
            available_symbols.update(st.session_state["screener_results"]["Symbol"].tolist())
        available_symbols.update(load_watchlist())
        available_symbols.update(["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]) # some defaults
        
        # Select ticker symbol
        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            selected_symbol = st.selectbox(
                "Wählen Sie ein Symbol aus Ihren Watchlists/Scans:",
                options=sorted(list(available_symbols)),
                key="sec_ticker_select"
            )
        with col_t2:
            manual_symbol = st.text_input("Oder Ticker manuell eingeben (z.B. TSLA):", key="sec_ticker_manual").strip().upper()
            
        ticker_to_load = manual_symbol if manual_symbol else selected_symbol
        
        if ticker_to_load:
            # Dropdown options for report types
            report_type_filter = st.selectbox(
                "Filter für Berichtstyp",
                ["Nur Hauptberichte (10-K / 10-Q)", "Alle Berichte (10-K, 10-Q, 8-K, SD, etc.)"]
            )
            
            # Fetch filings button
            if st.button("🔌 Verfügbare Berichte abrufen"):
                with st.spinner(f"Rufe Berichte für {ticker_to_load} von Yahoo Finance ab..."):
                    filings_list = fetch_sec_filings(ticker_to_load)
                    if filings_list:
                        st.session_state["available_filings"] = filings_list
                        st.session_state["available_filings_ticker"] = ticker_to_load
                        st.success(f"{len(filings_list)} Berichte für {ticker_to_load} gefunden!")
                    else:
                        st.error(f"Keine Berichte für Ticker {ticker_to_load} gefunden. Bitte prüfen Sie die Schreibweise oder laden Sie ein PDF hoch.")
                        if "available_filings" in st.session_state:
                            del st.session_state["available_filings"]
                        
            # Show list of filings if fetched and match current ticker
            if "available_filings" in st.session_state and st.session_state.get("available_filings_ticker") == ticker_to_load:
                filings_list = st.session_state["available_filings"]
                
                # Filter if needed
                if report_type_filter == "Nur Hauptberichte (10-K / 10-Q)":
                    filings_list = [f for f in filings_list if f["type"] in ["10-K", "10-Q"]]
                    
                if not filings_list:
                    st.warning("Keine Berichte entsprechen dem gewählten Filter.")
                else:
                    st.markdown("### 📋 Gefundene Berichte")
                    st.markdown("Sie können Berichte direkt anklicken, um sie im Browser zu lesen, oder unten auswählen, um sie im Analyzer einzulesen:")
                    
                    # Display a table with URLs that can be clicked
                    df_filings = pd.DataFrame([
                        {
                            "Datum": f["date"],
                            "Typ": f["type"],
                            "Titel": f["title"],
                            "Link": f["url"]
                        }
                        for f in filings_list
                    ])
                    
                    st.dataframe(
                        df_filings,
                        column_config={
                            "Link": st.column_config.LinkColumn("Bericht öffnen", display_text="Im Browser öffnen ↗")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    st.markdown("---")
                    st.markdown("### 📥 Bericht im Analyzer laden")
                    
                    # Select report for analyzer
                    report_options = [
                        f"{f['date']} | {f['type']} | {f['title']}" for f in filings_list
                    ]
                    selected_report_str = st.selectbox(
                        "Wählen Sie den zu analysierenden Bericht:",
                        options=report_options,
                        key="sec_report_select_to_analyze"
                    )
                    
                    selected_index = report_options.index(selected_report_str)
                    selected_filing = filings_list[selected_index]
                    
                    if st.button("⚡ Bericht laden & analysieren"):
                        with st.spinner("Lade Bericht herunter und extrahiere Text..."):
                            try:
                                pages_data = download_and_parse_filing(selected_filing["url"])
                                if pages_data:
                                    st.session_state["pages_data"] = pages_data
                                    st.session_state["loaded_report_name"] = f"{ticker_to_load} {selected_filing['type']} ({selected_filing['date']})"
                                    st.success(f"Erfolgreich geladen! {len(pages_data)} Abschnitte eingelesen.")
                                    st.rerun()
                                else:
                                    st.error("Text konnte nicht aus dem Bericht extrahiert werden.")
                            except Exception as e:
                                st.error(f"Fehler beim Herunterladen des Berichts: {e}")
                                
    else: # Eigene PDF-Datei hochladen (Manuell)
        uploaded_file = st.file_uploader("PDF-Finanzbericht hochladen", type="pdf")
        if uploaded_file is not None:
            pdf_id = f"pdf_{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get("loaded_report_name") != pdf_id:
                with st.spinner("Extrahiere Text aus PDF-Seiten..."):
                    try:
                        pdf_bytes = io.BytesIO(uploaded_file.read())
                        pages_data = extract_text_from_pdf(pdf_bytes)
                        if pages_data:
                            st.session_state["pages_data"] = pages_data
                            st.session_state["loaded_report_name"] = pdf_id
                            st.session_state["loaded_report_display_name"] = uploaded_file.name
                            st.success(f"Erfolgreich {len(pages_data)} Seiten eingelesen!")
                            st.rerun()
                        else:
                            st.error("Text konnte nicht extrahiert werden.")
                    except Exception as e:
                        st.error(f"Fehler beim Einlesen des PDFs: {e}")

    # Display report details & analysis tools if pages_data is loaded
    if st.session_state["pages_data"] is not None:
        display_name = st.session_state.get("loaded_report_display_name", st.session_state["loaded_report_name"])
        if display_name.startswith("pdf_"):
            # Clean display name for PDF
            display_name = display_name[4:].rsplit("_", 1)[0]
            
        st.markdown("---")
        st.markdown(f"📊 **Geladener Bericht:** `{display_name}` ({len(st.session_state['pages_data'])} Abschnitte/Seiten)")
        
        # Reset button
        if st.button("🗑️ Bericht zurücksetzen / entfernen"):
            st.session_state["pages_data"] = None
            st.session_state["loaded_report_name"] = ""
            if "loaded_report_display_name" in st.session_state:
                del st.session_state["loaded_report_display_name"]
            st.success("Bericht erfolgreich zurückgesetzt.")
            st.rerun()
            
        # Interactive functions
        analysis_mode = st.radio(
            "Analyse-Modus wählen",
            ["Automatischer Scan nach Schlüsseldaten", "Stichwortsuche (Keywords)"]
        )
        
        pages_data = st.session_state["pages_data"]
        
        # Option 1: Automated Financial Scan
        if analysis_mode == "Automatischer Scan nach Schlüsseldaten":
            st.markdown("### 🔍 Gefundene Finanzzahlen im Bericht")
            st.info("Dieses Tool scannt Zeilen mit Zahlen, die typische Finanzbegriffe wie 'Revenue', 'Net Income', 'Operating Cash Flow' oder 'Debt' enthalten.")
            
            findings = scan_for_financial_metrics(pages_data)
            
            for metric, items in findings.items():
                with st.expander(f"📌 {metric} (Gefundene Treffer: {len(items)})"):
                    if not items:
                        st.write("Keine direkten Treffer gefunden.")
                    else:
                        for item in items:
                            st.markdown(f"**Abschnitt/Seite {item['page']}:** `{item['line']}`")
                            
        # Option 2: Custom Keyword Search
        elif analysis_mode == "Stichwortsuche (Keywords)":
            st.markdown("### 🔑 Stichwortsuche im Bericht")
            
            keyword_input = st.text_input(
                "Geben Sie Suchbegriffe ein (kommagetrennt, z.B. debt, Schulden, risk, Risiko, outlook, Prognose):",
                "debt, Schulden, risk, Risiko, revenue, Umsatz"
            )
            
            keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
            
            if keywords:
                with st.spinner("Durchsuche Bericht..."):
                    matches = search_keywords_in_pdf(pages_data, keywords)
                    
                st.write(f"Insgesamt **{len(matches)} Treffer** für die Begriffe `{keywords}` gefunden:")
                
                # Display matches in a clean table or list
                if matches:
                    matches_df = pd.DataFrame(matches)
                    st.dataframe(matches_df, use_container_width=True)
                    
                    csv_matches = matches_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "📥 Suchergebnisse herunterladen",
                        data=csv_matches,
                        file_name="report_search_results.csv",
                        mime="text/csv"
                    )
                else:
                    st.write("Keine Treffer gefunden.")


