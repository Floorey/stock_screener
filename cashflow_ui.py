import streamlit as st
import pandas as pd
import os
import sys
import subprocess
from datetime import datetime
import matplotlib.pyplot as plt
from dotenv import load_dotenv

# Import utilities
from alpaca_trader import (
    is_alpaca_configured,
    get_account_info,
    get_positions,
    place_order,
    get_account_activities,
    get_position_qty
)
from options_advisor import (
    get_options_data_for_ticker,
    calculate_black_scholes_metrics,
    suggest_option_strategy
)

# Load environment
load_dotenv(override=True)

# Path for persistent cashflow ledger
LEDGER_PATH = os.path.join(os.path.dirname(__file__), "cashflow_ledger.csv")

def load_ledger() -> pd.DataFrame:
    """Loads the cashflow ledger from a CSV file or creates a default one if missing."""
    if os.path.exists(LEDGER_PATH):
        try:
            df = pd.read_csv(LEDGER_PATH)
            # Ensure correct columns
            required_cols = ["ID", "Date", "Ticker", "Type", "Description", "Amount", "Source"]
            for col in required_cols:
                if col not in df.columns:
                    if col == "ID":
                        df["ID"] = [f"tx_{i}" for i in range(len(df))]
                    elif col == "Source":
                        df["Source"] = "Manual"
                    else:
                        df[col] = ""
            return df
        except Exception as e:
            st.error(f"Fehler beim Laden des Cashflow-Buchs: {e}")
            
    # Default mock ledger to populate the UI initially
    default_data = [
        {
            "ID": "tx_1",
            "Date": "2026-06-01",
            "Ticker": "SPY",
            "Type": "Option Premium",
            "Description": "Stillhalter-Einnahme: 1x 450 Put Expiration 2026-07-01",
            "Amount": 350.00,
            "Source": "Manual"
        },
        {
            "ID": "tx_2",
            "Date": "2026-06-10",
            "Ticker": "JAAA",
            "Type": "Dividend",
            "Description": "Monatliche Dividenden-Ausschüttung",
            "Amount": 45.20,
            "Source": "Manual"
        },
        {
            "ID": "tx_3",
            "Date": "2026-06-15",
            "Ticker": "TLT",
            "Type": "Option Premium",
            "Description": "Covered Call Prämie $95 Strike",
            "Amount": 120.00,
            "Source": "Manual"
        },
        {
            "ID": "tx_4",
            "Date": "2026-06-22",
            "Ticker": "USD",
            "Type": "Interest",
            "Description": "Broker-Guthabenzinsen auf Cash-Bestand",
            "Amount": 12.50,
            "Source": "Manual"
        }
    ]
    df = pd.DataFrame(default_data)
    df.to_csv(LEDGER_PATH, index=False)
    return df

def save_ledger(df: pd.DataFrame):
    """Saves the ledger dataframe to CSV."""
    df.to_csv(LEDGER_PATH, index=False)

