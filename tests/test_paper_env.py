import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alpaca_trader import load_paper_credentials,get_alpaca_credentials


class PaperEnvTests(unittest.TestCase):
    def test_project_keys_replace_stale_values_without_enabling_trading(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ALPACA_API_KEY':'old','ALPACA_SECRET_KEY':'old','ALPACA_TRADING_ENABLED':'false'},clear=True):
            path=Path(directory)/'.env'
            path.write_text('ALPACA_API_KEY=new-test-key\nALPACA_SECRET_KEY=new-test-secret\nALPACA_TRADING_ENABLED=true\n')
            load_paper_credentials(path)
            self.assertEqual(get_alpaca_credentials()[:2],('new-test-key','new-test-secret'))
            self.assertEqual(os.environ['ALPACA_TRADING_ENABLED'],'false')
            path.write_text('ALPACA_API_KEY=updated-test-key\nALPACA_SECRET_KEY=updated-test-secret\n')
            load_paper_credentials(path)
            self.assertEqual(get_alpaca_credentials()[:2],('updated-test-key','updated-test-secret'))
    def test_missing_file_keeps_environment_and_empty_key_clears_stale_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ALPACA_API_KEY':'old','ALPACA_SECRET_KEY':'old'},clear=True):
            path=Path(directory)/'.env'
            load_paper_credentials(path)
            self.assertEqual(os.environ['ALPACA_API_KEY'],'old')
            path.write_text('ALPACA_API_KEY=\n')
            load_paper_credentials(path)
            self.assertEqual(os.environ['ALPACA_API_KEY'],'')
            self.assertEqual(os.environ['ALPACA_SECRET_KEY'],'old')


if __name__=='__main__':unittest.main()
