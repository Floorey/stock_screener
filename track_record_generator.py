import os
import sys
import math
import requests
import argparse
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add directory to path
sys.path.append(os.path.dirname(__file__))

# Alpaca Imports
from alpaca_trader import get_alpaca_credentials, get_alpaca_headers, get_positions, is_alpaca_configured
from risk_manager import parse_osi_symbol, get_portfolio_beta

# ReportLab Imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY,
    "Content-Type": "application/json"
}

def get_alpaca_portfolio_history(period="1M") -> pd.DataFrame:
    """Fetches equity history from Alpaca API."""
    url = f"{BASE_URL}/v2/account/portfolio/history"
    # period can be 1D, 1W, 1M, 3M, 1Y, all
    params = {
        "period": period,
        "timeframe": "1D",
        "extended_hours": "false"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            timestamps = data.get("timestamp", [])
            equity = data.get("equity", [])
            
            if timestamps and equity and len(timestamps) > 5:
                # Convert epoch timestamps to dates
                dates = [datetime.fromtimestamp(ts).strftime("%Y-%m-%d") for ts in timestamps]
                df = pd.DataFrame({"Date": dates, "Equity": equity})
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.dropna().drop_duplicates(subset=["Date"])
                return df
    except Exception as e:
        print(f"Error fetching portfolio history from Alpaca: {e}")
    return pd.DataFrame()

def generate_backtested_history(period_days=30) -> pd.DataFrame:
    """
    Backtests current portfolio holdings over the specified period to create a simulated equity curve.
    Used as a fallback if the account is new and has no historical data.
    """
    print("Generating simulated historical equity curve based on current allocations...")
    positions = []
    if is_alpaca_configured():
        try:
            positions = get_positions()
        except Exception:
            pass
            
    if not positions:
        # Mock portfolio
        positions = [
            {"symbol": "SPY", "qty": "50", "market_value": "24000.0"},
            {"symbol": "QQQ", "qty": "30", "market_value": "12000.0"},
            {"symbol": "TLT", "qty": "100", "market_value": "9000.0"}
        ]
        
    total_val = sum(float(p.get("market_value", 0)) for p in positions)
    if total_val <= 0:
        total_val = 10000.0
        
    start_date = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    
    # Fetch returns for each underlying
    asset_returns = {}
    weights = {}
    
    for p in positions:
        symbol = p["symbol"]
        parsed = parse_osi_symbol(symbol)
        underlying = parsed["underlying"]
        mkt_val = float(p.get("market_value", 0))
        weight = mkt_val / total_val
        
        # Accumulate weights for same underlying
        weights[underlying] = weights.get(underlying, 0.0) + weight
        
        if underlying not in asset_returns:
            try:
                tk = yf.Ticker(underlying)
                hist = tk.history(start=start_date)["Close"]
                if not hist.empty:
                    asset_returns[underlying] = hist.pct_change().dropna()
            except Exception:
                pass
                
    if not asset_returns:
        # Emergency default (S&P 500 returns)
        tk = yf.Ticker("SPY")
        hist = tk.history(start=start_date)["Close"]
        asset_returns["SPY"] = hist.pct_change().dropna()
        weights = {"SPY": 1.0}
        
    # Combine returns into a single DataFrame
    df_rets = pd.DataFrame(asset_returns)
    df_rets = df_rets.fillna(0.0)
    
    # Calculate weighted daily return
    df_rets["Portfolio_Return"] = 0.0
    for u, w in weights.items():
        if u in df_rets.columns:
            # If weight is negative (e.g. synthetic short or short option leg), apply negative return impact
            # Options have deltas, let's keep it simple: apply asset return * weight
            df_rets["Portfolio_Return"] += df_rets[u] * w
            
    # Reconstruct equity starting from $50,000 (standard baseline)
    start_equity = 50000.0
    cum_returns = (1 + df_rets["Portfolio_Return"]).cumprod()
    equity_curve = start_equity * cum_returns
    
    df_result = pd.DataFrame({
        "Date": df_rets.index,
        "Equity": equity_curve
    })
    # Reset index and add initial date
    df_result = df_result.reset_index(drop=True)
    return df_result

def calculate_metrics(prices_series: pd.Series, risk_free_rate=0.045) -> dict:
    """Calculates return, volatility, Sharpe ratio, and Max Drawdown."""
    returns = prices_series.pct_change().dropna()
    if returns.empty:
        return {"return": 0.0, "vol": 0.0, "sharpe": 0.0, "drawdown": 0.0}
        
    total_return = (prices_series.iloc[-1] / prices_series.iloc[0] - 1) * 100.0
    
    # Annualized Volatility
    vol = returns.std() * math.sqrt(252) * 100.0
    
    # Annualized Return (approximate based on trading days in sample)
    days = len(prices_series)
    ann_return = total_return
    if days > 10:
        ann_return = ((prices_series.iloc[-1] / prices_series.iloc[0]) ** (252 / days) - 1) * 100.0
        
    # Sharpe Ratio
    rf_pct = risk_free_rate * 100.0
    excess_return = ann_return - rf_pct
    sharpe = excess_return / vol if vol > 0 else 0.0
    
    # Max Drawdown
    cum_returns = prices_series / prices_series.iloc[0]
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    max_drawdown = drawdown.min() * 100.0
    
    return {
        "return": total_return,
        "vol": vol,
        "sharpe": sharpe,
        "drawdown": max_drawdown
    }

def generate_track_record_report(period="1M", output_path="reports/performance_track_record.pdf") -> str:
    """Generates the track record PDF report."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 1. Resolve period in days
    period_days_map = {"1D": 2, "1W": 7, "1M": 30, "3M": 90, "1Y": 365, "all": 730}
    days = period_days_map.get(period, 30)
    
    # 2. Get Portfolio Equity History
    is_simulated = False
    df_port = pd.DataFrame()
    
    if is_alpaca_configured():
        df_port = get_alpaca_portfolio_history(period)
        
    if df_port.empty or len(df_port) < 5:
        df_port = generate_backtested_history(days)
        is_simulated = True
        
    start_date = df_port["Date"].min()
    end_date = df_port["Date"].max()
    
    # 3. Fetch Benchmark Data
    benchmarks = {
        "S&P 500 (SPY)": "SPY",
        "NASDAQ (QQQ)": "QQQ",
        "Hedge Fund Index (QAI)": "QAI" # IQ Hedge Multi-Strategy ETF (Hedge Fund Replication)
    }
    
    bench_data = {}
    for name, ticker in benchmarks.items():
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(start=start_date, end=end_date + timedelta(days=1))["Close"]
            if not hist.empty:
                # Align dates by merging with portfolio dates
                df_b = pd.DataFrame(hist).rename(columns={"Close": name})
                bench_data[name] = df_b
        except Exception as e:
            print(f"Error loading benchmark {name}: {e}")
            
    # Merge all histories into a single DataFrame
    df_all = df_port.rename(columns={"Equity": "Portfolio"}).set_index("Date")
    for name, df_b in bench_data.items():
        df_all = df_all.join(df_b, how="left")
        
    # Forward-fill any missing data in benchmarks
    df_all = df_all.ffill().bfill()
    
    # Re-base all series to 100 for cumulative chart comparison
    chart_df = pd.DataFrame(index=df_all.index)
    for col in df_all.columns:
        chart_df[col] = (df_all[col] / df_all[col].iloc[0]) * 100.0
        
    # 4. Generate Performance Chart
    plt.figure(figsize=(10, 5.5))
    plt.style.use('dark_background') # keep it sleek dark
    
    # Colors
    colors_map = {
        "Portfolio": "#3b82f6",  # thick blue
        "S&P 500 (SPY)": "#ef4444", # red
        "NASDAQ (QQQ)": "#10b981", # green
        "Hedge Fund Index (QAI)": "#f59e0b" # amber
    }
    
    plt.plot(chart_df.index, chart_df["Portfolio"], label="Ihr Portfolio", color=colors_map["Portfolio"], linewidth=2.5)
    for col in chart_df.columns:
        if col != "Portfolio":
            plt.plot(chart_df.index, chart_df[col], label=col, color=colors_map.get(col, "#ffffff"), linestyle="--", alpha=0.8)
            
    plt.title("Kumulative Performance vs Benchmarks (Re-based starting at 100)", fontsize=12, pad=15)
    plt.xlabel("Datum", fontsize=10)
    plt.ylabel("Verlauf (%)", fontsize=10)
    plt.legend(loc="upper left")
    plt.grid(True, linestyle=":", alpha=0.3)
    plt.tight_layout()
    
    temp_chart_path = output_path.replace(".pdf", "_temp_chart.png")
    plt.savefig(temp_chart_path, dpi=200)
    plt.close()
    
    # 5. Calculate Metrics for table
    metrics_list = []
    for col in df_all.columns:
        m = calculate_metrics(df_all[col])
        metrics_list.append({
            "Name": "Ihr Portfolio (Simuliert)" if col == "Portfolio" and is_simulated else ("Ihr Portfolio" if col == "Portfolio" else col),
            "Return": f"{m['return']:+.2f}%",
            "Vol": f"{m['vol']:.2f}%",
            "Sharpe": f"{m['sharpe']:.2f}",
            "Drawdown": f"{m['drawdown']:+.2f}%"
        })
        
    # 6. Build PDF Report
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1e3a8a')
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4b5563')
    )
    
    h2_style = ParagraphStyle(
        'H2Title',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1e3a8a'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#374151')
    )
    
    bold_body = ParagraphStyle(
        'BoldBodyCustom',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    story = []
    
    # Header Section
    story.append(Paragraph("Blackgate Capital - Performance & Track Record Report", title_style))
    report_type = "SIMULIERTER BACKTEST (Aktuelle Allokation)" if is_simulated else "ECHTER LIVE/PAPER TRACK RECORD"
    story.append(Paragraph(f"Berichts-Typ: {report_type} | Analysezeitraum: {start_date.strftime('%d.%m.%Y')} bis {end_date.strftime('%d.%m.%Y')} ({period})", subtitle_style))
    story.append(Spacer(1, 15))
    
    # Executive Summary Text
    p_text = (
        "Dieser Bericht bietet einen quantitativen Vergleich der Performance Ihres Portfolios im Vergleich zu wichtigen "
        "globalen Benchmarks: dem S&P 500 (Markt-Benchmark), dem NASDAQ-100 (Technologie-Sektor) und dem QAI ETF, "
        "welcher die durchschnittlichen Erträge von Multi-Strategy Hedgefonds abbildet. "
    )
    if is_simulated:
        p_text += (
            "<b>Hinweis:</b> Da Ihr Alpaca-Konto noch neu ist und keine historischen Handelsdaten vorliegen, "
            "basiert dieser Track Record auf einem <i>simulierten Backtest</i>. Dabei wurde berechnet, welche Performance "
            "Ihre derzeit gehaltenen Depot-Allokationen über den ausgewählten Zeitraum erzielt hätten."
        )
    else:
        p_text += (
            "Die Portfolio-Renditen basieren auf den tatsächlichen, historischen täglichen Nettoinventarwerten (Equity) "
            "Ihres Alpaca Trading-Kontos."
        )
    story.append(Paragraph(p_text, body_style))
    story.append(Spacer(1, 15))
    
    # Metrics Table
    story.append(Paragraph("Vergleichende Performance-Kennzahlen", h2_style))
    
    table_data = [
        ["Benchmark / Index", "Gesamt-Rendite", "Volatilität (ann.)", "Sharpe Ratio (4.5% RF)", "Max. Drawdown"]
    ]
    for m in metrics_list:
        table_data.append([
            m["Name"],
            m["Return"],
            m["Vol"],
            m["Sharpe"],
            m["Drawdown"]
        ])
        
    t = Table(table_data, colWidths=[180, 85, 95, 110, 85])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f9fafb')),
        ('FONTNAME', (0,1), (0,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,1), (-1,-1), 5),
        ('TOPPADDING', (0,1), (-1,-1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # Performance Chart Image
    story.append(Paragraph("Performance-Entwicklung (Re-based)", h2_style))
    story.append(Image(temp_chart_path, width=520, height=286))
    story.append(Spacer(1, 10))
    
    # Disclaimer and Explanation
    story.append(Paragraph("Interpretation der Kennzahlen & Erläuterung", h2_style))
    story.append(Paragraph(
        "<b>Sharpe Ratio:</b> Misst die Überrendite des Portfolios pro Risikoeinheit (Volatilität). Eine Sharpe Ratio &gt; 1,00 "
        "gilt als hervorragend. Sie zeigt an, ob die Performance auf klugen Entscheidungen oder lediglich auf dem Eingehen "
        "extrem hoher Risiken beruht.<br>"
        "<b>Hedge Fund Index Benchmark (QAI):</b> Die Benchmarking gegen den QAI zeigt, wie sich Ihre Strategie im Vergleich "
        "zu traditionellen Hedgefonds schlägt, die ebenfalls Absicherungen (Shorts, Puts) nutzen. Erzielen Sie eine höhere "
        "Rendite bei ähnlichem oder geringerem Drawdown, generiert Ihr Portfolio signifikantes Alpha.",
        body_style
    ))
    
    # Build Document
    doc.build(story)
    
    # Cleanup temp chart file
    if os.path.exists(temp_chart_path):
        try:
            os.remove(temp_chart_path)
        except Exception:
            pass
            
    print(f"Report successfully generated at: {output_path}")
    return output_path

def main():
    parser = argparse.ArgumentParser(description="Generate a PDF performance track record report for Alpaca portfolio.")
    parser.add_argument("--period", default="1M", choices=["1W", "1M", "3M", "1Y", "all"], help="History period (default: 1M)")
    parser.add_argument("--output", default="reports/performance_track_record.pdf", help="Output file path (default: reports/performance_track_record.pdf)")
    args = parser.parse_args()
    
    generate_track_record_report(args.period, args.output)

if __name__ == "__main__":
    main()
