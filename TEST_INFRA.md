# E2E Test Infra: Polars StatArb Analytics & Bloomberg UI Integration

## Test Philosophy
- **Opaque-box & Requirement-driven**: Test cases are derived strictly from user requirements in `ORIGINAL_REQUEST.md` and public API contracts in `PROJECT.md`. Tests verify external behavior, statistical calculations, edge handling, and UI routing without depending on internal implementation shortcuts.
- **Methodology**: Systematic 4-tier testing integrating Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Testing, and Realistic Real-World Financial Market Workloads.
- **Strict Verification**: Mathematical correctness, numerical stability, zero division resilience, proper Polars DataFrame outputs, metric validity, and Streamlit router integration.

---

## Feature Inventory

| # | Feature | Requirement Source | Description & Interface Contract | Tier 1 | Tier 2 | Tier 3 |
|---|---------|-------------------|-----------------------------------|:------:|:------:|:------:|
| **F1** | Dynamic Rolling VWAP Spread | R1 / `PROJECT.md §Interface` | $S_t = \text{VWAP}_A - \beta \cdot \text{VWAP}_B$; `compute_vwap_spread(df_a, df_b, rolling_window, beta)` | 5 | 5 | ✓ |
| **F2** | Volume-Weighted Z-Scores | R1 / `PROJECT.md §Interface` | Volume-weighted rolling mean & std spread normalizer; `compute_volume_weighted_zscore(spread_df, rolling_window)` | 5 | 5 | ✓ |
| **F3** | Order Flow CVD | R1 / `PROJECT.md §Interface` | Cumulative Volume Delta derived from bar price action / volume; `compute_cvd(df)` | 5 | 5 | ✓ |
| **F4** | Volume Profile Nodes | R1 / `PROJECT.md §Interface` | POC, VAH, VAL (70% value area), HVN list; `compute_volume_profile(df, price_col, volume_col, num_bins, value_area_pct)` | 5 | 5 | ✓ |
| **F5** | Vectorized Backtest Runner | R1 / `PROJECT.md §Interface` | Sharpe, Sortino, Max Drawdown %, Win Rate, Profit Factor, Trade logs, Equity curve; `run_statarb_backtest(df_a, df_b, entry_z, exit_z, stop_z, rolling_window, beta)` | 6 | 6 | ✓ |
| **F6** | Bloomberg Screen & Router | R2 / `PROJECT.md §Interface` | `[STAR] STATARB` terminal screen, routing for `STAR`, `STAT`, `STAR <T1> <T2>`, command parsing & rendering | 5 | 5 | ✓ |
| **F7** | Dependencies & System Interop | R3 / `PROJECT.md §Interface` | `polars>=1.0.0` in `requirements.txt`, clean data conversion with pandas / yfinance, import compatibility with `app.py` | 5 | 5 | ✓ |

---

## 4-Tier Test Architecture & Methodology

### Tier 1 — Feature Coverage (>=5 test cases per feature)
- **F1 (VWAP Spread)**:
  1. Identical assets ($\beta=1.0$) produce zero spread.
  2. Spread calculation with explicit $\beta \ne 1.0$.
  3. Dynamic OLS/rolling beta estimation when $\beta=\text{None}$.
  4. Rolling window accumulation over time.
  5. Multi-column schema preservation (`timestamp`, `close`, `vwap_spread`).
- **F2 (Volume-Weighted Z-Score)**:
  1. Mean-reverting synthetic series generates standard Z-scores oscillating around 0.
  2. Z-score standard deviation approximates 1.0 on Gaussian spread.
  3. Rolling window size parameter changes responsiveness.
  4. Non-equal volume weighting biases Z-score toward high-volume bars.
  5. Constant volume simplifies to standard unweighted rolling Z-score.
- **F3 (Cumulative Volume Delta - CVD)**:
  1. Uptrending bars with close > open yield positive delta and rising CVD.
  2. Downtrending bars with close < open yield negative delta and falling CVD.
  3. Flat bars (close == open) produce zero delta.
  4. Monotonically increasing accumulation test.
  5. Correct output schema with `cvd` and `delta` columns.
- **F4 (Volume Profile Nodes)**:
  1. Single price mode correctly sets POC to peak volume bin.
  2. Value Area High (VAH) and Value Area Low (VAL) span exactly 70% of total volume.
  3. HVN (High Volume Nodes) identification on bimodal distribution.
  4. Configurable `num_bins` (e.g. 20, 50, 100).
  5. Configurable `value_area_pct` (e.g. 68%, 70%, 95%).
- **F5 (Vectorized Backtest Engine)**:
  1. Profitable synthetic mean-reverting pair yields positive Sharpe and win rate > 50%.
  2. Stop-loss execution triggers when $|Z| \ge \text{stop\_z}$.
  3. Exit execution triggers when $|Z| \le \text{exit\_z}$.
  4. Correct trade log generation with entry/exit timestamps, prices, and PnL.
  5. Metric calculation correctness: Sharpe ratio, Sortino ratio, max drawdown %, profit factor.
  6. Equity curve monotonicity and compounding verification.
- **F6 (Bloomberg UI & Command Router)**:
  1. Command parser recognizes `STAR` command.
  2. Command parser recognizes `STAT` command.
  3. Command parser extracts tickers from `STAR AAPL MSFT`.
  4. Screen selection dictionary includes `[STAR] STATARB`.
  5. UI rendering function executes cleanly with mock Streamlit session state.
