"""Streamlit UI for the Q-Report analyzer (tab "Quartalsbericht-Analyzer").

Three modes share one tab:

* **Ticker-Analyse** – SEC XBRL + optional LLM extraction of the latest 10-Q +
  yfinance fallback, merged into one quarterly KPI table with QoQ/YoY deltas and
  an own PDF research note.
* **Eigener Bericht (PDF)** – upload a Quartalsbericht; Claude reads the PDF
  itself and returns the same structured KPI set.
* **Klassischer Scanner** – the previous heuristic regex scan and keyword search
  from ``pdf_analyzer.py``, kept for documents the structured path can't handle.
"""

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import qreport_analyzer as qa
from qreport_report import format_value, generate_qreport_pdf, save_qreport_pdf
from pdf_analyzer import (
    detect_report_locale,
    download_and_parse_filing,
    extract_structured_financials,
    extract_text_from_pdf,
    fetch_sec_filings,
    search_keywords_in_pdf,
)
from watchlist_manager import load_watchlist

RESULT_KEY = "qr_result"
PAGES_KEY = "qr_pages_data"
REPORT_NAME_KEY = "qr_report_name"


# ----------------------------------------------------------------------------
# Shared rendering helpers
# ----------------------------------------------------------------------------

def _ticker_picker(key_prefix: str) -> str:
    """Ticker from watchlist/screener results, with a manual override field."""
    symbols = set()
    screener_results = st.session_state.get("screener_results")
    if screener_results is not None and not screener_results.empty:
        symbols.update(screener_results["Symbol"].tolist())
    try:
        symbols.update(load_watchlist())
    except Exception:
        pass
    symbols.update(["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA"])

    col_select, col_manual = st.columns([2, 1])
    with col_select:
        selected = st.selectbox(
            "Symbol aus Watchlist / Scan:",
            options=sorted(symbols),
            key=f"{key_prefix}_select",
        )
    with col_manual:
        manual = st.text_input(
            "Oder Ticker manuell:", key=f"{key_prefix}_manual"
        ).strip().upper()
    return manual or selected


def _format_frame(result: qa.ExtractionResult) -> pd.DataFrame:
    """KPI frame with German labels and formatted values, newest quarter last."""
    frame = qa.facts_to_frame(result.facts)
    if frame.empty:
        return frame
    formatted = pd.DataFrame(
        [[format_value(value, metric, result.currency) for value in frame.loc[metric]]
         for metric in frame.index],
        index=[qa.KPI_BY_KEY[m].label_de if m in qa.KPI_BY_KEY else m for m in frame.index],
        columns=frame.columns,
    )
    formatted.index.name = "Kennzahl"
    return formatted


def _render_headline_metrics(result: qa.ExtractionResult, delta_rows: List[Dict[str, Any]]) -> None:
    latest = qa.latest_period(result.facts)
    if not latest:
        return
    rows = [row for row in delta_rows if row["period"] == latest]
    rows.sort(key=lambda r: qa.KPI_ORDER.index(r["metric"]) if r["metric"] in qa.KPI_ORDER else 99)

    st.markdown(f"#### 📌 Kennzahlen {latest}")
    for chunk_start in range(0, len(rows), 4):
        columns = st.columns(4)
        for column, row in zip(columns, rows[chunk_start:chunk_start + 4]):
            with column:
                if row["yoy_pct"] is not None:
                    delta = f"{row['yoy_pct']:+.1f}% YoY"
                elif row["yoy_abs"] is not None:
                    delta = f"{format_value(row['yoy_abs'], row['metric'], result.currency)} YoY"
                else:
                    delta = None
                kpi = qa.KPI_BY_KEY.get(row["metric"])
                st.metric(
                    row["metric_label"],
                    format_value(row["value"], row["metric"], result.currency),
                    delta=delta,
                    delta_color="normal" if (kpi is None or kpi.higher_is_better) else "inverse",
                )


