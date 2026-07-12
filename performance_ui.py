import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import math
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Alpaca / Portfolio Imports
from alpaca_trader import is_alpaca_configured, get_positions
from track_record_generator import get_alpaca_portfolio_history
from risk_manager import parse_osi_symbol

# ReportLab Imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.lib.units import inch

# Load env variables
load_dotenv(override=True)

# CSS for DC Comic Style - Arkham Asylum Aesthetic
ARKHAM_STYLE = """
<style>
    /* Arkham Theme Container */
    .arkham-container {
        background-color: #0b0c10;
        border: 4px solid #1f2833;
        padding: 20px;
        border-radius: 10px;
        color: #c5c6c7;
        font-family: 'Courier New', Courier, monospace;
        margin-bottom: 25px;
        box-shadow: 8px 8px 0px #1f2833;
    }
    
    /* Comic Title Style */
    .arkham-title {
        font-family: 'Impact', 'Arial Black', sans-serif;
        color: #ff0055; /* Joker Pink/Red */
        text-transform: uppercase;
        font-size: 3rem;
        letter-spacing: 3px;
        text-shadow: 3px 3px 0px #00ffcc, 6px 6px 0px #000; /* Toxic Cyan & Black shadow */
        margin-bottom: 10px;
        text-align: center;
        border-bottom: 5px dashed #ff0055;
        padding-bottom: 10px;
    }
    
    .arkham-subtitle {
        font-family: 'Courier New', Courier, monospace;
        color: #00ffcc; /* Toxic Cyan */
        font-weight: bold;
        font-size: 1.2rem;
        text-align: center;
        margin-bottom: 30px;
    }
    
    /* Comic Panel Style (Cards) */
    .comic-panel {
        background-color: #1a1a24;
        border: 3px solid #000;
        border-radius: 4px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 5px 5px 0px #ff0055; /* Bright Pink Offset Shadow */
        transition: transform 0.2s;
    }
    
    .comic-panel:hover {
        transform: translate(-2px, -2px);
        box-shadow: 7px 7px 0px #00ffcc; /* Glowing cyan hover shadow */
    }
    
    .comic-panel-title {
        font-family: 'Impact', sans-serif;
        text-transform: uppercase;
        color: #ffea00; /* Bat-Yellow */
        font-size: 1.3rem;
        letter-spacing: 1px;
        border-bottom: 2px solid #000;
        margin-bottom: 10px;
        padding-bottom: 5px;
    }
    
    .comic-panel-value {
        font-family: 'Courier New', Courier, monospace;
        font-size: 1.8rem;
        font-weight: 900;
        color: #ffffff;
    }
    
    /* Sound effect badge (e.g. POW!, BAM!, OOF!) */
    .sfx-badge {
        display: inline-block;
        background-color: #ffea00;
        color: #000;
        font-family: 'Impact', sans-serif;
        font-size: 1rem;
        padding: 3px 8px;
        border: 2px solid #000;
        transform: rotate(-3deg);
        box-shadow: 2px 2px 0px #000;
        font-weight: bold;
        text-transform: uppercase;
        margin-right: 5px;
    }
    
    .sfx-green {
        background-color: #00ffcc;
    }
    
    .sfx-red {
        background-color: #ff0055;
        color: #fff;
    }
    
    .sfx-purple {
        background-color: #a855f7;
        color: #fff;
    }

    /* Warning strip */
    .warning-strip {
        background: repeating-linear-gradient(
          -45deg,
          #ffea00,
          #ffea00 10px,
          #000000 10px,
          #000000 20px
        );
        height: 12px;
        margin: 15px 0;
        border: 1px solid #000;
    }
</style>
"""

def get_period_dates(period: str):
    """Calculates start and end dates based on a string code (1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, Custom)."""
    end_date = datetime.now()
    if period == "1M":
        start_date = end_date - timedelta(days=30)
    elif period == "3M":
        start_date = end_date - timedelta(days=90)
    elif period == "6M":
        start_date = end_date - timedelta(days=180)
    elif period == "1Y":
        start_date = end_date - timedelta(days=365)
    elif period == "3Y":
        start_date = end_date - timedelta(days=365 * 3)
    elif period == "5Y":
        start_date = end_date - timedelta(days=365 * 5)
    elif period == "YTD":
        start_date = datetime(end_date.year, 1, 1)
    else: # Fallback to 1Y
        start_date = end_date - timedelta(days=365)
    return start_date, end_date

