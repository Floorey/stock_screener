"""Run app or importer with server-side runtime configuration."""
import argparse
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("app", "import"))
    args, extra = parser.parse_known_args()
    load_dotenv(ROOT / ".runtime" / "runtime.env", override=False)
    load_dotenv(ROOT / ".env", override=False)
    os.chdir(ROOT)
    if args.service == "app":
        command = [sys.executable, "-m", "streamlit", "run", "app.py",
                   "--server.address=127.0.0.1", "--server.port=8501",
                   "--server.headless=true", "--browser.gatherUsageStats=false"]
    else:
        command = [sys.executable, "analytics_import.py", *extra]
    os.execv(sys.executable, command)
