import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from datetime import datetime
from typing import Dict, List, Any

def generate_pdf_report(
    symbol: str,
    company_name: str,
    info: Dict[str, Any],
    long_score: int,
    short_score: int,
    news: List[Dict[str, Any]],
    polymarket: List[Dict[str, Any]],
    analyst_notes: str,
    analyst_name: str,
    recommendation: str
) -> io.BytesIO:
    """
    Generates a professional, print-ready PDF Investment Memo for Blackgate Capital.
    Returns the PDF as a BytesIO stream.
    """
    pdf_buffer = io.BytesIO()
    
    # Page setup
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Define custom corporate styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#1e3a8a'), # Dark Navy
        alignment=0, # Left
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0d9488'), # Teal
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#1e3a8a'),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1f2937'), # Charcoal
        spaceAfter=8
    )
    
    news_title_style = ParagraphStyle(
        'NewsTitle',
        parent=body_style,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#2563eb'), # Blue link-like
        spaceAfter=2
    )
    
    meta_label_style = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#4b5563')
    )
    
    meta_val_style = ParagraphStyle(
        'MetaVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#111827')
    )
    
    # Set Recommendation Colors
    rec_colors = {
        "STRONG BUY": "#10b981", # Green
        "BUY": "#059669",
        "HOLD": "#f59e0b", # Amber
        "SHORT": "#dc2626", # Red
        "STRONG SHORT": "#991b1b"
    }
    rec_color = rec_colors.get(recommendation, "#111827")
    
    rec_style = ParagraphStyle(
        'RecStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.HexColor(rec_color)
    )

    # 1. Document Header (Blackgate Capital Branding)
    story.append(Paragraph("BLACKGATE CAPITAL", title_style))
    story.append(Paragraph("INVESTMENT RESEARCH MEMORANDUM", subtitle_style))
    
    # 2. Metadata Table
    current_date = datetime.now().strftime("%d. %B %Y")
    metadata_data = [
        [
            Paragraph("Unternehmen:", meta_label_style), Paragraph(company_name, meta_val_style),
            Paragraph("Datum:", meta_label_style), Paragraph(current_date, meta_val_style)
        ],
        [
            Paragraph("Symbol / Index:", meta_label_style), Paragraph(f"{symbol} ({info.get('sector', 'N/A')})", meta_val_style),
            Paragraph("Analyst:", meta_label_style), Paragraph(analyst_name, meta_val_style)
        ],
        [
            Paragraph("Aktueller Kurs:", meta_label_style), Paragraph(f"${info.get('currentPrice', info.get('previousClose', 0.0)):.2f}", meta_val_style),
            Paragraph("Empfehlung:", meta_label_style), Paragraph(recommendation, rec_style)
        ]
    ]
    
    # Width = 7.5 inches total (letter is 8.5, margins are 0.5 each side)
    meta_table = Table(metadata_data, colWidths=[1.25*inch, 2.5*inch, 1.25*inch, 2.5*inch])
    meta_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))
    
    # 3. Business Summary Section
    story.append(Paragraph("Unternehmensprofil & Sektor", h1_style))
    summary_text = info.get("longBusinessSummary", "Keine Zusammenfassung verfügbar.")
    # Limit business summary length on page 1
    if len(summary_text) > 600:
        summary_text = summary_text[:600] + "..."
    story.append(Paragraph(summary_text, body_style))
    story.append(Spacer(1, 10))
    
    # 4. Fundamental Metrics Grid
    story.append(Paragraph("Fundamentaldaten & Scores", h1_style))
    
    # Extract values for table
    de_ratio = info.get("debtToEquity")
    de_str = f"{de_ratio/100:.2f}" if de_ratio is not None else "N/A"
    
    metrics_data = [
        [
            Paragraph("<b>Metrik</b>", meta_label_style), Paragraph("<b>Wert</b>", meta_label_style),
            Paragraph("<b>Metrik</b>", meta_label_style), Paragraph("<b>Wert</b>", meta_label_style)
        ],
        [
            Paragraph("KGV (P/E)", body_style), Paragraph(str(info.get('trailingPE', 'N/A')), body_style),
            Paragraph("Free Cash Flow (FCF)", body_style), Paragraph(f"${info.get('freeCashflow', 0):,}" if info.get('freeCashflow') else "N/A", body_style)
        ],
        [
            Paragraph("KBV (P/B)", body_style), Paragraph(str(info.get('priceToBook', 'N/A')), body_style),
            Paragraph("Debt-to-Equity (D/E)", body_style), Paragraph(de_str, body_style)
        ],
        [
            Paragraph("Current Ratio", body_style), Paragraph(str(info.get('currentRatio', 'N/A')), body_style),
            Paragraph("Eigenkapitalrendite (ROE)", body_style), Paragraph(f"{(info.get('returnOnEquity', 0)*100):.2f}%" if info.get('returnOnEquity') else "N/A", body_style)
        ],
        [
            Paragraph("Umsatzwachstum (YoY)", body_style), Paragraph(f"{(info.get('revenueGrowth', 0)*100):.2f}%" if info.get('revenueGrowth') else "N/A", body_style),
            Paragraph("Nettomarge", body_style), Paragraph(f"{(info.get('profitMargins', 0)*100):.2f}%" if info.get('profitMargins') else "N/A", body_style)
        ],
        [
            Paragraph("<b>Long-Score</b>", meta_label_style), Paragraph(f"<b>{long_score} / 7</b>", rec_style if "BUY" in recommendation else meta_label_style),
            Paragraph("<b>Short-Score</b>", meta_label_style), Paragraph(f"<b>{short_score} / 7</b>", rec_style if "SHORT" in recommendation else meta_label_style)
        ]
    ]
    
    metrics_table = Table(metrics_data, colWidths=[2.2*inch, 1.55*inch, 2.2*inch, 1.55*inch])
    metrics_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1e3a8a')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f9fafb')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(metrics_table)
    
    # Force Page Break for Memo details and Sentiment
    story.append(PageBreak())
    
    # Page 2 Header
    story.append(Paragraph(f"BLACKGATE CAPITAL - {symbol} Research Memo (Forts.)", subtitle_style))
    
    # 5. Analyst Investment Thesis / Notes
    story.append(Paragraph("Investment-These (Analysten-Notizen)", h1_style))
    # Replace newlines with Paragraph spacing
    notes_formatted = analyst_notes.replace("\n", "<br/>")
    story.append(Paragraph(notes_formatted if notes_formatted.strip() else "Keine Investment-These hinterlegt.", body_style))
    story.append(Spacer(1, 10))
    
    # 6. News and Polymarket Sentiment
    story.append(Paragraph("Katalysatoren & Stimmung (Sentiment)", h1_style))
    
    sent_col_data = []
    
    # News column (left)
    news_flowables = []
    news_flowables.append(Paragraph("<b>Aktuelle Meldungen</b>", meta_label_style))
    news_flowables.append(Spacer(1, 4))
    if not news:
        news_flowables.append(Paragraph("Keine aktuellen Nachrichten gefunden.", body_style))
    else:
        for article in news[:3]: # Take 3 stories
            news_flowables.append(Paragraph(article['Titel'], news_title_style))
            news_flowables.append(Paragraph(f"{article['Herausgeber']} | {article['Datum']}", ParagraphStyle('NewsMeta', parent=body_style, fontSize=8, textColor=colors.HexColor('#6b7280'))))
            news_flowables.append(Spacer(1, 4))
            
    # Polymarket column (right)
    poly_flowables = []
    poly_flowables.append(Paragraph("<b>Prognosemärkte Sentiment</b>", meta_label_style))
    poly_flowables.append(Spacer(1, 4))
    if not polymarket:
        poly_flowables.append(Paragraph("Keine Prognosemärkte zu diesem Unternehmen gelistet.", body_style))
    else:
        for m in polymarket[:3]: # Take 3 markets
            odds_html = f"<font color='#059669'><b>{m['Wahrscheinlichkeiten']}</b></font>"
            poly_flowables.append(Paragraph(f"<b>Wette:</b> {m['Wettfrage']}", body_style))
            poly_flowables.append(Paragraph(f"<b>Implizierte Quoten:</b> {odds_html}", body_style))
            poly_flowables.append(Paragraph(f"Enddatum: {m['Enddatum']}", ParagraphStyle('PolyMeta', parent=body_style, fontSize=8, textColor=colors.HexColor('#6b7280'))))
            poly_flowables.append(Spacer(1, 4))
            
    # Assemble side-by-side tables
    sentiment_table_data = [[news_flowables, poly_flowables]]
    sentiment_table = Table(sentiment_table_data, colWidths=[3.65*inch, 3.65*inch])
    sentiment_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
    ]))
    story.append(sentiment_table)
    story.append(Spacer(1, 20))
    
    # 7. Signature / Sign-Off Box
    story.append(Paragraph("Research Freigabe & Konformität", h1_style))
    sig_data = [
        [
            Paragraph("<b>Analysten-Unterschrift:</b>", meta_label_style), Paragraph("___________________________", meta_val_style),
            Paragraph("<b>Freigabe (IC):</b>", meta_label_style), Paragraph("___________________________", meta_val_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[1.8*inch, 1.95*inch, 1.8*inch, 1.95*inch])
    sig_table.setStyle(TableStyle([
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(sig_table)

    # Build PDF document
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer
