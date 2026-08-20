# AGENTS.md

Cross-agent guide to this repository (Claude Code, Gemini CLI, Codex, Antigravity, or any other coding agent). If you are Claude Code specifically, also read `CLAUDE.md` — it has more implementation detail. This file is the shorter, tool-agnostic version, plus the one section every agent working with a frontend/mobile client needs: how to call `mobile_api.py`.

## What this is

A Python/Streamlit trading and research terminal ("Falcone Capital" branding in places) built around Alpaca (paper trading by default). It combines a fundamental stock screener, options/CDS analytics, PDF/SEC filing analysis, portfolio risk management, algo-trading backtests, an MCP server layer, and a REST API for mobile/frontend clients. UI strings are German (German-market-facing tool) — match that tone if you touch UI code.

## Running it

```bash
pip install -r requirements.txt          # venv already at .venv, Python 3.14

streamlit run app.py                     # main dashboard, all tabs
python screener.py                       # CLI screener test, no UI
python mcp_server.py                     # MCP server: watchlist/screener/account tools
python falcone_server.py                 # MCP server: VPEI/volume-spike scanner
uvicorn mobile_api:app --host 0.0.0.0 --port 8000   # REST API for mobile/frontend clients
```

No lint/test tooling is configured (no pytest, no linter config). Verify changes by running the relevant module directly, or `streamlit run app.py` and exercising the affected tab.

## Architecture in one paragraph

`app.py` is the Streamlit entrypoint; each dashboard tab either renders inline or delegates to `render_*_tab()` in a dedicated `*_ui.py` module. `screener.py` pulls fundamentals via `yfinance`, checks tradability via Alpaca, computes Long/Short scores, and caches results in `screener_cache.json` (keyed by ticker, each entry `{"timestamp": ..., "data": {...fields...}}`). `alpaca_trader.py` is the single source of truth for Alpaca account/positions/orders — every other module goes through it rather than calling the Alpaca REST API directly; `is_alpaca_configured()` gates all Alpaca-dependent paths. `watchlist_manager.py` is a flat JSON-file-backed ticker list. Full detail (tab→module map, algo router, report generation) is in `CLAUDE.md`.

## Mobile / frontend REST API (`mobile_api.py`)

This is the one piece of the codebase built specifically so a frontend (mobile app, web client, another agent acting on a user's behalf) can drive the terminal over plain HTTP instead of importing Python modules directly. It's a thin FastAPI wrapper — no business logic of its own — over `alpaca_trader.py`, `watchlist_manager.py`, and `screener.py`.

**Start it:**
```bash
uvicorn mobile_api:app --host 0.0.0.0 --port 8000
```

**Auth:** every route except `/health` requires an `X-API-Key` header matching the `MOBILE_API_KEY` value in `.env`. No key configured → `503`. Wrong key → `401`.

**Endpoints:**

| Method | Path | Purpose | Body |
|---|---|---|---|
| GET | `/health` | Liveness + whether Alpaca is configured. No auth. | — |
| GET | `/account` | Alpaca account (cash, buying power, equity). | — |
| GET | `/positions` | Open portfolio positions. | — |
| GET | `/orders` | Open/pending orders. | — |
| POST | `/orders` | Place an order. | `{"symbol","qty","side","order_type","limit_price","time_in_force"}` (only `symbol`/`qty`/`side` required) |
| DELETE | `/orders/{order_id}` | Cancel an order. | — |
| GET | `/watchlist` | Current watchlist tickers. | — |
| POST | `/watchlist` | Add a ticker. | `{"ticker": "AAPL"}` |
| DELETE | `/watchlist/{ticker}` | Remove a ticker. | — |
| GET | `/screener?side=long\|short&limit=N` | Top-N cached screener results by Long/Short score. | — |

**Example:**
```bash
curl -H "X-API-Key: $MOBILE_API_KEY" http://localhost:8000/positions

curl -X POST -H "X-API-Key: $MOBILE_API_KEY" -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","qty":1,"side":"buy"}' \
  http://localhost:8000/orders

curl -H "X-API-Key: $MOBILE_API_KEY" "http://localhost:8000/screener?side=long&limit=10"
```

Interactive OpenAPI docs are auto-served at `/docs` while the server is running.

`/screener` reads from `screener_cache.json` as-is — it does not trigger a fresh scan (that's `run_screener()` in `screener.py`, which is slow/network-bound and only meant to run from the Streamlit sidebar or scheduled jobs). If the cache is empty, `/screener` returns `[]`.

## Conventions to respect

- **Dependencies**: prefer native `numpy`/`pandas` over adding `scikit-learn`/`scipy`. Check `.venv` before assuming any package is available; don't add new dependencies without checking first.
- **Alpaca access**: go through `alpaca_trader.py`, never call the Alpaca REST API directly from a new module.
- **UI copy**: German. Match existing tone/terminology.
- **Local state files** (`screener_cache.json`, `watchlist.json`, `execution_logs.json`, `active_pairs.json`, `*.csv`, `*.xlsx`, `*.log`) are gitignored and regenerate on run — don't assume they exist, don't commit them.

## Where to go deeper

- `CLAUDE.md` — full architecture (tab→module map, algo router internals, report generation).
- `.claude/skills/`, `.agents/skills/`, `.gemini/skills/` — packaged skill references (high-frequency-trading, pdf-analyzer) kept in sync by `sync_agent_skills.py`.
- `PROJECT.md` / `TEST_INFRA.md` — the Polars stat-arb engine (`statarb_engine.py`) design and test plan.
