# Why extracted numbers come out wrong

Every failure below is reproducible with
`.claude/skills/pdf-analyzer/scripts/characterize.py`, and the outputs quoted here are
that script's actual results. Read this before patching a regex in response to a bad
extraction — most of these are structural, and a local fix usually moves the failure
rather than removing it.

## Contents

- [The root cause](#the-root-cause)
- [Trap 1: table-header scale is invisible](#trap-1-table-header-scale-is-invisible)
- [Trap 2: column-table years never pair](#trap-2-column-table-years-never-pair)
- [Trap 3: accounting negatives are lost](#trap-3-accounting-negatives-are-lost)
- [Trap 4: positional year/value pairing](#trap-4-positional-yearvalue-pairing)
- [Secondary limits](#secondary-limits)
- [What actually helps](#what-actually-helps)
- [Talking to users about the output](#talking-to-users-about-the-output)

## The root cause

`pypdf.extract_text()` returns a flat string per page. Column alignment survives only as
runs of spaces, and every structural fact a financial table carries — which column is
which year, that the whole statement is denominated in millions, that parentheses mean
negative, which rows are subtotals — lives in *layout*, not in the text of the data line.

The module then evaluates **one line at a time**, in isolation. It cannot see the header
three lines up. That single design fact generates all four traps, so no combination of
regex changes eliminates them; only a layout-aware or table-aware extractor would.

## Trap 1: table-header scale is invisible

**The most consequential one**, because the output looks entirely plausible.

Fixture:

```
Consolidated Statements of Operations
(in millions, except per share data)
                                    2023      2022
Total revenue                     45,200    39,100
```

Result: `Raw Value: '45,200'` → `Value (Mio): 0.05`.

The company earned $45.2 billion. The pivot table in `qreport_ui.py` reports 0.05 million. The
scale declaration sat two lines above the data and was never read; `45,200` was taken as
45,200 units, then divided by 10⁶ for the `Value (Mio)` column.

Inline suffixes work correctly, which makes the inconsistency worse — the same document
can produce one right number and one wrong one:

| Input | `Value (Mio)` | Correct? |
|---|---|---|
| `Free cash flow of $3.2 billion` | 3200.0 | yes |
| `Operativer Cashflow 2023 2,5 Mrd.` | 2500.0 | yes |
| `Total revenue 45,200` under `(in millions)` | 0.05 | **off by 10⁶** |

So prose figures tend to be right and table figures tend to be wrong, which is the
opposite of what a reader expects.

**A real fix** would mean tracking document-level or section-level scale: scan for
`in millions` / `in thousands` / `in Mio. €` / `in TEUR` near the top of a page or
statement, carry it as page state, and apply it to bare values on that page. That is a
genuine feature with its own failure modes (multiple statements at different scales on
one page, scale changing mid-document) — worth doing deliberately, not as a drive-by
regex tweak. It would also need a new field so the UI can show whether a scale was
inferred.

## Trap 2: column-table years never pair

Same fixture. Every row comes back with `Year: None`:

```
{'metric': 'Revenue / Umsatz',  'year': None, 'raw': '45,200', 'page': 7}
{'metric': 'Revenue / Umsatz',  'year': None, 'raw': '39,100', 'page': 7}
{'metric': 'Operating Income…', 'year': None, 'raw': '9,400',  'page': 7}
```

The years are in the header row; the data lines contain no `20xx`, so branch 4 of the
pairing logic fires — one row per value, no year. `qreport_ui.py` then filters on
`extracted_df["Year"].notna()` to build the pivot table, so **these rows are dropped from
the main comparison view entirely**. The user sees "Treffer gesamt: 6" and an empty or
partial time series, which reads as a bug and is actually this.

Prose pairs correctly, because the year is on the line:

```
"Total revenue for 2023 was 45,200 compared to 39,100 in 2022."
  -> Year 2023 / 45,200  and  Year 2022 / 39,100     ✓
```

A German statement with the year inline also works:

```
"Umsatzerlöse 2023 12.540,50"  ->  Year 2023 ✓
```

**A real fix** means detecting a header row of years and mapping value *position* to
column — reconstructing the table. Substantially harder than trap 1 and probably the
point at which swapping `pypdf` for a layout-aware extractor (`pdfplumber`, `camelot`)
becomes the better answer than more regex.

## Trap 3: accounting negatives are lost

```
Net loss                          (1,234)   (2,100)
```

→ `+1234.0` and `+2100.0`, classified as `Net Income / Konzernergebnis`.

A loss is reported as a profit of the same magnitude. `normalize_value_with_locale`
strips currency symbols and then extracts `([-+]?\s*\d[\d.,\s]*)`; the opening
parenthesis is not part of the match and nothing later reconsults it. A trailing minus
(`1.234-`, common in German exports) is lost the same way.

**This is the cheapest of the four to fix**, and the one most likely to mislead, since a
sign error is invisible in a chart. But it needs a change in **two** places, and it is
worth knowing why before starting.

The obvious fix — detect a wrapping `(...)` in `normalize_value_with_locale` and negate —
is not sufficient on its own, and on the structured path it is dead code. The reason is
that `extract_structured_financials` extracts values with `value_regex`, which begins
matching at a digit and therefore **never captures the parentheses**:

```python
esf([{"page_number": 1, "content": "Net loss   (1,234)   (2,100)"}], "en")
# Raw Value: '1,234'   <- parens already gone
# Raw Value: '2,100'
```

By the time `normalize_value_with_locale` is called, the sign information has been
discarded. A working fix has to either widen `value_regex` to admit an optional wrapping
`(...)` (and keep the parens in `Raw Value`, which changes what the UI displays), or
inspect the source line around each match to decide the sign before normalizing.

Verify with the harness both ways: a normalize-only change moves
`normalize_en['(1,234)']` and *nothing else*, which is the signal that the structured
path is unaffected. A complete fix also moves `structured__us_table`.

## Trap 4: positional year/value pairing

When a line has both years and values but in unequal numbers, pairing is by order of
appearance up to `min(len(years), len(values))`, and the surplus is dropped silently.

There is no attempt to check that a pairing is sensible, and the result carries no
uncertainty marker — a mispaired row is indistinguishable in the output from a correct
one. Lines mixing a fiscal-year reference, a note number and two figures are where this
shows up.

Note also that the year regex is `\b(20[12]\d)\b`: **2010–2029 only**. A 2009 comparative
or a 2030 forecast is not seen as a year — and worse, a bare `2009` on the line is then
eligible to be captured as a *value*, since the "discard values that are years" filter
only knows about years it matched.

## Secondary limits

- **A label and its figure must be on the same line.** Both scanners skip lines with no
  digits, so a wrapped label (`Total revenue and\nother income   45,200`) is missed.
- **Substring aliases over-match.** `ebit` matches inside `ebitda`, so EBITDA rows are
  recorded as EBIT. `verbindlichkeiten` matches `pensionsverbindlichkeiten`.
- **One metric per line** in `extract_structured_financials`, first key in `patterns`
  order winning — `Revenue / Umsatz` always. `scan_for_financial_metrics` records all
  matching metrics for the same line, so the two views legitimately disagree.
- **Percentages are indistinguishable from amounts.** `Operating margin 12.5%` yields a
  value of 12.5 with no marker.
- **Per-share figures** parse as ordinary values, so EPS lands in the same column as
  revenue.
- **Scanned pages disappear** rather than erroring — `extract_text_from_pdf` drops pages
  with no extractable text, so a scanned annual report can return `[]` or, worse, a
  partial document with no indication that pages are missing.
- **HTML filings are worse than PDFs**, not better: `text_content()` flattens tables
  completely, so traps 1, 2 and 4 all intensify.

## What actually helps

Ordered by value per unit of risk:

1. **Sign handling** (trap 3) — small, contained, unambiguous improvement.
2. **Document/section scale detection** (trap 1) — high value, moderate complexity,
   needs a UI signal for "scale inferred" so users can tell.
3. **A confidence or provenance field** on each row — cheaper than fixing the pairing and
   arguably more honest: mark rows where the year came from the same line versus rows
   where it is `None` or positionally guessed, and let `qreport_ui.py` render the difference.
4. **Table-aware extraction** (trap 2) — the real fix, and a dependency change. Worth
   proposing rather than starting unprompted.

What does *not* help: adding more aliases to `patterns`. Recall is not the binding
constraint — the scanners already find the right lines. The numbers on those lines are
what's wrong.

## Talking to users about the output

The honest framing, and the one to use in `qreport_ui.py` copy or in an answer:

> This tool locates figures in a long report and tells you which page and line they came
> from. Treat the numbers as candidates to check against the quoted line, not as
> extracted financials — particularly the scale, and particularly for losses.

`Page` and `Context` are the reliable columns; `Value (Mio)` is the unreliable one.
`qreport_ui.py` already leans this way — it shows the source line for each hit — and that is a
feature worth preserving in any redesign.
