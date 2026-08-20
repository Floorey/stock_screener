# Project: Polars StatArb Analytics & Bloomberg UI Integration

## Architecture
- `statarb_engine.py`: Core analytics and backtesting engine implemented in Polars.
  - Dynamic rolling VWAP spread computation: $S_t = \text{VWAP}_A - \beta \cdot \text{VWAP}_B$
  - Volume-Weighted Z-scores, Order Flow Cumulative Volume Delta (CVD)
  - Volume Profile nodes: Point of Control (POC), Value Area High (VAH), Value Area Low (VAL), High Volume Nodes (HVN)
  - Vectorized backtest runner: Sharpe ratio, Sortino ratio, max drawdown %, win rate, profit factor, trade logs
- `bloomberg_ui.py`: Terminal UI screen & command router integration.
  - New screen `[STAR] STATARB`
  - Command routing for `STAR`, `STAT`, `STAR <TICKER1> <TICKER2>`
  - Bloomberg-styled dark theme interactive UI (summary cards, dual-axis charts, Volume Profile histograms, trade log table)
- `requirements.txt`: Include `polars>=1.0.0`.
- `tests/`: Comprehensive unit, integration, and E2E test suite.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | StatArb Polars Core Engine & Requirements | `statarb_engine.py`, `requirements.txt` | none | IN_PROGRESS |
| M2 | Bloomberg UI & Command Router Integration | `bloomberg_ui.py`, `app.py` integration | M1 | PLANNED |
| M3 | Final Verification & Coverage Hardening | 100% test suite pass + adversarial coverage | M1, M2 | PLANNED |

## Interface Contracts
### `statarb_engine.py` ↔ `bloomberg_ui.py` / Callers
- `compute_vwap_spread(df_a, df_b, rolling_window=20, beta=None) -> pl.DataFrame`
- `compute_volume_weighted_zscore(spread_df, rolling_window=20) -> pl.DataFrame`
- `compute_cvd(df) -> pl.DataFrame`
- `compute_volume_profile(df, price_col='close', volume_col='volume', num_bins=50, value_area_pct=0.70) -> dict` (returns `{ 'poc': float, 'vah': float, 'val': float, 'profile': pl.DataFrame, 'hvn': list[float] }`)
- `run_statarb_backtest(df_a, df_b, entry_z=2.0, exit_z=0.5, stop_z=3.5, rolling_window=20, beta=None) -> dict` (returns metrics: `sharpe_ratio`, `sortino_ratio`, `max_drawdown_pct`, `win_rate`, `profit_factor`, `trades`: `pl.DataFrame` or `list[dict]`, `equity_curve`: `pl.DataFrame`)
- Ticker data ingestion helper supporting yfinance DataFrame / Polars DataFrame conversions cleanly.

## Code Layout
- Root directory: `/home/lukasenderle/Dokumente/stock_screener/`
- Core Engine: `/home/lukasenderle/Dokumente/stock_screener/statarb_engine.py`
- Bloomberg UI: `/home/lukasenderle/Dokumente/stock_screener/bloomberg_ui.py`
- App Integration: `/home/lukasenderle/Dokumente/stock_screener/app.py`
- Requirements: `/home/lukasenderle/Dokumente/stock_screener/requirements.txt`
- Tests: `/home/lukasenderle/Dokumente/stock_screener/tests/` (and root test scripts)
- Agent metadata: `/home/lukasenderle/Dokumente/stock_screener/.agents/`