def _render_delta_table(result: qa.ExtractionResult, delta_rows: List[Dict[str, Any]]) -> None:
    if not delta_rows:
        return
    frame = pd.DataFrame([{
        "Kennzahl": row["metric_label"],
        "Periode": row["period"],
        "Wert": format_value(row["value"], row["metric"], result.currency),
        "QoQ %": row["qoq_pct"],
        "YoY %": row["yoy_pct"],
        "Quelle": row["source"],
        "Abgeleitet": row["derived"],
        "Herkunft": row["detail"],
    } for row in delta_rows])
    st.dataframe(
        frame,
        column_config={
            "QoQ %": st.column_config.NumberColumn("QoQ %", format="%.1f%%"),
            "YoY %": st.column_config.NumberColumn("YoY %", format="%.1f%%"),
            "Herkunft": st.column_config.TextColumn("Herkunft", width="large"),
        },
        hide_index=True,
        use_container_width=True,
    )


def _render_charts(result: qa.ExtractionResult) -> None:
    frame = qa.facts_to_frame(result.facts)
    if frame.empty:
        return
    available = [m for m in frame.index if m in qa.KPI_BY_KEY]
    if not available:
        return

    st.markdown("#### 📈 Verlauf")
    chart_metric = st.selectbox(
        "Kennzahl visualisieren:",
        options=available,
        format_func=lambda m: qa.KPI_BY_KEY[m].label_de,
        key="qr_chart_metric",
    )
    series = frame.loc[chart_metric].dropna()
    if series.empty:
        st.info("Für diese Kennzahl liegen keine Werte vor.")
        return

    scale = 1.0 if qa.KPI_BY_KEY[chart_metric].unit == "per_share" else 1_000_000.0
    unit = result.currency if scale == 1.0 else f"Mio. {result.currency}"
    st.bar_chart(
        pd.DataFrame({f"{qa.KPI_BY_KEY[chart_metric].label_de} ({unit})": series / scale}),
        use_container_width=True,
    )


def _render_margins(result: qa.ExtractionResult) -> None:
    margins = qa.compute_margins(result.facts)
    if not margins:
        return
    frame = pd.DataFrame(margins).set_index("period")
    frame = frame.drop(columns=[c for c in ("fiscal_year", "fiscal_quarter") if c in frame.columns])
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if frame.empty:
        return
    st.markdown("#### 🧮 Margen (in % vom Umsatz)")
    st.dataframe(frame.T.style.format("{:.1f}%", na_rep="–"), use_container_width=True)


def _render_pdf_export(result: qa.ExtractionResult) -> None:
    st.markdown("#### 📄 Eigenen Quartalsreport erzeugen")
    col_left, col_right = st.columns([1, 2])
    with col_left:
        analyst = st.text_input("Analyst / Absender:", "Falcone Capital Research", key="qr_analyst")
        max_periods = st.slider("Quartale im Report:", 2, 12, 6, key="qr_pdf_periods")
    with col_right:
        commentary = st.text_area(
            "Kommentar (erscheint im Report):",
            placeholder="Einschätzung zum Quartal, Sondereffekte, Ausblick ...",
            height=120,
            key="qr_commentary",
        )

    if st.button("📄 Quartalsreport als PDF generieren", key="qr_generate_pdf"):
        with st.spinner("Erzeuge PDF-Report ..."):
            try:
                stream = generate_qreport_pdf(result, analyst, commentary, max_periods)
                st.session_state["qr_pdf_bytes"] = stream.getvalue()
                path = save_qreport_pdf(result, analyst, commentary, max_periods)
                st.session_state["qr_pdf_path"] = path
                st.success(f"Report erstellt und gespeichert: `{path}`")
            except Exception as exc:
                st.error(f"PDF konnte nicht erzeugt werden: {exc}")

    if st.session_state.get("qr_pdf_bytes"):
        st.download_button(
            "📥 Quartalsreport herunterladen",
            data=st.session_state["qr_pdf_bytes"],
            file_name=f"Quartalsreport_{result.ticker}_{datetime.now():%Y%m%d}.pdf",
            mime="application/pdf",
            key="qr_download_pdf",
        )


