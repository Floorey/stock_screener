"""
test_qreport_analyzer.py - Unit tests for the Q-Report analyzer (XBRL parsing,
fiscal calendar mapping, source merging, delta computation).

Run with:  python -m unittest test_qreport_analyzer -v

Every test works off synthetic fixtures — no SEC, Yahoo or Anthropic call is made,
so the suite runs offline.
"""
import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

import qreport_analyzer as qa


def _duration_entry(start, end, val, filed="2025-01-01"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": "10-Q"}


def _instant_entry(end, val, filed="2025-01-01"):
    return {"end": end, "val": val, "filed": filed, "form": "10-Q"}


class TestFiscalLabel(unittest.TestCase):
    def test_calendar_year_company(self):
        self.assertEqual(qa.fiscal_label(date(2025, 6, 30), 12), (2025, 2, "Q2 FY2025"))
        self.assertEqual(qa.fiscal_label(date(2025, 12, 31), 12), (2025, 4, "Q4 FY2025"))

    def test_september_fiscal_year_end(self):
        """Apple-style: the December quarter is Q1 of the *next* fiscal year."""
        self.assertEqual(qa.fiscal_label(date(2025, 12, 27), 9), (2026, 1, "Q1 FY2026"))
        self.assertEqual(qa.fiscal_label(date(2026, 3, 28), 9), (2026, 2, "Q2 FY2026"))
        self.assertEqual(qa.fiscal_label(date(2026, 9, 26), 9), (2026, 4, "Q4 FY2026"))

    def test_52_53_week_spillover_into_next_month(self):
        """A period ending 2026-01-03 is the December quarter, not January."""
        self.assertEqual(qa.fiscal_label(date(2026, 1, 3), 12), (2025, 4, "Q4 FY2025"))

    def test_without_fiscal_year_end_falls_back_to_calendar(self):
        self.assertEqual(qa.fiscal_label(date(2025, 8, 15), None), (2025, 3, "Q3 2025"))


class TestQuarterlyFromDurations(unittest.TestCase):
    def test_direct_quarterly_facts(self):
        entries = [
            _duration_entry("2025-01-01", "2025-03-31", 100.0),
            _duration_entry("2025-04-01", "2025-06-30", 120.0),
        ]
        series = qa._quarterly_from_durations(entries, 12, "Revenues")
        self.assertEqual(series["Q1 FY2025"]["value"], 100.0)
        self.assertEqual(series["Q2 FY2025"]["value"], 120.0)
        self.assertFalse(series["Q1 FY2025"]["derived"])

    def test_derives_quarters_from_year_to_date_series(self):
        """Q2/Q3/Q4 come out of consecutive differences of the YTD columns."""
        entries = [
            _duration_entry("2025-01-01", "2025-03-31", 100.0),   # Q1
            _duration_entry("2025-01-01", "2025-06-30", 220.0),   # H1
            _duration_entry("2025-01-01", "2025-09-30", 360.0),   # 9M
            _duration_entry("2025-01-01", "2025-12-31", 520.0),   # FY
        ]
        series = qa._quarterly_from_durations(entries, 12, "Revenues")
        self.assertEqual(series["Q1 FY2025"]["value"], 100.0)
        self.assertEqual(series["Q2 FY2025"]["value"], 120.0)
        self.assertEqual(series["Q3 FY2025"]["value"], 140.0)
        self.assertEqual(series["Q4 FY2025"]["value"], 160.0)
        self.assertTrue(series["Q4 FY2025"]["derived"])
        self.assertFalse(series["Q1 FY2025"]["derived"])

    def test_reported_quarter_beats_derived_quarter(self):
        entries = [
            _duration_entry("2025-01-01", "2025-03-31", 100.0),
            _duration_entry("2025-01-01", "2025-06-30", 220.0),   # implies Q2 = 120
            _duration_entry("2025-04-01", "2025-06-30", 119.0),   # directly reported Q2
        ]
        series = qa._quarterly_from_durations(entries, 12, "Revenues")
        self.assertEqual(series["Q2 FY2025"]["value"], 119.0)
        self.assertFalse(series["Q2 FY2025"]["derived"])

    def test_restatement_wins_by_filing_date(self):
        entries = [
            _duration_entry("2025-01-01", "2025-03-31", 100.0, filed="2025-04-30"),
            _duration_entry("2025-01-01", "2025-03-31", 98.0, filed="2025-10-30"),
        ]
        series = qa._quarterly_from_durations(entries, 12, "Revenues")
        self.assertEqual(series["Q1 FY2025"]["value"], 98.0)

    def test_annual_only_series_yields_nothing(self):
        """A full year on its own is not a quarter and must not be reported as one."""
        entries = [_duration_entry("2025-01-01", "2025-12-31", 520.0)]
        self.assertEqual(qa._quarterly_from_durations(entries, 12, "Revenues"), {})

    def test_negative_values_survive(self):
        entries = [_duration_entry("2025-01-01", "2025-03-31", -45.0)]
        series = qa._quarterly_from_durations(entries, 12, "NetIncomeLoss")
        self.assertEqual(series["Q1 FY2025"]["value"], -45.0)


class TestInstants(unittest.TestCase):
    def test_instants_map_to_quarter_ends(self):
        entries = [_instant_entry("2025-03-31", 500.0), _instant_entry("2025-06-30", 540.0)]
        series = qa._instants_by_period(entries, 12, "CashAndCashEquivalentsAtCarryingValue")
        self.assertEqual(series["Q1 FY2025"]["value"], 500.0)
        self.assertEqual(series["Q2 FY2025"]["value"], 540.0)


class TestXbrlEndToEnd(unittest.TestCase):
    """Drive extract_kpis_from_xbrl against a synthetic companyfacts payload."""

    FACTS = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    _duration_entry("2024-01-01", "2024-03-31", 900e6),
                    _duration_entry("2025-01-01", "2025-03-31", 1000e6),
                    _duration_entry("2025-04-01", "2025-06-30", 1100e6),
                ]}},
                "NetIncomeLoss": {"units": {"USD": [
                    _duration_entry("2024-01-01", "2024-03-31", 80e6),
                    _duration_entry("2025-01-01", "2025-03-31", 100e6),
                    _duration_entry("2025-04-01", "2025-06-30", 90e6),
                ]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                    _duration_entry("2025-04-01", "2025-06-30", 200e6),
                ]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                    _duration_entry("2025-04-01", "2025-06-30", 50e6),
                ]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [
                    _duration_entry("2025-04-01", "2025-06-30", 1.25),
                ]}},
                "LongTermDebtNoncurrent": {"units": {"USD": [_instant_entry("2025-06-30", 3e9)]}},
                "LongTermDebtCurrent": {"units": {"USD": [_instant_entry("2025-06-30", 500e6)]}},
            }
        }
    }

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._cache_patch = patch.object(qa, "CACHE_FILE", self._tmp.name)
        self._cache_patch.start()

    def tearDown(self):
        self._cache_patch.stop()
        os.unlink(self._tmp.name)

    def _run(self):
        with patch.object(qa, "resolve_cik", return_value="0000000001"), \
             patch.object(qa, "fetch_company_submissions",
                          return_value={"name": "Test Corp", "fiscalYearEnd": "1231"}), \
             patch.object(qa, "fetch_company_facts", return_value=self.FACTS):
            return qa.extract_kpis_from_xbrl("TEST")

    def test_metrics_and_periods(self):
        result = self._run()
        self.assertEqual(result.company_name, "Test Corp")
        self.assertEqual(result.fiscal_year_end_month, 12)
        self.assertIn("XBRL", result.sources_used)

        values = {(f.metric, f.period_label): f.value for f in result.facts}
        self.assertEqual(values[("revenue", "Q2 FY2025")], 1100e6)
        self.assertEqual(values[("net_income", "Q1 FY2024")], 80e6)
        self.assertEqual(values[("eps_diluted", "Q2 FY2025")], 1.25)

    def test_total_debt_is_summed_from_components(self):
        values = {(f.metric, f.period_label): f.value for f in self._run().facts}
        self.assertEqual(values[("total_debt", "Q2 FY2025")], 3.5e9)

    def test_free_cash_flow_is_derived(self):
        result = self._run()
        fcf = next(f for f in result.facts if f.metric == "free_cash_flow")
        self.assertEqual(fcf.value, 150e6)
        self.assertTrue(fcf.derived)

    def test_eps_keeps_per_share_unit(self):
        result = self._run()
        eps = next(f for f in result.facts if f.metric == "eps_diluted")
        self.assertEqual(eps.unit, "USD/shares")


class TestMergeAndDeltas(unittest.TestCase):
    def _fact(self, metric, year, quarter, value, source="XBRL", derived=False):
        return qa.QuarterFact(
            metric=metric,
            period_label=f"Q{quarter} FY{year}",
            fiscal_year=year,
            fiscal_quarter=quarter,
            period_end=f"{year}-0{quarter * 3}-28",
            value=value,
            source=source,
            derived=derived,
        )

    def test_xbrl_wins_over_llm_and_yfinance(self):
        xbrl = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 100.0)])
        llm = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 101.0, "LLM")])
        yahoo = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 102.0, "yfinance")])

        merged = qa.merge_results(xbrl, llm, yahoo)
        self.assertEqual(len(merged.facts), 1)
        self.assertEqual(merged.facts[0].value, 100.0)
        self.assertEqual(merged.facts[0].source, "XBRL")

    def test_llm_fills_a_period_xbrl_does_not_cover(self):
        xbrl = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 100.0)])
        llm = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 3, 110.0, "LLM")])
        merged = qa.merge_results(xbrl, llm)
        self.assertEqual(len(merged.facts), 2)
        self.assertEqual({f.source for f in merged.facts}, {"XBRL", "LLM"})

    def test_reported_beats_derived_within_same_source(self):
        derived = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 99.0, derived=True)])
        reported = qa.ExtractionResult(ticker="T", facts=[self._fact("revenue", 2025, 2, 100.0)])
        merged = qa.merge_results(derived, reported)
        self.assertEqual(merged.facts[0].value, 100.0)
        self.assertFalse(merged.facts[0].derived)

    def test_qoq_and_yoy(self):
        facts = [
            self._fact("revenue", 2024, 2, 100.0),
            self._fact("revenue", 2025, 1, 110.0),
            self._fact("revenue", 2025, 2, 121.0),
        ]
        rows = {row["period"]: row for row in qa.compute_deltas(facts)}
        self.assertAlmostEqual(rows["Q2 FY2025"]["qoq_pct"], 10.0)
        self.assertAlmostEqual(rows["Q2 FY2025"]["yoy_pct"], 21.0)
        self.assertIsNone(rows["Q2 FY2024"]["qoq_pct"])

    def test_quarter_one_compares_against_prior_year_q4(self):
        facts = [self._fact("revenue", 2024, 4, 100.0), self._fact("revenue", 2025, 1, 90.0)]
        rows = {row["period"]: row for row in qa.compute_deltas(facts)}
        self.assertAlmostEqual(rows["Q1 FY2025"]["qoq_pct"], -10.0)

    def test_loss_to_profit_swing_has_no_percentage(self):
        """-100 -> +50 has no meaningful percent change; only the absolute is shown."""
        facts = [self._fact("net_income", 2025, 1, -100.0), self._fact("net_income", 2025, 2, 50.0)]
        rows = {row["period"]: row for row in qa.compute_deltas(facts)}
        self.assertIsNone(rows["Q2 FY2025"]["qoq_pct"])
        self.assertEqual(rows["Q2 FY2025"]["qoq_abs"], 150.0)

    def test_margins(self):
        facts = [
            self._fact("revenue", 2025, 2, 1000.0),
            self._fact("operating_income", 2025, 2, 250.0),
            self._fact("net_income", 2025, 2, 200.0),
        ]
        row = qa.compute_margins(facts)[0]
        self.assertAlmostEqual(row["Operative Marge"], 25.0)
        self.assertAlmostEqual(row["Nettomarge"], 20.0)
        self.assertIsNone(row["Bruttomarge"])


class TestFrames(unittest.TestCase):
    def test_frame_shape_and_source_marks(self):
        facts = [
            qa.QuarterFact("revenue", "Q1 FY2025", 2025, 1, "2025-03-31", 100.0),
            qa.QuarterFact("revenue", "Q2 FY2025", 2025, 2, "2025-06-30", 120.0),
            qa.QuarterFact("net_income", "Q2 FY2025", 2025, 2, "2025-06-30", 20.0,
                           source="LLM", derived=True),
        ]
        frame = qa.facts_to_frame(facts)
        self.assertEqual(list(frame.columns), ["Q1 FY2025", "Q2 FY2025"])
        self.assertEqual(list(frame.index), ["revenue", "net_income"])
        self.assertEqual(frame.loc["revenue", "Q2 FY2025"], 120.0)

        marks = qa.source_frame(facts)
        self.assertEqual(marks.loc["net_income", "Q2 FY2025"], "LLM*")
        self.assertEqual(marks.loc["revenue", "Q1 FY2025"], "XBRL")


class TestPageSelection(unittest.TestCase):
    def test_statement_pages_outrank_prose(self):
        pages = [
            {"page_number": 1, "content": "Dear shareholders, this quarter we focused on our mission and values."},
            {"page_number": 2, "content": "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS\n"
                                          "Net sales 94,036 90,753\nOperating income 28,202 25,352\n"
                                          "Net income 23,636 21,448\nEarnings per share 1.57 1.40"},
            {"page_number": 3, "content": "Risk factors: competition, supply chain, regulation."},
        ]
        selected = qa.select_financial_pages(pages, max_pages=1)
        self.assertEqual([p["page_number"] for p in selected], [2])

    def test_selection_keeps_document_order(self):
        pages = [
            {"page_number": 1, "content": "Balance sheets\nTotal assets 100 200\nCash 10 20"},
            {"page_number": 2, "content": "prose only"},
            {"page_number": 3, "content": "Statements of cash flows\nOperating income 5 6\nNet income 3 4"},
        ]
        selected = qa.select_financial_pages(pages, max_pages=2)
        self.assertEqual([p["page_number"] for p in selected], [1, 3])

    def test_empty_input(self):
        self.assertEqual(qa.select_financial_pages([]), [])


