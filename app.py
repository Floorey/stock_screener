import streamlit as st
import pandas as pd
import os
import sys
import io
import yfinance as yf
from screener import run_screener, get_single_ticker_data, calculate_scores
from pdf_analyzer import extract_text_from_pdf, search_keywords_in_pdf, scan_for_financial_metrics
from watchlist_manager import load_watchlist, add_to_watchlist, remove_from_watchlist
from macro_fetcher import fetch_macro_futures, search_polymarket_markets, fetch_company_news

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
    ["Dow Jones", "S&P 500", "Russell 2000"],
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
        os.environ["ALPACA_API_KEY"] = alpaca_key
    if alpaca_secret:
        os.environ["ALPACA_SECRET_KEY"] = alpaca_secret
    if alpaca_url:
        os.environ["ALPACA_BASE_URL"] = alpaca_url

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
tab1, tab_wl, tab2, tab3 = st.tabs([
    "🎯 Screener Dashboard", 
    "⭐ Watchlist Manager", 
    "📈 Einzelwert-Analyse", 
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
            st.dataframe(
                short_df[["Symbol", "Company", "ShortScore", "PE", "DebtToEquity", "CurrentRatio", "FCF"]].head(10),
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
                    
                    # Layout card metrics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Aktueller Kurs", f"${info.get('currentPrice', info.get('previousClose', 0.0)):.2f}")
                        st.metric("KGV (P/E)", f"{info.get('trailingPE', 'N/A')}")
                        st.metric("KGV Vorwärts (Forward P/E)", f"{info.get('forwardPE', 'N/A')}")
                    with col2:
                        st.metric("KBV (P/B)", f"{info.get('priceToBook', 'N/A')}")
                        de_ratio = info.get("debtToEquity")
                        st.metric("Debt-to-Equity", f"{de_ratio/100:.2f}" if de_ratio is not None else "N/A")
                        st.metric("Current Ratio", f"{info.get('currentRatio', 'N/A')}")
                    with col3:
                        st.metric("Free Cash Flow", f"${info.get('freeCashflow', 0):,}" if info.get('freeCashflow') else "N/A")
                        st.metric("ROE", f"{(info.get('returnOnEquity', 0)*100):.2f}%" if info.get('returnOnEquity') else "N/A")
                        st.metric("Umsatzwachstum (YoY)", f"{(info.get('revenueGrowth', 0)*100):.2f}%" if info.get('revenueGrowth') else "N/A")
                        
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
                else:
                    st.error(f"Keine ausreichenden Daten für Ticker {target_symbol} gefunden. Bitte Ticker prüfen.")
            except Exception as e:
                st.error(f"Fehler beim Abrufen der Einzelwertdaten: {e}")

# ----------------------------------------------------
# TAB 3: PDF FINANCIAL REPORT ANALYZER
# ----------------------------------------------------
with tab3:
    st.markdown("### 📄 PDF Finanzberichte Einlesen & Filtern")
    st.markdown("Laden Sie Geschäftsberichte (10-K, 10-Q) hoch, um gezielt nach Fundamentaldaten oder qualitativen Aussagen zu scannen.")
    
    uploaded_file = st.file_uploader("PDF-Finanzbericht hochladen", type="pdf")
    
    if uploaded_file is not None:
        # Load PDF details
        with st.spinner("Extrahiere Text aus PDF-Seiten..."):
            pdf_bytes = io.BytesIO(uploaded_file.read())
            pages_data = extract_text_from_pdf(pdf_bytes)
            
            if not pages_data:
                st.error("Text konnte nicht extrahiert werden. Möglicherweise ist das PDF passwortgeschützt oder bildbasiert.")
            else:
                st.success(f"Erfolgreich {len(pages_data)} Seiten eingelesen!")
                
                # Interactive functions
                analysis_mode = st.radio(
                    "Analyse-Modus wählen",
                    ["Automatischer Scan nach Schlüsseldaten", "Stichwortsuche (Keywords)"]
                )
                
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
                                    st.markdown(f"**Seite {item['page']}:** `{item['line']}`")
                                    
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
                                file_name="pdf_search_results.csv",
                                mime="text/csv"
                            )
                        else:
                            st.write("Keine Treffer gefunden.")
