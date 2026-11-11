"""Fixed-data checks for original screener/watchlist/export behavior."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from pypdf import PdfReader
import screener
import watchlist_manager as watchlist
from report_generator import generate_pdf_report


class OriginalFeatureContracts(unittest.TestCase):
    def test_original_scores_and_csv_excel_exports(self):
        data = pd.DataFrame([
            dict(Symbol="QUALITY", PE=15, PB=2, DebtToEquity=.5, CurrentRatio=2,
                 FCF=100, ROE=.2, RevenueGrowth=.1, EVToRevenue=5,
                 NetMargin=.2, ShortInterestPercent=.01),
            dict(Symbol="STRESSED", PE=-1, PB=8, DebtToEquity=4, CurrentRatio=.5,
                 FCF=-100, ROE=-.2, RevenueGrowth=-.1, EVToRevenue=15,
                 NetMargin=-.2, ShortInterestPercent=.01),
        ])
        result = screener.calculate_scores(data)
        self.assertEqual(result.LongScore.tolist(), [7, 0])
        self.assertEqual(result.ShortScore.tolist(), [0, 6.5])
        self.assertNotIn("LongScore", data)
        csv = pd.read_csv(io.StringIO(result.to_csv(index=False)))
        pd.testing.assert_frame_equal(csv, result, check_dtype=False)
        buffer = io.BytesIO()
        result.to_excel(buffer, index=False)
        buffer.seek(0)
        pd.testing.assert_frame_equal(pd.read_excel(buffer), result, check_dtype=False)

    def test_watchlist_legacy_format_and_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "watchlist.json"
            file.write_text(json.dumps([{"symbol": "SPY"}, {"symbol": "QQQ"}]))
            with patch.object(watchlist, "WATCHLIST_FILE", str(file)):
                self.assertEqual(watchlist.load_watchlist(), ["SPY", "QQQ"])
                self.assertFalse(watchlist.add_to_watchlist("spy"))
                self.assertTrue(watchlist.add_to_watchlist(" iwm "))
                self.assertTrue(watchlist.remove_from_watchlist("qqq"))
                self.assertEqual(watchlist.load_watchlist(), ["IWM", "SPY"])

    def test_pdf_export_contains_original_report_content(self):
        pdf = generate_pdf_report("SPY", "Fixture Company", {}, 7, 0, [], [],
                                  "Fixed research note", "Test Analyst", "Halten")
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))
        pdf.seek(0)
        text = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
        self.assertIn("SPY", text)
        self.assertIn("Fixture Company", text)
        self.assertIn("Fixed research note", text)


if __name__ == "__main__":
    unittest.main()
