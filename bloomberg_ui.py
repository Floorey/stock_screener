import streamlit as st
import pandas as pd
import yfinance as yf
import datetime
import io
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from alpaca_trader import is_alpaca_configured, get_positions, get_account_info
from macro_fetcher import fetch_company_news

MOCK_PORTFOLIO = [
    {"symbol": "AAPL", "qty": 100.0, "avg_entry_price": 175.50, "name": "Apple Inc."},
    {"symbol": "MSFT", "qty": 80.0, "avg_entry_price": 380.00, "name": "Microsoft Corp."},
    {"symbol": "NVDA", "qty": 250.0, "avg_entry_price": 95.20, "name": "NVIDIA Corp."},
    {"symbol": "TSLA", "qty": 120.0, "avg_entry_price": 185.00, "name": "Tesla Inc."},
    {"symbol": "MSTR", "qty": 100.0, "avg_entry_price": 145.00, "name": "MicroStrategy Inc."},
    {"symbol": "BTC-USD", "qty": 0.75, "avg_entry_price": 58000.00, "name": "Bitcoin USD"},
    {"symbol": "GC=F", "qty": 10.0, "avg_entry_price": 2100.00, "name": "Gold Futures"}
]

def format_val(val, fmt_type="decimal", suffix=""):
    """Safely formats values fetched from yfinance, handling None values gracefully."""
    if val is None:
        return "N/A"
    try:
        if fmt_type == "currency":
            return f"${val:,.2f}{suffix}"
        elif fmt_type == "percent":
            return f"{val:,.2f}%"
        elif fmt_type == "percent_raw":
            return f"{val*100:,.2f}%"
        elif fmt_type == "int":
            return f"{int(val):,}{suffix}"
        elif fmt_type == "billions":
            return f"${val/1e9:,.2f}B"
        else: # decimal
            return f"{val:,.2f}{suffix}"
    except Exception:
        return str(val)

def get_market_clocks():
    """Calculates current time for New York, London, Tokyo, Frankfurt and determines if markets are open."""
    try:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
    except AttributeError:
        utc_now = datetime.datetime.utcnow()
    
    # Simple DST helper for July
    is_dst_us = True
    is_dst_eu = True
    
    month = utc_now.month
    day = utc_now.day
    
    if month < 3 or month > 11:
        is_dst_us = False
    elif month == 3:
        first_day_of_month = datetime.datetime(utc_now.year, 3, 1, tzinfo=datetime.timezone.utc)
        first_sunday = 1 + (6 - first_day_of_month.weekday()) % 7
        second_sunday = first_sunday + 7
        if day < second_sunday:
            is_dst_us = False
    elif month == 11:
        first_day_of_month = datetime.datetime(utc_now.year, 11, 1, tzinfo=datetime.timezone.utc)
        first_sunday = 1 + (6 - first_day_of_month.weekday()) % 7
        if day >= first_sunday:
            is_dst_us = False
            
    if month < 3 or month > 10:
        is_dst_eu = False
    elif month == 3:
        last_day_of_month = datetime.datetime(utc_now.year, 3, 31, tzinfo=datetime.timezone.utc)
        last_sunday = 31 - (last_day_of_month.weekday() + 1) % 7
        if day < last_sunday:
            is_dst_eu = False
    elif month == 10:
        last_day_of_month = datetime.datetime(utc_now.year, 10, 31, tzinfo=datetime.timezone.utc)
        last_sunday = 31 - (last_day_of_month.weekday() + 1) % 7
        if day >= last_sunday:
            is_dst_eu = False
            
    ny_offset = -4 if is_dst_us else -5
    london_offset = 1 if is_dst_eu else 0
    tokyo_offset = 9
    frankfurt_offset = 2 if is_dst_eu else 1
    
    ny_time = utc_now + datetime.timedelta(hours=ny_offset)
    london_time = utc_now + datetime.timedelta(hours=london_offset)
    tokyo_time = utc_now + datetime.timedelta(hours=tokyo_offset)
    frankfurt_time = utc_now + datetime.timedelta(hours=frankfurt_offset)
    
    clocks = {
        "NEW YORK": ny_time.strftime("%H:%M:%S"),
        "LONDON": london_time.strftime("%H:%M:%S"),
        "TOKYO": tokyo_time.strftime("%H:%M:%S"),
        "FRANKFURT": frankfurt_time.strftime("%H:%M:%S")
    }
    
    ny_market_open = False
    if ny_time.weekday() < 5:
        market_start = ny_time.replace(hour=9, minute=30, second=0)
        market_end = ny_time.replace(hour=16, minute=0, second=0)
        if market_start <= ny_time <= market_end:
            ny_market_open = True
            
    ffm_market_open = False
    if frankfurt_time.weekday() < 5:
        market_start = frankfurt_time.replace(hour=9, minute=0, second=0)
        market_end = frankfurt_time.replace(hour=17, minute=30, second=0)
        if market_start <= frankfurt_time <= market_end:
            ffm_market_open = True
            
    tokyo_market_open = False
    if tokyo_time.weekday() < 5:
        market_start1 = tokyo_time.replace(hour=9, minute=0, second=0)
        market_end1 = tokyo_time.replace(hour=11, minute=30, second=0)
        market_start2 = tokyo_time.replace(hour=12, minute=30, second=0)
        market_end2 = tokyo_time.replace(hour=15, minute=0, second=0)
        if (market_start1 <= tokyo_time <= market_end1) or (market_start2 <= tokyo_time <= market_end2):
            tokyo_market_open = True
            
    return clocks, {
        "NY": ny_market_open,
        "FFM": ffm_market_open,
        "TKY": tokyo_market_open
    }

