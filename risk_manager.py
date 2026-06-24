import os
import io
import time
import requests
import re
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# ReportLab Imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# Import credentials and order client from alpaca_trader
from alpaca_trader import get_alpaca_credentials, get_positions, get_account_info, is_alpaca_configured
from options_advisor import calculate_black_scholes_metrics

# Load configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def parse_osi_symbol(symbol: str) -> dict:
    """
    Parses option symbol in OSI format.
    E.g. TLT260624C00070000 -> Ticker: TLT, Expiry: 2026-06-24, Type: call, Strike: 70.0
    """
    match = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", symbol)
    if match:
        ticker, expiry, otype, strike_raw = match.groups()
        strike = float(strike_raw) / 1000.0
        return {
            "is_option": True,
            "underlying": ticker,
            "expiry": f"20{expiry[:2]}-{expiry[2:4]}-{expiry[4:]}",
            "type": "call" if otype == "C" else "put",
            "strike": strike
        }
    return {"is_option": False, "underlying": symbol}

def get_underlying_price_and_delta(symbol: str) -> tuple[float, float, str]:
    """
    Gets the current underlying price and option delta if it is an option.
    Returns (underlying_price, delta, underlying_symbol).
    """
    parsed = parse_osi_symbol(symbol)
    if parsed["is_option"]:
        underlying = parsed["underlying"]
        # Fetch current price of underlying
        try:
            tk = yf.Ticker(underlying)
            hist = tk.history(period="1d")
            s = hist["Close"].iloc[-1] if not hist.empty else 100.0
        except Exception:
            s = 100.0
            
        # Estimate delta using Black-Scholes
        k = parsed["strike"]
        # calculate remaining days to expiry
        today = datetime.now().date()
        try:
            expiry_dt = datetime.strptime(parsed["expiry"], "%Y-%m-%d").date()
            days = max((expiry_dt - today).days, 1)
        except Exception:
            days = 30
            
        option_type = parsed["type"]
        # Default parameters: 4.5% interest, 25% Implied Volatility
        delta, _ = calculate_black_scholes_metrics(s=s, k=k, days=days, r=0.045, iv=0.25, option_type=option_type)
        return s, delta, underlying
    else:
        # Standard Stock / ETF
        try:
            tk = yf.Ticker(symbol)
            hist = tk.history(period="1d")
            s = hist["Close"].iloc[-1] if not hist.empty else 100.0
        except Exception:
            s = 100.0
        return s, 1.0, symbol

def get_portfolio_beta(ticker: str) -> float:
    """Returns estimated beta for the ticker relative to S&P 500."""
    betas = {
        "SPY": 1.0, "IVV": 1.0, "VOO": 1.0,
        "QQQ": 1.25, "IWM": 1.15,
        "TLT": -0.15, "IEF": -0.05, "SHY": 0.0,
        "AAPL": 1.15, "MSFT": 1.10, "GOOGL": 1.15, "AMZN": 1.20, "TSLA": 1.55, "NVDA": 1.70,
        "GLD": 0.05, "SLV": 0.15, "USO": 0.80
    }
    return betas.get(ticker, 1.0)

