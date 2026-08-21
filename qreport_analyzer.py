"""Quartalsbericht-Analyzer (Q-Report Analyzer).

Turns a quarterly report into a clean per-quarter KPI table with QoQ/YoY deltas.

Three data sources feed the same normalized fact structure, in this precedence:

1. **SEC XBRL** (``data.sec.gov/api/xbrl/companyfacts``) — the numbers the company
   itself tagged. Exact, no parsing heuristics, US filers only.
2. **LLM extraction** — the filing text (or the raw PDF) is handed to Claude, which
   returns structured JSON. Works for German Quartalsberichte and any non-XBRL PDF.
3. **yfinance quarterly financials** — coarse fallback / cross-check.

Everything downstream (``qreport_ui.py``, ``qreport_report.py``) consumes
:class:`QuarterFact` lists and the frames built from them, so a source can be added
or dropped without touching the UI.

Unlike ``pdf_analyzer.py`` — the line-regex scanner this module supersedes for
quarterly work — no figure here is guessed from a text line: every value carries the
source it came from and, where applicable, the XBRL tag or the report page.
"""

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

# Windows consoles choke on the € / ü in the German labels below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# The SEC requires a descriptive User-Agent on every request and throttles at
# 10 req/s. Set SEC_USER_AGENT in .env to add your own contact address.
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "Falcone Capital Research Terminal (qreport-analyzer)",
)
SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

EDGAR_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
EDGAR_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{doc}"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qreport_cache.json")
CACHE_TTL_SECONDS = 6 * 60 * 60  # EDGAR data changes at filing frequency, not by the minute

DEFAULT_LLM_MODEL = "claude-opus-5"
# Claude Opus 5 list price, USD per 1M tokens (input / output).
LLM_PRICE_PER_MTOK = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (3.0, 15.0)}

_HTTP_TIMEOUT = 30


# ----------------------------------------------------------------------------
# KPI definitions
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class KpiDef:
    key: str
    label_de: str
    kind: str            # "flow" (period total) | "instant" (balance date) | "per_share"
    unit: str            # "currency" | "per_share"
    xbrl_tags: Tuple[str, ...] = ()
    higher_is_better: bool = True
    sort_order: int = 0