def _render_result(result: qa.ExtractionResult) -> None:
    """Everything that is shown once an analysis produced facts."""
    for warning in result.warnings:
        st.warning(warning)
    for note in result.notes:
        st.info(f"Hinweis aus dem Bericht: {note}")

    if not result.facts:
        st.error("Es konnten keine Quartalskennzahlen extrahiert werden.")
        return

    usage = result.llm_usage
    source_line = ", ".join(result.sources_used) or "–"
    meta_cols = st.columns(4)
    meta_cols[0].metric("Unternehmen", result.company_name or result.ticker)
    meta_cols[1].metric("Quellen", source_line)
    meta_cols[2].metric("Quartale", len({f.period_label for f in result.facts}))
    if usage:
        cost = "aus Cache" if usage.from_cache else f"${usage.cost_usd:.3f}"
        meta_cols[3].metric("LLM-Kosten", cost,
                            help=f"{usage.input_tokens:,} Input- / {usage.output_tokens:,} Output-Tokens")
    else:
        meta_cols[3].metric("Währung", result.currency)

    delta_rows = qa.compute_deltas(result.facts)
    _render_headline_metrics(result, delta_rows)

    st.markdown("#### 📊 Quartalsverlauf")
    formatted = _format_frame(result)
    if not formatted.empty:
        st.dataframe(formatted, use_container_width=True)
        st.caption("Werte in Millionen der Berichtswährung, EPS je Aktie.")

    _render_charts(result)
    _render_margins(result)

    with st.expander("🔍 Details, Deltas & Quellennachweis"):
        st.markdown(
            "`XBRL` = von der Gesellschaft getaggte SEC-Daten · `LLM` = von Claude aus dem "
            "Berichtstext gelesen · `yfinance` = Yahoo-Fallback. `Abgeleitet` bedeutet, dass das "
            "Quartal aus kumulierten Werten berechnet wurde (z. B. Q4 = Geschäftsjahr − 9 Monate)."
        )
        _render_delta_table(result, delta_rows)
        marks = qa.source_frame(result.facts)
        if not marks.empty:
            marks.index = [qa.KPI_BY_KEY[m].label_de if m in qa.KPI_BY_KEY else m for m in marks.index]
            st.markdown("**Quelle je Zelle**")
            st.dataframe(marks, use_container_width=True)
        csv = pd.DataFrame([f.to_dict() for f in result.facts]).to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Rohdaten als CSV",
            data=csv,
            file_name=f"qreport_{result.ticker}_{datetime.now():%Y%m%d}.csv",
            mime="text/csv",
            key="qr_csv_download",
        )

    st.markdown("---")
    _render_pdf_export(result)


# ----------------------------------------------------------------------------
# Mode 1: ticker analysis via SEC
# ----------------------------------------------------------------------------