def fetch_portfolio_positions() -> list[dict]:
    """
    Fetches positions from Alpaca. If empty or not configured,
    returns a mock portfolio containing the Option A Synthetic Short setup.
    """
    positions = []
    if is_alpaca_configured():
        alp_positions = get_positions()
        for p in alp_positions:
            symbol = p["symbol"]
            qty = float(p["qty"])
            market_val = float(p["market_value"])
            avg_entry = float(p["avg_entry_price"])
            
            # Get underlying and delta
            s, delta, underlying = get_underlying_price_and_delta(symbol)
            beta = get_portfolio_beta(underlying)
            
            positions.append({
                "symbol": symbol,
                "qty": qty,
                "market_value": market_val,
                "price": market_val / qty if qty != 0 else 0.0,
                "underlying": underlying,
                "underlying_price": s,
                "delta": delta,
                "beta": beta,
                "is_option": symbol != underlying
            })
            
    if not positions:
        # Load mock portfolio representing Option A and some tech/index allocations
        # Let's say: 100 SPY, 1 contract TLT Synthetic Short (Long Put, Short Call at $90)
        mock_positions = [
            {"symbol": "SPY", "qty": 100, "market_value": 48000.0, "price": 480.0, "underlying": "SPY", "underlying_price": 480.0, "delta": 1.0, "beta": 1.0, "is_option": False},
            {"symbol": "TLT260717P00090000", "qty": 1, "market_value": 150.0, "price": 150.0, "underlying": "TLT", "underlying_price": 90.0, "delta": -0.50, "beta": -0.15, "is_option": True},
            {"symbol": "TLT260717C00090000", "qty": -1, "market_value": -140.0, "price": 140.0, "underlying": "TLT", "underlying_price": 90.0, "delta": -0.50, "beta": -0.15, "is_option": True} # short call has short delta
        ]
        return mock_positions
        
    return positions

def calculate_portfolio_var(positions: list[dict], confidence=0.95) -> tuple[float, float]:
    """
    Calculates Parametric Value at Risk (VaR) based on historical standard deviation.
    confidence: 0.95 or 0.99
    Returns (VaR_USD, VaR_Percent)
    """
    total_val = sum(abs(p["market_value"]) for p in positions)
    if total_val == 0:
        return 0.0, 0.0
        
    # Gather historical prices of underlyings
    underlyings = list(set(p["underlying"] for p in positions))
    
    # Fetch 30 days of history
    hist_data = {}
    for u in underlyings:
        try:
            tk = yf.Ticker(u)
            hist = tk.history(period="1mo")["Close"]
            if not hist.empty:
                hist_data[u] = hist.pct_change().dropna()
        except Exception:
            pass
            
    if not hist_data:
        # Default standard deviation of 1.5% if no history available
        std_dev = 0.015
    else:
        # Align series into a DataFrame
        df_rets = pd.DataFrame(hist_data)
        
        # Calculate portfolio returns
        # Weight each asset by its relative absolute market value
        weights = {}
        for p in positions:
            u = p["underlying"]
            w = abs(p["market_value"]) / total_val
            # Accumulate weight for underlying
            weights[u] = weights.get(u, 0.0) + w
            
        df_rets["Portfolio"] = 0.0
        for u, w in weights.items():
            if u in df_rets.columns:
                df_rets["Portfolio"] += df_rets[u] * w
                
        std_dev = df_rets["Portfolio"].std()
        if pd.isna(std_dev) or std_dev == 0:
            std_dev = 0.015
            
    # Z-Score
    z = 1.645 if confidence == 0.95 else 2.33
    
    # 1-day VaR
    var_pct = z * std_dev
    var_usd = total_val * var_pct
    
    return var_usd, var_pct

