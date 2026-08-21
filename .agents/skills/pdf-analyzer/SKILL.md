---
name: pdf-analyzer
description: >-
  How the pdf_analyzer module in this repository works — the financial-report
  extraction pipeline behind the "Klassischer Scanner" mode of the Streamlit
  "Quartalsbericht-Analyzer" tab (qreport_ui.py).
  Use it whenever the work touches pdf_analyzer.py or that tab: extracting text from a
  10-K/10-Q or Geschäftsbericht, scanning for revenue / net income / EBIT / debt / cash
  flow figures, adding or changing a metric pattern, keyword search with context
  snippets, German vs US number formats and locale detection, parsing values like
  "12.540,50" or "$45,200 million", pulling SEC filings through yfinance, or the
  pages_data structure passed between these functions. Read it before editing any
  regex, pattern dict or normalization rule in that module — the extraction is
  heuristic and has documented failure modes that are easy to make worse by accident.
  It also applies when someone reports that extracted numbers look wrong, years come
  out empty, a figure is off by a factor of a million, a loss shows as positive, or a
  keyword search returns duplicate hits — those are known behaviours explained here.
---

# pdf_analyzer

## What this module is

`pdf_analyzer.py` (349 lines, repo root) turns a financial report — an uploaded PDF or
an SEC filing fetched over HTTP — into text, then applies regex heuristics to pull out
financial figures and keyword matches. Its only consumer is `qreport_ui.py`, which
imports six of its functions and drives them from the "Klassischer Scanner" mode of
the Quartalsbericht-Analyzer tab.

**It is no longer the primary path for quarterly figures.** `qreport_analyzer.py` does
that job with SEC XBRL facts and LLM extraction, and every value it produces carries a
source. Reach for `pdf_analyzer` when the structured path cannot help: keyword search
with page context, or a report that has neither XBRL nor an API key behind it. When
someone reports wrong numbers from the *classic scanner*, this skill explains why;
when they report wrong numbers from the Q-Report tab's Ticker/PDF modes, the answer is
in `qreport_analyzer.py`, not here.

The thing to hold onto: **this is a heuristic text scraper, not a financial data
parser.** It reads lines of text with regexes. It has no model of a table, a column, a
unit header, or an accounting convention. Most surprises people report are that gap
showing through, not bugs in the usual sense. Before "fixing" one, read
`references/accuracy.md` — several of these limits are structural, and a local regex
patch usually trades one failure mode for another.

## The `pages_data` contract

Every analysis function speaks the same shape, and it is the spine of the module:

```python
[{"page_number": int, "content": str}, ...]
```

Three properties matter more than they look:

1. **`page_number` is a label, not an index.** `extract_text_from_pdf` skips pages whose
   extracted text is falsy, so a scanned or image-only page simply never appears.
   `pages_data[i]["page_number"] != i + 1` in general, and `len(pages_data)` is *not*
   the document's page count. `qreport_ui.py` displays `len(pages_data)` to the user as
   "Abschnitte/Seiten" — deliberately vague wording, because it isn't reliably pages.
2. **"Page" means something different per source.** For PDFs it is a real page. For SEC
   filings, `download_and_parse_filing` chunks the HTML text into pseudo-pages of 60
   non-empty lines. Same contract, different semantics — never tell a user "page 12 of
   the filing" for an HTML-sourced report.
3. **Everything downstream is line-oriented.** The scanners split `content` on `\n` and
   evaluate one line at a time. A figure and its label must survive PDF extraction on
   the *same* line or it will not be found. This single fact explains most misses.

## The pipeline

```
  PDF upload ──> extract_text_from_pdf ──┐
                                          ├──> pages_data ──> detect_report_locale ──> "de" | "en"
  yfinance ──> fetch_sec_filings                   │                     │
       └──> download_and_parse_filing ──┘          │                     │ (locale is used
                                                    │                     │  ONLY for number
                          ┌─────────────────────────┴──────┐              │  parsing)
                          │                                │              v
              scan_for_financial_metrics      extract_structured_financials
              (labelled lines, no parsing)    (parses values, pairs years)
                                                            │
                          search_keywords_in_pdf            └──> normalize_value_with_locale
                          (context snippets)
```

`detect_report_locale` counts German vs English stopwords across the first five entries
of `pages_data` and returns `"de"` or `"en"`. Its result feeds *only*
`normalize_value_with_locale` — the metric patterns already contain both German and
English aliases and match regardless of locale. In `qreport_ui.py` the user can override the
detection with a dropdown, which is why the call site passes `effective_locale` rather
than the detected value.

## The one hazard that bites hardest

**The `patterns` dict is duplicated verbatim** in `scan_for_financial_metrics`
(line ~146) and `extract_structured_financials` (line ~197). They are currently
identical and must stay that way; the automated-scan UI relies on both agreeing.

If you add or change a metric alias, change it in **both** copies. Better, if you are
already touching this code: lift it to a module-level constant and have both functions
reference it. That is a safe, contained refactor and removes the trap permanently —
but run the characterization harness either side of it, because the two functions do
*not* treat a matched line identically (see below).

## Where the two scanners deliberately diverge

Same patterns, different loop structure, different answers — this is not a bug, but it
surprises people:

- `scan_for_financial_metrics` breaks out of the *alias* loop only, so one line can be
  recorded under **several metrics**.
- `extract_structured_financials` breaks out of the *metric* loop, so one line yields
  **exactly one metric** — the first match in `patterns` insertion order, which means
  `Revenue / Umsatz` always wins a tie.

Concretely, the line `"Revenue and operating income both improved in 2023 to 12,000"`
appears under both Revenue and Operating Income in the scan, but only as Revenue in the
structured output. If you change either loop, you change which figures reach the pivot
table in `qreport_ui.py`.

## Four ways the numbers come out wrong

All four are reproducible with the bundled harness, and all four are inherent to a
line-regex approach. Summarized here so you don't have to rediscover them; full detail
and the reasoning about what to do in `references/accuracy.md`.

| Trap | What happens |
|---|---|
| **Scale from table headers is invisible** | `(in millions)` sits in a header line, not on the data line. `Total revenue 45,200` is read as 45,200 units, reported as `0.05` Mio — off by 10⁶. Inline suffixes (`$3.2 billion`, `2,5 Mrd.`) *are* handled correctly. |
| **Column-table years don't pair** | Years live in a header row, values in data rows. With no year on the line, every value gets `Year: None` and drops out of the year-indexed pivot in `qreport_ui.py`. Prose like `"revenue for 2023 was 45,200"` pairs fine. |
| **Accounting negatives are lost** | `(1,234)` normalizes to `+1234.0`. A net loss is reported as a positive net income. Nothing in the module reads parentheses or trailing minus as a sign. |
| **Positional year/value pairing** | When counts differ, years and values are zipped by order of appearance. Plausible-looking but arbitrary pairs result. |

The practical consequence for anyone *using* the output: treat `Page` and `Context` as
the trustworthy columns and the numbers as candidates to verify against the cited line.
That is also how to phrase it to a user — the module is a fast way to locate figures in
a long document, not a source of clean financials.

## Keyword search behaviour

`search_keywords_in_pdf` does a case-insensitive **substring** match. The inline comment
says "regex for word boundaries"; it does not — `re.escape(kw)` with no `\b`. Searching
`risk` matches `brisk` and `risky`. Two further behaviours that look like bugs in the UI:

- One match is emitted **per occurrence**, so overlapping context windows produce
  near-duplicate rows for text that repeats a term.
- The highlighter re-runs a case-insensitive `sub` over the whole snippet, so *every*
  occurrence in the window gets bolded, rewritten in the casing of the one that
  triggered the match. `RISK` in the snippet can come back rendered as `risk`.

Adding `\b` around the pattern is a one-line change that would fix the `brisk` problem —
but it would also break searches for German compounds like `Umsatzerlöse` matched by
`Umsatz`, which is a plausible reason the current behaviour exists. Ask before changing
it rather than assuming it is an oversight.

## Verifying a change

The repo has no test suite, so the bundled harness is the safety net. It runs the
pipeline over fixtures covering US and German tables, inline-year prose, parenthesised
negatives, multi-metric lines and keyword overlap, and prints exactly what came back:

```bash
python .claude/skills/pdf-analyzer/scripts/characterize.py --save-baseline /tmp/before.json
# make the change
python .claude/skills/pdf-analyzer/scripts/characterize.py --baseline /tmp/before.json
```

It exits 1 on any difference and prints the before/after for each section that moved. A
difference is not automatically a regression — if the change was intended, re-save the
baseline. What matters is that nothing shifts silently, which is easy when a regex
alias quietly starts matching a new line shape.

Run it from the repository root; it needs `requirements.txt` installed (importing
`pdf_analyzer` pulls in `yfinance`, `lxml` and `requests`) but touches no network.

## Network-facing functions

`fetch_sec_filings` and `download_and_parse_filing` are the only functions that leave the
process, and both have sharp edges worth knowing before you touch them:

- `fetch_sec_filings` wraps everything in `except Exception: pass` and returns `[]`. A
  network failure, an auth problem and "this ticker has no filings" are indistinguishable
  to the caller, and `qreport_ui.py` reports all three as no filings found. If you are debugging
  a report of "no filings", that swallowed exception is the first place to look.
- It depends on the shape of `yfinance`'s `ticker.sec_filings`, including an `exhibits`
  dict — an unpinned upstream detail (`requirements.txt` says `yfinance>=0.2.38`) that
  has changed across versions.
- `download_and_parse_filing` sends a hardcoded Chrome `User-Agent` and passes no
  timeout to `requests.get`. The missing timeout can hang the Streamlit worker
  indefinitely. The spoofed UA is worth flagging to the user if filings start failing:
  SEC fair-access guidance expects a declaring User-Agent with contact details, and
  browser-impersonating requests are the ones that get rate-limited first.

Neither issue is in scope to fix unprompted, but say so if you are working nearby.

## Reference files

| File | Read it when |
|---|---|
| `references/api.md` | You need the exact signature, return shape and edge cases of a specific function |
| `references/accuracy.md` | Numbers look wrong, or you're deciding whether an extraction failure is fixable; includes reproductions and what a real fix would require |
| `scripts/characterize.py` | Before and after any change to the module |
