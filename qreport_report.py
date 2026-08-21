"""PDF generation for the Q-Report analyzer.

Turns an :class:`qreport_analyzer.ExtractionResult` into a print-ready quarterly
research note — the same Blackgate Capital layout as ``report_generator.py``, but
driven by the extracted quarterly figures instead of yfinance snapshot data.

Every figure in the PDF carries its provenance: the source table at the end names
the origin (XBRL tag, report page, or yfinance row) of each headline number, so a
reader can check it against the filing.
"""

import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether,
)

from qreport_analyzer import (
    KPI_BY_KEY,
    KPI_ORDER,
    ExtractionResult,
    QuarterFact,
    compute_deltas,
    compute_margins,
)

NAVY = colors.HexColor("#1e3a8a")
TEAL = colors.HexColor("#0d9488")
CHARCOAL = colors.HexColor("#1f2937")
GREY = colors.HexColor("#4b5563")
LIGHT_GREY = colors.HexColor("#f3f4f6")
BORDER = colors.HexColor("#d1d5db")
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#dc2626")

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# ----------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------

def format_value(value: Optional[float], metric: str, currency: str = "USD") -> str:
    """Currency figures in millions, per-share figures with two decimals."""
    if value is None or value != value:
        return "–"
    kpi = KPI_BY_KEY.get(metric)
    if kpi and kpi.unit == "per_share":
        return f"{value:,.2f} {currency}"
    return f"{value / 1_000_000:,.1f} Mio. {currency}"


def format_delta(pct: Optional[float], absolute: Optional[float], metric: str, currency: str) -> str:
    if pct is not None:
        return f"{pct:+.1f}%"
    if absolute is not None:
        return format_value(absolute, metric, currency).replace("–", "n/a")
    return "–"


def _delta_color(pct: Optional[float], absolute: Optional[float], metric: str) -> colors.Color:
    change = pct if pct is not None else absolute
    if change is None or change == 0:
        return CHARCOAL
    kpi = KPI_BY_KEY.get(metric)
    good = change > 0 if (kpi is None or kpi.higher_is_better) else change < 0
    return GREEN if good else RED


# ----------------------------------------------------------------------------
# Trend chart
# ----------------------------------------------------------------------------