@st.cache_data(ttl=3600)
def fetch_benchmark_data(tickers, start_date, end_date):
    """Fetches benchmark closing prices and returns daily percentage returns."""
    data = {}
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            # Fetch extra days to avoid missing data at boundary
            hist = tk.history(start=start_date - timedelta(days=5), end=end_date + timedelta(days=1))["Close"]
            if not hist.empty:
                # Remove timezone to prevent pandas comparison errors
                hist.index = hist.index.tz_localize(None)
                data[ticker] = hist
        except Exception as e:
            st.error(f"Fehler beim Laden des Benchmarks {ticker}: {e}")
    
    if not data:
        return pd.DataFrame()
        
    df = pd.DataFrame(data)
    # Forward fill to handle non-trading days differences
    df = df.ffill().bfill()
    # Filter to exact requested start_date
    df = df[df.index >= pd.to_datetime(start_date)]
    return df

@st.cache_data(ttl=3600)
def fetch_portfolio_components_data(tickers, start_date, end_date):
    """Fetches closing prices for portfolio components."""
    data = {}
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(start=start_date - timedelta(days=5), end=end_date + timedelta(days=1))["Close"]
            if not hist.empty:
                hist.index = hist.index.tz_localize(None)
                data[ticker] = hist
        except Exception:
            pass
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data).ffill().bfill()
    df = df[df.index >= pd.to_datetime(start_date)]
    return df

def calculate_detailed_metrics(prices_series: pd.Series, spy_returns: pd.Series = None, risk_free_rate=0.045) -> dict:
    """Calculates all key performance figures (returns, vol, Sharpe, Sortino, Max Drawdown, Beta, Alpha)."""
    returns = prices_series.pct_change().dropna()
    if returns.empty:
        return {"return": 0.0, "ann_return": 0.0, "vol": 0.0, "sharpe": 0.0, "sortino": 0.0, "drawdown": 0.0, "beta": 1.0, "alpha": 0.0}
        
    total_return = (prices_series.iloc[-1] / prices_series.iloc[0] - 1) * 100.0
    
    # Total trading days in sample
    trading_days = len(prices_series)
    
    # Annualized Return
    if trading_days > 10:
        ann_return = ((prices_series.iloc[-1] / prices_series.iloc[0]) ** (252 / trading_days) - 1) * 100.0
    else:
        ann_return = total_return
        
    # Annualized Volatility
    vol = returns.std() * math.sqrt(252) * 100.0
    
    # Sharpe Ratio (using annualized values)
    excess_return = ann_return - (risk_free_rate * 100.0)
    sharpe = excess_return / vol if vol > 0 else 0.0
    
    # Downside Volatility for Sortino
    negative_returns = returns[returns < 0]
    downside_vol = negative_returns.std() * math.sqrt(252) * 100.0
    sortino = excess_return / downside_vol if downside_vol > 0 else 0.0
    
    # Max Drawdown
    cum_returns = prices_series / prices_series.iloc[0]
    running_max = cum_returns.cummax()
    drawdowns = (cum_returns - running_max) / running_max
    max_drawdown = drawdowns.min() * 100.0
    
    # Beta and Alpha (vs SPY)
    beta = 1.0
    alpha = 0.0
    if spy_returns is not None and len(spy_returns) == len(returns):
        try:
            cov = np.cov(returns, spy_returns)[0][1]
            spy_var = np.var(spy_returns)
            if spy_var > 0:
                beta = cov / spy_var
                
            # Annualized Alpha (Jensen's Alpha)
            # Alpha = Port_Ann_Return - [Risk_Free + Beta * (SPY_Ann_Return - Risk_Free)]
            # We calculate this using decimals, then convert to percentage.
            spy_ann_return = ((1 + spy_returns).prod() ** (252 / len(spy_returns)) - 1)
            port_ann_return_dec = ann_return / 100.0
            alpha_dec = port_ann_return_dec - (risk_free_rate + beta * (spy_ann_return - risk_free_rate))
            alpha = alpha_dec * 100.0
        except Exception:
            pass
            
    return {
        "return": total_return,
        "ann_return": ann_return,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "drawdown": max_drawdown,
        "beta": beta,
        "alpha": alpha
    }