def fetch_prices_for_tickers(tickers_list):
    """Fetches real-time prices for list of tickers in a fast batch process."""
    prices = {}
    try:
        data = yf.download(tickers_list, period="5d", group_by="ticker", progress=False)
        for ticker in tickers_list:
            try:
                if ticker in data.columns.levels[0]:
                    ticker_df = data[ticker]
                    valid_closes = ticker_df["Close"].dropna()
                    if not valid_closes.empty:
                        prices[ticker] = float(valid_closes.iloc[-1])
            except Exception:
                pass
    except Exception as e:
        print(f"Error downloading batch prices: {e}")
        
    for ticker in tickers_list:
        if ticker not in prices:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="2d")
                if not hist.empty:
                    prices[ticker] = float(hist["Close"].iloc[-1])
            except Exception:
                pass
    return prices

def get_portfolio_data(alpaca_positions=None, mock_prices=None):
    """Constructs the unified portfolio DataFrame containing cost and valuation columns."""
    if alpaca_positions:
        data = []
        for pos in alpaca_positions:
            qty = float(pos.get("qty", 0))
            avg_price = float(pos.get("avg_entry_price", 0))
            curr_price = float(pos.get("current_price", 0))
            mkt_val = float(pos.get("market_value", 0))
            pnl = float(pos.get("unrealized_pl", 0))
            pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100.0
            symbol = pos.get("symbol", "")
            
            data.append({
                "Symbol": symbol,
                "Name": symbol,
                "Qty": qty,
                "Avg Price": avg_price,
                "Last": curr_price,
                "Cost Basis": qty * avg_price,
                "Market Value": mkt_val,
                "PnL": pnl,
                "PnL %": pnl_pct
            })
        return pd.DataFrame(data)
    else:
        data = []
        for pos in MOCK_PORTFOLIO:
            symbol = pos["symbol"]
            qty = pos["qty"]
            avg_price = pos["avg_entry_price"]
            name = pos["name"]
            
            curr_price = mock_prices.get(symbol)
            if curr_price is None:
                defaults = {
                    "AAPL": 220.50, "MSFT": 445.00, "NVDA": 125.80,
                    "TSLA": 210.00, "MSTR": 160.00, "BTC-USD": 63500.00, "GC=F": 2380.00
                }
                curr_price = defaults.get(symbol, avg_price)
                
            cost_basis = qty * avg_price
            mkt_val = qty * curr_price
            pnl = mkt_val - cost_basis
            pnl_pct = (pnl / cost_basis) * 100.0 if cost_basis > 0 else 0.0
            
            data.append({
                "Symbol": symbol,
                "Name": name,
                "Qty": qty,
                "Avg Price": avg_price,
                "Last": curr_price,
                "Cost Basis": cost_basis,
                "Market Value": mkt_val,
                "PnL": pnl,
                "PnL %": pnl_pct
            })
        return pd.DataFrame(data)

