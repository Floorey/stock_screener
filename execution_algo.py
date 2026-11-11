import os
import time
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

from alpaca_trader import place_order

class ExecutionAlgoManager:
    def __init__(self):
        self.log_file = os.path.join(os.path.dirname(__file__), "execution_logs.json")
        self._ensure_log_file()
        
    def _ensure_log_file(self):
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump([], f)
                
    def get_logs(self) -> list:
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
            
    def add_log(self, log_entry: dict):
        logs = self.get_logs()
        logs.append(log_entry)
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4)

    def calculate_twap_schedule(self, qty: int, intervals: int) -> list[int]:
        """Splits total quantity equally across intervals."""
        if intervals <= 0:
            return [qty]
        base = qty // intervals
        remainder = qty % intervals
        schedule = [base] * intervals
        for i in range(remainder):
            schedule[i] += 1
        return [q for q in schedule if q > 0]

    def calculate_vwap_schedule(self, qty: int, intervals: int) -> list[int]:
        """
        Splits quantity based on a typical U-shaped intraday volume profile.
        High volume at market open/close, lower volume in the middle.
        """
        if intervals <= 1:
            return [qty]
            
        # Create a U-shaped probability distribution using a quadratic curve
        x = np.linspace(-1, 1, intervals)
        y = x**2 + 0.2  # U-shape with a baseline
        weights = y / np.sum(y)
        
        # Distribute quantities
        schedule = np.round(weights * qty).astype(int)
        
        # Adjust for rounding errors
        diff = qty - np.sum(schedule)
        if diff != 0:
            # Add/subtract the difference to the first/last intervals where volume is highest
            schedule[0] += diff // 2
            schedule[-1] += diff - (diff // 2)
            
        return [max(1, q) for q in schedule]

    def execute_algo_trade(self, ticker: str, side: str, qty: int, algo_type: str, intervals: int, interval_seconds: int) -> dict:
        """Automatische Ausführung ist gesperrt; manuelle Orders nur im Paper-Desk."""
        from alpaca_trader import BLOCKED_MESSAGE
        return {"status": "blocked", "message": BLOCKED_MESSAGE}
