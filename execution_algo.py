import os
import time
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

# Load Alpaca configuration
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from alpaca_trader import place_order, get_alpaca_option_quote

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
        """
        Executes a simulated or real Alpaca order using TWAP or VWAP.
        Runs synchronously in this call (suitable for background tasks or small demo intervals).
        """
        if algo_type.upper() == "TWAP":
            schedule = self.calculate_twap_schedule(qty, intervals)
        elif algo_type.upper() == "VWAP":
            schedule = self.calculate_vwap_schedule(qty, intervals)
        else:
            schedule = [qty]
            
        execution_id = f"EXE_{int(time.time())}"
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = {
            "execution_id": execution_id,
            "ticker": ticker.upper(),
            "side": side.upper(),
            "total_qty": qty,
            "algo_type": algo_type,
            "start_time": start_time,
            "status": "Running",
            "filled_qty": 0,
            "average_price": 0.0,
            "slices": []
        }
        
        self.add_log(log_entry)
        
        total_filled = 0
        total_cost = 0.0
        
        for idx, slice_qty in enumerate(schedule):
            # Fetch latest price
            price = 100.0
            try:
                tk = yf.Ticker(ticker)
                hist = tk.history(period="1d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass
                
            # Place order (Paper trading or mock if API keys not configured)
            order_id = "MOCK_ORDER"
            status = "filled"
            actual_price = price
            
            # Check if Alpaca keys are loaded
            api_key = os.getenv("ALPACA_API_KEY")
            secret_key = os.getenv("ALPACA_SECRET_KEY")
            
            if api_key and secret_key:
                # Place real limit/market order
                try:
                    # Place order slightly below/above mid to simulate execution
                    # Here we just place a market/limit order
                    order_status, order_res = place_order(
                        symbol=ticker,
                        qty=slice_qty,
                        side=side,
                        order_type="market"
                    )
                    if order_status in [200, 201] or order_res.get("status") == "success":
                        order_id = order_res.get("order", {}).get("id", "N/A")
                        # For simple demo, we assume execution at current market price
                        status = "filled"
                    else:
                        status = "failed"
                        actual_price = 0.0
                except Exception as e:
                    status = f"failed: {e}"
                    actual_price = 0.0
            else:
                # Simulated execution with a small random slippage
                slippage = np.random.normal(0, 0.0005) * price
                if side.upper() == "BUY":
                    actual_price = price + abs(slippage)
                else:
                    actual_price = price - abs(slippage)
            
            if "failed" not in status:
                total_filled += slice_qty
                total_cost += actual_price * slice_qty
                avg_price = total_cost / total_filled if total_filled > 0 else 0.0
            else:
                actual_price = 0.0
                
            slice_log = {
                "slice_index": idx + 1,
                "qty": slice_qty,
                "price": actual_price,
                "status": status,
                "order_id": order_id,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            
            # Reload logs, update the current log entry, and save
            logs = self.get_logs()
            for log in logs:
                if log["execution_id"] == execution_id:
                    log["filled_qty"] = total_filled
                    log["average_price"] = avg_price
                    log["slices"].append(slice_log)
                    if total_filled >= qty:
                        log["status"] = "Completed"
                        log["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    elif idx == len(schedule) - 1:
                        log["status"] = "Partial"
                        log["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    break
            
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=4)
                
            # If not the last slice, wait
            if idx < len(schedule) - 1:
                time.sleep(interval_seconds)
                
        # Return final log state
        logs = self.get_logs()
        for log in logs:
            if log["execution_id"] == execution_id:
                return log
        return log_entry