def run_stress_test(positions: list[dict]) -> list[dict]:
    """
    Runs stress test scenarios on the portfolio.
    Returns a list of scenario results containing estimated impact.
    """
    scenarios = [
        {
            "name": "Black Monday (Market Crash -20%, VIX Surge)",
            "description": "S&P 500 loses 20%. Flight to safety pushes Bonds (TLT/IEF) +5%. High beta stocks fall heavily.",
            "equity_shock": -0.20,
            "bond_shock": 0.05,
            "commodity_shock": -0.05
        },
        {
            "name": "Yield Shock (Rates +150bps)",
            "description": "US Interest rates surge 150bps. Bond prices plunge: TLT falls 24%, IEF falls 11%. Equity markets contract 10%.",
            "equity_shock": -0.10,
            "bond_shock": -0.20, # weighted average bond crash
            "commodity_shock": -0.05
        },
        {
            "name": "Inflation / Stagflation Shock",
            "description": "CPI spikes. Commodities (GLD/USO) jump +15%. Tech stocks sell off -15%. Bonds fall -8%.",
            "equity_shock": -0.15,
            "bond_shock": -0.08,
            "commodity_shock": 0.15
        }
    ]
    
    results = []
    for sc in scenarios:
        stressed_positions = []
        total_loss = 0.0
        portfolio_init_val = 0.0
        
        for p in positions:
            symbol = p["symbol"]
            val = p["market_value"]
            underlying = p["underlying"]
            is_opt = p["is_option"]
            delta = p["delta"]
            beta = p["beta"]
            qty = p["qty"]
            
            portfolio_init_val += val
            
            # Determine which shock applies to this asset class
            if underlying in ["TLT", "IEF", "SHY"]:
                shock = sc["bond_shock"]
            elif underlying in ["GLD", "SLV", "USO"]:
                shock = sc["commodity_shock"]
            else:
                # Equities: apply market shock weighted by beta
                shock = sc["equity_shock"] * beta
                
            # Calculate position change
            if is_opt:
                # Option price change estimated by delta
                # Option price = Premium. Total value = Premium * 100 * Qty
                # Delta = Change in option premium / change in underlying price
                # Change in premium = Delta * (Change in underlying)
                # Underlying change = underlying_price * shock
                underlying_change = p["underlying_price"] * shock
                premium_change = delta * underlying_change
                # Total change = premium_change * 100 * Qty
                # Wait, if Qty is negative (short call), the loss is inverted
                val_change = premium_change * 100 * qty
            else:
                # Stock/ETF price change
                val_change = val * shock
                
            total_loss += val_change
            stressed_val = val + val_change
            
            stressed_positions.append({
                "symbol": symbol,
                "initial_value": val,
                "change": val_change,
                "stressed_value": stressed_val
            })
            
        results.append({
            "name": sc["name"],
            "description": sc["description"],
            "initial_portfolio_value": portfolio_init_val,
            "stressed_portfolio_value": portfolio_init_val + total_loss,
            "impact_usd": total_loss,
            "impact_pct": (total_loss / portfolio_init_val * 100.0) if portfolio_init_val != 0 else 0.0,
            "positions": stressed_positions
        })
        
    return results

def generate_risk_report_pdf(
    account_info: dict,
    positions: list[dict],
    var_95: tuple[float, float],
    var_99: tuple[float, float],
    stress_results: list[dict]
) -> str:
    """
    Generates a ReportLab PDF Report in the reports/ folder.
    Returns the absolute path of the generated PDF.
    """
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"risk_report_{timestamp}.pdf"
    filepath = os.path.join(reports_dir, filename)
    
    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#0d9488'),
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1e3a8a'),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=6
    )
    
    body_bold_style = ParagraphStyle(
        'BodyTextBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    # Header Logo/Title block
    story.append(Paragraph("BLACKGATE CAPITAL", title_style))
    story.append(Paragraph(f"PORTFOLIO RISK & RISK METRICS REPORT | GENERATED AT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
    story.append(Spacer(1, 10))
    
    # Account Summary Block
    story.append(Paragraph("1. Account Overview", h1_style))
    equity = float(account_info.get("equity", 100000.0))
    cash = float(account_info.get("cash", 100000.0))
    buying_power = float(account_info.get("buying_power", 400000.0))
    
    summary_data = [
        [Paragraph("Portfolio Equity (Net Value):", body_bold_style), Paragraph(f"${equity:,.2f}", body_style),
         Paragraph("Free Cash Capital:", body_bold_style), Paragraph(f"${cash:,.2f}", body_style)],
        [Paragraph("Option Buying Power:", body_bold_style), Paragraph(f"${buying_power:,.2f}", body_style),
         Paragraph("Brokerage Connection:", body_bold_style), Paragraph("Alpaca Paper (Verified)" if is_alpaca_configured() else "Fallback Simulation Portfolio", body_style)]
    ]
    t_summary = Table(summary_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch])
    t_summary.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#f3f4f6')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 12))
    
    # Value at Risk (VaR) Block
    story.append(Paragraph("2. Value at Risk (VaR) Analysis", h1_style))
    story.append(Paragraph(
        "Value at Risk (VaR) estimates the maximum potential loss in the portfolio over a 1-day holding period "
        "at a specific confidence level based on historical daily volatility from the past 30 days.", body_style
    ))
    
    var_data = [
        [Paragraph("Confidence Level", body_bold_style), Paragraph("Z-Score", body_bold_style), Paragraph("1-Day VaR (%)", body_bold_style), Paragraph("1-Day VaR (USD Risk)", body_bold_style)],
        [Paragraph("95% (Standard Risk)", body_style), Paragraph("1.645", body_style), Paragraph(f"{var_95[1]*100:.2f}%", body_style), Paragraph(f"${var_95[0]:,.2f}", body_bold_style)],
        [Paragraph("99% (Extreme Stress)", body_style), Paragraph("2.33", body_style), Paragraph(f"{var_99[1]*100:.2f}%", body_style), Paragraph(f"${var_99[0]:,.2f}", body_bold_style)]
    ]
    t_var = Table(var_data, colWidths=[2.0 * inch, 1.2 * inch, 1.8 * inch, 2.2 * inch])
    t_var.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    # Quick fix for text color in ReportLab table headers
    for i in range(4):
        var_data[0][i].style.textColor = colors.white
    story.append(t_var)
    story.append(Spacer(1, 12))
    
    # Current Positions Table
    story.append(Paragraph("3. Active Portfolio Positions", h1_style))
    pos_headers = [
        Paragraph("Asset Ticker", body_bold_style),
        Paragraph("Quantity", body_bold_style),
        Paragraph("Market Value", body_bold_style),
        Paragraph("Delta", body_bold_style),
        Paragraph("Beta", body_bold_style),
        Paragraph("Asset Class", body_bold_style)
    ]
    pos_data = [pos_headers]
    for p in positions:
        pos_data.append([
            Paragraph(p["symbol"], body_style),
            Paragraph(f"{p['qty']}", body_style),
            Paragraph(f"${p['market_value']:,.2f}", body_style),
            Paragraph(f"{p['delta']:.2f}" if p['is_option'] else "1.00", body_style),
            Paragraph(f"{p['beta']:.2f}", body_style),
            Paragraph("Option Contract" if p['is_option'] else "Stock / ETF", body_style)
        ])
        
    t_pos = Table(pos_data, colWidths=[1.8 * inch, 1.0 * inch, 1.4 * inch, 1.0 * inch, 1.0 * inch, 1.3 * inch])
    t_pos.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f3f4f6')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_pos)
    story.append(Spacer(1, 12))
    
    # Stress Test Results Block
    story.append(Paragraph("4. Macroeconomic Stress Testing Scenarios", h1_style))
    story.append(Paragraph(
        "Historical or hypothetical shock simulations applied to the underlying values of the portfolio assets. "
        "Option re-evaluations are computed using Delta approximations.", body_style
    ))
    
    stress_headers = [
        Paragraph("Stress Scenario", body_bold_style),
        Paragraph("Underlying Description", body_bold_style),
        Paragraph("Stressed Portfolio Value", body_bold_style),
        Paragraph("Estimated Loss (USD)", body_bold_style),
        Paragraph("Impact (%)", body_bold_style)
    ]
    stress_table_data = [stress_headers]
    for res in stress_results:
        impact_color = colors.HexColor('#b91c1c') if res['impact_usd'] < 0 else colors.HexColor('#15803d')
        stress_table_data.append([
            Paragraph(res["name"], body_bold_style),
            Paragraph(res["description"], body_style),
            Paragraph(f"${res['stressed_portfolio_value']:,.2f}", body_style),
            Paragraph(f"${res['impact_usd']:,.2f}", ParagraphStyle('LossVal', parent=body_style, textColor=impact_color, fontName='Helvetica-Bold')),
            Paragraph(f"{res['impact_pct']:.2f}%", ParagraphStyle('LossPct', parent=body_style, textColor=impact_color, fontName='Helvetica-Bold'))
        ])
        
    t_stress = Table(stress_table_data, colWidths=[1.8 * inch, 2.2 * inch, 1.4 * inch, 1.2 * inch, 0.9 * inch])
    t_stress.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f3f4f6')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_stress)
    story.append(Spacer(1, 15))
    
    # Strategic Risk Control Recommendations
    story.append(Paragraph("5. Strategic Recommendations & Actions", h1_style))
    
    rec_text = "<b>Portfolio Risk Profile:</b> "
    # Dynamic recommendation
    any_short_call = any(p["is_option"] and p["qty"] < 0 and p["symbol"].endswith("00") for p in positions) # short options check
    if any_short_call:
        rec_text += (
            "Detected active short option call exposures (e.g. Option A Call leg). "
            "Under severe upside shocks or interest rate cuts, these naked short legs pose substantial unlimited risk. "
            "Ensure a strict stop-loss orders are placed at 5% above underlying strike. "
            "Consider purchasing an out-of-the-money Call option to convert the naked short call into a Bear Call Spread / Iron Condor structure."
        )
    else:
        rec_text += (
            "The portfolio currently consists of standard diversified index and bond holdings. "
            "To guard against the simulated 'Black Monday' scenario (-20% market crash), "
            "it is recommended to purchase index hedges (e.g. SPY Put Options with 10% OTM distance and 45 DTE) "
            "which will yield significant net credits or offset equity losses under stress."
        )
        
    story.append(Paragraph(rec_text, body_style))
    
    doc.build(story)
    
    # Also save a copy as a static file in the base stock_screener directory for quick access
    latest_report_path = os.path.join(os.path.dirname(__file__), "reports", "latest_risk_report.pdf")
    try:
        import shutil
        shutil.copy(filepath, latest_report_path)
    except Exception:
        pass
        
    return filepath

def run_risk_manager_run() -> str:
    """Executes a single check and generates a PDF report."""
    print("Fetching portfolio details...")
    acc_info = get_account_info()
    if not acc_info:
        # Default mock account info
        acc_info = {"equity": 100000.0, "cash": 100000.0, "buying_power": 400000.0}
        
    positions = fetch_portfolio_positions()
    print(f"Loaded {len(positions)} positions.")
    
    print("Calculating Value at Risk...")
    var_95 = calculate_portfolio_var(positions, 0.95)
    var_99 = calculate_portfolio_var(positions, 0.99)
    print(f"  VaR 95%: ${var_95[0]:,.2f} ({var_95[1]*100:.2f}%)")
    print(f"  VaR 99%: ${var_99[0]:,.2f} ({var_99[1]*100:.2f}%)")
    
    print("Executing Stress Tests...")
    stress_results = run_stress_test(positions)
    for s in stress_results:
        print(f"  Scenario: {s['name']} -> Est. Impact: ${s['impact_usd']:,.2f} ({s['impact_pct']:.2f}%)")
        
    print("Generating PDF Risk Report...")
    pdf_path = generate_risk_report_pdf(acc_info, positions, var_95, var_99, stress_results)
    print(f"Report saved to: {pdf_path}")
    return pdf_path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Blackgate Capital Risk Manager Bot")
    parser.add_argument("--daemon", action="store_true", help="Start as daemon bot running every 10 minutes")
    args = parser.parse_args()
    
    if args.daemon:
        print("Starting Risk Manager Bot in Daemon Mode (Running every 10 minutes)...")
        print("To stop, press Ctrl+C.")
        while True:
            try:
                run_risk_manager_run()
                print(f"Waiting 10 minutes before next run... (Next run at {datetime.now().hour:02d}:{datetime.now().minute:02d})")
                time.sleep(600)
            except KeyboardInterrupt:
                print("Risk Manager Bot stopped by user.")
                break
            except Exception as e:
                print(f"Error in Risk Manager Loop: {e}")
                time.sleep(60) # wait 1 min before retrying if there's a connection crash
    else:
        print("Starting Risk Manager Bot (One-Shot Mode)...")
        run_risk_manager_run()