- **F7 (Dependencies & System Interop)**:
  1. `requirements.txt` contains `polars>=1.0.0`.
  2. Polars import succeeds without version mismatch or deprecation warnings.
  3. Interoperability: Conversion helper handles Pandas DataFrame input.
  4. Interoperability: Conversion helper handles PyArrow table / Polars DataFrame.
  5. `app.py` and `bloomberg_ui.py` import `statarb_engine` without circular dependencies.

### Tier 2 — Boundary & Corner Cases (>=5 test cases per feature)
- **F1 Boundary**: Zero volume bars, missing/null prices, single-row DataFrames, mismatched dates/lengths between df_a and df_b, negative prices/spreads.
- **F2 Boundary**: Zero variance spread (constant price) ensuring no `ZeroDivisionError` (NaN/0 handling), rolling window larger than dataset length, extreme spike outliers.
- **F3 Boundary**: Massive single-tick volume shocks, zero volume throughout, 1-bar DataFrame, alternating tick directions.
- **F4 Boundary**: All trades at exact same price (single point distribution), uniform volume across all bins, empty DataFrame, skewed distribution with all volume at minimum or maximum price.
- **F5 Boundary**: No trades triggered (Z-score never breaches entry threshold), always-in-market condition (Z-score never exits), continuous loss streak testing max drawdown calculation, zero losing trades (profit factor = inf/safe handling).
- **F6 Boundary**: Case insensitivity (`star aapl msft`, `Star`), extra whitespace (`STAR   GOOGL   AMZN  `), single ticker input (`STAR NVDA`), invalid/malformed commands (`STAR123`), unknown screen inputs.
- **F7 Boundary**: Empty requirements lines/comments parsing, large datasets (>100,000 bars) memory and execution efficiency, timezone-aware vs naive timestamp handling.

### Tier 3 — Cross-Feature Combinations (Pairwise Interaction)
1. **F1 + F2 (Spread -> Z-Score)**: Feed dynamic VWAP spread output directly into Volume-Weighted Z-Score engine to verify end-to-end signal pipeline.
2. **F2 + F5 (Z-Score -> Backtest)**: End-to-end signal generation to backtest execution pipeline with custom entry/exit/stop thresholds.
3. **F3 + F4 (CVD + Volume Profile)**: Order flow delta combined with Volume Profile POC/VAH/VAL to filter directional trade entries.
4. **F1 + F4 + F5 (Spread + Volume Profile + Backtest)**: Volume profile value area filter applied to statarb spread mean-reversion trades.
5. **F6 + F5 + F1 (Bloomberg UI -> Engine -> Spread & Backtest)**: Command router `STAR KO PEP` triggering data retrieval, spread computation, and backtest rendering.
6. **F7 + F1..F5 (Pandas/yfinance -> Polars -> All Analytics)**: Ingest raw Pandas/yfinance market data, process through full Polars StatArb pipeline, verify zero data loss and type safety.

### Tier 4 — Real-World Application Workloads
1. **Scenario 1: Tech Mega-Cap Pair Trading (MSFT vs AAPL)**: Real-world 1-year daily/hourly bars, cointegration drift, rolling beta adjustment, backtest with transaction costs.
2. **Scenario 2: Oil & Energy Sector Mean-Reversion (XOM vs CVX)**: High volume, continuous mean reversion, Volume Profile POC support/resistance confluence trading.
3. **Scenario 3: Volatile Semi-Conductors with Volume Shocks (NVDA vs AMD)**: Asymmetric earnings gaps, high CVD divergence, stop-loss trigger validation under extreme volatility.
4. **Scenario 4: Consumer Staples Low-Volatility Stability (KO vs PEP)**: Tight spread oscillations, small profit factor verification, zero drawdown anomaly checking.
5. **Scenario 5: Multi-Asset Sector Rotation Stress Test (SPY vs QQQ vs IWM)**: Tri-pair backtest suite with regime shifts, market crash scenario simulation (2020 crash / 2022 rate hike).

---

## Test Directory Layout

```
/home/lukasenderle/Dokumente/stock_screener/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Shared synthetic & market data fixtures
│   ├── test_statarb_engine.py        # F1, F2, F3: VWAP Spread, Z-Scores, CVD (Tiers 1 & 2)
│   ├── test_volume_profile.py        # F4: POC, VAH, VAL, HVN (Tiers 1 & 2)
│   ├── test_backtest_runner.py       # F5: Vectorized Backtesting & Metrics (Tiers 1 & 2)
│   ├── test_bloomberg_router.py      # F6: Terminal UI, Command Router, Theme (Tiers 1 & 2)
│   ├── test_cross_feature.py         # Tier 3: Cross-Feature Interactions (F1-F7 pairwise)
│   └── test_e2e_integration.py       # Tier 4 & F7: Real-world workloads & System integration
├── TEST_INFRA.md                     # Test infrastructure documentation (this file)
└── TEST_READY.md                     # Published test suite verification signal
```

---

## Test Execution Runner

```bash
pytest /home/lukasenderle/Dokumente/stock_screener/tests/ -v --tb=short
```
