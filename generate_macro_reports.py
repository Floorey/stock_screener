import io
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from datetime import datetime

def generate_option_a_pdf(target_path: str):
    """Generates PDF for Option A: Synthetic Short Bond Trade on TLT/IEF"""
    doc = SimpleDocTemplate(
        target_path,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#1e3a8a'), # Dark Navy
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
    
    rec_style = ParagraphStyle(
        'RecStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.HexColor('#dc2626') # Red for Short
    )

    # 1. Branding Header
    story.append(Paragraph("BLACKGATE CAPITAL", title_style))
    story.append(Paragraph("MACRO INVESTMENT RESEARCH MEMORANDUM", subtitle_style))
    
    # 2. Metadata Table
    current_date = datetime.now().strftime("%d. %B %Y")
    metadata_data = [
        [
            Paragraph("Thema / Setup:", meta_label_style), Paragraph("Option A - Synthetischer Short auf US-Staatsanleihen", meta_val_style),
            Paragraph("Datum:", meta_label_style), Paragraph(current_date, meta_val_style)
        ],
        [
            Paragraph("Ziel-Underlying:", meta_label_style), Paragraph("TLT / IEF (US Treasury Bond ETFs)", meta_val_style),
            Paragraph("Analyst:", meta_label_style), Paragraph("Lukas", meta_val_style)
        ],
        [
            Paragraph("Strategischer Fokus:", meta_label_style), Paragraph("Zinsänderungs- & Inflationswette", meta_val_style),
            Paragraph("Empfehlung:", meta_label_style), Paragraph("STRATEGIC SHORT (Bonds)", rec_style)
        ]
    ]
    
    meta_table = Table(metadata_data, colWidths=[1.5*inch, 2.25*inch, 1.25*inch, 2.5*inch])
    meta_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))
    
    # 3. Macro Thesis
    story.append(Paragraph("Makroökonomische Investment-These", h1_style))
    thesis_text = (
        "Die US-Wirtschaft zeigt sich trotz des restriktiven Zinsniveaus der Federal Reserve weiterhin robust. "
        "Hartnäckige Kerninflation und eine steigende staatliche Neuverschuldung in den USA üben anhaltenden Druck "
        "auf die Renditen am langen Ende der Zinskurve aus. Da die Anleihekurse (z. B. IEF für 7-10y oder TLT für 20y+ US-Bonds) "
        "mathematisch zwingend fallen, wenn die Zinsen steigen, ist der Leerverkauf von Anleihen das direkte Instrument, "
        "um von diesem Trend zu profitieren.<br/><br/>"
        "Ein physischer Leerverkauf von ETFs birgt jedoch Nachteile wie tägliche Leihgebühren (Borrow Fees), "
        "die Gefahr von Short Squeezes und erhebliche Margin-Anforderungen. Zur Effizienzsteigerung und Kostenminimierung "
        "wird dieses Exposure durch einen synthetischen Short Swap abgebildet."
    )
    story.append(Paragraph(thesis_text, body_style))
    story.append(Spacer(1, 10))
    
    # 4. Position Layout & Table
    story.append(Paragraph("Synthetische Short-Struktur (Replikations-Modell)", h1_style))
    
    struct_data = [
        [
            Paragraph("<b>Kontrakt-Komponente</b>", meta_label_style), Paragraph("<b>Typ / Ausrichtung</b>", meta_label_style),
            Paragraph("<b>Ziel-Strike</b>", meta_label_style), Paragraph("<b>Griechische Kennzahlen (Delta)</b>", meta_label_style)
        ],
        [
            Paragraph("Kauf Put-Option (Long Put)", body_style), Paragraph("Kreditschutz / Kursabfall-Profit", body_style),
            Paragraph("At-the-Money (z. B. $90)", body_style), Paragraph("Delta: -0.50 (Gewinn bei fallendem Kurs)", body_style)
        ],
        [
            Paragraph("Verkauf Call-Option (Short Call)", body_style), Paragraph("Prämiengenerierung / Stillhalter", body_style),
            Paragraph("At-the-Money (z. B. $90)", body_style), Paragraph("Delta: -0.50 (Gewinn bei fallendem/seitwärts Kurs)", body_style)
        ],
        [
            Paragraph("<b>Synthetische Gesamtposition</b>", meta_label_style), Paragraph("<b>Synthetischer Short Bond</b>", meta_label_style),
            Paragraph("<b>Netto-Kosten: Nahe $0.00</b>", meta_label_style), Paragraph("<b>Gesamt-Delta: -1.00 (100% short)</b>", rec_style)
        ]
    ]
    
    struct_table = Table(struct_data, colWidths=[2.2*inch, 1.8*inch, 1.5*inch, 2.0*inch])
    struct_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1e3a8a')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f9fafb')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(struct_table)
    story.append(Spacer(1, 15))
    
    # 5. Risk & Risk Management
    story.append(Paragraph("Risikoprofil & Stop-Loss Richtlinien", h1_style))
    risk_text = (
        "<b>Risiko:</b> Ein unerwarteter Konjunktureinbruch (Rezession) oder exogene Krisen ('Black Swan') führen "
        "zu einer Flucht in sichere Häfen (Flight-to-Safety). Dies würde die Zinsen drastisch senken und die Anleihepreise "
        "nach oben treiben. <br/>"
        "Da die Struktur einen ungedeckten Short Call beinhaltet, ist das Verlustrisiko bei unvorhergesehenen Zinsrutschen "
        "theoretisch unbegrenzt. <br/><br/>"
        "<b>Risikomanagement:</b> Die Position sollte strikt abgesichert werden. <br/>"
        "1. <i>Stop-Loss:</i> Glattstellung der Position bei einem Anleihekurs-Anstieg von mehr als 5% über den Strike-Kurs.<br/>"
        "2. <i>Bear Put Spread mit Short Call Absicherung:</i> Kauf eines tieferen Puts zur Gewinnmitnahme und Kauf eines weiter "
        "aus dem Geld liegenden Calls als Verlustbegrenzung (Verwandlung des Setups in einen definierten Iron Condor / Bear Spread)."
    )
    story.append(Paragraph(risk_text, body_style))
    story.append(Spacer(1, 20))
    
    # 6. Signature Block
    story.append(Paragraph("Research Freigabe & Konformität", h1_style))
    sig_data = [
        [
            Paragraph("<b>Analysten-Unterschrift:</b>", meta_label_style), Paragraph("Lukas (via Antigravity)", meta_val_style),
            Paragraph("<b>Freigabe (IC):</b>", meta_label_style), Paragraph("___________________________", meta_val_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[1.8*inch, 1.95*inch, 1.8*inch, 1.95*inch])
    sig_table.setStyle(TableStyle([
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(sig_table)
    
    doc.build(story)

def generate_option_b_pdf(target_path: str):
    """Generates PDF for Option B: Synthetic Long Yield Trade on ^TNX"""
    doc = SimpleDocTemplate(
        target_path,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#1e3a8a'), # Dark Navy
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
    
    rec_style = ParagraphStyle(
        'RecStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.HexColor('#10b981') # Green for Long
    )

    # 1. Branding Header
    story.append(Paragraph("BLACKGATE CAPITAL", title_style))
    story.append(Paragraph("MACRO INVESTMENT RESEARCH MEMORANDUM", subtitle_style))
    
    # 2. Metadata Table
    current_date = datetime.now().strftime("%d. %B %Y")
    metadata_data = [
        [
            Paragraph("Thema / Setup:", meta_label_style), Paragraph("Option B - Synthetischer Long auf 10y Zinsrendite (^TNX)", meta_val_style),
            Paragraph("Datum:", meta_label_style), Paragraph(current_date, meta_val_style)
        ],
        [
            Paragraph("Ziel-Underlying:", meta_label_style), Paragraph("^TNX (CBOE 10-Year Treasury Yield Index)", meta_val_style),
            Paragraph("Analyst:", meta_label_style), Paragraph("Lukas", meta_val_style)
        ],
        [
            Paragraph("Strategischer Fokus:", meta_label_style), Paragraph("Direkte Zins- & Zinskurven-Ausrichtung", meta_val_style),
            Paragraph("Empfehlung:", meta_label_style), Paragraph("STRATEGIC LONG (Yield)", rec_style)
        ]
    ]
    
    meta_table = Table(metadata_data, colWidths=[1.5*inch, 2.25*inch, 1.25*inch, 2.5*inch])
    meta_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))
    
    # 3. Macro Thesis
    story.append(Paragraph("Makroökonomische Investment-These", h1_style))
    thesis_text = (
        "Im aktuellen Umfeld von anhaltenden Inflationserwartungen und restriktiver Zinspolitik steigen die Zinsen am langen "
        "Ende der US-Zinskurve. Während traditionelle Trades (z.B. Shorten von IEF oder TLT) indirekte Zinswetten sind, die durch "
        "ETF-Replikationen, Zinskupons und Dividendenzahlungen verzerrt werden, ermöglicht der CBOE 10-Year Treasury Yield Index "
        "(^TNX) eine direkte, ungefilterte Wette auf die Zinsrendite. Ein Zinsstand von z. B. 4,50% entspricht einem Indexwert von 45.00.<br/><br/>"
        "Durch das Aufsetzen eines synthetischen Long-Swaps auf den ^TNX partizipieren wir linear an jedem Basispunkt Renditeanstieg, "
        "ohne Kapital im physischen Bondmarkt binden zu müssen. Der Trade hat die Struktur eines klassischen Pay-Fixed Zins-Swaps."
    )
    story.append(Paragraph(thesis_text, body_style))
    story.append(Spacer(1, 10))
    
    # 4. Position Layout & Table
    story.append(Paragraph("Synthetische Long Yield Struktur (Pay-Fixed Swap)", h1_style))
    
    struct_data = [
        [
            Paragraph("<b>Kontrakt-Komponente</b>", meta_label_style), Paragraph("<b>Typ / Ausrichtung</b>", meta_label_style),
            Paragraph("<b>Ziel-Strike</b>", meta_label_style), Paragraph("<b>Griechische Kennzahlen (Delta)</b>", meta_label_style)
        ],
        [
            Paragraph("Kauf Call-Option (Long Call)", body_style), Paragraph("Partizipation an Zinsanstieg", body_style),
            Paragraph("At-the-Money (z. B. 45)", body_style), Paragraph("Delta: +0.50 (Gewinn bei steigenden Zinsen)", body_style)
        ],
        [
            Paragraph("Verkauf Put-Option (Short Put)", body_style), Paragraph("Prämieneinnahme zur Refinanzierung", body_style),
            Paragraph("At-the-Money (z. B. 45)", body_style), Paragraph("Delta: +0.50 (Risiko/Gewinn bei Zinsanstieg)", body_style)
        ],
        [
            Paragraph("<b>Synthetische Gesamtposition</b>", meta_label_style), Paragraph("<b>Synthetischer Long Zins (^TNX)</b>", meta_label_style),
            Paragraph("<b>Netto-Kosten: Nahe $0.00</b>", meta_label_style), Paragraph("<b>Gesamt-Delta: +1.00 (Zins-Long)</b>", rec_style)
        ]
    ]
    
    struct_table = Table(struct_data, colWidths=[2.2*inch, 1.8*inch, 1.5*inch, 2.0*inch])
    struct_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1e3a8a')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f9fafb')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),
        ('PADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(struct_table)
    story.append(Spacer(1, 15))
    
    # 5. Risk & Risk Management
    story.append(Paragraph("Risikoprofil & Stop-Loss Richtlinien", h1_style))
    risk_text = (
        "<b>Risiko:</b> Das Verlustrisiko steigt, wenn die Renditen der 10-jährigen US-Bonds fallen (Zinsrückgang). "
        "Die verkaufte Put-Option verzeichnet dann Verluste, während der Long Call wertlos verfällt. "
        "Das maximale Risiko entspricht einem Zinsrutsch auf 0,00% (^TNX = 0), was im aktuellen makroökonomischen Umfeld "
        "äußerst unwahrscheinlich, aber theoretisch möglich ist. Es müssen Margin-Anforderungen für den Short Put hinterlegt werden.<br/><br/>"
        "<b>Risikomanagement:</b> <br/>"
        "1. <i>Stop-Loss:</i> Automatisches Schließen der Gesamtposition, falls die Rendite unter ein kritisches Unterstützungsniveau "
        "fällt (z. B. 4,00% / Indexwert 40.00).<br/>"
        "2. <i>Yield Bull Spread:</i> Absicherung durch Kauf eines tieferen Puts (z. B. Strike 40). Dies begrenzt das maximale Risiko "
        "auf den Abstand zwischen Strike 45 und Strike 40 abzüglich eingenommener Prämien."
    )
    story.append(Paragraph(risk_text, body_style))
    story.append(Spacer(1, 20))
    
    # 6. Signature Block
    story.append(Paragraph("Research Freigabe & Konformität", h1_style))
    sig_data = [
        [
            Paragraph("<b>Analysten-Unterschrift:</b>", meta_label_style), Paragraph("Lukas (via Antigravity)", meta_val_style),
            Paragraph("<b>Freigabe (IC):</b>", meta_label_style), Paragraph("___________________________", meta_val_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[1.8*inch, 1.95*inch, 1.8*inch, 1.95*inch])
    sig_table.setStyle(TableStyle([
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(sig_table)
    
    doc.build(story)

if __name__ == "__main__":
    docs_dir = r"C:\Users\lukas\Documents"
    
    path_a = os.path.join(docs_dir, "Blackgate_Macro_Memo_Option_A.pdf")
    path_b = os.path.join(docs_dir, "Blackgate_Macro_Memo_Option_B.pdf")
    
    print(f"Generiere Option A unter: {path_a} ...")
    generate_option_a_pdf(path_a)
    print("Option A erfolgreich erstellt.")
    
    print(f"Generiere Option B unter: {path_b} ...")
    generate_option_b_pdf(path_b)
    print("Option B erfolgreich erstellt.")
