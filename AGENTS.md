# AGENTS.md

Cross-agent guide to this repository (Claude Code, Gemini CLI, Codex, Antigravity, or any other coding agent). If you are Claude Code specifically, also read `CLAUDE.md` — it has more implementation detail. This file is the shorter, tool-agnostic version, plus the two sections every agent working with this terminal needs: how to call `mobile_api.py` over REST, and — if you're an MCP client rather than an HTTP client — how to connect to `mcp_gateway/` and use its tools instead.

## What this is

A Python/Streamlit trading and research terminal ("Falcone Capital" branding in places) built around Alpaca (paper trading by default). It combines a fundamental stock screener, options/CDS analytics, quarterly-report (10-Q) and SEC filing analysis, portfolio risk management, algo-trading backtests, an MCP server layer, and a REST API for mobile/frontend clients. UI strings are German (German-market-facing tool) — match that tone if you touch UI code.

## Running it

```bash
pip install -r requirements.txt          # venv already at .venv, Python 3.14

streamlit run app.py                     # main dashboard, all tabs
python screener.py                       # CLI screener test, no UI
python qreport_analyzer.py AAPL          # CLI quarterly-report analysis, no UI
python mcp_server.py                     # MCP server: watchlist/screener/account tools
python falcone_server.py                 # MCP server: VPEI/volume-spike scanner
uvicorn mobile_api:app --host 0.0.0.0 --port 8000   # REST API for mobile/frontend clients
```

No lint/test tooling is configured (no pytest, no linter config); the `test_*.py` files at the repo root are plain `unittest` suites (`python -m unittest test_qreport_analyzer -v`). Verify changes by running the relevant module directly, or `streamlit run app.py` and exercising the affected tab.

## Architecture in one paragraph

`app.py` is the Streamlit entrypoint; each dashboard tab either renders inline or delegates to `render_*_tab()` in a dedicated `*_ui.py` module. `screener.py` pulls fundamentals via `yfinance`, checks tradability via Alpaca, computes Long/Short scores, and caches results in `screener_cache.json` (keyed by ticker, each entry `{"timestamp": ..., "data": {...fields...}}`). `alpaca_trader.py` is the single source of truth for Alpaca account/positions/orders — every other module goes through it rather than calling the Alpaca REST API directly; `is_alpaca_configured()` gates all Alpaca-dependent paths. `watchlist_manager.py` is a flat JSON-file-backed ticker list. `qreport_analyzer.py` extracts quarterly KPIs from company reports — SEC XBRL facts, Claude-based extraction of the filing text or PDF (needs `ANTHROPIC_API_KEY`), and yfinance as fallback, merged by source precedence with the origin of every figure preserved. Full detail (tab→module map, algo router, report generation) is in `CLAUDE.md`.

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

## MCP server (`mcp_gateway/`)

**If you're an MCP client — Claude, Gemini CLI, or any other agent that calls tools rather than raw HTTP — use this instead of the REST API above.** It's the same functionality (account/positions/orders/watchlist/screener), exposed as MCP tools. `mcp_gateway/` is a thin Go+Gin proxy: it has no business logic of its own and forwards every tool call straight to `mobile_api.py`, so **`mobile_api.py` must already be running** before you connect.

**Start both:**
```bash
uvicorn mobile_api:app --host 0.0.0.0 --port 8000 &
cd mcp_gateway && go build -o mcp_gateway . && ./mcp_gateway --transport=stdio
# or for a remote/multi-client setup: ./mcp_gateway --transport=http --addr=:8090
```

**Connect as a client:**

- **stdio** (the client spawns the binary itself — Claude Desktop, Gemini CLI, and similar config-file-based clients):
  ```json
  {
    "mcpServers": {
      "falcone-capital": {
        "command": "/absolute/path/to/mcp_gateway/mcp_gateway",
        "args": ["--transport=stdio"],
        "env": {
          "MOBILE_API_BASE_URL": "http://localhost:8000",
          "MOBILE_API_KEY": "<value of MOBILE_API_KEY in .env>"
        }
      }
    }
  }
  ```
- **streamable HTTP** (a remote agent, or anything without a local-subprocess launcher): connect to `http://<host>:8090/mcp` with header `X-API-Key: <MCP_GATEWAY_KEY from .env>`. Every route but `/health` requires this header — wrong or missing key → `401`; if `MCP_GATEWAY_KEY` was never set on the server, the HTTP transport runs unauthenticated (fine for localhost-only use, not for anything exposed further).

**Tools available** (same shape as the REST endpoints they proxy — see the table above for request/response detail): `get_health`, `get_account`, `get_positions`, `get_orders`, `place_order`, `cancel_order`, `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist`, `get_screener`. Call `tools/list` after connecting to confirm the live set rather than assuming this list is exhaustive.

**Two config values gate everything**, both already set in `.env` for local use: `MOBILE_API_KEY` (the gateway's own outbound credential when it calls `mobile_api.py`) and `MCP_GATEWAY_KEY` (what an incoming MCP client must present over HTTP). The gateway reads `.env` automatically (checks `./.env` and `../.env`), same as `mobile_api.py`.

**Choosing between the REST API and the MCP server:** if you're driving this from tool-calling logic (deciding at runtime whether to check positions, place an order, update the watchlist), use MCP — that's what it's for. If you just need one fixed payload once (e.g. prototyping a UI against real numbers), the plain REST endpoints above are simpler and need no MCP client library. Full detail, including why this is a proxy rather than a Go reimplementation of the business logic, is in `mcp_gateway/README.md`.

## Conventions to respect

- **Dependencies**: prefer native `numpy`/`pandas` over adding `scikit-learn`/`scipy`. Check `.venv` before assuming any package is available; don't add new dependencies without checking first.
- **Alpaca access**: go through `alpaca_trader.py`, never call the Alpaca REST API directly from a new module.
- **UI copy**: German. Match existing tone/terminology.
- **Local state files** (`screener_cache.json`, `watchlist.json`, `execution_logs.json`, `active_pairs.json`, `*.csv`, `*.xlsx`, `*.log`) are gitignored and regenerate on run — don't assume they exist, don't commit them.

## Where to go deeper

- `CLAUDE.md` — full architecture (tab→module map, algo router internals, report generation).
- `mcp_gateway/README.md` — MCP gateway internals: why it's a proxy and not a Go reimplementation, full config table, transport details.
- `.claude/skills/`, `.agents/skills/`, `.gemini/skills/` — packaged skill references (high-frequency-trading, pdf-analyzer) kept in sync by `sync_agent_skills.py`.
- `PROJECT.md` / `TEST_INFRA.md` — the Polars stat-arb engine (`statarb_engine.py`) design and test plan.