class TestLlmPayloadMapping(unittest.TestCase):
    PAYLOAD = {
        "company_name": "Muster AG",
        "currency": "EUR",
        "fiscal_year_end_month": 12,
        "notes": "Werte in Mio. EUR skaliert.",
        "quarters": [{
            "fiscal_year": 2025,
            "fiscal_quarter": 2,
            "period_end": "2025-06-30",
            "is_derived": True,
            "metrics": [
                {"key": "revenue", "value": 12540500000.0, "reported_text": "12.540,5", "page": 7},
                {"key": "net_income", "value": -450000000.0, "reported_text": "(450,0)", "page": 7},
                {"key": "not_a_metric", "value": 1.0, "reported_text": "1", "page": 7},
            ],
        }],
    }

    def test_maps_metrics_and_drops_unknown_keys(self):
        facts = qa._facts_from_llm_payload(self.PAYLOAD, 12)
        by_metric = {f.metric: f for f in facts}
        self.assertEqual(by_metric["revenue"].value, 12540500000.0)
        self.assertEqual(by_metric["net_income"].value, -450000000.0)
        self.assertNotIn("not_a_metric", by_metric)

    def test_provenance_is_preserved(self):
        facts = qa._facts_from_llm_payload(self.PAYLOAD, 12)
        revenue = next(f for f in facts if f.metric == "revenue")
        self.assertEqual(revenue.source, "LLM")
        self.assertEqual(revenue.unit, "EUR")
        self.assertTrue(revenue.derived)
        self.assertIn("Seite 7", revenue.detail)

    def test_llm_extraction_without_api_key_degrades_gracefully(self):
        with patch.dict(os.environ, {}, clear=True):
            result = qa.extract_kpis_with_llm("TEST", pages_data=[{"page_number": 1, "content": "x"}])
        self.assertEqual(result.facts, [])
        self.assertTrue(any("ANTHROPIC_API_KEY" in w for w in result.warnings))


