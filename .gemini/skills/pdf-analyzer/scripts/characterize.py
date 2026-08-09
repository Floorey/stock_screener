#!/usr/bin/env python3
"""Characterization harness for pdf_analyzer.

The module has no test suite, and most of its behaviour is emergent from regex
and heuristics rather than stated anywhere. This script pins down what it
*actually* does on a fixed set of fixtures, so a change can be checked against
the behaviour that preceded it.

    python .claude/skills/pdf-analyzer/scripts/characterize.py
    python .claude/skills/pdf-analyzer/scripts/characterize.py --save-baseline before.json
    # ...make your change...
    python .claude/skills/pdf-analyzer/scripts/characterize.py --baseline before.json

Exit code is 1 when output differs from the baseline. A difference is not
automatically a bug -- if you intended the change, re-save the baseline. The
point is that no behaviour changes silently.

Run from the repository root. Importing pdf_analyzer pulls in yfinance, lxml and
requests, so the repo's requirements must be installed; nothing here touches the
network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from pdf_analyzer import (  # noqa: E402
    detect_report_locale,
    extract_structured_financials,
    normalize_value_with_locale,
    scan_for_financial_metrics,
    search_keywords_in_pdf,
)

# --- Fixtures -------------------------------------------------------------
# Each is a shape that shows up in real filings and exercises a different part
# of the heuristics. Page numbers are deliberately not 1..N, to keep the
# "page_number is a label, not an index" property visible.

US_TABLE = [
    {
        "page_number": 7,
        "content": (
            "Consolidated Statements of Operations\n"
            "(in millions, except per share data)\n"
            "                                    2023      2022\n"
            "Total revenue                     45,200    39,100\n"
            "Operating income                   9,400     7,250\n"
            "Net loss                          (1,234)   (2,100)\n"
        ),
    }
]

INLINE_YEARS = [
    {
        "page_number": 12,
        "content": (
            "Total revenue for 2023 was 45,200 compared to 39,100 in 2022.\n"
            "Revenue and operating income both improved in 2023 to 12,000.\n"
            "Free cash flow of $3.2 billion was generated during the year.\n"
        ),
    }
]

GERMAN_TABLE = [
    {
        "page_number": 3,
        "content": (
            "Konzern-Gewinn- und Verlustrechnung\n"
            "Umsatzerlöse 2023 12.540,50\n"
            "Jahresüberschuss 2023 1.234,00\n"
            "Finanzverbindlichkeiten 2023 8.900,25\n"
            "Operativer Cashflow 2023 2,5 Mrd.\n"
        ),
    }
]

KEYWORD_PAGE = [
    {
        "page_number": 1,
        "content": "Risk factors. RISK is risky. Brisk winds. Risiko besteht.",
    }
]

LOCALE_SAMPLES = {
    "german_report": [
        {
            "page_number": 1,
            "content": "Der Bericht und die Umsatz Entwicklung. Die Verbindlichkeiten und das Ergebnis.",
        }
    ],
    "english_report": [
        {
            "page_number": 1,
            "content": "The report and the revenue development. The debt and the earnings balance.",
        }
    ],
}

NORMALIZE_CASES_EN = [
    "$45,200 million",
    "12,540",
    "12,540.50",
    "1.5 bn",
    "(1,234)",
    "1.234",
    "45200",
    "3.2 billion",
]

NORMALIZE_CASES_DE = [
    "12.540,50",
    "12.540",
    "12,54 Mio. €",
    "1,5 Mrd.",
    "12,540",
    "1.234",
]


def observe() -> dict:
    """Run every fixture through the module and collect what came back."""
    report: dict = {}

    report["normalize_en"] = {
        case: normalize_value_with_locale(case, "en") for case in NORMALIZE_CASES_EN
    }
    report["normalize_de"] = {
        case: normalize_value_with_locale(case, "de") for case in NORMALIZE_CASES_DE
    }

    report["detect_locale"] = {
        name: detect_report_locale(pages) for name, pages in LOCALE_SAMPLES.items()
    }

    for name, pages, locale in (
        ("us_table", US_TABLE, "en"),
        ("inline_years", INLINE_YEARS, "en"),
        ("german_table", GERMAN_TABLE, "de"),
    ):
        report[f"structured__{name}"] = [
            {
                "metric": row["Metric"],
                "year": row["Year"],
                "raw": row["Raw Value"],
                "mio": row["Value (Mio)"],
                "page": row["Page"],
            }
            for row in extract_structured_financials(pages, locale=locale)
        ]
        report[f"scan__{name}"] = {
            metric: [hit["line"] for hit in hits]
            for metric, hits in scan_for_financial_metrics(pages).items()
            if hits
        }

    report["keyword_search"] = [
        {"page": m["page"], "keyword": m["keyword"], "matched": m["matched_text"], "context": m["context"]}
        for m in search_keywords_in_pdf(KEYWORD_PAGE, ["risk", "Risiko"], context_window=25)
    ]

    return report


def render(report: dict) -> str:
    lines: list[str] = []
    for section, payload in report.items():
        lines.append(f"\n=== {section} ===")
        if isinstance(payload, dict):
            for key, value in payload.items():
                lines.append(f"  {key!r} -> {value!r}")
        else:
            for item in payload:
                lines.append(f"  {item!r}")
            if not payload:
                lines.append("  (nothing returned)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-baseline", metavar="PATH", help="write current behaviour to PATH")
    parser.add_argument("--baseline", metavar="PATH", help="compare against PATH; exit 1 on any difference")
    parser.add_argument("--quiet", action="store_true", help="suppress the human-readable dump")
    args = parser.parse_args()

    report = observe()

    if not args.quiet:
        print(render(report))

    if args.save_baseline:
        Path(args.save_baseline).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nBaseline written to {args.save_baseline}")

    if args.baseline:
        previous = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        # Round-trip through JSON so tuple/list and int/float distinctions match.
        current = json.loads(json.dumps(report))
        if current == previous:
            print(f"\nNo behaviour change against {args.baseline}")
            return 0

        print(f"\nBEHAVIOUR CHANGED against {args.baseline}:")
        for section in sorted(set(previous) | set(current)):
            if previous.get(section) != current.get(section):
                print(f"  {section}")
                print(f"    before: {previous.get(section)!r}")
                print(f"    after:  {current.get(section)!r}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