def _render_ticker_mode() -> None:
    st.markdown(
        "Zieht die Quartalszahlen direkt von der SEC: **XBRL-Fakten** (von der Gesellschaft "
        "selbst getaggt, exakt) und optional die **LLM-Extraktion** des letzten 10-Q durch "
        "Claude. Yahoo dient als Gegencheck."
    )

    ticker = _ticker_picker("qr_ticker")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        use_xbrl = st.checkbox("SEC XBRL (exakt)", value=True, key="qr_use_xbrl")
    with col_b:
        llm_available = qa.is_llm_configured()
        use_llm = st.checkbox(
            "LLM-Extraktion (Claude)",
            value=llm_available,
            disabled=not llm_available,
            help="Benötigt ANTHROPIC_API_KEY in der .env" if not llm_available else
                 "Liest den Berichtstext des letzten 10-Q und ergänzt fehlende Kennzahlen.",
            key="qr_use_llm",
        )
    with col_c:
        use_yf = st.checkbox("yfinance-Fallback", value=True, key="qr_use_yf")

    col_q, col_m = st.columns(2)
    with col_q:
        max_quarters = st.slider("Anzahl Quartale:", 4, 20, 12, key="qr_max_quarters")
    with col_m:
        model = st.selectbox(
            "LLM-Modell:",
            options=["claude-opus-5", "claude-sonnet-5"],
            disabled=not use_llm,
            key="qr_model",
        )

    if not llm_available:
        st.caption(
            "💡 Für die LLM-Extraktion `ANTHROPIC_API_KEY=...` in die `.env` eintragen und "
            "`pip install -r requirements.txt` ausführen."
        )

    if st.button("⚡ Quartalsanalyse starten", key="qr_run_analysis", type="primary"):
        if not ticker:
            st.error("Bitte einen Ticker angeben.")
        else:
            with st.spinner(f"Analysiere Quartalszahlen für {ticker} ..."):
                try:
                    result = qa.analyze_ticker(
                        ticker,
                        use_xbrl=use_xbrl,
                        use_llm=use_llm,
                        use_yfinance=use_yf,
                        max_quarters=max_quarters,
                        model=model,
                    )
                    st.session_state[RESULT_KEY] = result
                    st.session_state.pop("qr_pdf_bytes", None)
                except Exception as exc:
                    st.error(f"Analyse fehlgeschlagen: {exc}")

    with st.expander("📋 Verfügbare SEC-Berichte (EDGAR)"):
        if st.button("🔌 Berichte abrufen", key="qr_fetch_filings"):
            with st.spinner("Frage EDGAR ab ..."):
                try:
                    st.session_state["qr_filings"] = qa.fetch_edgar_filings(
                        ticker, forms=("10-Q", "10-K", "8-K"), limit=15
                    )
                    st.session_state["qr_filings_ticker"] = ticker
                except Exception as exc:
                    st.error(f"EDGAR-Abfrage fehlgeschlagen: {exc}")

        filings = st.session_state.get("qr_filings") or []
        if filings and st.session_state.get("qr_filings_ticker") == ticker:
            st.dataframe(
                pd.DataFrame([
                    {"Eingereicht": f["date"], "Typ": f["type"], "Stichtag": f.get("period", ""),
                     "Link": f["url"]}
                    for f in filings
                ]),
                column_config={
                    "Link": st.column_config.LinkColumn("Bericht", display_text="Öffnen ↗"),
                },
                hide_index=True,
                use_container_width=True,
            )
            if qa.is_llm_configured():
                options = [f"{f['date']} | {f['type']}" for f in filings]
                choice = st.selectbox("Bericht für LLM-Extraktion:", options, key="qr_filing_choice")
                if st.button("🤖 Diesen Bericht mit Claude auswerten", key="qr_llm_filing"):
                    filing = filings[options.index(choice)]
                    with st.spinner("Lade Bericht und extrahiere Kennzahlen ..."):
                        try:
                            pages = qa.fetch_filing_text(filing["url"])
                            result = qa.extract_kpis_with_llm(
                                ticker,
                                pages_data=pages,
                                model=st.session_state.get("qr_model", qa.DEFAULT_LLM_MODEL),
                                document_label=f"{filing['type']} {filing['date']}",
                            )
                            previous = st.session_state.get(RESULT_KEY)
                            st.session_state[RESULT_KEY] = (
                                qa.merge_results(previous, result) if previous else result
                            )
                            st.session_state.pop("qr_pdf_bytes", None)
                            st.success("Bericht ausgewertet.")
                        except Exception as exc:
                            st.error(f"Auswertung fehlgeschlagen: {exc}")

    result = st.session_state.get(RESULT_KEY)
    if result:
        st.markdown("---")
        _render_result(result)


# ----------------------------------------------------------------------------
# Mode 2: own PDF report
# ----------------------------------------------------------------------------