class TestLlmRequestPath(unittest.TestCase):
    """Exercise extract_kpis_with_llm against a mocked Anthropic client."""

    RESPONSE = {
        "company_name": "Mock Inc.",
        "currency": "USD",
        "fiscal_year_end_month": 12,
        "notes": "",
        "quarters": [{
            "fiscal_year": 2025,
            "fiscal_quarter": 2,
            "period_end": "2025-06-30",
            "is_derived": False,
            "metrics": [{"key": "revenue", "value": 500e6, "reported_text": "500.0", "page": 2}],
        }],
    }

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._cache_patch = patch.object(qa, "CACHE_FILE", self._tmp.name)
        self._cache_patch.start()
        self._env_patch = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._cache_patch.stop()
        os.unlink(self._tmp.name)

    def _client(self, payload=None, stop_reason="end_turn"):
        """A stand-in for anthropic.Anthropic whose stream yields one JSON text block."""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.stop_reason = stop_reason
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps(payload if payload is not None else self.RESPONSE)
        message.content = [block]
        message.usage.input_tokens = 40_000
        message.usage.output_tokens = 2_000
        message.usage.cache_read_input_tokens = 0

        client = MagicMock()
        stream = MagicMock()
        stream.__enter__.return_value.get_final_message.return_value = message
        client.messages.stream.return_value = stream
        return client

    PAGES = [{"page_number": 2, "content": "Statements of operations\nNet sales 500.0 480.0"}]

    def test_text_extraction_produces_facts_and_usage(self):
        client = self._client()
        with patch("anthropic.Anthropic", return_value=client):
            result = qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES)

        self.assertEqual(result.company_name, "Mock Inc.")
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].value, 500e6)
        self.assertEqual(result.facts[0].source, "LLM")
        self.assertEqual(result.llm_usage.input_tokens, 40_000)
        self.assertAlmostEqual(result.llm_usage.cost_usd, 40_000 * 5e-6 + 2_000 * 25e-6)

    def test_request_uses_configured_model_and_json_schema(self):
        client = self._client()
        with patch("anthropic.Anthropic", return_value=client):
            qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES, model="claude-opus-5")

        kwargs = client.messages.stream.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5")
        self.assertEqual(kwargs["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kwargs["thinking"], {"type": "adaptive"})
        self.assertNotIn("budget_tokens", json.dumps(kwargs["thinking"]))

    def test_pdf_bytes_are_sent_as_a_document_block(self):
        client = self._client()
        with patch("anthropic.Anthropic", return_value=client):
            qa.extract_kpis_with_llm("MOCK", pdf_bytes=b"%PDF-1.7 fake")

        content = client.messages.stream.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "document")
        self.assertEqual(content[0]["source"]["media_type"], "application/pdf")

    def test_second_call_is_served_from_cache_without_billing(self):
        client = self._client()
        with patch("anthropic.Anthropic", return_value=client):
            qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES)
            second = qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES)

        self.assertEqual(client.messages.stream.call_count, 1)
        self.assertTrue(second.llm_usage.from_cache)
        self.assertEqual(second.llm_usage.cost_usd, 0.0)
        self.assertEqual(len(second.facts), 1)

    def test_refusal_is_reported_not_raised(self):
        client = self._client(stop_reason="refusal")
        with patch("anthropic.Anthropic", return_value=client):
            result = qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES)
        self.assertEqual(result.facts, [])
        self.assertTrue(result.warnings)

    def test_invalid_json_is_reported_not_raised(self):
        from unittest.mock import MagicMock

        client = self._client()
        block = MagicMock()
        block.type = "text"
        block.text = "not json"
        client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value.content = [block]

        with patch("anthropic.Anthropic", return_value=client):
            result = qa.extract_kpis_with_llm("MOCK", pages_data=self.PAGES)
        self.assertEqual(result.facts, [])
        self.assertTrue(any("JSON" in w for w in result.warnings))


class TestCostAccounting(unittest.TestCase):
    def test_opus_pricing(self):
        usage = qa.LlmUsage(model="claude-opus-5", input_tokens=1_000_000, output_tokens=100_000)
        self.assertAlmostEqual(usage.cost_usd, 5.0 + 2.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
