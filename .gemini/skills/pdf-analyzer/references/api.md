# pdf_analyzer function reference

Every signature, return shape and edge case, in source order. Line numbers refer to
`pdf_analyzer.py` at the time of writing and will drift — treat them as hints.

## Contents

- [extract_text_from_pdf](#extract_text_from_pdf)
- [detect_report_locale](#detect_report_locale)
- [search_keywords_in_pdf](#search_keywords_in_pdf)
- [normalize_value_with_locale](#normalize_value_with_locale)
- [scan_for_financial_metrics](#scan_for_financial_metrics)
- [extract_structured_financials](#extract_structured_financials)
- [fetch_sec_filings](#fetch_sec_filings)
- [download_and_parse_filing](#download_and_parse_filing)
- [The metric patterns](#the-metric-patterns)

---

## extract_text_from_pdf

```python
extract_text_from_pdf(pdf_file) -> List[Dict[str, Any]]
```

*Line ~8.* Wraps `pypdf.PdfReader`. Accepts anything pypdf accepts: a path, a file-like
object, or bytes. `app.py` passes `io.BytesIO(uploaded_file.read())`.

Returns `[{"page_number": 1-based int, "content": str}, ...]`.

**Edge cases**
- Pages whose `extract_text()` returns falsy are **omitted entirely** — not included with
  empty content. Scanned/image-only pages therefore vanish, leaving gaps in
  `page_number` and making `len(pages_data)` smaller than the real page count.
- No OCR. A PDF that is entirely scanned images yields `[]`, and `app.py` surfaces that
  as "Text konnte nicht extrahiert werden."
- Encrypted PDFs raise out of pypdf; `app.py` catches and shows the exception text.
- No page limit. A large filing is read fully into memory, synchronously.

## detect_report_locale

```python
detect_report_locale(pages_data) -> str   # "de" | "en"
```

*Line ~26.* Concatenates `content` from the **first five entries** of `pages_data`,
lowercases, and counts word-boundary matches of two stopword lists:

- German: `und, der, die, umsatz, jahresüberschuss, verbindlichkeiten, bericht, ergebnis`
- English: `and, the, revenue, income, debt, report, earnings, balance`

Returns `"de"` if the German count is strictly greater, else `"en"` — so ties and empty
input both fall to `"en"`.

**Edge cases**
- "First five pages" means the first five *surviving* entries, which may be pages 3, 7,
  9, 11, 12 of the actual document.
- A German report with a heavily English cover page or an English-language summary can
  misdetect. `app.py` exposes an explicit override dropdown for exactly this reason;
  when reproducing a user's result, ask which setting they had.
- The result feeds only `normalize_value_with_locale`. It does **not** switch which
  metric patterns are used — those always include both languages.

## search_keywords_in_pdf

```python
search_keywords_in_pdf(pages_data, keywords: List[str], context_window: int = 150)
    -> List[Dict[str, Any]]
```

*Line ~47.* Returns one dict per occurrence:

```python
{"page": int, "keyword": str, "matched_text": str, "context": str}
```

`keyword` is the search term as supplied; `matched_text` is the text as it appeared in
the document (preserving its casing); `context` is `±context_window` characters around
the hit, newlines flattened to spaces, wrapped in `... ` markers, with matches wrapped in
markdown `**bold**` for Streamlit.

**Edge cases**
- **Substring match, not word match.** `re.escape(kw)` with `re.IGNORECASE` and no `\b`,
  despite the inline comment claiming word boundaries. `risk` matches `brisk`, `risky`,
  `Risikofaktoren`.
- **One row per occurrence**, so a term repeated in a paragraph yields several rows with
  heavily overlapping context.
- **The highlighter over-reaches.** It runs `re.sub` for `matched_text` across the whole
  snippet, so every occurrence in the window is bolded, and each is rewritten in the
  casing of the triggering match — `RISK` can be displayed as `risk`.
- Ordering is page-major, then keyword order, then position — not document order across
  keywords.

## normalize_value_with_locale

```python
normalize_value_with_locale(val_str: str, locale: str = "en") -> float
```

*Line ~80.* Parses a financial value string to a float. Returns `0.0` on anything it
cannot parse — never raises, never returns `None`.

Steps: strip `$€£¥`; grab the first run of digits/signs/separators; treat the remainder
as a magnitude suffix; clean separators per locale; multiply.

**Magnitude suffixes** (substring tests against the trailing text, case-insensitive,
checked in this order):

| Multiplier | Matches any of |
|---|---|
| 1e9 | `billion`, `milliarden`, `mrd`, `b` |
| 1e6 | `million`, `millionen`, `mio`, `m` |
| 1e3 | `thousand`, `tausend`, `k` |

Because these are substring tests on single letters, any trailing text containing a bare
`b`, `m` or `k` triggers a multiplier. In practice the input comes from a value regex
that only admits those letters as a suffix, so this rarely misfires — but it is the first
thing to suspect if a value is 1000× or 10⁶× off with no visible unit.

**Separator handling**

| Input | `locale="en"` | `locale="de"` |
|---|---|---|
| `12,540.50` | 12540.5 | 12540.5 |
| `12.540,50` | 12540.5 (via the `,`+`.` branch) | 12540.5 |
| `12,540` | 12540.0 | **12.54** |
| `1.234` | **1.234** | 1234.0 |
| `12.540` | 12540.0 | 12540.0 |

The `12,540` and `1.234` rows are why the locale override in `app.py` matters: the same
string means different numbers, and neither reading is inferable from the string alone.

For German, a lone comma is read as a decimal separator unless there are more than two
comma-separated groups and the last has exactly three digits (i.e. `1,234,567`-style US
formatting appearing inside a German document).

**Edge cases**
- **Parentheses are not a sign.** `(1,234)` → `+1234.0`. Accounting negatives silently
  become positive. Same for a trailing minus.
- Percentages are not recognized: `12.5%` → `12.5`, indistinguishable from a currency
  value.
- The suffix is derived via `s.replace(num_match.group(0), '')`, which replaces *all*
  occurrences of that substring, so a repeated numeral can corrupt the suffix text.

## scan_for_financial_metrics

```python
scan_for_financial_metrics(pages_data) -> Dict[str, List[Dict[str, Any]]]
```

*Line ~140.* Locates labelled lines without parsing any numbers. Returns a dict keyed by
the five metric names, each mapping to `[{"page": int, "line": str}, ...]`. Keys with no
hits are present with empty lists.

Line filter: skipped unless it contains at least one digit — a cheap way to drop headings
and prose, and also the reason a label alone on one line with its figure on the next is
never picked up.

**Breaks out of the alias loop only**, so a single line may be recorded under multiple
metrics. This diverges from `extract_structured_financials`; see below.

## extract_structured_financials

```python
extract_structured_financials(pages_data, locale: str = "en") -> List[Dict[str, Any]]
```

*Line ~191.* The main extraction path — the one feeding the pivot table in `app.py`.
Returns flat rows:

```python
{
  "Metric": str,            # one of the five pattern keys
  "Year": int | None,       # None when no 20xx appeared on the line
  "Raw Value": str,         # the matched substring, e.g. "$45,200" or "2,5 Mrd"
  "Value (Mio)": float,     # round(normalized / 1e6, 2)
  "Normalized Value": float,
  "Page": int,
  "Context": str,           # the whole source line, stripped
}
```

Two regexes do the work:
- years: `\b(20[12]\d)\b` — matches 2010–2029 only. A 2009 or 2030 comparative is
  invisible.
- values: digits with `.`/`,`/space group separators, an optional leading currency
  symbol and an optional magnitude suffix.

**Pairing logic**, in order:
1. Values matching a found year string are discarded, so a year is not also read as a
   value. The comparison is exact string equality against the year list, so `2,023`
   would survive as a value.
2. Equal counts of years and values → zipped positionally.
3. Unequal but both non-empty → zipped positionally up to `min(len(years), len(values))`,
   silently dropping the excess. **This is where plausible-but-arbitrary pairs come
   from.**
4. Values but no years → one row per value with `Year=None`.

**Breaks out of the metric loop**, so each line contributes exactly one metric — the
first match in `patterns` insertion order. `Revenue / Umsatz` is declared first and
therefore always wins a tie.

## fetch_sec_filings

```python
fetch_sec_filings(ticker_symbol: str) -> List[Dict[str, Any]]
```

*Line ~282.* Calls `yfinance.Ticker(symbol).sec_filings` and flattens to
`{"date": str, "type": str, "title": str, "url": str}`. URL preference: the exhibit
matching the filing's own type, else `10-K`, else `10-Q`, else the first exhibit.
Filings with no resolvable exhibit URL are dropped.

**Edge cases**
- `except Exception: pass` around the whole body → `[]` on any failure. Network errors,
  yfinance API changes and genuinely empty filing lists are indistinguishable. This is
  the first suspect for a "no filings found" report.
- Depends on the `exhibits` dict in yfinance's return shape, which is unpinned
  (`yfinance>=0.2.38`) and has changed between versions.
- No caching; every rerun re-hits the network.

## download_and_parse_filing

```python
download_and_parse_filing(url: str) -> List[Dict[str, Any]]
```

*Line ~318.* `requests.get` with a hardcoded Chrome User-Agent, `raise_for_status()`,
then `lxml.html` `text_content()`. Strips whitespace, drops empty lines, and chunks the
result into pseudo-pages of **60 non-empty lines** with 1-based `page_number`.

Returns the same `pages_data` contract, so every downstream function works unchanged —
but `page_number` now means "60-line chunk", not a page of anything.

**Edge cases**
- **No timeout** on `requests.get`. A slow or hanging endpoint blocks the Streamlit
  worker indefinitely.
- The spoofed browser User-Agent conflicts with SEC fair-access guidance, which expects a
  declaring User-Agent with contact details. Impersonating requests are the ones most
  likely to be throttled or blocked.
- `text_content()` flattens all markup, so table structure is destroyed. Cells that were
  columns become adjacent text, which is why HTML filings pair years and values even more
  unreliably than PDFs.
- `raise_for_status()` propagates; `app.py` catches and displays the error.

## The metric patterns

Five keys, each a list of case-insensitive regex aliases covering English and German.
**Defined twice, identically** — in `scan_for_financial_metrics` (~line 146) and
`extract_structured_financials` (~line 197). Keep them in sync.

| Key | Aliases |
|---|---|
| `Revenue / Umsatz` | `(total)?\s*revenue(s)?`, `net\s*sales`, `total\s*sales`, `umsatz(erlöse)?`, `gesamtumsatz`, `erlöse` |
| `Net Income / Konzernergebnis` | `net\s*income`, `net\s*earnings`, `net\s*loss`, `jahresüberschuss`, `konzernergebnis`, `konzerngewinn`, `jahresergebnis`, `reingewinn` |
| `Operating Income / EBIT / Betriebsergebnis` | `operating\s*income`, `operating\s*profit`, `operating\s*loss`, `ebit`, `betriebsergebnis`, `operatives\s*ergebnis` |
| `Total Debt / Verbindlichkeiten` | `total\s*debt`, `long-term\s*debt`, `short-term\s*debt`, `finanzverbindlichkeiten`, `verbindlichkeiten`, `schulden`, `fremdkapital` |
| `Cash Flow` | `cash\s*provided\s*by\s*operating\s*activities`, `operating\s*cash\s*flow`, `free\s*cash\s*flow`, `cashflow\s*aus\s*der\s*betrieblichen\s*tätigkeit`, `operativer\s*cashflow`, `freier\s*cashflow` |

Notes for anyone editing these:
- The keys are **display strings** — they reach the user through the `Metric` column and
  the pivot table. Renaming a key changes the UI.
- Aliases are unanchored substrings. `verbindlichkeiten` also matches inside
  `finanzverbindlichkeiten` and `pensionsverbindlichkeiten`; `ebit` matches inside
  `ebitda`, so EBITDA lines are recorded as EBIT.
- Insertion order is significant in `extract_structured_financials` — the first matching
  key wins the line. Adding a new metric before `Revenue / Umsatz` would change existing
  classifications.
- `Cash Flow` aliases are the most specific; the generic `cashflow` alone is not an alias,
  so a bare "Cashflow 2023 1.234" line is missed.