def _render_upload_mode() -> None:
    st.markdown(
        "Für Berichte ohne SEC-XBRL — deutsche Quartalsmitteilungen, Geschäftsberichte, "
        "IR-PDFs. Claude liest das PDF direkt (inklusive Tabellenlayout) und liefert dieselbe "
        "Kennzahlenstruktur."
    )

    uploaded = st.file_uploader("Quartalsbericht als PDF", type="pdf", key="qr_upload")
    ticker = st.text_input("Ticker / Kürzel für den Report:", key="qr_upload_ticker").strip().upper()

    if uploaded is None:
        return

    pdf_bytes = uploaded.getvalue()
    st.caption(f"`{uploaded.name}` — {len(pdf_bytes) / 1_000_000:.1f} MB")

    if not qa.is_llm_configured():
        st.warning(
            "Die LLM-Extraktion benötigt `ANTHROPIC_API_KEY` in der `.env` und das Paket "
            "`anthropic`. Ohne Key steht für dieses PDF nur der klassische Scanner zur Verfügung."
        )
        return

    col_model, col_button = st.columns([1, 2])
    with col_model:
        model = st.selectbox("Modell:", ["claude-opus-5", "claude-sonnet-5"], key="qr_upload_model")
    with col_button:
        st.markdown("&nbsp;")
        run = st.button("🤖 Bericht auswerten", key="qr_upload_run", type="primary")

    if run:
        with st.spinner("Claude liest den Bericht ..."):
            try:
                result = qa.extract_kpis_with_llm(
                    ticker or uploaded.name.rsplit(".", 1)[0][:12].upper(),
                    pdf_bytes=pdf_bytes,
                    model=model,
                    document_label=uploaded.name,
                )
                st.session_state[RESULT_KEY] = result
                st.session_state.pop("qr_pdf_bytes", None)
            except Exception as exc:
                st.error(f"Auswertung fehlgeschlagen: {exc}")

    result = st.session_state.get(RESULT_KEY)
    if result:
        st.markdown("---")
        _render_result(result)


# ----------------------------------------------------------------------------
# Mode 3: classic heuristic scanner (previous PDF analyzer)
# ----------------------------------------------------------------------------

def _load_classic_document() -> None:
    """Source selection for the heuristic scanner: Yahoo filing list or PDF upload."""
    source = st.radio(
        "Quelle des Finanzberichts",
        ["Yahoo Finance (Automatisch laden)", "Eigene PDF-Datei hochladen (Manuell)"],
        horizontal=True,
        key="qr_classic_source",
    )

    if source == "Yahoo Finance (Automatisch laden)":
        st.info(
            "💡 **Hinweis:** SEC-Finanzberichte (10-K, 10-Q) stehen primär für "
            "**US-amerikanische Unternehmen** zur Verfügung. Für europäische oder asiatische "
            "Aktien (z. B. SAP, ASML, BMW) bitte die PDF-Upload-Option verwenden."
        )
        ticker = _ticker_picker("qr_classic_ticker")
        if not ticker:
            return

        report_filter = st.selectbox(
            "Filter für Berichtstyp",
            ["Nur Hauptberichte (10-K / 10-Q)", "Alle Berichte (10-K, 10-Q, 8-K, SD, etc.)"],
            key="qr_classic_filter",
        )

        if st.button("🔌 Verfügbare Berichte abrufen", key="qr_classic_fetch"):
            with st.spinner(f"Rufe Berichte für {ticker} ab ..."):
                filings = fetch_sec_filings(ticker)
                if filings:
                    st.session_state["qr_classic_filings"] = filings
                    st.session_state["qr_classic_filings_ticker"] = ticker
                    st.success(f"{len(filings)} Berichte für {ticker} gefunden!")
                else:
                    st.error(
                        f"Keine Berichte für {ticker} gefunden. Bitte Schreibweise prüfen "
                        "oder ein PDF hochladen."
                    )
                    st.session_state.pop("qr_classic_filings", None)

        filings = st.session_state.get("qr_classic_filings") or []
        if not filings or st.session_state.get("qr_classic_filings_ticker") != ticker:
            return

        if report_filter.startswith("Nur Hauptberichte"):
            filings = [f for f in filings if f["type"] in ("10-K", "10-Q")]
        if not filings:
            st.warning("Keine Berichte entsprechen dem gewählten Filter.")
            return

        st.dataframe(
            pd.DataFrame([
                {"Datum": f["date"], "Typ": f["type"], "Titel": f["title"], "Link": f["url"]}
                for f in filings
            ]),
            column_config={
                "Link": st.column_config.LinkColumn("Bericht öffnen", display_text="Im Browser öffnen ↗"),
            },
            hide_index=True,
            use_container_width=True,
        )

        options = [f"{f['date']} | {f['type']} | {f['title']}" for f in filings]
        choice = st.selectbox("Zu analysierenden Bericht wählen:", options, key="qr_classic_choice")
        if st.button("⚡ Bericht laden & analysieren", key="qr_classic_load"):
            filing = filings[options.index(choice)]
            with st.spinner("Lade Bericht und extrahiere Text ..."):
                try:
                    pages = download_and_parse_filing(filing["url"])
                    if pages:
                        st.session_state[PAGES_KEY] = pages
                        st.session_state[REPORT_NAME_KEY] = (
                            f"{ticker} {filing['type']} ({filing['date']})"
                        )
                        st.success(f"Erfolgreich geladen! {len(pages)} Abschnitte eingelesen.")
                        st.rerun()
                    else:
                        st.error("Text konnte nicht aus dem Bericht extrahiert werden.")
                except Exception as exc:
                    st.error(f"Fehler beim Herunterladen des Berichts: {exc}")

    else:
        uploaded = st.file_uploader("PDF-Finanzbericht hochladen", type="pdf", key="qr_classic_upload")
        if uploaded is None:
            return
        document_id = f"pdf_{uploaded.name}_{uploaded.size}"
        if st.session_state.get(REPORT_NAME_KEY) == document_id:
            return
        with st.spinner("Extrahiere Text aus PDF-Seiten ..."):
            try:
                pages = extract_text_from_pdf(io.BytesIO(uploaded.read()))
                if pages:
                    st.session_state[PAGES_KEY] = pages
                    st.session_state[REPORT_NAME_KEY] = document_id
                    st.session_state["qr_classic_display_name"] = uploaded.name
                    st.success(f"Erfolgreich {len(pages)} Seiten eingelesen!")
                    st.rerun()
                else:
                    st.error(
                        "Text konnte nicht extrahiert werden — bei gescannten PDFs liefert "
                        "die Textextraktion keine Inhalte."
                    )
            except Exception as exc:
                st.error(f"Fehler beim Einlesen des PDFs: {exc}")