def build_trend_chart(
    facts: Sequence[QuarterFact],
    periods: Sequence[str],
    currency: str = "USD",
) -> Optional[io.BytesIO]:
    """Revenue bars with a net-income line over the shown quarters."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    revenue = {f.period_label: f.value for f in facts if f.metric == "revenue"}
    net_income = {f.period_label: f.value for f in facts if f.metric == "net_income"}
    labels = [p for p in periods if p in revenue]
    if len(labels) < 2:
        return None

    revenue_values = [revenue[p] / 1_000_000 for p in labels]
    income_values = [net_income.get(p, float("nan")) / 1_000_000 if p in net_income else float("nan")
                     for p in labels]

    figure, axis = plt.subplots(figsize=(7.2, 2.6), dpi=150)
    axis.bar(labels, revenue_values, color="#1e3a8a", width=0.6, label=f"Umsatz (Mio. {currency})")
    if any(v == v for v in income_values):
        axis.plot(labels, income_values, color="#0d9488", marker="o", linewidth=2,
                  label=f"Konzernergebnis (Mio. {currency})")

    axis.axhline(0, color="#9ca3af", linewidth=0.8)
    axis.set_ylabel(f"Mio. {currency}", fontsize=8)
    axis.tick_params(axis="both", labelsize=8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="y", color="#e5e7eb", linewidth=0.6)
    axis.set_axisbelow(True)
    axis.legend(fontsize=7, frameon=False, loc="upper left")
    figure.tight_layout()

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    buffer.seek(0)
    return buffer


# ----------------------------------------------------------------------------
# Page furniture
# ----------------------------------------------------------------------------

def _draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GREY)
    canvas.drawString(
        0.5 * inch, 0.3 * inch,
        "Blackgate Capital – Quartalsbericht-Analyse | Keine Anlageberatung. "
        "Zahlen aus Originalberichten extrahiert, ohne Gewähr.",
    )
    canvas.drawRightString(doc.pagesize[0] - 0.5 * inch, 0.3 * inch, f"Seite {doc.page}")
    canvas.restoreState()


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

def generate_qreport_pdf(
    result: ExtractionResult,
    analyst_name: str = "Falcone Capital Research",
    commentary: str = "",
    max_periods: int = 6,
) -> io.BytesIO:
    """Render the quarterly analysis as a PDF and return it as a BytesIO stream."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"Quartalsanalyse {result.ticker}",
        author=analyst_name,
    )
    content_width = doc.pagesize[0] - inch

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("QTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
                                 fontSize=22, leading=26, textColor=NAVY, spaceAfter=2)
    subtitle_style = ParagraphStyle("QSubtitle", parent=styles["Normal"], fontName="Helvetica-Bold",
                                    fontSize=11, leading=14, textColor=TEAL, spaceAfter=12)
    h1_style = ParagraphStyle("QSection", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=12, leading=15, textColor=NAVY, spaceBefore=10,
                              spaceAfter=5, keepWithNext=True)
    body_style = ParagraphStyle("QBody", parent=styles["Normal"], fontName="Helvetica",
                                fontSize=9, leading=12, textColor=CHARCOAL, spaceAfter=6)
    small_style = ParagraphStyle("QSmall", parent=body_style, fontSize=7.5, leading=9.5,
                                 textColor=GREY)
    label_style = ParagraphStyle("QLabel", parent=styles["Normal"], fontName="Helvetica-Bold",
                                 fontSize=8.5, leading=11, textColor=GREY)
    value_style = ParagraphStyle("QValue", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=8.5, leading=11, textColor=CHARCOAL)

    facts = result.facts
    periods = sorted({(f.fiscal_year, f.fiscal_quarter, f.period_label) for f in facts})
    period_labels = [p[2] for p in periods][-max_periods:]
    latest = period_labels[-1] if period_labels else "–"
    currency = result.currency or "USD"
    delta_rows = compute_deltas(facts)

    story: List[Any] = []

    # 1. Header
    story.append(Paragraph("BLACKGATE CAPITAL", title_style))
    story.append(Paragraph("QUARTALSBERICHT-ANALYSE (Q-REPORT)", subtitle_style))

    # 2. Metadata
    meta = [
        [Paragraph("Unternehmen:", label_style),
         Paragraph(result.company_name or result.ticker, value_style),
         Paragraph("Berichtsperiode:", label_style), Paragraph(latest, value_style),
         Paragraph("Erstellt:", label_style),
         Paragraph(datetime.now().strftime("%d.%m.%Y %H:%M"), value_style)],
        [Paragraph("Ticker:", label_style), Paragraph(result.ticker, value_style),
         Paragraph("Datenquellen:", label_style),
         Paragraph(", ".join(result.sources_used) or "–", value_style),
         Paragraph("Analyst:", label_style), Paragraph(analyst_name, value_style)],
        [Paragraph("Währung:", label_style), Paragraph(currency, value_style),
         Paragraph("Dokument:", label_style),
         Paragraph(result.document_label or "–", value_style),
         Paragraph("Quartale:", label_style), Paragraph(str(len(period_labels)), value_style)],
    ]
    column = content_width / 6
    meta_table = Table(meta, colWidths=[column * 0.85, column * 1.15] * 3)
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GREY),
        ("BACKGROUND", (2, 0), (2, -1), LIGHT_GREY),
        ("BACKGROUND", (4, 0), (4, -1), LIGHT_GREY),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    if not facts:
        story.append(Paragraph("Kennzahlen", h1_style))
        story.append(Paragraph(
            "Für diesen Bericht konnten keine Quartalskennzahlen extrahiert werden.", body_style))
        doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
        buffer.seek(0)
        return buffer

    # 3. Headline quarter
    story.append(Paragraph(f"Kennzahlen {latest} – Veränderung QoQ / YoY", h1_style))
    headline = [[
        Paragraph("<b>Kennzahl</b>", label_style), Paragraph("<b>Wert</b>", label_style),
        Paragraph("<b>QoQ</b>", label_style), Paragraph("<b>YoY</b>", label_style),
        Paragraph("<b>Quelle</b>", label_style),
    ]]
    latest_rows = [row for row in delta_rows if row["period"] == latest]
    latest_rows.sort(key=lambda row: KPI_ORDER.index(row["metric"]) if row["metric"] in KPI_ORDER else 99)

    for row in latest_rows:
        qoq_style = ParagraphStyle(f"qoq_{row['metric']}", parent=value_style,
                                   textColor=_delta_color(row["qoq_pct"], row["qoq_abs"], row["metric"]))
        yoy_style = ParagraphStyle(f"yoy_{row['metric']}", parent=value_style,
                                   textColor=_delta_color(row["yoy_pct"], row["yoy_abs"], row["metric"]))
        headline.append([
            Paragraph(row["metric_label"], value_style),
            Paragraph(format_value(row["value"], row["metric"], currency), value_style),
            Paragraph(format_delta(row["qoq_pct"], row["qoq_abs"], row["metric"], currency), qoq_style),
            Paragraph(format_delta(row["yoy_pct"], row["yoy_abs"], row["metric"], currency), yoy_style),
            Paragraph(f"{row['source']}{'*' if row['derived'] else ''}", small_style),
        ])

    headline_table = Table(headline, colWidths=[content_width * w for w in (0.28, 0.22, 0.16, 0.16, 0.18)])
    headline_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(headline_table)
    story.append(Spacer(1, 10))

    # 4. Trend chart
    chart = build_trend_chart(facts, period_labels, currency)
    if chart:
        story.append(KeepTogether([
            Paragraph("Umsatz- und Ergebnisverlauf", h1_style),
            Image(chart, width=content_width, height=content_width * 2.6 / 7.2),
        ]))
        story.append(Spacer(1, 8))

    # 5. Quarter-by-quarter table
    story.append(Paragraph("Quartalsverlauf", h1_style))
    history = [[Paragraph("<b>Kennzahl</b>", label_style)] +
               [Paragraph(f"<b>{label}</b>", label_style) for label in period_labels]]
    values_by_key = {(f.metric, f.period_label): f.value for f in facts}
    for metric in KPI_ORDER:
        if not any((metric, label) in values_by_key for label in period_labels):
            continue
        history.append(
            [Paragraph(KPI_BY_KEY[metric].label_de, value_style)] +
            [Paragraph(format_value(values_by_key.get((metric, label)), metric, currency), value_style)
             for label in period_labels]
        )

    label_width = content_width * 0.22
    history_table = Table(
        history,
        colWidths=[label_width] + [(content_width - label_width) / len(period_labels)] * len(period_labels),
        repeatRows=1,
    )
    history_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(history_table)
    story.append(Spacer(1, 10))

    # 6. Margins
    margin_rows = [row for row in compute_margins(facts) if row["period"] in period_labels]
    if margin_rows:
        margin_names = ["Bruttomarge", "Operative Marge", "Nettomarge", "FCF-Marge"]
        margin_table_data = [[Paragraph("<b>Marge</b>", label_style)] +
                             [Paragraph(f"<b>{row['period']}</b>", label_style) for row in margin_rows]]
        for name in margin_names:
            if all(row.get(name) is None for row in margin_rows):
                continue
            margin_table_data.append(
                [Paragraph(name, value_style)] +
                [Paragraph(f"{row[name]:.1f}%" if row.get(name) is not None else "–", value_style)
                 for row in margin_rows]
            )
        if len(margin_table_data) > 1:
            margin_table = Table(
                margin_table_data,
                colWidths=[label_width] + [(content_width - label_width) / len(margin_rows)] * len(margin_rows),
            )
            margin_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(KeepTogether([Paragraph("Margenentwicklung", h1_style), margin_table]))
            story.append(Spacer(1, 10))

    # 7. Analyst commentary
    if commentary.strip():
        story.append(Paragraph("Kommentar", h1_style))
        for paragraph in commentary.strip().split("\n"):
            if paragraph.strip():
                story.append(Paragraph(paragraph.strip(), body_style))
        story.append(Spacer(1, 6))

    # 8. Provenance
    story.append(Paragraph("Quellennachweis", h1_style))
    provenance = [[
        Paragraph("<b>Kennzahl</b>", label_style), Paragraph("<b>Periode</b>", label_style),
        Paragraph("<b>Quelle</b>", label_style), Paragraph("<b>Herkunft / Tag / Seite</b>", label_style),
    ]]
    for row in latest_rows:
        provenance.append([
            Paragraph(row["metric_label"], small_style),
            Paragraph(row["period"], small_style),
            Paragraph(f"{row['source']}{'*' if row['derived'] else ''}", small_style),
            Paragraph(row["detail"] or "–", small_style),
        ])
    provenance_table = Table(provenance, colWidths=[content_width * w for w in (0.24, 0.14, 0.14, 0.48)])
    provenance_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(provenance_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "* = aus kumulierten Werten abgeleitet (z. B. Q4 = Geschäftsjahr – 9 Monate) "
        "und nicht direkt im Bericht ausgewiesen.", small_style))

    for note in result.notes:
        story.append(Paragraph(f"Hinweis: {note}", small_style))
    for warning in result.warnings:
        story.append(Paragraph(f"Warnung: {warning}", small_style))

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    buffer.seek(0)
    return buffer


def save_qreport_pdf(
    result: ExtractionResult,
    analyst_name: str = "Falcone Capital Research",
    commentary: str = "",
    max_periods: int = 6,
    directory: str = REPORTS_DIR,
) -> str:
    """Write the report into ``reports/`` and return the file path."""
    stream = generate_qreport_pdf(result, analyst_name, commentary, max_periods)
    os.makedirs(directory, exist_ok=True)
    filename = f"qreport_{result.ticker or 'UNKNOWN'}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    path = os.path.join(directory, filename)
    with open(path, "wb") as handle:
        handle.write(stream.getvalue())
    return path
