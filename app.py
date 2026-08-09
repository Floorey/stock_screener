import streamlit as st
from dotenv import load_dotenv
load_dotenv(override=True)
import pandas as pd
import os
import sys
from screener import run_screener
from watchlist_manager import add_to_watchlist
from macro_fetcher import fetch_macro_futures, fetch_wsb_trending
from algo_lab_ui import render_algo_lab_tab
from alpaca_trader import verify_alpaca_connection

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

    # Save to .env button
    if alpaca_key or alpaca_secret:
        if st.button("Schlüssel in .env speichern", use_container_width=True):
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            try:
                lines = []
                if os.path.exists(env_path):
                    with open(env_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                
                new_lines = []
                for line in lines:
                    if not any(line.strip().startswith(prefix) for prefix in ["ALPACA_API_KEY=", "ALPACA_SECRET_KEY=", "ALPACA_BASE_URL="]):
                        new_lines.append(line)
                
                new_lines.append(f"ALPACA_API_KEY={alpaca_key.strip()}\n")
                new_lines.append(f"ALPACA_SECRET_KEY={alpaca_secret.strip()}\n")
                new_lines.append(f"ALPACA_BASE_URL={alpaca_url.strip()}\n")
                
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                st.success("Erfolgreich in .env gespeichert!")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Speichern: {e}")

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
tab1, tab_algo = st.tabs([
    "🎯 Screener Dashboard",
    "🔬 Algorithmus TestLab"
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
# TAB ALGO: ALGO-TRADING TESTLAB
# ----------------------------------------------------
with tab_algo:
    render_algo_lab_tab()