def _render_classic_scan(pages_data: List[Dict[str, Any]], locale: str) -> None:
    st.markdown("### 🔍 Gefundene Finanzzahlen im Bericht")
    st.info(
        "Der klassische Scanner durchsucht Zeilen mit Zahlen nach Begriffen wie 'Revenue', "
        "'Net Income', 'Operating Cash Flow' oder 'Verbindlichkeiten'. Er arbeitet rein "
        "heuristisch — für belastbare Quartalszahlen die Ticker- oder PDF-Analyse oben nutzen."
    )

    with st.spinner("Extrahiere und strukturiere Finanzkennzahlen ..."):
        extracted = extract_structured_financials(pages_data, locale=locale)

    if not extracted:
        st.warning("Keine strukturierten Finanzkennzahlen im Bericht gefunden.")
        return

    frame = pd.DataFrame(extracted)
    col1, col2, col3 = st.columns(3)
    col1.metric("Treffer gesamt", f"{len(frame)} Kennzahlen")
    years = frame["Year"].dropna().unique()
    col2.metric("Zeitraum", f"{int(min(years))} - {int(max(years))}" if len(years) else "Keine Jahreszahl")
    col3.metric("Dokumentenlänge", f"{len(pages_data)} Abschnitte")

    with_years = frame[frame["Year"].notna()].copy()
    if with_years.empty:
        st.warning("Keine Werte mit zuordenbaren Jahreszahlen gefunden.")
    else:
        with_years["Year"] = with_years["Year"].astype(int)
        pivot = with_years.pivot_table(index="Metric", columns="Year", values="Value (Mio)", aggfunc="first")
        desired = [
            "Revenue / Umsatz",
            "Operating Income / EBIT / Betriebsergebnis",
            "Net Income / Konzernergebnis",
            "Cash Flow",
            "Total Debt / Verbindlichkeiten",
        ]
        order = [m for m in desired if m in pivot.index]
        pivot = pivot.reindex(order + [m for m in pivot.index if m not in desired])

        formatter = pivot.map if hasattr(pivot, "map") else pivot.applymap
        st.markdown("#### 📊 Finanzkennzahlen im Zeitverlauf (in Millionen)")
        st.dataframe(
            formatter(lambda v: f"{v:,.2f} Mio." if pd.notna(v) else "-"),
            use_container_width=True,
        )

        chart_metric = st.selectbox(
            "Kennzahl visualisieren:",
            options=sorted(with_years["Metric"].unique()),
            key="qr_classic_chart",
        )
        chart_data = with_years[with_years["Metric"] == chart_metric]
        if not chart_data.empty:
            st.bar_chart(
                chart_data.groupby("Year")["Value (Mio)"].max().to_frame(),
                use_container_width=True,
            )

    with st.expander("📂 Quellennachweis & Rohdaten anzeigen"):
        st.dataframe(
            frame[["Metric", "Year", "Raw Value", "Value (Mio)", "Page", "Context"]],
            column_config={
                "Page": st.column_config.NumberColumn("Seite", format="%d"),
                "Year": st.column_config.NumberColumn("Jahr", format="%d"),
                "Value (Mio)": st.column_config.NumberColumn("Wert (Mio)", format="%.2f"),
                "Context": st.column_config.TextColumn("Quellsatz / Kontext", width="large"),
            },
            hide_index=True,
            use_container_width=True,
        )
        st.download_button(
            "📥 Extrahierte Daten als CSV herunterladen",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"financial_extract_{st.session_state.get(REPORT_NAME_KEY, 'report')}.csv",
            mime="text/csv",
            key="qr_classic_csv",
        )


