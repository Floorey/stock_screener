# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python/Streamlit trading and research terminal ("Falcone Capital" branding in places) built around Alpaca (paper trading by default). It combines a fundamental stock screener, options/CDS analytics, PDF/SEC filing analysis, portfolio risk management, algo-trading backtests, and an MCP server layer so Claude/other agents can query the screener and place trades. German-language UI strings throughout (this is a German-market-facing tool).

## Commands

```bash
# Install deps (venv already present at .venv, Python 3.14)
pip install -r requirements.txt

# Run the main Streamlit dashboard (all tabs)
streamlit run app.py

# Quick CLI test of the fundamental screener (no UI)
python screener.py

# Run the Falcone MCP server (VPEI/volume-spike scanner + synthetic swap execution)
python falcone_server.py                       # stdio MCP server
python falcone_server.py --scanner --interval 5  # standalone background scan loop, no MCP

# Run the simpler MCP server (watchlist/screener/account tools for agents)
python mcp_server.py

# Run the mobile REST API (watchlist/screener/account/orders over HTTP, API-key gated)
uvicorn mobile_api:app --host 0.0.0.0 --port 8000

# One-off index shortlist scripts
python short_sp500.py
python short_nasdaq.py
python short_russell.py
```

There is no lint/test tooling configured (no pytest, no linter config) — verify changes by running the relevant script/module directly or launching `streamlit run app.py` and exercising the affected tab.

## Environment

Credentials live in `.env` (gitignored): `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` (defaults to paper trading). If unset, the app assumes everything is tradable/shortable and Alpaca-dependent features degrade gracefully rather than failing. `mcp_config.json` wires an `alpaca-mcp-server` MCP server with its own copy of these keys — treat this file as sensitive, it is not gitignored. `MOBILE_API_KEY` (also in `.env`) is the shared secret `mobile_api.py` checks against the `X-API-Key` header; every route but `/health` returns 503 until it's set.

Local state/cache files are gitignored and regenerate on run: `screener_cache.json`, `watchlist.json`, `execution_logs.json`, `active_pairs.json`, `*.csv`, `*.xlsx`, `*.log`.

## Architecture

**`app.py`** is the Streamlit entrypoint and is intentionally monolithic (~2600 lines): it owns the sidebar (index selection, scan trigger, Alpaca connection widget, macro banner) and lays out `st.tabs(...)` where each tab either renders inline or delegates to a `render_*_tab()` function imported from a dedicated `*_ui.py` module. When adding a new dashboard section, follow this pattern: put the render logic in its own `<name>_ui.py` module exposing `render_<name>_tab()`, then wire it into the `st.tabs([...])` list and `with tab_x:` block in `app.py` — don't grow `app.py`'s inline sections further.

Tab → module map (see the `st.tabs([...])` call in `app.py`):
- Bloomberg Terminal → `bloomberg_ui.py` (command-driven screens: PORT/WEIS/MACR/MAPS/NEWS/ALGO/ROUT/HELP/ticker; the `ROUT` screen delegates to `algo_router_ui.py`)
- Screener Dashboard → inline in `app.py`, backed by `screener.py`
- Watchlist Manager → `watchlist_manager.py` (JSON-file backed)
- Options-Screener → `options_ui.py` (logic in `options_advisor.py`)
- Arkham-Performance → `performance_ui.py`
- Einzelwert-Analyse (single ticker) → inline in `app.py`
- Alpaca Trading → inline in `app.py`, backed by `alpaca_trader.py`
- Cashflow-Management → `cashflow_ui.py`
- Strategie-Desk → inline in `app.py`, uses `pairs_tracker.py`, `synthetic_swap_builder.py`, `market_hedger.py`, `execution_algo.py`, `trade_strategy_runner.py`, `arbitrage_lab.py`
- Risk-Manager & Stress-Test → inline in `app.py`, backed by `risk_manager.py` (VaR, stress tests, PDF report via `reportlab`)
- Algo-Trading Testlab → `algo_lab_ui.py`
- PDF Finanzbericht Analyzer → inline in `app.py`, backed by `pdf_analyzer.py` (local PDF parsing + SEC EDGAR filing fetch)
- LLM-Token-Tracker → `token_tracker_ui.py`