KPI_DEFINITIONS: Tuple[KpiDef, ...] = (
    KpiDef(
        key="revenue",
        label_de="Umsatz",
        kind="flow",
        unit="currency",
        xbrl_tags=(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
        ),
        sort_order=10,
    ),
    KpiDef(
        key="gross_profit",
        label_de="Bruttoergebnis",
        kind="flow",
        unit="currency",
        xbrl_tags=("GrossProfit",),
        sort_order=20,
    ),
    KpiDef(
        key="operating_income",
        label_de="Betriebsergebnis (EBIT)",
        kind="flow",
        unit="currency",
        xbrl_tags=("OperatingIncomeLoss",),
        sort_order=30,
    ),
    KpiDef(
        key="net_income",
        label_de="Konzernergebnis",
        kind="flow",
        unit="currency",
        xbrl_tags=("NetIncomeLoss", "ProfitLoss"),
        sort_order=40,
    ),
    KpiDef(
        key="eps_diluted",
        label_de="Ergebnis je Aktie (verwässert)",
        kind="per_share",
        unit="per_share",
        xbrl_tags=("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
        sort_order=50,
    ),
    KpiDef(
        key="operating_cash_flow",
        label_de="Operativer Cashflow",
        kind="flow",
        unit="currency",
        xbrl_tags=(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        sort_order=60,
    ),
    KpiDef(
        key="capex",
        label_de="Investitionen (CapEx)",
        kind="flow",
        unit="currency",
        xbrl_tags=(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        higher_is_better=False,
        sort_order=70,
    ),
    KpiDef(
        key="free_cash_flow",
        label_de="Free Cashflow",
        kind="flow",
        unit="currency",
        sort_order=80,
    ),
    KpiDef(
        key="cash",
        label_de="Liquide Mittel",
        kind="instant",
        unit="currency",
        xbrl_tags=(
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        sort_order=90,
    ),
    KpiDef(
        key="total_debt",
        label_de="Finanzverbindlichkeiten",
        kind="instant",
        unit="currency",
        higher_is_better=False,
        sort_order=100,
    ),
)

KPI_BY_KEY: Dict[str, KpiDef] = {k.key: k for k in KPI_DEFINITIONS}
KPI_ORDER: List[str] = [k.key for k in sorted(KPI_DEFINITIONS, key=lambda k: k.sort_order)]

# total_debt is assembled from current + non-current components.
_DEBT_COMPONENT_TAGS = ("LongTermDebtNoncurrent", "LongTermDebtCurrent")
_DEBT_FALLBACK_TAGS = ("LongTermDebt", "DebtLongtermAndShorttermCombinedAmount")

_MONEY_UNITS = ("USD", "EUR", "CHF", "GBP", "JPY", "CAD")
_PER_SHARE_UNITS = ("USD/shares", "EUR/shares", "CHF/shares", "GBP/shares")


# ----------------------------------------------------------------------------
# Fact structure
# ----------------------------------------------------------------------------

@dataclass
class QuarterFact:
    """One KPI value for one fiscal quarter, with its provenance."""

    metric: str
    period_label: str          # "Q3 FY2025"
    fiscal_year: int
    fiscal_quarter: int
    period_end: str            # ISO date
    value: float
    unit: str = "USD"
    source: str = "XBRL"       # XBRL | LLM | yfinance | derived
    detail: str = ""           # XBRL tag, report page, or derivation note
    derived: bool = False      # computed (e.g. Q4 = FY - 9M) rather than reported

    @property
    def sort_key(self) -> Tuple[int, int]:
        return (self.fiscal_year, self.fiscal_quarter)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LlmUsage:
    """Token spend of one extraction run, for the cost readout in the UI."""

    model: str = DEFAULT_LLM_MODEL
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    from_cache: bool = False

    @property
    def cost_usd(self) -> float:
        price_in, price_out = LLM_PRICE_PER_MTOK.get(self.model, (5.0, 25.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000.0


@dataclass
class ExtractionResult:
    """What one analysis run produced, ready for the UI and the PDF report."""

    ticker: str
    company_name: str = ""
    currency: str = "USD"
    facts: List[QuarterFact] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    fiscal_year_end_month: Optional[int] = None
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    llm_usage: Optional[LlmUsage] = None
    document_label: str = ""


# ----------------------------------------------------------------------------
# Small on-disk cache (EDGAR payloads + LLM extractions)
# ----------------------------------------------------------------------------

def _load_cache() -> Dict[str, Any]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_get(key: str, ttl: int = CACHE_TTL_SECONDS) -> Optional[Any]:
    entry = _load_cache().get(key)
    if not isinstance(entry, dict):
        return None
    if ttl and time.time() - entry.get("ts", 0) > ttl:
        return None
    return entry.get("payload")


def _cache_put(key: str, payload: Any) -> None:
    cache = _load_cache()
    cache[key] = {"ts": time.time(), "payload": payload}
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass  # a non-writable cache must never break an analysis


def clear_cache() -> None:
    try:
        os.remove(CACHE_FILE)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Fiscal calendar helpers
# ----------------------------------------------------------------------------

def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fiscal_label(period_end: date, fye_month: Optional[int] = None) -> Tuple[int, int, str]:
    """Map a period end date onto (fiscal_year, fiscal_quarter, label).

    52/53-week fiscal calendars let a quarter end in the first days of the next
    month (a period ending 2026-01-03 is the December quarter), so early days are
    pulled back into the previous month before the calendar maths.
    """
    month = period_end.month
    year = period_end.year
    if period_end.day <= 7:
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    if not fye_month:
        return year, (month - 1) // 3 + 1, f"Q{(month - 1) // 3 + 1} {year}"

    months_after_fye = (month - fye_month) % 12
    quarter = 4 if months_after_fye == 0 else (months_after_fye - 1) // 3 + 1
    fiscal_year = year + 1 if month > fye_month else year
    return fiscal_year, quarter, f"Q{quarter} FY{fiscal_year}"


def _period_sort_key(fact: "QuarterFact") -> Tuple[int, int]:
    return fact.sort_key


# ----------------------------------------------------------------------------
# SEC EDGAR: CIK lookup, filings, XBRL company facts
# ----------------------------------------------------------------------------

def _sec_get_json(url: str, cache_key: str, ttl: int = CACHE_TTL_SECONDS) -> Optional[Any]:
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    response = requests.get(url, headers=SEC_HEADERS, timeout=_HTTP_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    _cache_put(cache_key, payload)
    return payload


def resolve_cik(ticker: str) -> Optional[str]:
    """Ticker -> zero-padded 10-digit CIK via the SEC's public ticker map."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    try:
        mapping = _sec_get_json(EDGAR_TICKER_MAP_URL, "edgar_ticker_map", ttl=7 * 24 * 3600)
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(mapping, dict):
        return None
    for entry in mapping.values():
        if str(entry.get("ticker", "")).upper() == ticker:
            return str(entry.get("cik_str", "")).zfill(10)
    return None


def fetch_company_submissions(cik: str) -> Optional[Dict[str, Any]]:
    try:
        return _sec_get_json(
            EDGAR_SUBMISSIONS_URL.format(cik=cik), f"edgar_submissions_{cik}"
        )
    except (requests.RequestException, ValueError):
        return None


def fiscal_year_end_month_from_submissions(submissions: Dict[str, Any]) -> Optional[int]:
    """``fiscalYearEnd`` is an "MMDD" string, e.g. "0930" for a September year end."""
    raw = str(submissions.get("fiscalYearEnd") or "").strip()
    if len(raw) == 4 and raw.isdigit():
        month = int(raw[:2])
        if 1 <= month <= 12:
            return month
    return None


def fetch_edgar_filings(
    ticker: str,
    forms: Sequence[str] = ("10-Q", "10-K"),
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Recent filings for a ticker, newest first, straight from EDGAR.

    Each entry: ``date``, ``type``, ``title``, ``url`` (primary document),
    ``accession``, ``period``. Same shape as ``pdf_analyzer.fetch_sec_filings`` so
    both can feed the same UI, but sourced from EDGAR rather than yfinance.
    """
    cik = resolve_cik(ticker)
    if not cik:
        return []
    submissions = fetch_company_submissions(cik)
    if not submissions:
        return []

    recent = (submissions.get("filings") or {}).get("recent") or {}
    form_list = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    descriptions = recent.get("primaryDocDescription") or []

    wanted = {f.upper() for f in forms} if forms else None
    cik_int = str(int(cik))
    filings: List[Dict[str, Any]] = []

    for i, form in enumerate(form_list):
        if wanted and str(form).upper() not in wanted:
            continue
        accession = str(accessions[i]).replace("-", "") if i < len(accessions) else ""
        document = documents[i] if i < len(documents) else ""
        if not accession or not document:
            continue
        period = report_dates[i] if i < len(report_dates) else ""
        filings.append({
            "date": filing_dates[i] if i < len(filing_dates) else "",
            "type": str(form),
            "title": (descriptions[i] if i < len(descriptions) else "") or str(form),
            "period": period,
            "accession": accession,
            "url": EDGAR_ARCHIVE_URL.format(cik_int=cik_int, accession=accession, doc=document),
        })
        if len(filings) >= limit:
            break

    return filings


def fetch_company_facts(cik: str) -> Optional[Dict[str, Any]]:
    try:
        return _sec_get_json(
            EDGAR_COMPANYFACTS_URL.format(cik=cik), f"edgar_companyfacts_{cik}"
        )
    except (requests.RequestException, ValueError):
        return None


def _dedupe_entries(entries: Iterable[Dict[str, Any]], key_fields: Sequence[str]) -> List[Dict[str, Any]]:
    """Keep the most recently *filed* fact per period — restatements win."""
    best: Dict[Tuple, Dict[str, Any]] = {}
    for entry in entries:
        if entry.get("val") is None:
            continue
        key = tuple(entry.get(f) for f in key_fields)
        current = best.get(key)
        if current is None or str(entry.get("filed", "")) > str(current.get("filed", "")):
            best[key] = entry
    return list(best.values())


def _quarterly_from_durations(
    entries: Sequence[Dict[str, Any]],
    fye_month: Optional[int],
    tag: str,
) -> Dict[str, Dict[str, Any]]:
    """Turn duration facts into one value per fiscal quarter.

    Companies report a mix of quarterly and year-to-date periods (and only a
    year-to-date figure in Q4). Facts sharing a start date form a cumulative
    series, so the missing quarters come out of consecutive differences:
    ``Q3 = 9M - H1``, ``Q4 = FY - 9M``.
    """
    by_start: Dict[date, List[Tuple[date, float, Dict[str, Any]]]] = {}
    for entry in _dedupe_entries(entries, ("start", "end")):
        start = _parse_date(entry.get("start"))
        end = _parse_date(entry.get("end"))
        if not start or not end or end <= start:
            continue
        by_start.setdefault(start, []).append((end, float(entry["val"]), entry))

    results: Dict[str, Dict[str, Any]] = {}
    for start, series in by_start.items():
        series.sort(key=lambda item: item[0])
        previous_end, previous_value = start, 0.0
        for end, value, entry in series:
            span_days = (end - previous_end).days
            if 80 <= span_days <= 100:
                quarter_value = value - previous_value
                is_derived = previous_value != 0.0
                fiscal_year, quarter, label = fiscal_label(end, fye_month)
                existing = results.get(label)
                # A directly reported quarter always beats a derived one.
                if existing is None or (existing["derived"] and not is_derived):
                    results[label] = {
                        "value": quarter_value,
                        "fiscal_year": fiscal_year,
                        "fiscal_quarter": quarter,
                        "period_end": end.isoformat(),
                        "derived": is_derived,
                        "detail": f"{tag} ({'abgeleitet' if is_derived else 'berichtet'})",
                        "filed": entry.get("filed", ""),
                    }
            previous_end, previous_value = end, value

    return results


def _instants_by_period(
    entries: Sequence[Dict[str, Any]],
    fye_month: Optional[int],
    tag: str,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for entry in _dedupe_entries(entries, ("end",)):
        end = _parse_date(entry.get("end"))
        if not end:
            continue
        fiscal_year, quarter, label = fiscal_label(end, fye_month)
        existing = results.get(label)
        if existing is None or end.isoformat() > existing["period_end"]:
            results[label] = {
                "value": float(entry["val"]),
                "fiscal_year": fiscal_year,
                "fiscal_quarter": quarter,
                "period_end": end.isoformat(),
                "derived": False,
                "detail": tag,
                "filed": entry.get("filed", ""),
            }
    return results


def _pick_unit(units: Dict[str, Any], kind: str) -> Optional[str]:
    candidates = _PER_SHARE_UNITS if kind == "per_share" else _MONEY_UNITS
    for unit in candidates:
        if units.get(unit):
            return unit
    return next(iter(units), None) if units else None


def _series_for_tags(
    us_gaap: Dict[str, Any],
    tags: Sequence[str],
    kind: str,
    fye_month: Optional[int],
) -> Tuple[Dict[str, Dict[str, Any]], str]:
    """First tag in priority order that yields data wins; returns (series, unit)."""
    for tag in tags:
        fact = us_gaap.get(tag)
        if not fact:
            continue
        units = fact.get("units") or {}
        unit = _pick_unit(units, kind)
        if not unit:
            continue
        entries = units.get(unit) or []
        if kind == "instant":
            series = _instants_by_period(entries, fye_month, tag)
        else:
            series = _quarterly_from_durations(entries, fye_month, tag)
        if series:
            return series, unit
    return {}, ""


def extract_kpis_from_xbrl(
    ticker: str,
    max_quarters: int = 12,
) -> ExtractionResult:
    """Quarterly KPIs straight out of the company's own XBRL tagging."""
    result = ExtractionResult(ticker=ticker.upper())
    cik = resolve_cik(ticker)
    if not cik:
        result.warnings.append(
            f"Kein SEC-CIK für {ticker} gefunden — XBRL steht nur für US-Emittenten zur Verfügung."
        )
        return result

    submissions = fetch_company_submissions(cik) or {}
    fye_month = fiscal_year_end_month_from_submissions(submissions)
    result.fiscal_year_end_month = fye_month
    result.company_name = submissions.get("name", "") or ticker.upper()

    facts_payload = fetch_company_facts(cik)
    if not facts_payload:
        result.warnings.append("SEC companyfacts konnten nicht geladen werden.")
        return result

    us_gaap = (facts_payload.get("facts") or {}).get("us-gaap") or {}
    if not us_gaap:
        result.warnings.append("Keine us-gaap-Fakten in den SEC-Daten enthalten.")
        return result

    currency = "USD"
    collected: List[QuarterFact] = []

    for kpi in KPI_DEFINITIONS:
        if not kpi.xbrl_tags:
            continue
        series, unit = _series_for_tags(us_gaap, kpi.xbrl_tags, kpi.kind, fye_month)
        if unit and kpi.unit == "currency":
            currency = unit
        for label, item in series.items():
            collected.append(QuarterFact(
                metric=kpi.key,
                period_label=label,
                fiscal_year=item["fiscal_year"],
                fiscal_quarter=item["fiscal_quarter"],
                period_end=item["period_end"],
                value=item["value"],
                unit=unit or "USD",
                source="XBRL",
                detail=item["detail"],
                derived=item["derived"],
            ))

    collected.extend(_debt_facts_from_xbrl(us_gaap, fye_month))
    collected.extend(derive_free_cash_flow(collected))

    result.currency = currency if currency in _MONEY_UNITS else "USD"
    result.facts = _trim_to_recent_quarters(collected, max_quarters)
    if result.facts:
        result.sources_used.append("XBRL")
    else:
        result.warnings.append("XBRL enthielt keine auswertbaren Quartalswerte.")
    return result


def _debt_facts_from_xbrl(us_gaap: Dict[str, Any], fye_month: Optional[int]) -> List[QuarterFact]:
    """Total debt = current + non-current portion, falling back to combined tags."""
    component_series: List[Tuple[str, Dict[str, Dict[str, Any]], str]] = []
    for tag in _DEBT_COMPONENT_TAGS:
        series, unit = _series_for_tags(us_gaap, (tag,), "instant", fye_month)
        if series:
            component_series.append((tag, series, unit))

    facts: List[QuarterFact] = []
    if component_series:
        labels = set()
        for _, series, _ in component_series:
            labels.update(series.keys())
        for label in labels:
            total = 0.0
            parts: List[str] = []
            unit = "USD"
            meta: Optional[Dict[str, Any]] = None
            for tag, series, series_unit in component_series:
                item = series.get(label)
                if item:
                    total += item["value"]
                    parts.append(tag)
                    unit = series_unit or unit
                    meta = item
            if meta and parts:
                facts.append(QuarterFact(
                    metric="total_debt",
                    period_label=label,
                    fiscal_year=meta["fiscal_year"],
                    fiscal_quarter=meta["fiscal_quarter"],
                    period_end=meta["period_end"],
                    value=total,
                    unit=unit,
                    source="XBRL",
                    detail=" + ".join(parts),
                ))
        if facts:
            return facts

    series, unit = _series_for_tags(us_gaap, _DEBT_FALLBACK_TAGS, "instant", fye_month)
    for label, item in series.items():
        facts.append(QuarterFact(
            metric="total_debt",
            period_label=label,
            fiscal_year=item["fiscal_year"],
            fiscal_quarter=item["fiscal_quarter"],
            period_end=item["period_end"],
            value=item["value"],
            unit=unit or "USD",
            source="XBRL",
            detail=item["detail"],
        ))
    return facts


def derive_free_cash_flow(facts: Sequence[QuarterFact]) -> List[QuarterFact]:
    """FCF = operating cash flow - CapEx, for every quarter that has both."""
    ocf = {f.period_label: f for f in facts if f.metric == "operating_cash_flow"}
    capex = {f.period_label: f for f in facts if f.metric == "capex"}
    existing = {f.period_label for f in facts if f.metric == "free_cash_flow"}

    derived: List[QuarterFact] = []
    for label, cash_flow in ocf.items():
        if label in existing or label not in capex:
            continue
        derived.append(QuarterFact(
            metric="free_cash_flow",
            period_label=label,
            fiscal_year=cash_flow.fiscal_year,
            fiscal_quarter=cash_flow.fiscal_quarter,
            period_end=cash_flow.period_end,
            value=cash_flow.value - abs(capex[label].value),
            unit=cash_flow.unit,
            source=cash_flow.source,
            detail="Operativer Cashflow - CapEx",
            derived=True,
        ))
    return derived


def _trim_to_recent_quarters(facts: Sequence[QuarterFact], max_quarters: int) -> List[QuarterFact]:
    if not max_quarters:
        return list(facts)
    periods = sorted({f.sort_key for f in facts}, reverse=True)[:max_quarters]
    keep = set(periods)
    return [f for f in facts if f.sort_key in keep]


# ----------------------------------------------------------------------------
# Filing text (EDGAR HTML documents)
# ----------------------------------------------------------------------------

def fetch_filing_text(url: str, lines_per_page: int = 60) -> List[Dict[str, Any]]:
    """Download an EDGAR document and chunk it into ``pages_data`` pseudo-pages.

    Same contract as ``pdf_analyzer.download_and_parse_filing`` — a list of
    ``{"page_number": int, "content": str}`` — so both feed the LLM extractor.
    """
    response = requests.get(url, headers=SEC_HEADERS, timeout=_HTTP_TIMEOUT)
    response.raise_for_status()

    try:
        import lxml.html
        text = lxml.html.fromstring(response.content).text_content()
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", response.text)

    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]

    pages: List[Dict[str, Any]] = []
    for start in range(0, len(lines), lines_per_page):
        pages.append({
            "page_number": start // lines_per_page + 1,
            "content": "\n".join(lines[start:start + lines_per_page]),
        })
    return pages


_STATEMENT_MARKERS = (
    r"statements?\s+of\s+operations", r"statements?\s+of\s+income",
    r"balance\s+sheets?", r"statements?\s+of\s+cash\s+flows?",
    r"comprehensive\s+income", r"net\s+sales", r"total\s+revenue",
    r"operating\s+income", r"net\s+income", r"earnings\s+per\s+share",
    r"gewinn-\s*und\s*verlustrechnung", r"konzernbilanz", r"kapitalflussrechnung",
    r"umsatzerlöse", r"konzernergebnis", r"ergebnis\s+je\s+aktie", r"betriebsergebnis",
)
_STATEMENT_REGEX = re.compile("|".join(_STATEMENT_MARKERS), re.IGNORECASE)


def score_page(page: Dict[str, Any]) -> float:
    """How likely a page carries a financial statement rather than prose."""
    content = page.get("content") or ""
    if not content:
        return 0.0
    marker_hits = len(_STATEMENT_REGEX.findall(content))
    digits = sum(char.isdigit() for char in content)
    digit_density = digits / max(len(content), 1)
    grouped_numbers = len(re.findall(r"\d[\d.,]{2,}", content))
    return marker_hits * 3.0 + digit_density * 40.0 + min(grouped_numbers, 60) * 0.1


def select_financial_pages(
    pages_data: Sequence[Dict[str, Any]],
    max_pages: int = 14,
    max_chars: int = 120_000,
) -> List[Dict[str, Any]]:
    """Pick the statement-like pages, in document order, under a character budget.

    Keeps the request small enough to stay cheap without truncating a page
    mid-table: whole pages are included or left out, never cut.
    """
    if not pages_data:
        return []
    ranked = sorted(pages_data, key=score_page, reverse=True)[:max_pages]
    ranked.sort(key=lambda page: page.get("page_number", 0))

    selected: List[Dict[str, Any]] = []
    used_chars = 0
    for page in ranked:
        length = len(page.get("content") or "")
        if selected and used_chars + length > max_chars:
            continue
        selected.append(page)
        used_chars += length
    return selected


# ----------------------------------------------------------------------------
# LLM extraction
# ----------------------------------------------------------------------------

def is_llm_configured() -> bool:
    """True when an Anthropic API key and the SDK are both available."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "Legal name as printed in the report."},
        "currency": {"type": "string", "description": "ISO code of the reporting currency, e.g. USD or EUR."},
        "fiscal_year_end_month": {
            "type": "integer",
            "description": "Month (1-12) in which the fiscal year ends; 12 if unclear.",
        },
        "quarters": {
            "type": "array",
            "description": "One entry per fiscal quarter that the report states figures for, including prior-year comparatives.",
            "items": {
                "type": "object",
                "properties": {
                    "fiscal_year": {"type": "integer"},
                    "fiscal_quarter": {"type": "integer", "description": "1-4."},
                    "period_end": {"type": "string", "description": "Period end date as YYYY-MM-DD."},
                    "is_derived": {
                        "type": "boolean",
                        "description": "true when the quarter was computed from year-to-date figures rather than printed directly.",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {
                                    "type": "string",
                                    "enum": [k.key for k in KPI_DEFINITIONS],
                                },
                                "value": {
                                    "type": "number",
                                    "description": "Absolute units after applying the table's scale header (in millions/thousands). Losses and cash outflows negative; capex as a positive spend amount.",
                                },
                                "reported_text": {
                                    "type": "string",
                                    "description": "The figure exactly as printed, e.g. '(1,204)' or '12.540,5'.",
                                },
                                "page": {"type": "integer", "description": "page_number the figure was read from."},
                            },
                            "required": ["key", "value", "reported_text", "page"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["fiscal_year", "fiscal_quarter", "period_end", "is_derived", "metrics"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "Anything that qualifies the figures: one-offs, restatements, scale ambiguity, segments excluded.",
        },
    },
    "required": ["company_name", "currency", "fiscal_year_end_month", "quarters", "notes"],
    "additionalProperties": False,
}

_EXTRACTION_SYSTEM = """You are a financial analyst extracting quarterly figures from company reports (10-Q, 10-K, Geschäftsbericht, Quartalsmitteilung). Reports may be English or German.

Rules:
- Report only figures that are printed in the document. Never estimate, interpolate or fill in from memory. Omit a metric you cannot find.
- Apply the table's scale header: "(in millions)" / "in Mio. EUR" / "in Tausend" means the printed figure must be multiplied out to absolute units.
- German number format uses '.' for thousands and ',' for decimals: "12.540,5 Mio. EUR" is 12540500000.
- Parentheses, a leading minus, or the word "loss"/"Verlust" mean a negative value.
- capex is the cash spent on property/plant/equipment, reported as a POSITIVE number.
- operating_cash_flow keeps its sign as reported (negative when operations consumed cash).
- Consolidated group figures only — never a single segment, region, or non-GAAP adjusted variant when the GAAP figure is present.
- A quarterly column ("Three Months Ended") is a quarter. A year-to-date column ("Six/Nine Months Ended") is NOT: only turn it into a quarter by subtracting the prior year-to-date column printed in the same report, and set is_derived=true when you do.
- Include the prior-year comparative quarter that the report prints alongside the current quarter.
- Set fiscal_quarter from the company's own fiscal calendar, not the calendar year."""


def _build_extraction_prompt(ticker: str, pages: Sequence[Dict[str, Any]]) -> str:
    blocks = [
        f"[page_number={page.get('page_number')}]\n{page.get('content', '')}"
        for page in pages
    ]
    return (
        f"Extract the quarterly KPIs for {ticker} from the report pages below.\n\n"
        "Each page is delimited by a [page_number=N] marker; cite that number in the "
        "`page` field of every metric you extract.\n\n"
        "=== REPORT PAGES ===\n" + "\n\n".join(blocks)
    )


def _facts_from_llm_payload(payload: Dict[str, Any], fye_month: Optional[int]) -> List[QuarterFact]:
    currency = str(payload.get("currency") or "USD").upper()
    facts: List[QuarterFact] = []

    for quarter in payload.get("quarters") or []:
        period_end = _parse_date(quarter.get("period_end"))
        fiscal_year = quarter.get("fiscal_year")
        fiscal_quarter = quarter.get("fiscal_quarter")

        if period_end and not (fiscal_year and fiscal_quarter):
            fiscal_year, fiscal_quarter, label = fiscal_label(period_end, fye_month)
        elif fiscal_year and fiscal_quarter:
            label = f"Q{int(fiscal_quarter)} FY{int(fiscal_year)}" if fye_month else f"Q{int(fiscal_quarter)} {int(fiscal_year)}"
        else:
            continue

        for metric in quarter.get("metrics") or []:
            key = metric.get("key")
            if key not in KPI_BY_KEY or metric.get("value") is None:
                continue
            page = metric.get("page")
            reported = metric.get("reported_text") or ""
            detail = f"Seite {page}: {reported}".strip() if page else reported
            facts.append(QuarterFact(
                metric=key,
                period_label=label,
                fiscal_year=int(fiscal_year),
                fiscal_quarter=int(fiscal_quarter),
                period_end=period_end.isoformat() if period_end else "",
                value=float(metric["value"]),
                unit=currency if KPI_BY_KEY[key].unit == "currency" else f"{currency}/share",
                source="LLM",
                detail=detail,
                derived=bool(quarter.get("is_derived")),
            ))

    facts.extend(derive_free_cash_flow(facts))
    return facts


def extract_kpis_with_llm(
    ticker: str,
    pages_data: Optional[Sequence[Dict[str, Any]]] = None,
    pdf_bytes: Optional[bytes] = None,
    model: str = DEFAULT_LLM_MODEL,
    fye_month: Optional[int] = None,
    max_pages: int = 14,
    use_cache: bool = True,
    document_label: str = "",
) -> ExtractionResult:
    """Hand the report to Claude and get structured quarterly KPIs back.

    Pass ``pdf_bytes`` to send the PDF itself (best accuracy — the model sees the
    table layout), or ``pages_data`` for text that was already extracted, e.g. an
    EDGAR HTML filing. Results are cached on disk by content hash so Streamlit
    reruns don't re-bill the same document.
    """
    result = ExtractionResult(ticker=ticker.upper(), document_label=document_label)

    if not os.getenv("ANTHROPIC_API_KEY"):
        result.warnings.append(
            "ANTHROPIC_API_KEY ist nicht gesetzt — die LLM-Extraktion steht nicht zur Verfügung."
        )
        return result
    try:
        import anthropic
    except ImportError:
        result.warnings.append(
            "Das Paket 'anthropic' ist nicht installiert (pip install -r requirements.txt)."
        )
        return result

    if pdf_bytes:
        fingerprint = hashlib.sha256(pdf_bytes).hexdigest()
        selected_pages: List[Dict[str, Any]] = []
    elif pages_data:
        selected_pages = select_financial_pages(pages_data, max_pages=max_pages)
        if not selected_pages:
            result.warnings.append("Keine auswertbaren Seiten im Dokument gefunden.")
            return result
        joined = "\n".join(page.get("content", "") for page in selected_pages)
        fingerprint = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    else:
        result.warnings.append("Weder PDF noch Textseiten übergeben.")
        return result

    cache_key = f"llm_extract_{model}_{fingerprint}"
    if use_cache:
        cached = _cache_get(cache_key, ttl=30 * 24 * 3600)
        if cached is not None:
            result_from_cache = _facts_from_llm_payload(cached, fye_month or cached.get("fiscal_year_end_month"))
            result.facts = result_from_cache
            result.company_name = cached.get("company_name", "")
            result.currency = str(cached.get("currency") or "USD").upper()
            result.fiscal_year_end_month = fye_month or cached.get("fiscal_year_end_month")
            if cached.get("notes"):
                result.notes.append(str(cached["notes"]))
            result.sources_used.append("LLM")
            result.llm_usage = LlmUsage(model=model, from_cache=True)
            return result

    client = anthropic.Anthropic()

    if pdf_bytes:
        import base64
        content: List[Dict[str, Any]] = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode("utf-8"),
                },
            },
            {
                "type": "text",
                "text": (
                    f"Extract the quarterly KPIs for {ticker} from this report. "
                    "Use the PDF page number for the `page` field of every metric."
                ),
            },
        ]
    else:
        content = [{"type": "text", "text": _build_extraction_prompt(ticker, selected_pages)}]

    try:
        with client.messages.stream(
            model=model,
            max_tokens=32_000,
            system=_EXTRACTION_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": _EXTRACTION_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.APIStatusError as exc:
        result.warnings.append(f"Claude-API-Fehler ({exc.status_code}): {exc.message}")
        return result
    except anthropic.APIConnectionError:
        result.warnings.append("Claude-API nicht erreichbar — Netzwerkverbindung prüfen.")
        return result

    if message.stop_reason == "refusal":
        result.warnings.append("Claude hat die Auswertung dieses Dokuments abgelehnt.")
        return result

    text = next((block.text for block in message.content if block.type == "text"), "")
    try:
        payload = json.loads(text)
    except ValueError:
        result.warnings.append("Antwort des Modells war kein gültiges JSON.")
        return result

    if use_cache:
        _cache_put(cache_key, payload)

    effective_fye = fye_month or payload.get("fiscal_year_end_month")
    result.facts = _facts_from_llm_payload(payload, effective_fye)
    result.company_name = payload.get("company_name", "")
    result.currency = str(payload.get("currency") or "USD").upper()
    result.fiscal_year_end_month = effective_fye
    if payload.get("notes"):
        result.notes.append(str(payload["notes"]))
    result.sources_used.append("LLM")
    result.llm_usage = LlmUsage(
        model=model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
    )
    if not result.facts:
        result.warnings.append("Das Modell hat keine Quartalswerte im Dokument gefunden.")
    return result


# ----------------------------------------------------------------------------
# yfinance fallback
# ----------------------------------------------------------------------------

_YF_ROW_MAP = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income", "EBIT"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "eps_diluted": ("Diluted EPS",),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure",),
    "free_cash_flow": ("Free Cash Flow",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "total_debt": ("Total Debt",),
}


def extract_kpis_from_yfinance(ticker: str, max_quarters: int = 12) -> ExtractionResult:
    """Coarse fallback: Yahoo's quarterly statements, for cross-checking."""
    result = ExtractionResult(ticker=ticker.upper())
    try:
        import yfinance as yf
    except ImportError:
        result.warnings.append("yfinance ist nicht installiert.")
        return result

    try:
        handle = yf.Ticker(ticker)
        frames = [
            handle.quarterly_financials,
            handle.quarterly_balance_sheet,
            handle.quarterly_cashflow,
        ]
        info = handle.info or {}
    except Exception as exc:  # yfinance raises a wide range of network/parse errors
        result.warnings.append(f"yfinance-Abruf fehlgeschlagen: {exc}")
        return result

    result.company_name = info.get("longName") or info.get("shortName") or ticker.upper()
    result.currency = (info.get("financialCurrency") or "USD").upper()

    facts: List[QuarterFact] = []
    for frame in frames:
        if frame is None or getattr(frame, "empty", True):
            continue
        for column in frame.columns:
            period_end = _parse_date(str(column))
            if not period_end:
                continue
            fiscal_year, quarter, label = fiscal_label(period_end)
            for key, row_names in _YF_ROW_MAP.items():
                for row in row_names:
                    if row not in frame.index:
                        continue
                    value = frame.loc[row, column]
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        continue
                    if value != value:  # NaN
                        continue
                    if key == "capex":
                        value = abs(value)
                    facts.append(QuarterFact(
                        metric=key,
                        period_label=label,
                        fiscal_year=fiscal_year,
                        fiscal_quarter=quarter,
                        period_end=period_end.isoformat(),
                        value=value,
                        unit=result.currency,
                        source="yfinance",
                        detail=row,
                    ))
                    break

    facts.extend(derive_free_cash_flow(facts))
    result.facts = _trim_to_recent_quarters(facts, max_quarters)
    if result.facts:
        result.sources_used.append("yfinance")
    else:
        result.warnings.append("yfinance lieferte keine Quartalsdaten.")
    return result


# ----------------------------------------------------------------------------
# Merging and analysis
# ----------------------------------------------------------------------------

SOURCE_PRECEDENCE = {"XBRL": 3, "LLM": 2, "yfinance": 1}


def merge_results(*results: ExtractionResult) -> ExtractionResult:
    """Combine source results; the highest-precedence value per (metric, period) wins."""
    ordered = [r for r in results if r is not None]
    if not ordered:
        return ExtractionResult(ticker="")

    merged = ExtractionResult(
        ticker=next((r.ticker for r in ordered if r.ticker), ""),
        company_name=next((r.company_name for r in ordered if r.company_name), ""),
        currency=next((r.currency for r in ordered if r.facts), ordered[0].currency),
        fiscal_year_end_month=next(
            (r.fiscal_year_end_month for r in ordered if r.fiscal_year_end_month), None
        ),
        document_label=next((r.document_label for r in ordered if r.document_label), ""),
    )

    best: Dict[Tuple[str, str], QuarterFact] = {}
    for result in ordered:
        merged.notes.extend(result.notes)
        merged.warnings.extend(result.warnings)
        if result.llm_usage and not merged.llm_usage:
            merged.llm_usage = result.llm_usage
        for source in result.sources_used:
            if source not in merged.sources_used:
                merged.sources_used.append(source)
        for fact in result.facts:
            key = (fact.metric, fact.period_label)
            current = best.get(key)
            if current is None:
                best[key] = fact
                continue
            rank_new = (SOURCE_PRECEDENCE.get(fact.source, 0), 0 if fact.derived else 1)
            rank_old = (SOURCE_PRECEDENCE.get(current.source, 0), 0 if current.derived else 1)
            if rank_new > rank_old:
                best[key] = fact

    merged.facts = sorted(
        best.values(),
        key=lambda f: (KPI_ORDER.index(f.metric) if f.metric in KPI_ORDER else 99, f.sort_key),
    )
    return merged


def facts_to_frame(facts: Sequence[QuarterFact]):
    """Wide KPI frame: rows = metric keys in report order, columns = periods (oldest first)."""
    import pandas as pd

    if not facts:
        return pd.DataFrame()

    periods = sorted({(f.fiscal_year, f.fiscal_quarter, f.period_label) for f in facts})
    columns = [p[2] for p in periods]
    metrics = [key for key in KPI_ORDER if any(f.metric == key for f in facts)]

    data = {column: {metric: float("nan") for metric in metrics} for column in columns}
    for fact in facts:
        if fact.metric in metrics:
            data[fact.period_label][fact.metric] = fact.value

    frame = pd.DataFrame(data, columns=columns).reindex(metrics)
    frame.index.name = "metric"
    return frame


def source_frame(facts: Sequence[QuarterFact]):
    """Same shape as :func:`facts_to_frame`, holding the source label per cell."""
    import pandas as pd

    if not facts:
        return pd.DataFrame()
    frame = facts_to_frame(facts)
    marks = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for fact in facts:
        if fact.metric in marks.index and fact.period_label in marks.columns:
            marks.loc[fact.metric, fact.period_label] = (
                f"{fact.source}*" if fact.derived else fact.source
            )
    return marks


def compute_deltas(facts: Sequence[QuarterFact]) -> List[Dict[str, Any]]:
    """QoQ and YoY change per metric for every period that has a comparison base."""
    by_key: Dict[Tuple[str, int, int], QuarterFact] = {
        (f.metric, f.fiscal_year, f.fiscal_quarter): f for f in facts
    }

    rows: List[Dict[str, Any]] = []
    for fact in sorted(facts, key=lambda f: (f.metric, f.sort_key)):
        previous_quarter = fact.fiscal_quarter - 1 or 4
        previous_year = fact.fiscal_year - (1 if fact.fiscal_quarter == 1 else 0)
        qoq_base = by_key.get((fact.metric, previous_year, previous_quarter))
        yoy_base = by_key.get((fact.metric, fact.fiscal_year - 1, fact.fiscal_quarter))

        rows.append({
            "metric": fact.metric,
            "metric_label": KPI_BY_KEY[fact.metric].label_de if fact.metric in KPI_BY_KEY else fact.metric,
            "period": fact.period_label,
            "fiscal_year": fact.fiscal_year,
            "fiscal_quarter": fact.fiscal_quarter,
            "value": fact.value,
            "unit": fact.unit,
            "source": fact.source,
            "derived": fact.derived,
            "detail": fact.detail,
            "qoq_abs": fact.value - qoq_base.value if qoq_base else None,
            "qoq_pct": _pct_change(fact.value, qoq_base.value) if qoq_base else None,
            "yoy_abs": fact.value - yoy_base.value if yoy_base else None,
            "yoy_pct": _pct_change(fact.value, yoy_base.value) if yoy_base else None,
        })
    return rows


def _pct_change(current: float, base: float) -> Optional[float]:
    """Percent change, undefined when the base is zero or flips sign.

    A swing from a loss to a profit has no meaningful percentage; the UI shows the
    absolute change for those instead of a misleading -320%.
    """
    if not base or base == 0:
        return None
    if (base < 0) != (current < 0) and base < 0:
        return None
    return (current - base) / abs(base) * 100.0


def compute_margins(facts: Sequence[QuarterFact]) -> List[Dict[str, Any]]:
    """Gross / operating / net margin and FCF conversion per quarter, in percent."""
    revenue = {f.period_label: f for f in facts if f.metric == "revenue" and f.value}
    rows: List[Dict[str, Any]] = []

    margin_specs = (
        ("gross_profit", "Bruttomarge"),
        ("operating_income", "Operative Marge"),
        ("net_income", "Nettomarge"),
        ("free_cash_flow", "FCF-Marge"),
    )
    by_metric_period = {(f.metric, f.period_label): f for f in facts}

    for label, base in sorted(revenue.items(), key=lambda item: item[1].sort_key):
        row: Dict[str, Any] = {
            "period": label,
            "fiscal_year": base.fiscal_year,
            "fiscal_quarter": base.fiscal_quarter,
        }
        for metric, name in margin_specs:
            fact = by_metric_period.get((metric, label))
            row[name] = (fact.value / base.value * 100.0) if fact else None
        rows.append(row)
    return rows


def latest_period(facts: Sequence[QuarterFact]) -> Optional[str]:
    if not facts:
        return None
    return max(facts, key=lambda f: f.sort_key).period_label


def analyze_ticker(
    ticker: str,
    use_xbrl: bool = True,
    use_llm: bool = True,
    use_yfinance: bool = True,
    filing_url: Optional[str] = None,
    max_quarters: int = 12,
    model: str = DEFAULT_LLM_MODEL,
) -> ExtractionResult:
    """Full pipeline for a ticker: XBRL + LLM on the latest 10-Q + yfinance fallback."""
    results: List[ExtractionResult] = []
    fye_month: Optional[int] = None

    if use_xbrl:
        xbrl = extract_kpis_from_xbrl(ticker, max_quarters=max_quarters)
        fye_month = xbrl.fiscal_year_end_month
        results.append(xbrl)

    if use_llm and is_llm_configured():
        url = filing_url
        label = ""
        if not url:
            filings = fetch_edgar_filings(ticker, forms=("10-Q",), limit=1)
            if filings:
                url = filings[0]["url"]
                label = f"{filings[0]['type']} {filings[0]['date']}"
        if url:
            try:
                pages = fetch_filing_text(url)
                results.append(extract_kpis_with_llm(
                    ticker,
                    pages_data=pages,
                    model=model,
                    fye_month=fye_month,
                    document_label=label or url,
                ))
            except requests.RequestException as exc:
                failed = ExtractionResult(ticker=ticker.upper())
                failed.warnings.append(f"Bericht konnte nicht geladen werden: {exc}")
                results.append(failed)

    if use_yfinance:
        results.append(extract_kpis_from_yfinance(ticker, max_quarters=max_quarters))

    merged = merge_results(*results)
    merged.facts = _trim_to_recent_quarters(merged.facts, max_quarters)
    return merged


# ----------------------------------------------------------------------------
# CLI smoke test
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Q-Report-Analyse für {symbol} ...")
    outcome = analyze_ticker(symbol, use_llm=is_llm_configured())

    print(f"Unternehmen : {outcome.company_name}")
    print(f"Quellen     : {', '.join(outcome.sources_used) or 'keine'}")
    print(f"Währung     : {outcome.currency}")
    for warning in outcome.warnings:
        print(f"  ! {warning}")

    frame = facts_to_frame(outcome.facts)
    if frame.empty:
        print("Keine Quartalswerte gefunden.")
    else:
        print(frame.to_string())