def _render_classic_keywords(pages_data: List[Dict[str, Any]]) -> None:
    st.markdown("### 🔑 Stichwortsuche im Bericht")
    keyword_input = st.text_input(
        "Suchbegriffe (kommagetrennt):",
        "debt, Schulden, risk, Risiko, revenue, Umsatz",
        key="qr_classic_keywords",
    )
    keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
    if not keywords:
        return

    with st.spinner("Durchsuche Bericht ..."):
        matches = search_keywords_in_pdf(pages_data, keywords)

    if not matches:
        st.info("Keine Treffer für die eingegebenen Begriffe gefunden.")
        return

    frame = pd.DataFrame(matches)
    col1, col2, col3 = st.columns(3)
    col1.metric("Treffer gesamt", f"{len(frame)}")
    col2.metric("Unique Begriffe", f"{frame['keyword'].nunique()}")
    col3.metric("Seiten mit Treffern", f"{frame['page'].nunique()}")

    st.markdown("#### 📊 Verteilung der Treffer")
    left, right = st.columns(2)
    with left:
        st.markdown("**Häufigkeit nach Suchbegriff**")
        st.bar_chart(frame["keyword"].value_counts(), use_container_width=True)
    with right:
        st.markdown("**Verteilung über den Dokumentenverlauf**")
        counts = frame.groupby("page").size().reset_index(name="Treffer")
        all_pages = pd.DataFrame({"page": range(1, len(pages_data) + 1)})
        st.area_chart(
            pd.merge(all_pages, counts, on="page", how="left").fillna(0).set_index("page"),
            use_container_width=True,
        )

    st.markdown("#### 📋 Treffer filtern")
    filter_left, filter_right = st.columns(2)
    with filter_left:
        keyword_filter = st.selectbox(
            "Nach Suchbegriff:", ["Alle"] + list(frame["keyword"].unique()), key="qr_classic_kwf"
        )
    with filter_right:
        page_filter = st.selectbox(
            "Nach Seite:", ["Alle"] + sorted(frame["page"].unique()), key="qr_classic_pagef"
        )

    filtered = frame
    if keyword_filter != "Alle":
        filtered = filtered[filtered["keyword"] == keyword_filter]
    if page_filter != "Alle":
        filtered = filtered[filtered["page"] == page_filter]

    st.markdown(f"Zeige **{len(filtered)}** gefilterte Treffer:")
    for _, row in filtered.head(100).iterrows():
        st.markdown(f"**Seite {row['page']}** | Begriff: `{row['keyword']}`")
        st.markdown(row["context"])
        st.markdown("---")
    if len(filtered) > 100:
        st.info("Es werden nur die ersten 100 Treffer angezeigt. Bitte Filter nutzen.")

    st.download_button(
        "📥 Alle Suchergebnisse herunterladen (CSV)",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=f"keyword_search_{st.session_state.get(REPORT_NAME_KEY, 'report')}.csv",
        mime="text/csv",
        key="qr_classic_kw_csv",
    )