def generate_reportlab_pdf(df_history, metrics_data, period_str) -> bytes:
    """
    Generates a beautifully designed DC Comic style / Arkham Research dossier PDF.
    Returns the PDF as raw bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Comic/Noir Styles
    title_style = ParagraphStyle(
        'ComicTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=26,
        leading=30,
        textColor=colors.HexColor('#ff0055'), # Joker Pink
        alignment=1, # Centered
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'ComicSub',
        parent=styles['Normal'],
        fontName='Helvetica-BoldOblique',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#00ffcc'), # Toxic Cyan
        alignment=1,
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'ComicH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=colors.HexColor('#ffea00'), # Bat Yellow
        spaceBefore=15,
        spaceAfter=8,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'ComicBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#d1d5db'), # Light Grey
        spaceAfter=8
    )
    
    bold_body = ParagraphStyle(
        'ComicBodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    stamp_style = ParagraphStyle(
        'StampText',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.HexColor('#ff0055'),
        alignment=1
    )
    
    story = []
    
    # Header Banner - Simulated comic book title frame
    banner_data = [
        [Paragraph("ARKHAM RESEARCH", title_style)],
        [Paragraph("PORTFOLIO PERFORMANCE DOSSIER // TOP SECRET", subtitle_style)]
    ]
    banner_table = Table(banner_data, colWidths=[540])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0d0f12')),
        ('BOX', (0,0), (-1,-1), 3, colors.HexColor('#ffea00')), # thick yellow frame
        ('TOPPADDING', (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    
    story.append(banner_table)
    story.append(Spacer(1, 15))
    
    # Executive Summary with Classified Stamp
    summary_text = (
        "<b>ANALYSEBERICHT DER PORTFOLIO-PERFORMANCE</b><br/>"
        "Dieses Dokument enthält die vertraulichen Leistungsdaten des Arkham-Research Fundings. "
        "Verglichen wird die Performance des Depots mit den führenden globalen Benchmarks: "
        "<b>SPDR S&P 500 ETF (SPY)</b>, <b>Invesco QQQ Trust (QQQ)</b>, sowie dem <b>IQ Hedge Multi-Strategy ETF (QAI)</b> "
        "als Benchmark für die durchschnittliche Hedgefonds-Rendite.<br/><br/>"
        "Die Berechnungen basieren auf dem gewählten Beobachtungszeitraum: <b>{}</b>. "
        "Kennzahlen wie die Sharpe-Ratio verwenden eine risikofreie Rendite (Risk-Free Rate) von 4.5% p.a."
    ).format(period_str)
    
    # Classified Stamp Table
    stamp_data = [[
        Paragraph(summary_text, body_style),
        Table([[Paragraph("CLASSIFIED<br/>ARKHAM<br/>INTELLIGENCE", stamp_style)]], colWidths=[120])
    ]]
    
    summary_table = Table(stamp_data, colWidths=[400, 140])
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOX', (1,0), (1,0), 2, colors.HexColor('#ff0055')), # Red stamp frame
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#1f131a')),
        ('TOPPADDING', (1,0), (1,0), 10),
        ('BOTTOMPADDING', (1,0), (1,0), 10),
        ('LEFTPADDING', (1,0), (1,0), 5),
        ('RIGHTPADDING', (1,0), (1,0), 5),
    ]))
    
    story.append(summary_table)
    story.append(Spacer(1, 15))
    
    # Metrics Table
    story.append(Paragraph("VERGLEICHENDE KENNZAHLEN (BENCHMARKING)", h1_style))
    
    table_data = [
        ["Benchmark / Index", "Gesamt-Rendite", "Ann. Rendite", "Ann. Volatilität", "Sharpe Ratio", "Max. Drawdown", "Beta vs SPY"]
    ]
    for key, metrics in metrics_data.items():
        table_data.append([
            key,
            f"{metrics['return']:+.2f}%",
            f"{metrics['ann_return']:+.2f}%",
            f"{metrics['vol']:.2f}%",
            f"{metrics['sharpe']:.2f}",
            f"{metrics['drawdown']:+.2f}%",
            f"{metrics['beta']:.2f}"
        ])
        
    metrics_table = Table(table_data, colWidths=[160, 68, 64, 78, 58, 68, 44])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a1a24')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#ffea00')), # yellow header text
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('GRID', (0,0), (-1,-1), 1.5, colors.HexColor('#ff0055')), # Pink borders
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#0f0f15')),
        ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#e5e7eb')),
        ('FONTNAME', (0,1), (0,-1), 'Helvetica-Bold'), # Ticker bold
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 15))
    
    # Performance Chart Section
    story.append(Paragraph("KUMULATIVE WERTENTWICKLUNG (RE-BASED AUF 100)", h1_style))
    
    # We will generate the matplotlib chart and save it as an image buffer, then load it in reportlab
    plt.figure(figsize=(10, 4.5))
    plt.style.use('dark_background')
    
    # Set background colors specifically
    fig = plt.gcf()
    fig.patch.set_facecolor('#0d0f12')
    ax = plt.gca()
    ax.set_facecolor('#1a1a24')
    
    # Re-base histories to 100
    colors_map = {
        "Arkham Portfolio": "#00ffcc",  # toxic cyan
        "S&P 500 (SPY)": "#ff0055",     # joker red
        "NASDAQ-100 (QQQ)": "#2563eb",  # dark blue
        "Hedge Fund Index (QAI)": "#ffea00" # bat yellow
    }
    
    for col in df_history.columns:
        lbl = col
        if col == "Portfolio":
            lbl = "Arkham Portfolio"
        color = colors_map.get(lbl, "#ffffff")
        lw = 2.5 if lbl == "Arkham Portfolio" else 1.2
        ls = "-" if lbl == "Arkham Portfolio" else "--"
        alpha = 1.0 if lbl == "Arkham Portfolio" else 0.7
        
        rebased = (df_history[col] / df_history[col].iloc[0]) * 100
        plt.plot(df_history.index, rebased, label=lbl, color=color, linewidth=lw, linestyle=ls, alpha=alpha)
        
    plt.title("Arkham Portfolio vs Benchmarks (Start = 100)", fontsize=11, fontname="sans-serif", color="#ffea00", weight="bold")
    plt.grid(True, color="#2f3542", linestyle=":", alpha=0.5)
    plt.legend(loc="upper left", frameon=True, facecolor="#0d0f12", edgecolor="#ff0055")
    plt.tick_params(colors='#d1d5db', labelsize=8)
    
    # Format labels
    plt.xlabel("Datum", color='#9ca3af', fontsize=8)
    plt.ylabel("Verlauf (%)", color='#9ca3af', fontsize=8)
    
    plt.tight_layout()
    
    chart_buffer = io.BytesIO()
    plt.savefig(chart_buffer, format='png', dpi=200, bbox_inches='tight', facecolor='#0d0f12')
    chart_buffer.seek(0)
    plt.close()
    
    story.append(Image(chart_buffer, width=540, height=243))
    story.append(Spacer(1, 10))
    
    # Warnings and Disclaimers
    story.append(Paragraph("RISIKOHINWEIS & METHODIK", h1_style))
    story.append(Paragraph(
        "<b>Risiko-Kennzahlen:</b> Sharpe-Ratio und Sortino-Ratio werden auf Jahresbasis berechnet. "
        "Ein hohes Beta (&gt; 1.0) signalisiert eine überproportionale Markt-Sensitivität, während ein positives Alpha "
        "die Outperformance (Mehrrendite) gegenüber dem S&P 500 nach Risiko-Bereinigung widerspiegelt. "
        "Die historische Performance ist keine Garantie für zukünftige Erträge.<br/>"
        "<b>Hedgefonds-Index (QAI):</b> Repräsentiert eine marktneutrale Multi-Asset-Hedgefonds-Replikation. "
        "Das Arkham-Portfolio zielt darauf ab, diese durch quantitatives Screening und derivatbasierte Hedging-Methoden "
        "deutlich zu übertreffen.",
        body_style
    ))
    
    # Footer / Caution Strip
    story.append(Spacer(1, 10))
    caution_data = [[""]]
    caution_table = Table(caution_data, colWidths=[540], rowHeights=[10])
    caution_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ffea00')), # yellow bar
        ('BOX', (0,0), (-1,-1), 1, colors.black),
    ]))
    story.append(caution_table)
    
    # Page template setup to use dark background for the whole PDF if desired
    def draw_background(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#090a0f'))
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=True, stroke=False)
        
        # Border
        canvas.setStrokeColor(colors.HexColor('#1f2833'))
        canvas.setLineWidth(4)
        canvas.rect(10, 10, doc.pagesize[0]-20, doc.pagesize[1]-20)
        
        # Strip details (Arkham Logo placeholder / Comic sound)
        canvas.setStrokeColor(colors.HexColor('#ff0055'))
        canvas.setLineWidth(1)
        canvas.line(10, 50, doc.pagesize[0]-10, 50)
        canvas.setFillColor(colors.HexColor('#ffea00'))
        canvas.setFont('Helvetica-Bold', 8)
        canvas.drawString(20, 25, "ARKHAM RESEARCH LABS - GOTHAM CITY // DATA DOSSIER")
        canvas.drawRightString(doc.pagesize[0]-20, 25, f"SEITE 1 / 1")
        canvas.restoreState()
        
    doc.build(story, onFirstPage=draw_background)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

def render_performance_tab():
    """Renders the Arkham Research Performance Tab."""
    # Inject Custom CSS
    st.markdown(ARKHAM_STYLE, unsafe_allow_html=True)
    
    # Main Title
    st.markdown('<div class="arkham-title">Arkham Research</div>', unsafe_allow_html=True)
    st.markdown('<div class="arkham-subtitle">🦇 Gotham City Portfolio Performance & Benchmarking 🦇</div>', unsafe_allow_html=True)
    
    # Check for logo
    if os.path.exists("arkham_logo.jpg"):
        col_logo, col_desc = st.columns([1, 4])
        with col_logo:
            st.image("arkham_logo.jpg", use_column_width=True)
        with col_desc:
            st.markdown("""
            **Willkommen im Arkham Research Performance-Desk.**
            
            Dieses Cockpit analysiert das Risikoprofil, die Volatilität und die Rendite-Kennzahlen Ihres Fundings. 
            Vergleichen Sie Ihr Portfolio live mit dem breiten Aktienmarkt (**SPY**), dem Tech-Sektor (**QQQ**) und dem globalen **Hedge-Fonds-Index** (QAI), um das generierte Alpha zu validieren.
            """)
    else:
        st.markdown("""
        **Willkommen im Arkham Research Performance-Desk.**
        
        Dieses Cockpit analysiert das Risikoprofil, die Volatilität und die Rendite-Kennzahlen Ihres Fundings. 
        Vergleichen Sie Ihr Portfolio live mit dem breiten Aktienmarkt (**SPY**), dem Tech-Sektor (**QQQ**) und dem globalen **Hedge-Fonds-Index** (QAI), um das generierte Alpha zu validieren.
        """)
        
    st.markdown('<div class="warning-strip"></div>', unsafe_allow_html=True)
    
    # Sidebar Configuration within the tab using layout columns
    col_conf1, col_conf2 = st.columns(2)
    
    with col_conf1:
        st.subheader("📊 Portfolio-Allokation")
        
        # Portfolio Source
        portfolio_mode = st.radio(
            "Portfolio-Quelle wählen:",
            ["Alpaca Depot-Verbindung (Live/Paper)", "Simuliertes Portfolio (Eigene Gewichtung)"],
            index=0 if is_alpaca_configured() else 1,
            help="Alpaca lädt die aktuellen Bestände. Die Simulation erlaubt die Eingabe eigener Werte."
        )
        
        # Risk free rate
        rf_rate = st.slider("Risikofreier Zinssatz (%) (Sharpe-Ratio)", 0.0, 10.0, 4.5, 0.1) / 100.0
        
    with col_conf2:
        st.subheader("⚙️ Analyse-Parameter")
        
        # Timeframe
        period_choice = st.selectbox(
            "Beobachtungszeitraum",
            ["1 Monat", "3 Monate", "6 Monate", "Year-To-Date (YTD)", "1 Jahr", "3 Jahre", "5 Jahre"],
            index=4
        )
        
        period_map = {
            "1 Monat": "1M",
            "3 Monate": "3M",
            "6 Monate": "6M",
            "Year-To-Date (YTD)": "YTD",
            "1 Jahr": "1Y",
            "3 Jahre": "3Y",
            "5 Jahre": "5Y"
        }
        period = period_map[period_choice]
        
        # Custom benchmarks input
        benchmarks_input = st.text_input("Benchmark-Tickers (Komma-separiert)", "SPY, QQQ, QAI")
        bench_list = [b.strip().upper() for b in benchmarks_input.split(",") if b.strip()]
        
    st.markdown("<br/>", unsafe_allow_html=True)
    
    # Custom Simulated Portfolio Holdings Editor
    custom_holdings = None
    if portfolio_mode == "Simuliertes Portfolio (Eigene Gewichtung)":
        st.markdown("##### 📝 Eigene Allokation definieren")
        st.markdown("<small>Geben Sie die Ticker und deren prozentuale Gewichtung an (wird automatisch auf 100% normalisiert):</small>", unsafe_allow_html=True)
        
        # Create default holdings DataFrame
        default_holdings = pd.DataFrame([
            {"Ticker": "SPY", "Gewichtung %": 40.0},
            {"Ticker": "QQQ", "Gewichtung %": 35.0},
            {"Ticker": "TLT", "Gewichtung %": 15.0},
            {"Ticker": "AAPL", "Gewichtung %": 10.0}
        ])
        
        # st.data_editor to let the user add/delete/modify holdings
        edited_df = st.data_editor(
            default_holdings,
            num_rows="dynamic",
            use_container_width=True,
            key="custom_portfolio_editor"
        )
        
        # Validate edited holdings
        if not edited_df.empty:
            edited_df["Ticker"] = edited_df["Ticker"].astype(str).str.strip().str.upper()
            edited_df["Gewichtung %"] = pd.to_numeric(edited_df["Gewichtung %"], errors='coerce').fillna(0.0)
            # Remove zero weights and empty tickers
            edited_df = edited_df[(edited_df["Ticker"] != "") & (edited_df["Gewichtung %"] > 0)]
            
            if not edited_df.empty:
                total_weight = edited_df["Gewichtung %"].sum()
                if total_weight > 0:
                    edited_df["Weight"] = edited_df["Gewichtung %"] / total_weight
                    custom_holdings = dict(zip(edited_df["Ticker"], edited_df["Weight"]))
                    
        if not custom_holdings:
            st.error("⚠️ Ungültige Portfolio-Zusammensetzung! Standard-Gewichtung (SPY: 40%, QQQ: 35%, TLT: 15%, AAPL: 10%) wird verwendet.")
            custom_holdings = {"SPY": 0.40, "QQQ": 0.35, "TLT": 0.15, "AAPL": 0.10}
            
    # Run calculation
    st.markdown('<div class="warning-strip"></div>', unsafe_allow_html=True)
    st.markdown("### 🦇 Performance-Auswertung")
    
    with st.spinner("⏳ Bat-Computer analysiert historische Marktdaten..."):
        start_date, end_date = get_period_dates(period)
        
        # 1. Fetch benchmark histories
        df_bench_prices = fetch_benchmark_data(bench_list, start_date, end_date)
        if df_bench_prices.empty:
            st.error("Fehler beim Abrufen der Benchmark-Daten von Yahoo Finance.")
            return
            
        # 2. Get Portfolio Prices / Returns
        df_port_history = pd.DataFrame()
        is_real = False
        
        if portfolio_mode == "Alpaca Depot-Verbindung (Live/Paper)":
            if is_alpaca_configured():
                # Try loading real equity history
                df_port_history = get_alpaca_portfolio_history(period)
                if not df_port_history.empty and len(df_port_history) > 5:
                    df_port_history = df_port_history.rename(columns={"Equity": "Portfolio"}).set_index("Date")
                    is_real = True
            
            if df_port_history.empty:
                if portfolio_mode == "Alpaca Depot-Verbindung (Live/Paper)":
                    st.info("ℹ️ Keine Alpaca-Historie gefunden oder Alpaca nicht konfiguriert. Fallback auf Backtest der aktuellen Alpaca-Positionen.")
                
                # Fallback backtest of current Alpaca positions
                positions = []
                if is_alpaca_configured():
                    try:
                        positions = get_positions()
                    except Exception:
                        pass
                
                # Mock holdings if no positions found
                if not positions:
                    positions = [
                        {"symbol": "SPY", "qty": "50", "market_value": "24000.0"},
                        {"symbol": "QQQ", "qty": "30", "market_value": "12000.0"},
                        {"symbol": "TLT", "qty": "100", "market_value": "9000.0"}
                    ]
                
                total_val = sum(float(p.get("market_value", 0)) for p in positions)
                if total_val <= 0:
                    total_val = 10000.0
                
                alpaca_holdings = {}
                for p in positions:
                    sym = p["symbol"]
                    parsed = parse_osi_symbol(sym)
                    underlying = parsed["underlying"]
                    mkt_val = float(p.get("market_value", 0))
                    alpaca_holdings[underlying] = alpaca_holdings.get(underlying, 0.0) + (mkt_val / total_val)
                    
                custom_holdings = alpaca_holdings
                
        # Calculate simulated returns if custom holdings are defined
        if not is_real and custom_holdings:
            # Fetch components
            tickers_to_fetch = list(custom_holdings.keys())
            df_comp_prices = fetch_portfolio_components_data(tickers_to_fetch, start_date, end_date)
            
            if not df_comp_prices.empty:
                # Calculate returns
                df_comp_rets = df_comp_prices.pct_change().dropna()
                df_comp_rets["Portfolio_Return"] = 0.0
                for sym, weight in custom_holdings.items():
                    if sym in df_comp_rets.columns:
                        df_comp_rets["Portfolio_Return"] += df_comp_rets[sym] * weight
                
                # Reconstruct portfolio equity curve
                start_equity = 10000.0
                cum_ret = (1 + df_comp_rets["Portfolio_Return"]).cumprod()
                df_port_history = pd.DataFrame({
                    "Portfolio": start_equity * cum_ret
                })
                # Re-index to match df_bench_prices
                df_port_history.index = df_comp_rets.index
        
        if df_port_history.empty:
            st.error("Fehler beim Rekonstruieren der Portfolio-Historie. Überprüfen Sie die Ticker-Eingaben.")
            return
            
        # Align all series
        df_all = df_port_history.join(df_bench_prices, how="inner")
        df_all = df_all.ffill().bfill()
        
        if df_all.empty or len(df_all) < 5:
            st.error("Nicht genügend deckungsgleiche Handelsdaten für das Portfolio und die Benchmarks vorhanden.")
            return
            
        # 3. Calculate Performance Metrics
        spy_col = "SPY" if "SPY" in df_all.columns else (df_bench_prices.columns[0] if not df_bench_prices.empty else None)
        spy_returns = df_all[spy_col].pct_change().dropna() if spy_col else None
        
        metrics_data = {}
        
        # Calculate for Portfolio
        metrics_data["Arkham Portfolio"] = calculate_detailed_metrics(df_all["Portfolio"], spy_returns, rf_rate)
        
        # Calculate for Benchmarks
        for col in df_bench_prices.columns:
            lbl = f"S&P 500 (SPY)" if col == "SPY" else (f"NASDAQ-100 (QQQ)" if col == "QQQ" else (f"Hedge Fund Index (QAI)" if col == "QAI" else col))
            metrics_data[lbl] = calculate_detailed_metrics(df_all[col], spy_returns, rf_rate)
            
        # Display Visual Panels / Comic Cards
        p_metrics = metrics_data["Arkham Portfolio"]
        
        # Comic badges logic
        ret_sfx = "KAPOW!" if p_metrics['return'] >= 10 else ("BAM!" if p_metrics['return'] >= 0 else "CRASH!")
        sharpe_sfx = "GENIUS!" if p_metrics['sharpe'] >= 1.5 else ("BULLSEYE!" if p_metrics['sharpe'] >= 1.0 else "MEH...")
        dd_sfx = "UNSCATHED!" if p_metrics['drawdown'] >= -5.0 else ("OOF!" if p_metrics['drawdown'] >= -15.0 else "ARGH!")
        alpha_sfx = "BAT-SIGNAL!" if p_metrics['alpha'] > 0 else "NO ALBEDO"
        
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        
        with col_m1:
            st.markdown(f"""
            <div class="comic-panel">
                <div class="comic-panel-title">Rendite ({period})</div>
                <div class="comic-panel-value">{p_metrics['return']:+.2f}%</div>
                <div style="margin-top: 8px;">
                    <span class="sfx-badge {'sfx-green' if p_metrics['return'] >= 0 else 'sfx-red'}">{ret_sfx}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_m2:
            st.markdown(f"""
            <div class="comic-panel">
                <div class="comic-panel-title">Sharpe Ratio</div>
                <div class="comic-panel-value">{p_metrics['sharpe']:.2f}</div>
                <div style="margin-top: 8px;">
                    <span class="sfx-badge {'sfx-green' if p_metrics['sharpe'] >= 1.0 else ('sfx-purple' if p_metrics['sharpe'] >= 0.5 else 'sfx-red')}">{sharpe_sfx}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_m3:
            st.markdown(f"""
            <div class="comic-panel">
                <div class="comic-panel-title">Max Drawdown</div>
                <div class="comic-panel-value">{p_metrics['drawdown']:+.2f}%</div>
                <div style="margin-top: 8px;">
                    <span class="sfx-badge {'sfx-green' if p_metrics['drawdown'] >= -5.0 else ('sfx-purple' if p_metrics['drawdown'] >= -15.0 else 'sfx-red')}">{dd_sfx}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_m4:
            st.markdown(f"""
            <div class="comic-panel">
                <div class="comic-panel-title">Ann. Excess Alpha</div>
                <div class="comic-panel-value">{p_metrics['alpha']:+.2f}%</div>
                <div style="margin-top: 8px;">
                    <span class="sfx-badge {'sfx-green' if p_metrics['alpha'] > 0 else 'sfx-red'}">{alpha_sfx}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        # Draw Cumulative Line Chart
        st.markdown("#### 📈 Kumulative Performance-Kurve")
        
        # We can construct a matplotlib figure for visual excellence and comic vibes
        fig, ax = plt.subplots(figsize=(10, 4.5))
        plt.style.use('dark_background')
        fig.patch.set_facecolor('#0d0f12')
        ax.set_facecolor('#1a1a24')
        
        colors_map = {
            "Arkham Portfolio": "#00ffcc",  # toxic cyan
            "S&P 500 (SPY)": "#ff0055",     # joker red
            "NASDAQ-100 (QQQ)": "#2563eb",  # dark blue
            "Hedge Fund Index (QAI)": "#ffea00" # bat yellow
        }
        
        for col in df_all.columns:
            lbl = "Arkham Portfolio" if col == "Portfolio" else (f"S&P 500 (SPY)" if col == "SPY" else (f"NASDAQ-100 (QQQ)" if col == "QQQ" else (f"Hedge Fund Index (QAI)" if col == "QAI" else col)))
            color = colors_map.get(lbl, "#ffffff")
            lw = 3.0 if col == "Portfolio" else 1.5
            ls = "-" if col == "Portfolio" else "--"
            alpha = 1.0 if col == "Portfolio" else 0.7
            
            rebased = (df_all[col] / df_all[col].iloc[0]) * 100
            ax.plot(df_all.index, rebased, label=lbl, color=color, linewidth=lw, linestyle=ls, alpha=alpha)
            
        ax.set_title("Kumulative Performance vs Benchmarks (Start = 100)", fontsize=12, color="#ffea00", weight="bold")
        ax.grid(True, color="#2f3542", linestyle=":", alpha=0.5)
        ax.legend(loc="upper left", frameon=True, facecolor="#0d0f12", edgecolor="#ff0055")
        ax.tick_params(colors='#d1d5db', labelsize=10)
        
        ax.set_xlabel("Datum", color='#9ca3af', fontsize=10)
        ax.set_ylabel("Verlauf (%)", color='#9ca3af', fontsize=10)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
        
        # Display Table Comparison
        st.markdown("#### 📋 Performance-Matrix")
        
        # Construct table dataframe
        table_rows = []
        for key, m in metrics_data.items():
            table_rows.append({
                "Index / Benchmark": key,
                "Rendite": f"{m['return']:+.2f}%",
                "Ann. Rendite": f"{m['ann_return']:+.2f}%",
                "Volatilität (ann.)": f"{m['vol']:.2f}%",
                "Sharpe Ratio": f"{m['sharpe']:.2f}",
                "Sortino Ratio": f"{m['sortino']:.2f}",
                "Max. Drawdown": f"{m['drawdown']:+.2f}%",
                "Beta vs SPY": f"{m['beta']:.2f}" if key != "S&P 500 (SPY)" else "1.00",
                "Alpha vs SPY": f"{m['alpha']:+.2f}%" if key != "S&P 500 (SPY)" else "-"
            })
            
        df_table = pd.DataFrame(table_rows)
        
        # Style table using standard dataframe display with full container width
        st.dataframe(df_table, hide_index=True, use_container_width=True)
        
        # 4. Generate & Download PDF Report
        st.markdown('<div class="warning-strip"></div>', unsafe_allow_html=True)
        st.markdown("#### 📄 Finanzbericht erzeugen & herunterladen")
        st.write("Generieren Sie ein offizielles, im Comic-Style gestaltetes Arkham-Research Dossier, das alle Tabellen, Diagramme und statistischen Analysen im PDF-Format enthält.")
        
        # Download button
        try:
            pdf_bytes = generate_reportlab_pdf(df_all, metrics_data, period_choice)
            
            st.download_button(
                label="🦇 DOWNLOAD ARKHAM INTELLIGENCE DOSSIER (PDF)",
                data=pdf_bytes,
                file_name=f"arkham_research_dossier_{period.lower()}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            st.success("Dossier erfolgreich kompiliert! Klicken Sie auf den Button zum Download.")
        except Exception as e:
            st.error(f"Fehler bei der PDF-Generierung: {e}")
            import traceback
            st.code(traceback.format_exc())

if __name__ == "__main__":
    st.set_page_config(layout="wide")
    render_performance_tab()
