# Original application feature matrix

Scope: inventory of source code at the repository's original `master` snapshot (`d116decbaa7fd13889003dd3e810f5f35b37d1ad`). This documents what is present in source; a listed feature is not a claim that its data feeds, account configuration, or outputs were live-verified.

## Dashboard

Main entry point: `streamlit run app.py`. The app is a German-language Python/Streamlit dashboard; `app.py` defines these 13 tabs.

| Tab | Source / module | What the source implements | Evidence status |
|---|---|---|---|
| Bloomberg Terminal | `bloomberg_ui.py`, `algo_router_ui.py` | Command-driven terminal screens for portfolio, market/macro, maps/news, algo routing, and ticker lookup. | Source present; no interactive tab verified. |
| Screener Dashboard | `app.py`, `screener.py` | Index selection, scan size, fundamental long/short scores, market indicator banner, WSB mentions, filters, watchlist add, CSV download. | Source present; scan requires external Yahoo/Wikipedia/GitHub feeds. |
| Watchlist Manager | `app.py`, `watchlist_manager.py` | Local JSON ticker list, refresh fundamentals, remove tickers, export fundamentals CSV and plain ticker list. | Source present; reads/writes local state. |
| Options-Screener | `options_ui.py`, `options_advisor.py` | Options chain/strategy analysis and Black-Scholes calculations. | Source present; market data and account/order capabilities depend on provider access. |
| Arkham-Performance | `performance_ui.py` | Portfolio/performance views and PDF report generation. | Source present; data and resulting report not checked. |
| Einzelwert-Analyse | `app.py`, `report_generator.py` | Single-symbol detail, news/prediction-market context, analyst notes, downloadable PDF investment memo. | Source present; external finance/news feeds required. |
| Alpaca Trading | `app.py`, `alpaca_trader.py` | Account/positions/open orders, stock/ETF and options order controls, cancel/close actions. | Source present only; no credentials, account reads, or order actions used in this review. Base URL is configurable, so source alone does not prove paper-only routing. |
| Cashflow-Management | `cashflow_ui.py` | Cash-flow ledger and portfolio cash/buying-power views. | Source present; local ledger and optional account data. |
| Strategie-Desk | `app.py`, `pairs_tracker.py`, `synthetic_swap_builder.py`, `market_hedger.py`, `execution_algo.py`, `trade_strategy_runner.py`, `arbitrage_lab.py` | Pair/stat-arb, synthetic strategies, hedging and execution controls. | Source present; calculations/data not validated. Some modules submit orders. |
| Risk-Manager & Stress-Test | `app.py`, `risk_manager.py` | Portfolio VaR, fixed scenario shocks, PDF risk report. | Source present; calculations are approximate and may use fallback/mock inputs; not independently validated. |
| Algo-Trading Testlab | `algo_lab_ui.py` | Execution, pairs, hedge, volatility, spread, and portfolio research controls. | Source present; no strategy or account action exercised. |
| PDF Finanzbericht Analyzer | `app.py`, `pdf_analyzer.py` | Upload/local PDF text and metric extraction, keyword search, SEC filing lookup, CSV extraction download. | Source present; external SEC calls and parsing accuracy not verified. |
| LLM-Token-Tracker | `token_tracker_ui.py` | Token usage tracking/views and CSV export. | Source present; source data availability not checked. |

## Other interfaces

### FastAPI mobile API (`mobile_api.py`)

`uvicorn mobile_api:app --host 0.0.0.0 --port 8000` serves these routes. Every route except `/health` requires `X-API-Key` matching `MOBILE_API_KEY`; a missing configured key returns 503. The service was not launched in this review.

| Method | Path | Behavior |
|---|---|---|
| GET | `/health` | Liveness and whether Alpaca keys are configured. |
| GET | `/account` | Alpaca account snapshot. |
| GET | `/positions` | Current positions. |
| GET | `/orders` | Open orders. |
| POST | `/orders` | Submits a single-symbol order through `alpaca_trader.py`. |
| DELETE | `/orders/{order_id}` | Cancels an order. |
| GET/POST/DELETE | `/watchlist`, `/watchlist/{ticker}` | Read, add, and remove local watchlist entries. |
| GET | `/screener?side=long\|short&limit=1..200` | Sorts existing local cache; does not start a new scan. |

OpenAPI docs at `/docs` are provided by FastAPI when served. `mcp_gateway/` is a Go proxy for these API routes, and requires the FastAPI service to be running. The HTTP MCP gateway has no authentication by default unless `MCP_GATEWAY_KEY` is set; do not expose it beyond localhost without configuring that key (per its README).

`mcp_server.py` is a separate local MCP server exposing watchlist, cached screener scores, account/positions, and an order submission tool. `falcone_server.py` exposes a separate volume-spike/VPEI scanner and synthetic-swap execution tools. These are source-level interfaces; no server was started and no tool call was made.

## Data, state, and outputs

| Concern | Source behavior | Limit / dependency |
|---|---|---|
| Fundamental and index data | `screener.py` gets index constituents from Wikipedia/GitHub lists, pulls fundamentals through `yfinance`, scores and caches results. | External services, rate limits, current coverage, and returned values are not guaranteed by source inspection. Cache duration is 24 hours. |
| Macro panel | `macro_fetcher.py` gets ES/NQ/RTY futures, VIX, 10-year yield, USD index, gold and WTI with `yfinance`. | Fetch errors can be silently skipped; data source and freshness require runtime verification. |
| Other context | `macro_fetcher.py` calls Polymarket, ApeWisdom, and Yahoo Finance news. | Third-party APIs and scraping; not verified live. |
| Alpaca | `alpaca_trader.py` uses REST calls for account, positions, orders and options-related reads. `ALPACA_BASE_URL` is configurable and defaults to paper. | Credentials/environment/account, entitlement, paper/live routing, and market-data access need explicit verification. |
| Risk inputs | `risk_manager.py` can use Alpaca positions, Yahoo Finance prices/history, hardcoded beta/default assumptions, or a mock portfolio fallback. | Existing scenarios are fixed, options shock impact is delta-only, and missing history can fall back to a fixed volatility. Treat outputs as estimates, not validated live risk. |
| Local state | `watchlist.json`, `screener_cache.json`, `execution_logs.json`, `active_pairs.json`, cashflow ledger and exports are file-backed/local. | No durable shared database was found in the reviewed Python paths. State is machine/local-file scoped. |
| Exports/reports | Screener and watchlist CSV; PDF investment memo, performance report, and risk report; PDF Analyzer CSV. | Export generation is implemented in source; generated outputs were not tested. |

## Environment check

Python 3.14.10 and import availability for Streamlit, pandas, yfinance, dotenv, FastAPI, uvicorn, ReportLab, pypdf and Polars were confirmed in the current environment. An offline Streamlit `AppTest` run subsequently rendered the original script with no uncaught exceptions while `requests.Session.request` was forced to fail; this verifies the UI render path under failed network requests, not provider connectivity or live data. A separate server startup attempt on port 8765 stopped before app code ran because the environment denied opening a listening socket (`PermissionError: Operation not permitted`). Docker, PostgreSQL and `psql` executables exist, but Docker cannot connect to `/var/run/docker.sock` and PostgreSQL is not responding on its local socket. Caddy was not found on `PATH`. These checks do not establish that the services are installed/configured for use.

No orders or broker account reads were made. No live external data feeds, interactive Streamlit actions, endpoint calls, MCP calls, or PDF exports were runtime-verified. The app requires external finance/data services and Alpaca credentials for those workflows. No top-level `LICENSE` file was present in the inspected repository snapshot.