def _render_classic_mode() -> None:
    st.markdown(
        "Der bisherige heuristische Scanner: Zeilen-Regex über den Berichtstext plus "
        "Stichwortsuche mit Kontext. Nützlich für Textstellen und Berichte, die die "
        "strukturierte Extraktion nicht abdeckt."
    )

    _load_classic_document()

    pages_data = st.session_state.get(PAGES_KEY)
    if not pages_data:
        return

    display_name = st.session_state.get("qr_classic_display_name") or st.session_state.get(REPORT_NAME_KEY, "")
    st.markdown("---")
    st.markdown(f"📊 **Geladener Bericht:** `{display_name}` ({len(pages_data)} Abschnitte/Seiten)")

    if st.button("🗑️ Bericht zurücksetzen", key="qr_classic_reset"):
        for key in (PAGES_KEY, REPORT_NAME_KEY, "qr_classic_display_name", "qr_classic_locale"):
            st.session_state.pop(key, None)
        st.rerun()

    if st.session_state.get("qr_classic_locale_for") != st.session_state.get(REPORT_NAME_KEY):
        st.session_state["qr_classic_locale"] = detect_report_locale(pages_data)
        st.session_state["qr_classic_locale_for"] = st.session_state.get(REPORT_NAME_KEY)
    detected = st.session_state.get("qr_classic_locale", "en")

    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            f"🌐 **Erkannte Berichtssprache:** "
            f"{'🇩🇪 Deutsch' if detected == 'de' else '🇺🇸 Englisch (US)'}"
        )
    with right:
        override = st.selectbox(
            "Zahlenformat für die Extraktion:",
            ["Automatisch (Erkannt)", "US-Format (z.B. 12,500.00)", "Deutsches Format (z.B. 12.500,00)"],
            key="qr_classic_format",
        )
    locale = {"US-Format (z.B. 12,500.00)": "en", "Deutsches Format (z.B. 12.500,00)": "de"}.get(
        override, detected
    )

    st.markdown("---")
    mode = st.radio(
        "Analyse-Modus wählen",
        ["Automatischer Scan nach Schlüsseldaten", "Stichwortsuche (Keywords)"],
        horizontal=True,
        key="qr_classic_mode",
    )
    if mode == "Automatischer Scan nach Schlüsseldaten":
        _render_classic_scan(pages_data, locale)
    else:
        _render_classic_keywords(pages_data)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def render_qreport_tab() -> None:
    """Render the "Quartalsbericht-Analyzer" tab."""
    st.markdown("### 📄 Quartalsbericht-Analyzer (Q-Report)")
    st.markdown(
        "Quartalszahlen aus Originalberichten extrahieren, QoQ/YoY vergleichen und einen "
        "eigenen Research-Report je Ticker erzeugen."
    )

    mode = st.radio(
        "Modus",
        ["📈 Ticker-Analyse (SEC)", "📤 Eigener Bericht (PDF)", "🔎 Klassischer Scanner"],
        horizontal=True,
        key="qr_mode",
    )

    st.markdown("---")
    if mode.startswith("📈"):
        _render_ticker_mode()
    elif mode.startswith("📤"):
        _render_upload_mode()
    else:
        _render_classic_mode()