def add_transaction(date_str: str, ticker: str, type_str: str, desc: str, amount: float, source: str = "Manual", tx_id: str = None) -> bool:
    """Adds a transaction to the ledger, avoiding duplicates by ID."""
    df = load_ledger()
    if not tx_id:
        tx_id = f"tx_{int(datetime.now().timestamp() * 1000)}"
        
    # Check duplicate ID
    if tx_id in df["ID"].values:
        return False
        
    new_row = {
        "ID": tx_id,
        "Date": date_str,
        "Ticker": ticker.upper().strip(),
        "Type": type_str,
        "Description": desc,
        "Amount": float(amount),
        "Source": source
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.sort_values(by="Date", ascending=False)
    save_ledger(df)
    return True

def delete_transaction(tx_id: str):
    """Deletes a transaction by ID from the ledger."""
    df = load_ledger()
    df = df[df["ID"] != tx_id]
    save_ledger(df)

def render_cashflow_tab(get_single_ticker_data, calculate_scores):
    st.markdown('<div class="wl-banner"><h2>💸 Cashflow-Management & Options-Income Desk</h2></div>', unsafe_allow_html=True)
    st.markdown("Verwalten Sie Ihre Cashflow-Ströme, analysieren Sie Stillhalter-Erträge, wickeln Sie Optionsgeschäfte ab und führen Sie Skripte zur Renditesteigerung und Absicherung aus.")
    
    # Internal Tabs
    c_tab1, c_tab2, c_tab3 = st.tabs([
        "📊 Dashboard & Cashflow-Buch",
        "🎫 Options-Income Generator (Alpaca)",
        "⚡ Hedges & Auto-Skripte"
    ])
    
    # Load the ledger
    ledger_df = load_ledger()
    
    # ----------------------------------------------------
    # TAB 1: DASHBOARD & CASHFLOW-BUCH
    # ----------------------------------------------------
    with c_tab1:
        # Calculate statistics
        total_income = ledger_df["Amount"].sum()
        options_premium = ledger_df[ledger_df["Type"] == "Option Premium"]["Amount"].sum()
        dividends = ledger_df[ledger_df["Type"] == "Dividend"]["Amount"].sum()
        interests = ledger_df[ledger_df["Type"] == "Interest"]["Amount"].sum()
        
        # Monthly projections
        try:
            # Group by year-month to find average monthly cashflow
            ledger_df_temp = ledger_df.copy()
            ledger_df_temp["Date"] = pd.to_datetime(ledger_df_temp["Date"])
            monthly_totals = ledger_df_temp.groupby(ledger_df_temp["Date"].dt.to_period("M"))["Amount"].sum()
            avg_monthly_cashflow = monthly_totals.mean() if not monthly_totals.empty else total_income
        except Exception:
            avg_monthly_cashflow = total_income
            
        # KPI Metric layout
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
        with kpi_col1:
            st.markdown(f"""
            <div class="metric-card" style="text-align: center;">
                <span style="font-size: 0.9rem; color: #9ca3af;">Gesamt-Cashflow (Netto)</span>
                <h2 style="margin: 0.5rem 0; color: #10b981;">+${total_income:,.2f}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">Kumulierter Ertrag</span>
            </div>
            """, unsafe_allow_html=True)
            
        with kpi_col2:
            st.markdown(f"""
            <div class="metric-card" style="text-align: center;">
                <span style="font-size: 0.9rem; color: #9ca3af;">Options-Prämien</span>
                <h2 style="margin: 0.5rem 0; color: #3b82f6;">+${options_premium:,.2f}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">{((options_premium/total_income*100) if total_income > 0 else 0.0):.1f}% vom Gesamt-Cashflow</span>
            </div>
            """, unsafe_allow_html=True)
            
        with kpi_col3:
            st.markdown(f"""
            <div class="metric-card" style="text-align: center;">
                <span style="font-size: 0.9rem; color: #9ca3af;">Dividenden-Erträge</span>
                <h2 style="margin: 0.5rem 0; color: #8b5cf6;">+${dividends:,.2f}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">Zins-Erträge: ${interests:,.2f}</span>
            </div>
            """, unsafe_allow_html=True)
            
        with kpi_col4:
            st.markdown(f"""
            <div class="metric-card" style="text-align: center;">
                <span style="font-size: 0.9rem; color: #9ca3af;">Ø Monatlicher Cashflow</span>
                <h2 style="margin: 0.5rem 0; color: #f59e0b;">+${avg_monthly_cashflow:,.2f}</h2>
                <span style="font-size: 0.8rem; color: #9ca3af;">Basiert auf Buchungen</span>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Alpaca Live Account Metrics
        if is_alpaca_configured():
            try:
                alpaca_acc = get_account_info()
                if alpaca_acc:
                    st.markdown("### 🦙 Alpaca Live-Konto (Echtzeit-Daten)")
                    alp_col1, alp_col2, alp_col3, alp_col4 = st.columns(4)
                    with alp_col1:
                        st.markdown(f"""
                        <div class="metric-card" style="text-align: center; border: 1px solid #10b981;">
                            <span style="font-size: 0.9rem; color: #9ca3af;">Alpaca Live Cash</span>
                            <h2 style="margin: 0.5rem 0; color: #10b981;">${float(alpaca_acc.get('cash', 0)):,.2f}</h2>
                            <span style="font-size: 0.8rem; color: #9ca3af;">Freies Barvermögen</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with alp_col2:
                        st.markdown(f"""
                        <div class="metric-card" style="text-align: center; border: 1px solid #3b82f6;">
                            <span style="font-size: 0.9rem; color: #9ca3af;">Alpaca Portfolio-Wert (Equity)</span>
                            <h2 style="margin: 0.5rem 0; color: #3b82f6;">${float(alpaca_acc.get('equity', 0)):,.2f}</h2>
                            <span style="font-size: 0.8rem; color: #9ca3af;">Gesamt-Eigenkapital</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with alp_col3:
                        st.markdown(f"""
                        <div class="metric-card" style="text-align: center; border: 1px solid #8b5cf6;">
                            <span style="font-size: 0.9rem; color: #9ca3af;">Alpaca Kaufkraft</span>
                            <h2 style="margin: 0.5rem 0; color: #8b5cf6;">${float(alpaca_acc.get('buying_power', 0)):,.2f}</h2>
                            <span style="font-size: 0.8rem; color: #9ca3af;">Optionen-Kaufkraft: ${float(alpaca_acc.get('options_buying_power', 0)):,.2f}</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with alp_col4:
                        from alpaca_trader import get_alpaca_credentials
                        _, _, base_url = get_alpaca_credentials()
                        account_mode = "LIVE" if "live" in base_url.lower() else "PAPER"
                        st.markdown(f"""
                        <div class="metric-card" style="text-align: center; border: 1px solid #f59e0b;">
                            <span style="font-size: 0.9rem; color: #9ca3af;">Handels-Modus</span>
                            <h2 style="margin: 0.5rem 0; color: #f59e0b;">{account_mode}</h2>
                            <span style="font-size: 0.8rem; color: #9ca3af;">Konto-Status: {alpaca_acc.get('status', 'ACTIVE')}</span>
                        </div>
                        """, unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Konnte Live-Daten von Alpaca nicht laden: {e}")

        st.markdown("<br>", unsafe_allow_html=True)
        
        # Visualizations & Table side-by-side
        v_col, t_col = st.columns([1, 1])
        
        with v_col:
            st.markdown("### 📈 Cashflow-Entwicklung & Verteilung")
            
            if not ledger_df.empty:
                # Prepare data for time series plot
                plot_df = ledger_df.copy()
                plot_df["Date"] = pd.to_datetime(plot_df["Date"])
                plot_df = plot_df.sort_values(by="Date")
                plot_df["Cumulative"] = plot_df["Amount"].cumsum()
                
                # Chart 1: Cumulative cashflow line chart
                fig, ax = plt.subplots(figsize=(8, 4), facecolor='#1f2937')
                ax.set_facecolor('#1f2937')
                ax.plot(plot_df["Date"], plot_df["Cumulative"], color='#10b981', marker='o', linewidth=2.5, markersize=6)
                
                # Styling matplotlib
                ax.set_title("Kumulative Cashflow-Entwicklung ($)", color='#f3f4f6', fontsize=12, fontweight='bold', pad=15)
                ax.tick_params(colors='#9ca3af', labelsize=9)
                ax.spines['bottom'].set_color('#374151')
                ax.spines['left'].set_color('#374151')
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.grid(True, color='#374151', linestyle='--', alpha=0.5)
                plt.xticks(rotation=30)
                plt.tight_layout()
                st.pyplot(fig)
                
                # Chart 2: Category breakdown pie chart
                cat_data = ledger_df.groupby("Type")["Amount"].sum()
                fig2, ax2 = plt.subplots(figsize=(6, 3.5), facecolor='#1f2937')
                ax2.set_facecolor('#1f2937')
                
                colors_list = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#9ca3af']
                wedges, texts, autotexts = ax2.pie(
                    cat_data.values, 
                    labels=cat_data.index, 
                    autopct='%1.1f%%',
                    startangle=90, 
                    colors=colors_list[:len(cat_data)],
                    textprops={'color': '#f3f4f6', 'fontsize': 8}
                )
                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_weight('bold')
                    
                ax2.axis('equal')  
                ax2.set_title("Cashflow nach Kategorien", color='#f3f4f6', fontsize=11, fontweight='bold', pad=10)
                plt.tight_layout()
                st.pyplot(fig2)
            else:
                st.info("Fügen Sie Transaktionen hinzu, um Visualisierungen anzuzeigen.")
                
        with t_col:
            st.markdown("### 📋 Cashflow-Buchungen Ledger")
            
            # Search / Filter options for Ledger
            search_ledger = st.text_input("Transaktionen durchsuchen (Ticker, Typ, etc.):", "", key="search_ledger_input")
            
            filtered_ledger = ledger_df.copy()
            if search_ledger:
                filtered_ledger = filtered_ledger[
                    filtered_ledger["Ticker"].str.contains(search_ledger, case=False) |
                    filtered_ledger["Type"].str.contains(search_ledger, case=False) |
                    filtered_ledger["Description"].str.contains(search_ledger, case=False)
                ]
                
            # Render Ledger Dataframe
            if filtered_ledger.empty:
                st.info("Keine Buchungen gefunden.")
            else:
                # Format amounts
                display_ledger = filtered_ledger.copy()
                display_ledger["Amount"] = display_ledger["Amount"].apply(lambda x: f"${x:,.2f}")
                
                st.dataframe(
                    display_ledger[["Date", "Ticker", "Type", "Description", "Amount", "Source", "ID"]],
                    hide_index=True,
                    use_container_width=True
                )
                
            # Manual Transaction Entry Form
            with st.expander("➕ Neue manuelle Buchung erfassen", expanded=False):
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    new_date = st.date_input("Buchungsdatum:", datetime.now())
                    new_ticker = st.text_input("Ticker-Symbol:", "TLT").upper().strip()
                    new_type = st.selectbox(
                        "Cashflow-Kategorie:",
                        ["Option Premium", "Dividend", "Interest", "Deposit", "Withdrawal", "Capital Gain", "Other"]
                    )
                with col_f2:
                    new_amount = st.number_input("Betrag in USD ($):", value=100.0, step=10.0, help="Verwenden Sie positive Werte für Einnahmen, negative Werte für Ausgaben/Gebühren.")
                    new_desc = st.text_input("Beschreibung:", "Einnahme aus...")
                    
                if st.button("💾 Transaktion buchen", use_container_width=True):
                    success = add_transaction(
                        date_str=new_date.strftime("%Y-%m-%d"),
                        ticker=new_ticker,
                        type_str=new_type,
                        desc=new_desc,
                        amount=new_amount,
                        source="Manual"
                    )
                    if success:
                        st.success("Transaktion erfolgreich eingebucht!")
                        st.rerun()
                    else:
                        st.error("Fehler beim Buchen der Transaktion.")
                        
            # Delete Transaction Form
            if not ledger_df.empty:
                with st.expander("🗑️ Buchung löschen", expanded=False):
                    tx_to_del = st.selectbox(
                        "Wählen Sie die zu löschende Buchung:",
                        options=ledger_df["ID"].tolist(),
                        format_func=lambda x: f"{ledger_df[ledger_df['ID']==x]['Date'].values[0]} | {ledger_df[ledger_df['ID']==x]['Ticker'].values[0]} | {ledger_df[ledger_df['ID']==x]['Type'].values[0]} (${ledger_df[ledger_df['ID']==x]['Amount'].values[0]:.2f})"
                    )
                    if st.button("❌ Ausgewählte Buchung löschen", use_container_width=True):
                        delete_transaction(tx_to_del)
                        st.success("Buchung erfolgreich gelöscht!")
                        st.rerun()
                        
                with st.expander("⚠️ Cashflow-Buch zurücksetzen", expanded=False):
                    st.markdown("<small style='color: #ef4444;'>Warnung: Dies löscht alle Buchungen dauerhaft aus dem lokalen Cashflow-Buch (cashflow_ledger.csv).</small>", unsafe_allow_html=True)
                    confirm_reset = st.checkbox("Ja, ich möchte das Cashflow-Buch komplett leeren.", value=False, key="confirm_ledger_reset_check")
                    if st.button("🚨 Ledger komplett leeren", use_container_width=True, disabled=not confirm_reset, key="execute_ledger_reset_btn"):
                        try:
                            # Create empty ledger dataframe
                            empty_df = pd.DataFrame(columns=["ID", "Date", "Ticker", "Type", "Description", "Amount", "Source"])
                            save_ledger(empty_df)
                            st.success("Cashflow-Buch wurde erfolgreich geleert!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fehler beim Leeren des Cashflow-Buchs: {e}")
                        
        # --- ALPACA SYNC ENGINE ---
        st.markdown("---")
        st.markdown("### 🦙 Alpaca Live-Aktivitäten Synchronisierung")
        st.markdown("Laden Sie Ihre echten Transaktionen (Fills, Dividenden, Zinsen, Gebühren) direkt von Ihrem Alpaca Broker-Konto herunter und pflegen Sie diese mit einem Klick in Ihr Cashflow-Buch ein.")
        
        if not is_alpaca_configured():
            st.warning("⚠️ Alpaca ist nicht konfiguriert. Bitte hinterlegen Sie Ihre API-Schlüssel in der Seitenleiste, um diese Synchronisierung zu nutzen.")
        else:
            sync_col1, sync_col2 = st.columns([1, 3])
            with sync_col1:
                st.markdown("<br>", unsafe_allow_html=True)
                fetch_acts = st.button("🔄 Alpaca-Aktivitäten abrufen")
            with sync_col2:
                act_types = st.multiselect(
                    "Aktivitätstypen abrufen:",
                    options=["FILL (Ausgeführte Orders)", "DIV (Dividenden)", "INT (Zinsen)", "FEE (Gebühren)"],
                    default=["FILL (Ausgeführte Orders)", "DIV (Dividenden)", "INT (Zinsen)"]
                )
                
            if fetch_acts:
                with st.spinner("Frage Aktivitäten von Alpaca ab..."):
                    # Resolve names to Alpaca codes
                    codes = []
                    for at in act_types:
                        if "FILL" in at: codes.append("FILL")
                        if "DIV" in at: codes.append("DIV")
                        if "INT" in at: codes.append("INT")
                        if "FEE" in at: codes.append("FEE")
                        
                    raw_activities = get_account_activities(codes)
                    
                    if not raw_activities:
                        st.info("Keine Aktivitäten für die ausgewählten Typen im Alpaca-Konto gefunden.")
                    else:
                        parsed_acts = []
                        for act in raw_activities:
                            act_id = act.get("id")
                            a_type = act.get("activity_type")
                            date_str = act.get("date") or act.get("transaction_time", "")[:10]
                            symbol = act.get("symbol", "USD")
                            
                            # Determine net cashflow impact
                            amount = 0.0
                            desc = ""
                            
                            if a_type == "FILL":
                                price = float(act.get("price", 0.0))
                                qty = float(act.get("qty", 0.0))
                                side = act.get("side", "")
                                
                                # Check if option contract (length > 5 or typical format)
                                is_option = len(symbol) > 5 or any(c.isdigit() for c in symbol[4:10] if len(symbol) > 10)
                                multiplier = 100.0 if is_option else 1.0
                                
                                raw_amt = price * qty * multiplier
                                if side.lower() == "buy":
                                    amount = -raw_amt # Buying costs cash
                                    desc = f"Kauf: {qty}x {symbol} @ ${price:.2f}"
                                else:
                                    amount = raw_amt # Selling credits cash
                                    desc = f"Verkauf: {qty}x {symbol} @ ${price:.2f}"
                                    
                            elif a_type in ["DIV", "INT", "FEE"]:
                                amount = float(act.get("net_amount", act.get("amount", 0.0)))
                                desc = f"Alpaca {a_type} Buchung"
                                if a_type == "DIV":
                                    desc = f"Dividende von {symbol}"
                                elif a_type == "INT":
                                    desc = "Zinsgutschrift" if amount >= 0 else "Zinsbelastung"
                                elif a_type == "FEE":
                                    desc = f"Transaktionsgebühr/Steuern ({symbol})"
                                    
                            # Check if already imported
                            is_dup = act_id in ledger_df["ID"].values
                            
                            parsed_acts.append({
                                "ID": act_id,
                                "Datum": date_str,
                                "Symbol": symbol,
                                "Typ": "Option Premium" if (a_type == "FILL" and is_option and side.lower() == "sell") else (
                                    "Dividend" if a_type == "DIV" else (
                                        "Interest" if a_type == "INT" else (
                                            "Option Premium" if (a_type == "FILL" and is_option) else "Other"
                                        )
                                    )
                                ),
                                "Beschreibung": desc,
                                "Betrag": amount,
                                "Importiert": "✅ Ja" if is_dup else "❌ Nein"
                            })
                            
                        df_parsed = pd.DataFrame(parsed_acts)
                        st.session_state["alpaca_activities_cache"] = df_parsed
                        
            if "alpaca_activities_cache" in st.session_state:
                df_cache = st.session_state["alpaca_activities_cache"]
                st.markdown("#### Gefundene Alpaca Aktivitäten:")
                st.dataframe(df_cache, use_container_width=True, hide_index=True)
                
                # Import actions
                unimported = df_cache[df_cache["Importiert"] == "❌ Nein"]
                if unimported.empty:
                    st.success("Alle gefundenen Aktivitäten wurden bereits in das Cashflow-Buch übernommen.")
                else:
                    if st.button(f"📥 Alle neuen Aktivitäten ({len(unimported)}) importieren"):
                        imported_count = 0
                        for _, row in unimported.iterrows():
                            # Map transaction types
                            type_mapped = row["Typ"]
                            success = add_transaction(
                                date_str=row["Datum"],
                                ticker=row["Symbol"],
                                type_str=type_mapped,
                                desc=row["Beschreibung"],
                                amount=row["Betrag"],
                                source="Alpaca",
                                tx_id=row["ID"]
                            )
                            if success:
                                imported_count += 1
                        st.success(f"{imported_count} Aktivitäten erfolgreich ins Buch übertragen!")
                        # Clean cache to trigger refresh
                        del st.session_state["alpaca_activities_cache"]
                        st.rerun()

    # ----------------------------------------------------
    # TAB 2: OPTIONS-INCOME GENERATOR
    # ----------------------------------------------------
    with c_tab2:
        st.markdown("### 🎫 Options-Trading & Income Generator Panel")
        st.markdown(
            "Verkaufen Sie Optionen (Short Puts / Covered Calls), um sofort Cashflow-Prämien einzunehmen. "
            "Hier finden Sie Optionsketten, Rendite-Rechner und das Orderbuch zur direkten Ausführung."
        )
        
        # Underlying Ticker Selector
        col_t1, col_t2 = st.columns([1, 2])
        with col_t1:
            suggested_tickers = ["TLT", "JAAA", "JBBB", "CLOI", "SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
            # Add watchlist if loaded
            if "watchlist_data_cache" in st.session_state:
                suggested_tickers += st.session_state["watchlist_data_cache"]["Symbol"].tolist()
            suggested_tickers = sorted(list(set(suggested_tickers)))
            
            sel_ticker = st.selectbox(
                "Basiswert (Underlying Ticker):",
                options=suggested_tickers,
                index=suggested_tickers.index("TLT") if "TLT" in suggested_tickers else 0,
                key="cf_options_ticker_select"
            )
        with col_t2:
            custom_t = st.text_input("Oder Ticker manuell eingeben:", "").upper().strip()
            ticker_symbol = custom_t if custom_t else sel_ticker
            
        if ticker_symbol:
            underlying_price = 0.0
            expiry_dates = []
            tk = None
            
            with st.spinner(f"Lade Kursdaten für {ticker_symbol}..."):
                try:
                    tk = yf.Ticker(ticker_symbol)
                    info = tk.info
                    underlying_price = info.get("currentPrice") or info.get("previousClose") or 0.0
                    expiry_dates = list(tk.options)
                except Exception as e:
                    st.error(f"Fehler beim Laden von {ticker_symbol}: {e}")
                    
            if underlying_price > 0:
                # Layout information on the selected stock
                col_i1, col_i2, col_i3 = st.columns(3)
                with col_i1:
                    st.metric(f"Kurs von {ticker_symbol}", f"${underlying_price:.2f}")
                with col_i2:
                    # Look up if this stock is in our screener scores
                    score_str = "N/A"
                    if "screener_results" in st.session_state:
                        scr_df = st.session_state["screener_results"]
                        row = scr_df[scr_df["Symbol"] == ticker_symbol]
                        if not row.empty:
                            score_str = f"Long {row.iloc[0]['LongScore']}/7 | Short {row.iloc[0]['ShortScore']}/7"
                    elif "watchlist_data_cache" in st.session_state:
                        wl_df = st.session_state["watchlist_data_cache"]
                        row = wl_df[wl_df["Symbol"] == ticker_symbol]
                        if not row.empty:
                            score_str = f"Long {row.iloc[0]['LongScore']}/7 | Short {row.iloc[0]['ShortScore']}/7"
                            
                    st.metric("Fundamental-Scores", score_str)
                with col_i3:
                    st.metric("Verfügbare Verfallstermine", len(expiry_dates))
                    
                if not expiry_dates:
                    st.warning(f"Keine Optionskontrakte für {ticker_symbol} gefunden.")
                else:
                    st.markdown("---")
                    st.markdown("#### ⚙️ Options-Kontraktauswahl & Renditerechner")
                    
                    col_p1, col_p2, col_p3 = st.columns(3)
                    with col_p1:
                        sel_expiry = st.selectbox(
                            "Verfallsdatum (Expiry Date):",
                            options=expiry_dates,
                            key="cf_opt_expiry_select"
                        )
                    with col_p2:
                        opt_type = st.radio("Optionstyp:", ["Put", "Call"], horizontal=True, key="cf_opt_type_radio")
                    with col_p3:
                        interest_rate = st.slider(
                            "Zinssatz (risk-free rate %) für Delta:",
                            min_value=0.0,
                            max_value=8.0,
                            value=4.5,
                            step=0.1,
                            key="cf_opt_r_rate"
                        ) / 100.0
                        
                    # Fetch chain for this expiry
                    try:
                        chain = tk.option_chain(sel_expiry)
                        df_chain = chain.puts if opt_type == "Put" else chain.calls
                        
                        # Process dates for Black Scholes
                        today = datetime.now().date()
                        expiry_dt = datetime.strptime(sel_expiry, "%Y-%m-%d").date()
                        days_to_exp = max((expiry_dt - today).days, 1)
                        
                        # Filter strikes near money for display
                        all_strikes = sorted(df_chain["strike"].tolist())
                        
                        # Find closest strike to ATM
                        atm_idx = min(range(len(all_strikes)), key=lambda idx: abs(all_strikes[idx] - underlying_price))
                        
                        # Show strikes in range +/- 20%
                        strikes_to_show = [
                            s for s in all_strikes 
                            if underlying_price * 0.8 <= s <= underlying_price * 1.2
                        ]
                        
                        # Strike selector
                        col_s1, col_s2 = st.columns(2)
                        with col_s1:
                            target_strike = st.selectbox(
                                "Basispreis (Strike):",
                                options=strikes_to_show,
                                index=strikes_to_show.index(all_strikes[atm_idx]) if all_strikes[atm_idx] in strikes_to_show else len(strikes_to_show)//2,
                                key="cf_opt_strike_select"
                            )
                        with col_s2:
                            contracts_qty = st.number_input("Menge (Kontrakte):", min_value=1, value=1, step=1, key="cf_opt_qty")
                            
                        # Retrieve specific contract details
                        con_row = df_chain[df_chain["strike"] == target_strike]
                        
                        if con_row.empty:
                            st.error(f"Kontrakt für Strike ${target_strike:.2f} auf {sel_expiry} nicht gefunden.")
                        else:
                            con = con_row.iloc[0].to_dict()
                            c_symbol = con.get("contractSymbol", "")
                            bid = con.get("bid", 0.0)
                            ask = con.get("ask", 0.0)
                            last = con.get("lastPrice", 0.0)
                            mid = (bid + ask) / 2.0 or last
                            iv = con.get("impliedVolatility", 0.20)
                            
                            # Black-Scholes calculations
                            delta, prob_otm = calculate_black_scholes_metrics(
                                s=underlying_price,
                                k=target_strike,
                                days=days_to_exp,
                                r=interest_rate,
                                iv=iv,
                                option_type=opt_type.lower()
                            )
                            
                            # Stillhalter Yield calculations
                            # For puts: Yield = premium / strike
                            # For calls: Yield = premium / stock price
                            denominator = target_strike if opt_type == "Put" else underlying_price
                            raw_yield = (mid / denominator) * 100 if denominator > 0 else 0.0
                            annualized_yield = raw_yield * (365.0 / days_to_exp) if days_to_exp > 0 else 0.0
                            
                            # Show Contract Detail Sheet in beautiful layout
                            st.markdown(f"""
                            <div style="background-color: #1f2937; border-radius: 12px; padding: 1.5rem; border: 1px solid #374151; margin-top: 1rem;">
                                <h4 style="margin-top: 0; color: #3b82f6;">🎫 Options-Bewertungsblatt (OSI: {c_symbol})</h4>
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-top: 1rem;">
                                    <div style="background-color: #111827; padding: 0.8rem; border-radius: 8px; text-align: center;">
                                        <span style="font-size: 0.8rem; color: #9ca3af;">Mittelpreis (Premium)</span>
                                        <h3 style="margin: 0.2rem 0; color: #10b981;">${mid:.2f}</h3>
                                        <span style="font-size: 0.75rem; color: #9ca3af;">Bid: ${bid:.2f} | Ask: ${ask:.2f}</span>
                                    </div>
                                    <div style="background-color: #111827; padding: 0.8rem; border-radius: 8px; text-align: center;">
                                        <span style="font-size: 0.8rem; color: #9ca3af;">Option-Yield (Prämie)</span>
                                        <h3 style="margin: 0.2rem 0; color: #3b82f6;">{raw_yield:.2f}%</h3>
                                        <span style="font-size: 0.75rem; color: #10b981;">{annualized_yield:.1f}% p.a.</span>
                                    </div>
                                    <div style="background-color: #111827; padding: 0.8rem; border-radius: 8px; text-align: center;">
                                        <span style="font-size: 0.8rem; color: #9ca3af;">BS Delta (Sensitivität)</span>
                                        <h3 style="margin: 0.2rem 0; color: #f59e0b;">{delta:.2f}</h3>
                                        <span style="font-size: 0.75rem; color: #9ca3af;">Typ: {opt_type} ({days_to_exp} Tage bis Expiry)</span>
                                    </div>
                                    <div style="background-color: #111827; padding: 0.8rem; border-radius: 8px; text-align: center;">
                                        <span style="font-size: 0.8rem; color: #9ca3af;">Wahrsch. wertlos (OTM)</span>
                                        <h3 style="margin: 0.2rem 0; color: #8b5cf6;">{prob_otm*100:.1f}%</h3>
                                        <span style="font-size: 0.75rem; color: #9ca3af;">Implizierte Volatilität: {iv*100:.1f}%</span>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Trading action section
                            st.markdown("<br>#### 🛒 Alpaca Order Ticket & Cashflow-Vorschau")
                            
                            trade_col1, trade_col2 = st.columns(2)
                            
                            with trade_col1:
                                action_side = st.selectbox("Order-Richtung:", ["Verkauf (Stillhalter / Sell to Open)", "Kauf (Glattstellung / Buy to Close)"], key="cf_order_side")
                                order_type_sel = st.selectbox("Order-Typ:", ["Limit", "Market"], key="cf_order_type")
                                
                                limit_price_input = None
                                if order_type_sel == "Limit":
                                    limit_price_input = st.number_input(
                                        "Limit-Preis ($)",
                                        min_value=0.01,
                                        value=float(mid) if mid > 0 else 0.10,
                                        step=0.01,
                                        key="cf_limit_price"
                                    )
                                    
                            with trade_col2:
                                # Show cashflow preview
                                est_multiplier = 100.0 * contracts_qty
                                est_premium_flow = (limit_price_input if limit_price_input else mid) * est_multiplier
                                is_selling = "Verkauf" in action_side
                                
                                net_cf_preview = est_premium_flow if is_selling else -est_premium_flow
                                st.markdown("##### 💸 Cashflow-Effekt (Vorschau):")
                                if net_cf_preview >= 0:
                                    st.markdown(f'<h3 style="color: #10b981; margin: 0.2rem 0;">+${net_cf_preview:,.2f} Einnahme</h3>', unsafe_allow_html=True)
                                    st.markdown("<small style='color: #9ca3af;'>Dieser Betrag wird Ihrem Barbestand sofort gutgeschrieben (Credit-Trade).</small>", unsafe_allow_html=True)
                                else:
                                    st.markdown(f'<h3 style="color: #ef4444; margin: 0.2rem 0;">-${abs(net_cf_preview):,.2f} Ausgabe</h3>', unsafe_allow_html=True)
                                    st.markdown("<small style='color: #9ca3af;'>Dieser Betrag wird von Ihrem Barbestand abgebucht (Debit-Trade).</small>", unsafe_allow_html=True)
                                    
                            # Check buying power
                            is_trade_disabled = False
                            if is_alpaca_configured():
                                acc_details = get_account_info()
                                if acc_details:
                                    avail_bp = float(acc_details.get("options_buying_power") or acc_details.get("buying_power") or acc_details.get("cash", 0.0))
                                    
                                    # Required collateral estimate
                                    req_margin = 0.0
                                    if is_selling:
                                        if opt_type == "Put":
                                            # Cash-secured put: 100% collateral
                                            req_margin = target_strike * 100.0 * contracts_qty
                                            st.markdown(f"🔒 **Benötigte Bar-Sicherheit (Collateral):** `${req_margin:,.2f}`")
                                        else:
                                            # Covered Call: Check if user has stock
                                            qty_held = get_position_qty(ticker_symbol)
                                            needed_shares = contracts_qty * 100
                                            if qty_held >= needed_shares:
                                                st.success(f"✅ **Gedeckt durch Aktienbestand:** Sie besitzen {qty_held:.0f} Aktien. Covered Call benötigt keine Bar-Sicherheit.")
                                            else:
                                                missing = needed_shares - qty_held
                                                req_margin = underlying_price * missing
                                                st.warning(f"⚠️ **Teilweise ungedeckt:** Sie besitzen nur {qty_held:.0f}/{needed_shares} Aktien. Sie müssen {missing:.0f} Aktien kaufen (Kosten: `${req_margin:,.2f}`) oder benötigen ungedeckte Margin-Sicherheit.")
                                                
                                    if req_margin > avail_bp:
                                        st.error(f"❌ Ungenügende Kaufkraft! Benötigt: `${req_margin:,.2f}` | Verfügbar: `${avail_bp:,.2f}`")
                                        is_trade_disabled = True
                                    else:
                                        st.write(f"💼 **Options-Kaufkraft:** Verfügbar: `${avail_bp:,.2f}`")
                            else:
                                st.warning("Alpaca ist nicht konfiguriert. Sie können diesen Trade simulieren, aber nicht absenden.")
                                is_trade_disabled = True
                                
                            confirm_check = st.checkbox("Ich möchte diese Optionsorder an Alpaca übermitteln.", value=False, key="cf_confirm_trade")
                            
                            if st.button("🚀 Optionsorder absenden", key="cf_submit_order_btn", disabled=is_trade_disabled or not confirm_check):
                                with st.spinner("Übermittle Order..."):
                                    side = "sell" if is_selling else "buy"
                                    ord_type_lower = order_type_sel.lower()
                                    
                                    res = place_order(
                                        symbol=c_symbol,
                                        qty=contracts_qty,
                                        side=side,
                                        order_type=ord_type_lower,
                                        limit_price=limit_price_input
                                    )
                                    
                                    if res.get("status") == "success":
                                        ord_info = res.get("order", {})
                                        st.success(f"Optionsorder erfolgreich platziert: {contracts_qty}x {c_symbol} ({ord_info.get('status')})")
                                        
                                        # Log the cashflow transaction automatically!
                                        add_transaction(
                                            date_str=datetime.now().strftime("%Y-%m-%d"),
                                            ticker=ticker_symbol,
                                            type_str="Option Premium",
                                            desc=f"{action_side.split()[0]} {contracts_qty}x {opt_type} Strike ${target_strike:.2f} (Alpaca Order)",
                                            amount=net_cf_preview,
                                            source="Alpaca",
                                            tx_id=ord_info.get("id")
                                        )
                                        st.rerun()
                                    else:
                                        st.error(f"Order fehlgeschlagen: {res.get('message')}")
                                        
                    except Exception as e:
                        st.error(f"Fehler beim Berechnen der Option: {e}")
                        
            else:
                st.info("Ungültiger Ticker-Symbol.")

    # ----------------------------------------------------
    # TAB 3: HEDGES & AUTO-SKRIPTE
    # ----------------------------------------------------
    with c_tab3:
        st.markdown("### ⚡ Absicherung (Hedging) & Auto-Skripte")
        st.markdown(
            "Führen Sie die im System hinterlegten Cashflow-Skripte und Makro-Absicherungen direkt auf dem Server aus. "
            "Hier können Sie physische Shorts, synthetische Zinswetten (Option A) oder System-Risikoanalysen starten."
        )
        
        script_choice = st.selectbox(
            "Wählen Sie ein Skript zum Ausführen aus:",
            [
                "trade_strategy_runner.py (Strategien & Option A ausführen)",
                "synthetic_swap_builder.py (Synthetischen Swap erstellen)",
                "risk_manager.py (Portfolio Risiko & Stresstests)",
                "short_sp500.py (S&P 500 Short-Absicherung)",
                "short_nasdaq.py (Nasdaq 100 Short-Absicherung)",
                "short_russell.py (Russell 2000 Short-Absicherung)"
            ],
            key="cf_script_choice"
        )
        
        # Dynamic inputs based on script
        cmd_args = []
        
        if "trade_strategy_runner.py" in script_choice:
            st.info("Dieses Skript führt vordefinierte Zinswetten oder Income-Strategien aus. Z.B. Option A (Synthetic Short Bond).")
            col_sc1, col_sc2 = st.columns(2)
            with col_sc1:
                runner_ticker = st.text_input("Ticker-Symbol:", "TLT", key="cf_runner_ticker").upper().strip()
                runner_qty = st.number_input("Anzahl Kontrakte:", min_value=1, value=1, step=1, key="cf_runner_qty")
            with col_sc2:
                runner_strike = st.text_input("Basispreis (leer für ATM):", "", key="cf_runner_strike").strip()
                runner_expiry = st.text_input("Ablaufdatum (YYYY-MM-DD, leer für ca. 30 Tage):", "", key="cf_runner_expiry").strip()
                
            cmd_args = ["--ticker", runner_ticker, "--qty", str(runner_qty)]
            if runner_strike:
                cmd_args += ["--strike", runner_strike]
            if runner_expiry:
                cmd_args += ["--expiry", runner_expiry]
                
        elif "synthetic_swap_builder.py" in script_choice:
            st.info("Dieses Skript baut einen synthetischen Swap (Long Put + Short Call) zur exakten Leerverkauf-Simulation ohne Leihgebühren.")
            col_sw1, col_sw2 = st.columns(2)
            with col_sw1:
                sw_ticker = st.text_input("Underlying Ticker:", "AAPL", key="cf_sw_ticker").upper().strip()
                sw_direction = st.selectbox("Richtung (Long/Short):", ["long", "short"], key="cf_sw_dir")
            with col_sw2:
                sw_qty = st.number_input("Menge (Kontrakte):", min_value=1, value=1, step=1, key="cf_sw_qty")
                sw_strike = st.text_input("Strike (leer für ATM):", "", key="cf_sw_strike").strip()
                
            cmd_args = ["--ticker", sw_ticker, "--direction", sw_direction, "--qty", str(sw_qty)]
            if sw_strike:
                cmd_args += ["--strike", sw_strike]
                
        elif "risk_manager.py" in script_choice:
            st.info("Dieses Skript berechnet die Value-at-Risk-Kennzahlen und Stresstests für Ihr echtes Alpaca-Portfolio.")
            risk_mode = st.radio("Risiko-Modus:", ["Analyse & PDF-Generierung", "Daemon (Hintergrundüberwachung starten)"], key="cf_risk_mode")
            if "Daemon" in risk_mode:
                cmd_args = ["--daemon"]
            else:
                cmd_args = []
                
        elif "short_" in script_choice:
            st.info("Dieses Skript kauft Absicherungs-Optionen oder Leerverkäufe auf die großen Aktienindizes (SPY, QQQ, IWM).")
            col_sh1, col_sh2 = st.columns(2)
            with col_sh1:
                hedge_type = st.selectbox(
                    "Absicherungs-Typ:",
                    ["put (OTM Put Option - empfohlen)", "short (Direkter physischer ETF-Short)", "synthetic (Synthetischer Short)"],
                    key="cf_hedge_type"
                )
                type_val = hedge_type.split()[0]
            with col_sh2:
                hedge_qty = st.number_input("Menge (Anteile bei Short / Kontrakte bei Put):", min_value=1, value=1, step=1, key="cf_hedge_qty")
                otm_pct = st.slider("OTM Abstand bei Puts (%):", min_value=2.0, max_value=20.0, value=5.0, step=0.5, key="cf_otm_pct")
                
            cmd_args = ["--type", type_val, "--qty", str(hedge_qty)]
            if type_val == "put":
                cmd_args += ["--otm", f"{otm_pct:.1f}"]
                
        # Trigger Execution
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Skript auf Server ausführen", key="cf_execute_script_btn"):
            script_filename = script_choice.split()[0]
            script_path = os.path.join(os.path.dirname(__file__), script_filename)
            
            if not os.path.exists(script_path):
                st.error(f"Skript-Datei `{script_filename}` wurde nicht unter `{script_path}` gefunden.")
            else:
                with st.spinner(f"Führe `python {script_filename} {' '.join(cmd_args)}` aus..."):
                    try:
                        cmd = [sys.executable, script_path] + cmd_args
                        result = subprocess.run(
                            cmd, 
                            capture_output=True, 
                            text=True, 
                            cwd=os.path.dirname(__file__), 
                            timeout=45
                        )
                        
                        st.markdown("**Konsolenausgabe (Stdout):**")
                        if result.stdout:
                            st.code(result.stdout, language="text")
                        else:
                            st.info("Keine Standardausgabe.")
                            
                        if result.stderr:
                            st.markdown("**Fehlerausgabe (Stderr):**")
                            st.code(result.stderr, language="text")
                            
                        if result.returncode == 0:
                            st.success(f"Skript `{script_filename}` wurde erfolgreich beendet (Exit Code 0).")
                        else:
                            st.error(f"Skript `{script_filename}` wurde mit Fehlercode {result.returncode} beendet.")
                    except subprocess.TimeoutExpired:
                        st.error("Zeitüberschreitung: Das Skript hat länger als 45 Sekunden für die Ausführung benötigt.")
                    except Exception as e:
                        st.error(f"Fehler beim Ausführen des Skripts: {e}")