**Core data flow**: `screener.py` fetches index constituents (S&P 500/Dow/Nasdaq 100 via Wikipedia scraping, Russell 2000 via a GitHub list), pulls fundamentals per ticker via `yfinance`, cross-checks tradability/shortability via the Alpaca Assets API, and computes Long/Short scores (`calculate_scores`) documented in `README.md`. Results are cached in `screener_cache.json`.

**Alpaca integration** (`alpaca_trader.py`) is the single source of truth for account/positions/orders — other modules (risk_manager, options_ui, cashflow_ui, performance_ui, pairs_tracker, market_hedger, execution_algo, trade_strategy_runner) import from it rather than calling the Alpaca REST API directly. `is_alpaca_configured()` gates all Alpaca-dependent code paths.

**MCP servers** (two, independent, both `FastMCP`-based, both load `alpaca_trader.py`/local modules):
- `mcp_server.py` — general-purpose tools for agents: watchlist, screener scores, Alpaca account/positions, trade execution.
- `falcone_server.py` — a volume-spike/VPEI scanner over a hardcoded Nasdaq/Russell ticker universe plus synthetic-swap signal execution (`synthetic_swap_builder.py`); also runnable standalone as a polling loop via `--scanner --interval N` (writes to `falcone_engine.log`) instead of serving MCP.

**`mobile_api.py`** — a `FastAPI` REST wrapper for mobile clients, no business logic of its own: it calls straight into `alpaca_trader.py` (account/positions/orders), `watchlist_manager.py`, and `screener.py` (`load_cache()` + `calculate_scores()` for `/screener`) and serializes the result. Every route except `/health` requires the `X-API-Key` header to match `MOBILE_API_KEY` from `.env`.

**Algo routing / gating** (`algo_router.py`, rendered by `algo_router_ui.py` as the Bloomberg `ROUT` screen): the analytical check that decides *which* algorithm may run. `route()` builds a regime snapshot (session phase, VIX, realized vol, Kaufman efficiency ratio, breadth, rates) plus portfolio context, then scores each candidate (Falcone VPEI, stat-arb pairs, premarket volume-rate, TWAP/VWAP execution, market hedge) against hard gates → GO/CONDITIONAL/BLOCKED. `preflight_signals()` validates concrete Falcone signals (bar freshness, liquidity, RR, position-size cap incl. the contract-rounding interaction, cooldown, existing exposure) before execution. The router never places orders — extend the gate/score functions here rather than adding trigger conditions inside the individual algo modules. `falcone_server.scan_signals()` is the structured feed it consumes; `scan_markets()` is the text-formatting MCP wrapper around it.

**Report generation**: `report_generator.py` (per-ticker PDF) and `generate_macro_reports.py` (macro/synthetic-trade PDFs) both use `reportlab`; `risk_manager.py` generates its own stress-test PDF report. Output lands in `reports/`.

**Standalone/offline utilities** not wired into the Streamlit app: `analyze_datasets.py` (native numpy/pandas PCA & K-Means, no sklearn — see below), `data_cleaning.py`, `track_record_generator.py`.

## Conventions

- **Dependency policy**: prefer native `numpy`/`pandas` implementations (e.g. SVD for PCA, Euclidean K-Means) over adding packages like `scikit-learn`/`scipy` when not already installed — check `.venv` before assuming a package is available, and don't add new dependencies without checking first.
- Windows console encoding: several entrypoints (`screener.py`, `alpaca_trader.py`, `mcp_server.py`, `falcone_server.py`, `synthetic_swap_builder.py`) reconfigure `sys.stdout`/`sys.stderr` to UTF-8 at import time to avoid crashes on Windows consoles — keep this guard (`if hasattr(sys.stdout, "reconfigure")`) when editing those files' headers.
- UI copy is German; match the existing tone/terminology when adding to a tab.