def fetch_bloomberg_macro():
    """Fetches real-time price info for indices, fixed income, currencies and commodities."""
    macro_symbols = {
        "^GSPC": "S&P 500 INDEX",
        "^IXIC": "NASDAQ COMPOSITE",
        "^DJI": "DOW JONES IND.",
        "^GDAXI": "DAX 40 INDEX",
        "^N225": "NIKKEI 225",
        "^TNX": "US 10YR BOND YLD",
        "EURUSD=X": "EUR / USD SPOT",
        "GBPUSD=X": "GBP / USD SPOT",
        "JPY=X": "USD / JPY SPOT",
        "GC=F": "GOLD SPOT OUNCE",
        "CL=F": "CRUDE OIL WTI",
        "BTC-USD": "BITCOIN USD"
    }
    symbols = list(macro_symbols.keys())
    results = []
    try:
        data = yf.download(symbols, period="5d", group_by="ticker", progress=False)
        for sym in symbols:
            try:
                name = macro_symbols[sym]
                if sym in data.columns.levels[0]:
                    sym_df = data[sym]
                    valid_closes = sym_df["Close"].dropna()
                    
                    if not valid_closes.empty:
                        price = float(valid_closes.iloc[-1])
                        prev_close = float(valid_closes.iloc[-2]) if len(valid_closes) >= 2 else price
                        change = price - prev_close
                        change_pct = (change / prev_close) * 100.0 if prev_close > 0 else 0.0
                        
                        results.append({
                            "Symbol": sym,
                            "Name": name,
                            "Price": price,
                            "Change": change,
                            "ChangePct": change_pct
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"Error fetching bloomberg macro: {e}")
        
    if not results:
        for sym, name in macro_symbols.items():
            try:
                t = yf.Ticker(sym)
                hist = t.history(period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100.0 if prev_close > 0 else 0.0
                    results.append({
                        "Symbol": sym,
                        "Name": name,
                        "Price": price,
                        "Change": change,
                        "ChangePct": change_pct
                    })
            except Exception:
                pass
    return results

def plot_terminal_chart(df, symbol, theme="amber"):
    """Plots a vintage-style terminal line chart with pitch black background and colored glow."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    fig.patch.set_facecolor('#000000')
    ax.set_facecolor('#000000')
    
    color_line = '#FFB300' if theme == "amber" else '#00FF00'
    color_text = '#FFB300' if theme == "amber" else '#00FF00'
    color_grid = '#1c1c1c'
    
    ax.plot(df.index, df['Close'], color=color_line, linewidth=2, label=f"{symbol} Close")
    ax.fill_between(df.index, df['Close'], df['Close'].min() * 0.99, color=color_line, alpha=0.08)
    
    ax.set_title(f"{symbol} HISTORICAL CLOSING PRICES", color=color_text, fontname='Courier New', fontsize=11, fontweight='bold', pad=12)
    ax.grid(True, which='both', color=color_grid, linestyle='--', linewidth=0.5)
    
    for spine in ax.spines.values():
        spine.set_color('#333333')
        spine.set_linewidth(1)
        
    ax.tick_params(colors=color_text, labelsize=8)
    plt.xticks(rotation=10)
    for label in (ax.get_xticklabels() + ax.get_yticklabels()):
        label.set_fontname('Courier New')
        
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none', dpi=150)
    buf.seek(0)
    plt.close(fig)
    return buf

def make_bloomberg_table(df, total_equity):
    """Formats the portfolio positions table in clean monospaced HTML with color classes."""
    html = '<table class="bloomberg-table">'
    html += '<thead><tr>'
    html += '<th style="text-align: left;">SYMBOL</th><th style="text-align: left;">NAME</th><th style="text-align: right;">QTY</th><th style="text-align: right;">AVG COST</th><th style="text-align: right;">LAST PRICE</th><th style="text-align: right;">MARKET VALUE</th><th style="text-align: right;">UNREALIZED P&L</th><th style="text-align: right;">WEIGHT %</th>'
    html += '</tr></thead><tbody>'
    
    total_cost = 0
    total_mkt = 0
    total_pnl = 0
    
    for _, row in df.iterrows():
        pnl = row["PnL"]
        pnl_pct = row["PnL %"]
        pnl_class = "bloomberg-green-text" if pnl >= 0 else "bloomberg-red-text"
        pnl_sign = "+" if pnl >= 0 else ""
        
        weight = (row["Market Value"] / total_equity) * 100 if total_equity > 0 else 0
        
        html += f'<tr>'
        html += f'<td class="bloomberg-amber-text" style="text-align: left;"><b>{row["Symbol"]}</b></td>'
        html += f'<td class="bloomberg-white-text" style="text-align: left;">{row["Name"]}</td>'
        html += f'<td class="bloomberg-white-text" style="text-align: right;">{row["Qty"]:.4f}</td>'
        html += f'<td class="bloomberg-white-text" style="text-align: right;">${row["Avg Price"]:,.2f}</td>'
        html += f'<td class="bloomberg-white-text" style="text-align: right;">${row["Last"]:,.2f}</td>'
        html += f'<td class="bloomberg-white-text" style="text-align: right;">${row["Market Value"]:,.2f}</td>'
        html += f'<td class="{pnl_class}" style="text-align: right;">{pnl_sign}${pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%)</td>'
        html += f'<td class="bloomberg-cyan-text" style="text-align: right;">{weight:.1f}%</td>'
        html += f'</tr>'
        
        total_cost += row["Cost Basis"]
        total_mkt += row["Market Value"]
        total_pnl += pnl
        
    pnl_class_tot = "bloomberg-green-text" if total_pnl >= 0 else "bloomberg-red-text"
    pnl_sign_tot = "+" if total_pnl >= 0 else ""
    tot_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0
    
    html += '<tr style="border-top: 2px solid #555555; background-color: #111111;">'
    html += '<td style="text-align: left;"><b>TOTAL</b></td>'
    html += '<td style="text-align: left;">Portfolio Holdings</td>'
    html += '<td></td>'
    html += '<td></td>'
    html += '<td></td>'
    html += f'<td style="text-align: right;"><b>${total_mkt:,.2f}</b></td>'
    html += f'<td class="{pnl_class_tot}" style="text-align: right;"><b>{pnl_sign_tot}${total_pnl:,.2f} ({pnl_sign_tot}{tot_pnl_pct:.2f}%)</b></td>'
    html += '<td style="text-align: right;"><b>100.0%</b></td>'
    html += '</tr>'
    
    html += '</tbody></table>'
    return html

def make_bloomberg_macro_table(macro_data):
    """Formats global market assets table in clean retro dashboard HTML."""
    html = '<table class="bloomberg-table">'
    html += '<thead><tr>'
    html += '<th style="text-align: left;">SYMBOL</th><th style="text-align: left;">SECURITY NAME</th><th style="text-align: right;">PRICE / YIELD</th><th style="text-align: right;">NET CHANGE</th><th style="text-align: right;">% CHANGE</th>'
    html += '</tr></thead><tbody>'
    
    for item in macro_data:
        price = item["Price"]
        change = item["Change"]
        pct = item["ChangePct"]
        
        pnl_class = "bloomberg-green-text" if change >= 0 else "bloomberg-red-text"
        sign = "+" if change >= 0 else ""
        
        sym = item["Symbol"]
        if sym == "^TNX":
            price_str = f"{price:.3f}%"
            change_str = f"{change:+.3f}"
        elif "USD" in sym or sym == "GC=F" or sym == "CL=F":
            price_str = f"${price:,.2f}"
            change_str = f"{change:+.2f}"
        elif "=X" in sym or "JPY=X" in sym:
            price_str = f"{price:.4f}"
            change_str = f"{change:+.4f}"
        else:
            price_str = f"{price:,.2f}"
            change_str = f"{change:+.2f}"
            
        html += '<tr>'
        html += f'<td class="bloomberg-amber-text" style="text-align: left;"><b>{sym}</b></td>'
        html += f'<td class="bloomberg-white-text" style="text-align: left;">{item["Name"]}</td>'
        html += f'<td class="bloomberg-white-text" style="text-align: right;">{price_str}</td>'
        html += f'<td class="{pnl_class}" style="text-align: right;">{change_str}</td>'
        html += f'<td class="{pnl_class}" style="text-align: right;">{pct:+.2f}%</td>'
        html += '</tr>'
        
    html += '</tbody></table>'
    return html

def make_bloomberg_news_html(news_items):
    """Formats financial news feeds like retro scrolling ticker logs."""
    html = '<div style="font-family: \'Courier New\', Courier, monospace; color: #00ff00;">'
    if not news_items:
        html += '<div class="bloomberg-amber-text">> NO NEWS HEADLINES CURRENTLY LOADED</div>'
        html += '</div>'
        return html
    for item in news_items:
        title = item["Titel"].upper()
        pub = item["Herausgeber"].upper()
        date = item["Datum"]
        link = item["Link"]
        
        if len(title) > 100:
            title = title[:97] + "..."
            
        html += f'<div style="margin-bottom: 12px; border-bottom: 1px dashed #222; padding-bottom: 8px;">'
        html += f'<span class="bloomberg-cyan-text">[{pub}]</span> '
        html += f'<span class="bloomberg-gray-text">({date})</span><br>'
        html += f'<a href="{link}" target="_blank" class="bloomberg-white-text" style="text-decoration: none;"><b>{title}</b></a>'
        html += f'</div>'
    html += '</div>'
    return html

def render_bloomberg_tab():
    """Main rendering entrypoint that manages state, routes commands, and draws the terminal layout."""
    # Inject scoped style sheet for Bloomberg theme styling
    st.markdown("""
    <style>
    .bloomberg-wrapper {
        background-color: #000000;
        color: #00ff00;
        font-family: 'Courier New', Courier, monospace;
        padding: 15px;
        border: 2px solid #333333;
        border-radius: 4px;
        margin-bottom: 20px;
    }
    
    .bloomberg-title-bar {
        background-color: #002244;
        color: #00ffff;
        font-size: 1.1rem;
        padding: 6px 12px;
        font-weight: bold;
        border-bottom: 2px solid #0088ff;
        display: flex;
        justify-content: space-between;
        margin-bottom: 15px;
    }
    
    .bloomberg-table {
        width: 100%;
        border-collapse: collapse;
        color: #00ff00;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.95rem;
    }
    
    .bloomberg-table th {
        border-bottom: 2px solid #444444;
        color: #00ffff;
        padding: 8px 4px;
        font-weight: bold;
    }
    
    .bloomberg-table td {
        border-bottom: 1px solid #222222;
        padding: 8px 4px;
    }
    
    .bloomberg-amber-text { color: #ffb300 !important; }
    .bloomberg-green-text { color: #00ff00 !important; }
    .bloomberg-red-text { color: #ff3333 !important; }
    .bloomberg-cyan-text { color: #00ffff !important; }
    .bloomberg-white-text { color: #ffffff !important; }
    .bloomberg-gray-text { color: #888888 !important; }
    
    .bloomberg-stat-box {
        background-color: #0c0c0c;
        border: 1px solid #222222;
        border-radius: 4px;
        padding: 12px;
        text-align: center;
    }
    
    .bloomberg-box {
        border: 1px solid #222222;
        background-color: #050505;
        padding: 12px;
        border-radius: 4px;
        margin-bottom: 15px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Initialize States
    if "bbg_screen" not in st.session_state:
        st.session_state["bbg_screen"] = "PORT"
    if "bbg_ticker" not in st.session_state:
        st.session_state["bbg_ticker"] = "AAPL"
        
    clocks, active_markets = get_market_clocks()
    
    # Draw Clock Banner
    clocks_html = f"""
    <div style="background-color: #0c0c0c; border: 1px solid #222222; padding: 10px; border-radius: 4px; font-family: 'Courier New', Courier, monospace; margin-bottom: 15px;">
        <div style="display: flex; justify-content: space-around; flex-wrap: wrap; text-align: center;">
            <div style="margin: 5px 10px;">
                <span class="bloomberg-gray-text">NEW YORK (EST/EDT)</span><br>
                <span class="bloomberg-white-text" style="font-size:1.2rem; font-weight:bold;">{clocks["NEW YORK"]}</span><br>
                <span class="{'bloomberg-green-text' if active_markets['NY'] else 'bloomberg-red-text'}" style="font-size:0.8rem; font-weight:bold;">
                    {'● OPEN' if active_markets['NY'] else '○ CLOSED'}
                </span>
            </div>
            <div style="margin: 5px 10px;">
                <span class="bloomberg-gray-text">LONDON (GMT/BST)</span><br>
                <span class="bloomberg-white-text" style="font-size:1.2rem; font-weight:bold;">{clocks["LONDON"]}</span><br>
                <span class="{'bloomberg-green-text' if active_markets['NY'] else 'bloomberg-red-text'}" style="font-size:0.8rem; font-weight:bold;">
                    {'● OPEN' if active_markets['NY'] else '○ CLOSED'}
                </span>
            </div>
            <div style="margin: 5px 10px;">
                <span class="bloomberg-gray-text">FRANKFURT (CET/CEST)</span><br>
                <span class="bloomberg-white-text" style="font-size:1.2rem; font-weight:bold;">{clocks["FRANKFURT"]}</span><br>
                <span class="{'bloomberg-green-text' if active_markets['FFM'] else 'bloomberg-red-text'}" style="font-size:0.8rem; font-weight:bold;">
                    {'● OPEN' if active_markets['FFM'] else '○ CLOSED'}
                </span>
            </div>
            <div style="margin: 5px 10px;">
                <span class="bloomberg-gray-text">TOKYO (JST)</span><br>
                <span class="bloomberg-white-text" style="font-size:1.2rem; font-weight:bold;">{clocks["TOKYO"]}</span><br>
                <span class="{'bloomberg-green-text' if active_markets['TKY'] else 'bloomberg-red-text'}" style="font-size:0.8rem; font-weight:bold;">
                    {'● OPEN' if active_markets['TKY'] else '○ CLOSED'}
                </span>
            </div>
        </div>
    </div>
    """
    
    st.markdown('<div class="bloomberg-title-bar"><span>📟 BLOOMBERG PROFESSIONAL SERVICES</span><span><kbd>HELP</kbd> FOR MENU</span></div>', unsafe_allow_html=True)
    st.markdown(clocks_html, unsafe_allow_html=True)
    
    # Bloomberg Command Input Line
    col_cmd, col_btn = st.columns([4, 8])
    
    with col_cmd:
        cmd_input = st.text_input(
            "CMD>", 
            placeholder="Type Ticker (e.g. TSLA, NVDA) or PORT, WEIS, NEWS, HELP...", 
            key="bbg_cmd_field",
            label_visibility="collapsed"
        )
        
        if cmd_input:
            cmd = cmd_input.strip().upper()
            if cmd in ["PORT", "DEPOT", "PORTFOLIO"]:
                st.session_state["bbg_screen"] = "PORT"
            elif cmd in ["WEIS", "WORLD", "MARKETS"]:
                st.session_state["bbg_screen"] = "WEIS"
            elif cmd in ["NEWS", "HEADLINES"]:
                st.session_state["bbg_screen"] = "NEWS"
            elif cmd in ["MACR", "MACRO"]:
                st.session_state["bbg_screen"] = "MACR"
            elif cmd in ["HELP", "?"]:
                st.session_state["bbg_screen"] = "HELP"
            else:
                st.session_state["bbg_screen"] = "TICKER"
                st.session_state["bbg_ticker"] = cmd
                
    with col_btn:
        col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
        with col_b1:
            if st.button("💼 PORT (Depot)", key="bbg_btn_port", use_container_width=True):
                st.session_state["bbg_screen"] = "PORT"
        with col_b2:
            if st.button("🌍 WEIS (Markets)", key="bbg_btn_weis", use_container_width=True):
                st.session_state["bbg_screen"] = "WEIS"
        with col_b3:
            if st.button("📊 MACR (Macro)", key="bbg_btn_macr", use_container_width=True):
                st.session_state["bbg_screen"] = "MACR"
        with col_b4:
            if st.button("📰 NEWS (Feed)", key="bbg_btn_news", use_container_width=True):
                st.session_state["bbg_screen"] = "NEWS"
        with col_b5:
            if st.button("❓ HELP", key="bbg_btn_help", use_container_width=True):
                st.session_state["bbg_screen"] = "HELP"
                
    # Refresh Checkbox
    col_ref, col_spacer = st.columns([5, 7])
    with col_ref:
        auto_refresh = st.checkbox("Auto-Refresh Terminal Display (15s)", value=False, key="bbg_auto_refresh")
        
    st.markdown("<hr style='border: 1px solid #222; margin: 10px 0;'>", unsafe_allow_html=True)
    
    # Router logic
    screen = st.session_state["bbg_screen"]
    
    if screen == "PORT":
        st.markdown("<h3 class='bloomberg-amber-text' style='margin-top: 0;'>💼 DEPO-MONITOR: PORTFOLIO HOLDINGS OVERVIEW</h3>", unsafe_allow_html=True)
        
        alpaca_ok = is_alpaca_configured()
        positions = []
        acc_info = {}
        
        if alpaca_ok:
            try:
                positions = get_positions()
                acc_info = get_account_info()
            except Exception:
                alpaca_ok = False
                
        if alpaca_ok and positions:
            df_port = get_portfolio_data(alpaca_positions=positions)
            cash = float(acc_info.get("cash", 0))
            portfolio_value = float(acc_info.get("equity", 0))
            buying_power = float(acc_info.get("buying_power", 0))
            
            last_equity = float(acc_info.get("last_equity", portfolio_value))
            day_pnl = portfolio_value - last_equity
            day_pnl_pct = (day_pnl / last_equity) * 100.0 if last_equity > 0 else 0.0
            
            total_cost = df_port["Cost Basis"].sum()
            total_pnl = portfolio_value - (total_cost + cash)
            total_pnl_pct = (total_pnl / total_cost) * 100.0 if total_cost > 0 else 0.0
            pnl_status_text = "LIVE ALPACA BROKERAGE ACCOUNT"
        else:
            # Mock portfolio prices live
            with st.spinner("Aktualisiere Marktpreise für Musterdepot..."):
                mock_tickers = [item["symbol"] for item in MOCK_PORTFOLIO]
                mock_prices = fetch_prices_for_tickers(mock_tickers)
                
            df_port = get_portfolio_data(mock_prices=mock_prices)
            cash = 50000.0
            holdings_value = df_port["Market Value"].sum()
            portfolio_value = holdings_value + cash
            buying_power = cash * 2.0
            
            day_pnl = 0.0
            for _, row in df_port.iterrows():
                try:
                    ticker = row["Symbol"]
                    t = yf.Ticker(ticker)
                    hist = t.history(period="2d")
                    if len(hist) >= 2:
                        prev_close = hist["Close"].iloc[-2]
                        day_change = row["Last"] - prev_close
                        day_pnl += day_change * row["Qty"]
                except Exception:
                    pass
                    
            day_pnl_pct = (day_pnl / portfolio_value) * 100.0 if portfolio_value > 0 else 0.0
            total_cost = df_port["Cost Basis"].sum()
            total_pnl = holdings_value - total_cost
            total_pnl_pct = (total_pnl / total_cost) * 100.0 if total_cost > 0 else 0.0
            pnl_status_text = "SIMULATED DEMO PORTFOLIO (MUSTERDEPOT)"
            
        # Draw Summary Stats Panel
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        
        with col_s1:
            st.markdown(f"""
            <div class="bloomberg-stat-box">
                <span class="bloomberg-gray-text" style="font-size:0.75rem; font-weight:bold;">TOTAL EQUITY VALUE</span><br>
                <span class="bloomberg-white-text" style="font-size:1.5rem; font-weight:bold;">${portfolio_value:,.2f}</span>
            </div>
            """, unsafe_allow_html=True)
            
        with col_s2:
            st.markdown(f"""
            <div class="bloomberg-stat-box">
                <span class="bloomberg-gray-text" style="font-size:0.75rem; font-weight:bold;">CASH / BUYING POWER</span><br>
                <span class="bloomberg-cyan-text" style="font-size:1.25rem; font-weight:bold;">${cash:,.2f}</span><br>
                <span class="bloomberg-gray-text" style="font-size:0.7rem;">BP: ${buying_power:,.2f}</span>
            </div>
            """, unsafe_allow_html=True)
            
        with col_s3:
            pnl_color_class = "bloomberg-green-text" if total_pnl >= 0 else "bloomberg-red-text"
            pnl_sign = "+" if total_pnl >= 0 else ""
            st.markdown(f"""
            <div class="bloomberg-stat-box">
                <span class="bloomberg-gray-text" style="font-size:0.75rem; font-weight:bold;">UNREALIZED P&L</span><br>
                <span class="{pnl_color_class}" style="font-size:1.25rem; font-weight:bold;">{pnl_sign}${total_pnl:,.2f}</span><br>
                <span class="{pnl_color_class}" style="font-size:0.8rem; font-weight:bold;">{pnl_sign}{total_pnl_pct:.2f}%</span>
            </div>
            """, unsafe_allow_html=True)
            
        with col_s4:
            day_pnl_class = "bloomberg-green-text" if day_pnl >= 0 else "bloomberg-red-text"
            day_pnl_sign = "+" if day_pnl >= 0 else ""
            st.markdown(f"""
            <div class="bloomberg-stat-box">
                <span class="bloomberg-gray-text" style="font-size:0.75rem; font-weight:bold;">DAILY CHANGE</span><br>
                <span class="{day_pnl_class}" style="font-size:1.25rem; font-weight:bold;">{day_pnl_sign}${day_pnl:,.2f}</span><br>
                <span class="{day_pnl_class}" style="font-size:0.8rem; font-weight:bold;">{day_pnl_sign}{day_pnl_pct:.2f}%</span>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown(f"<div style='text-align: right; font-size: 0.8rem; margin: 8px 0;' class='bloomberg-amber-text'>MODE: {pnl_status_text}</div>", unsafe_allow_html=True)
        
        # Draw Positions Table
        html_table = make_bloomberg_table(df_port, portfolio_value - cash)
        st.markdown(html_table, unsafe_allow_html=True)
        
    elif screen == "WEIS" or screen == "MACR":
        st.markdown("<h3 class='bloomberg-amber-text' style='margin-top: 0;'>🌍 WORLD MARKTÜBERSICHT: MAIN MACRO DATA FEEDS</h3>", unsafe_allow_html=True)
        
        with st.spinner("Lade globale Wirtschaftsdaten..."):
            macro_data = fetch_bloomberg_macro()
            
        if macro_data:
            indices = [x for x in macro_data if x["Symbol"] in ["^GSPC", "^IXIC", "^DJI", "^GDAXI", "^N225"]]
            bonds_curr = [x for x in macro_data if x["Symbol"] in ["^TNX", "EURUSD=X", "GBPUSD=X", "JPY=X"]]
            comm_crypto = [x for x in macro_data if x["Symbol"] in ["GC=F", "CL=F", "BTC-USD"]]
            
            col_m1, col_m2 = st.columns(2)
            
            with col_m1:
                st.markdown("<h4 class='bloomberg-cyan-text'>[INDEX] MAJOR STOCK INDEX MONITOR</h4>", unsafe_allow_html=True)
                if indices:
                    st.markdown(make_bloomberg_macro_table(indices), unsafe_allow_html=True)
                else:
                    st.markdown("<div class='bloomberg-red-text'>Fehler beim Laden der Indizes.</div>", unsafe_allow_html=True)
                    
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("<h4 class='bloomberg-cyan-text'>[COMM] COMMODITIES & CRYPTO INDICATORS</h4>", unsafe_allow_html=True)
                if comm_crypto:
                    st.markdown(make_bloomberg_macro_table(comm_crypto), unsafe_allow_html=True)
                else:
                    st.markdown("<div class='bloomberg-red-text'>Fehler beim Laden von Rohstoffen/Krypto.</div>", unsafe_allow_html=True)
                    
            with col_m2:
                st.markdown("<h4 class='bloomberg-cyan-text'>[CURR] FIXED INCOME & CURRENCY RATES</h4>", unsafe_allow_html=True)
                if bonds_curr:
                    st.markdown(make_bloomberg_macro_table(bonds_curr), unsafe_allow_html=True)
                else:
                    st.markdown("<div class='bloomberg-red-text'>Fehler beim Laden von Währungen/Anleihen.</div>", unsafe_allow_html=True)
                    
                st.markdown("<br>", unsafe_allow_html=True)
                # Static system box
                st.markdown("""
                <div class="bloomberg-box">
                    <h5 class="bloomberg-amber-text" style="margin:0 0 6px 0;">[SYSTEM] ECONOMIC NOTES</h5>
                    <p style="font-size:0.8rem; line-height:1.4; margin:0;" class="bloomberg-white-text">
                        ● US 10-Year yield stabilizes as traders gauge inflation indicators.<br>
                        ● ECB keeps interest rates unchanged in current session.<br>
                        ● WTI Crude climbs above standard baseline averages.<br>
                        ● Crypto markets consolidated with reduced momentum levels.
                    </p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.error("Es konnten keine Makrodaten abgerufen werden.")
            
    elif screen == "NEWS":
        st.markdown("<h3 class='bloomberg-amber-text' style='margin-top: 0;'>📰 GLOBAL FINANCIAL NEWS TICKER</h3>", unsafe_allow_html=True)
        
        with st.spinner("Rufe aktuelle Nachrichten ab..."):
            news_items = fetch_company_news("SPY")
            
        st.markdown(make_bloomberg_news_html(news_items), unsafe_allow_html=True)
        
    elif screen == "HELP":
        st.markdown("<h3 class='bloomberg-amber-text' style='margin-top: 0;'>⌨️ BBG TERMINAL COMMAND REFERENCE GUIDE</h3>", unsafe_allow_html=True)
        
        help_html = """
        <div style="font-family: 'Courier New', Courier, monospace;" class="bloomberg-white-text">
            <h4 class="bloomberg-cyan-text">AVAILABLE COMMANDS AND FUNCTIONS:</h4>
            
            <p>Type any of these commands inside the <b>CMD></b> prompt and hit Enter:</p>
            
            <table class="bloomberg-table" style="margin-top:15px;">
                <thead>
                    <tr>
                        <th style="width:25%; text-align: left;">COMMAND</th>
                        <th style="text-align: left;">FUNCTION SUMMARY</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td class="bloomberg-amber-text"><b>PORT</b></td>
                        <td>Loads total Portfolio Monitor (Musterdepot or live Alpaca account if configured).</td>
                    </tr>
                    <tr>
                        <td class="bloomberg-amber-text"><b>WEIS</b> or <b>MACR</b></td>
                        <td>Loads World Equity Indices, Currency Rates, Yields and Commodity Futures.</td>
                    </tr>
                    <tr>
                        <td class="bloomberg-amber-text"><b>NEWS</b></td>
                        <td>Retrieves top global market news headlines from real-time feeds.</td>
                    </tr>
                    <tr>
                        <td class="bloomberg-amber-text"><b>[TICKER]</b></td>
                        <td>Type any stock symbol (e.g. <b>AAPL</b>, <b>NVDA</b>, <b>TSLA</b>) to open the profile details page.</td>
                    </tr>
                    <tr>
                        <td class="bloomberg-amber-text"><b>HELP</b></td>
                        <td>Opens this quick start command dictionary sheet.</td>
                    </tr>
                </tbody>
            </table>
            
            <br>
            <h4 class="bloomberg-cyan-text">BLOOMBERG TERMINAL CLONE DETAILS:</h4>
            <p style="font-size:0.9rem; line-height:1.5;">
                This workspace mimics standard trading terminal designs: green/red denote price directions, amber denotes actions and commands, and cyan defines headings. The clock widget dynamically checks trading sessions in major cities.
            </p>
        </div>
        """
        st.markdown(help_html, unsafe_allow_html=True)
        
    elif screen == "TICKER":
        ticker = st.session_state["bbg_ticker"]
        st.markdown(f"<h3 class='bloomberg-amber-text' style='margin-top: 0;'>📊 SECURITY PROFILE: {ticker} US EQUITY</h3>", unsafe_allow_html=True)
        
        with st.spinner(f"Lade Profildaten für {ticker}..."):
            try:
                t_obj = yf.Ticker(ticker)
                info = t_obj.info
            except Exception:
                info = None
                
        if not info or len(info) <= 5:
            st.markdown(f"""
            <div style="background-color: #110000; border: 2px solid #ff3333; padding: 20px; border-radius: 4px; font-family: 'Courier New', Courier, monospace; text-align: center; margin: 20px 0;">
                <h3 class="bloomberg-red-text">🚨 ERROR: SECURITY NOT FOUND</h3>
                <p class="bloomberg-white-text" style="font-size: 1.1rem; margin: 10px 0;">
                    TICKER SYMBOL <span class="bloomberg-amber-text"><b>{ticker}</b></span> CANNOT BE RESOLVED.
                </p>
                <p class="bloomberg-gray-text" style="font-size: 0.9rem;">
                    Please input a valid US Equity ticker like AAPL, MSFT, TSLA, NVDA or return to PORT via command.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            company_name = info.get("longName", info.get("shortName", ticker))
            sector = info.get("sector", "N/A")
            industry = info.get("industry", "N/A")
            price = info.get("currentPrice") or info.get("previousClose") or info.get("regularMarketPrice") or 0.0
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or price
            change = price - prev_close
            change_pct = (change / prev_close) * 100.0 if prev_close else 0.0
            
            pnl_color = "bloomberg-green-text" if change >= 0 else "bloomberg-red-text"
            pnl_sign = "+" if change >= 0 else ""
            
            st.markdown(f"""
            <div class="bloomberg-box">
                <div style="display:flex; justify-content:space-between; flex-wrap:wrap;">
                    <div>
                        <span style="font-size:1.35rem; font-weight:bold;" class="bloomberg-cyan-text">{company_name}</span><br>
                        <span class="bloomberg-gray-text">SECTOR: {sector} | INDUSTRY: {industry}</span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size:1.5rem; font-weight:bold;" class="bloomberg-white-text">${price:,.2f}</span><br>
                        <span class="{pnl_color}" style="font-size:1.05rem; font-weight:bold;">{pnl_sign}${change:,.2f} ({pnl_sign}{change_pct:.2f}%)</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Key Ratios Grid
            col_d1, col_d2, col_d3 = st.columns(3)
            
            with col_d1:
                st.markdown("<h4 class='bloomberg-cyan-text'>[MKT] MARKET STATS</h4>", unsafe_allow_html=True)
                open_val = info.get("open")
                high_val = info.get("dayHigh")
                low_val = info.get("dayLow")
                volume = info.get("volume")
                avg_volume = info.get("averageVolume")
                beta = info.get("beta")
                high_52 = info.get("fiftyTwoWeekHigh")
                low_52 = info.get("fiftyTwoWeekLow")
                
                mkt_html = f"""
                <table class="bloomberg-table">
                    <tr><td class="bloomberg-gray-text">OPEN</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(open_val, "currency")}</td></tr>
                    <tr><td class="bloomberg-gray-text">DAY HIGH</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(high_val, "currency")}</td></tr>
                    <tr><td class="bloomberg-gray-text">DAY LOW</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(low_val, "currency")}</td></tr>
                    <tr><td class="bloomberg-gray-text">VOLUME</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(volume, "int")}</td></tr>
                    <tr><td class="bloomberg-gray-text">AVG VOLUME</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(avg_volume, "int")}</td></tr>
                    <tr><td class="bloomberg-gray-text">52W HIGH</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(high_52, "currency")}</td></tr>
                    <tr><td class="bloomberg-gray-text">52W LOW</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(low_52, "currency")}</td></tr>
                    <tr><td class="bloomberg-gray-text">BETA (3Y)</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(beta)}</td></tr>
                </table>
                """
                st.markdown(mkt_html, unsafe_allow_html=True)
                
            with col_d2:
                st.markdown("<h4 class='bloomberg-cyan-text'>[VAL] VALUATION FEEDS</h4>", unsafe_allow_html=True)
                mkt_cap = info.get("marketCap")
                ev = info.get("enterpriseValue")
                pe = info.get("trailingPE")
                fwd_pe = info.get("forwardPE")
                pb = info.get("priceToBook")
                ps = info.get("priceToSalesTrailing12Months")
                dy = info.get("dividendYield")
                
                val_html = f"""
                <table class="bloomberg-table">
                    <tr><td class="bloomberg-gray-text">MARKET CAP</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(mkt_cap, "billions")}</td></tr>
                    <tr><td class="bloomberg-gray-text">ENT. VALUE</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(ev, "billions")}</td></tr>
                    <tr><td class="bloomberg-gray-text">PE RATIO</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(pe)}</td></tr>
                    <tr><td class="bloomberg-gray-text">FORWARD PE</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(fwd_pe)}</td></tr>
                    <tr><td class="bloomberg-gray-text">PRICE/BOOK</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(pb)}</td></tr>
                    <tr><td class="bloomberg-gray-text">PRICE/SALES</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(ps)}</td></tr>
                    <tr><td class="bloomberg-gray-text">DIV YIELD</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(dy, "percent_raw")}</td></tr>
                </table>
                """
                st.markdown(val_html, unsafe_allow_html=True)
                
            with col_d3:
                st.markdown("<h4 class='bloomberg-cyan-text'>[FIN] BALANCE & MARGINS</h4>", unsafe_allow_html=True)
                de = info.get("debtToEquity")
                cr = info.get("currentRatio")
                qr = info.get("quickRatio")
                roe = info.get("returnOnEquity")
                roa = info.get("returnOnAssets")
                pm = info.get("profitMargins")
                om = info.get("operatingMargins")
                
                fin_html = f"""
                <table class="bloomberg-table">
                    <tr><td class="bloomberg-gray-text">DEBT/EQUITY</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(de, suffix="%")}</td></tr>
                    <tr><td class="bloomberg-gray-text">CURRENT RATIO</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(cr)}</td></tr>
                    <tr><td class="bloomberg-gray-text">QUICK RATIO</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(qr)}</td></tr>
                    <tr><td class="bloomberg-gray-text">ROE</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(roe, "percent_raw")}</td></tr>
                    <tr><td class="bloomberg-gray-text">ROA</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(roa, "percent_raw")}</td></tr>
                    <tr><td class="bloomberg-gray-text">PROFIT MARGIN</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(pm, "percent_raw")}</td></tr>
                    <tr><td class="bloomberg-gray-text">OPERATING MARGIN</td><td class="bloomberg-white-text" style="text-align: right;">{format_val(om, "percent_raw")}</td></tr>
                </table>
                """
                st.markdown(fin_html, unsafe_allow_html=True)
                
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Matplotlib Chart Panel
            st.markdown("<h4 class='bloomberg-cyan-text'>[GP] GRAPH HISTORICAL PERFORMANCE</h4>", unsafe_allow_html=True)
            col_ch1, col_ch2 = st.columns([9, 3])
            
            with col_ch2:
                period_choice = st.selectbox(
                    "TIME FRAME",
                    ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                    index=3,
                    key="bbg_ticker_period"
                )
                theme_choice = st.radio(
                    "MONITOR COLOR",
                    ["Amber Amber", "Phosphor Green"],
                    index=0,
                    key="bbg_ticker_theme"
                )
                
            with col_ch1:
                hist_df = t_obj.history(period=period_choice)
                if not hist_df.empty:
                    theme_name = "amber" if "Amber" in theme_choice else "green"
                    chart_buf = plot_terminal_chart(hist_df, ticker, theme=theme_name)
                    st.image(chart_buf, use_container_width=True)
                else:
                    st.error("Konnte historische Kursdaten für Chart nicht abrufen.")
                    
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Ticker specific news
            st.markdown(f"<h4 class='bloomberg-cyan-text'>[NEWS] HEADLINES FOR {ticker}</h4>", unsafe_allow_html=True)
            ticker_news = fetch_company_news(ticker)
            st.markdown(make_bloomberg_news_html(ticker_news), unsafe_allow_html=True)
            
    # Sleep & rerun for auto-refresh
    if auto_refresh:
        time.sleep(15)
        st.rerun()
