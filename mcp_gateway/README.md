# mcp_gateway

Exposes `mobile_api.py`'s REST endpoints as MCP tools, in Go, using Gin for the
HTTP transport layer. It has no business logic of its own — every tool is a
thin proxy: `mobile_api.py` stays the single source of truth for Alpaca,
watchlist, and screener data, and this binary only translates between the MCP
protocol and that REST API.

## Why a separate proxy instead of reimplementing everything in Go

The alternative was rewriting the Alpaca/screener/watchlist logic in Go. That
would duplicate `alpaca_trader.py`/`watchlist_manager.py`/`screener.py` in a
second language and require keeping both in sync on every change. Proxying to
the already-tested `mobile_api.py` instead keeps one implementation of the
business logic and lets this binary focus on what Go + Gin are actually good
at here: a small, dependency-light, single-binary MCP transport layer that's
trivial to hand to any MCP client.

## Build

```bash
go build -o mcp_gateway .
```

## Run

Two transports, picked with `--transport`:

```bash
# stdio - for a client that spawns this as a local subprocess (Claude Desktop, Gemini CLI, etc.)
./mcp_gateway --transport=stdio

# streamable HTTP - for a remote client, e.g. a design agent building a landing page
./mcp_gateway --transport=http --addr=:8090
```

Config is read from the environment, or from a `.env` file (`./.env` or
`../.env`, i.e. the repo root's `.env` also works — same file `mobile_api.py`
reads):

| Variable | Purpose | Default |
|---|---|---|
| `MOBILE_API_BASE_URL` | Where `mobile_api.py` is listening | `http://localhost:8000` |
| `MOBILE_API_KEY` | Forwarded as `X-API-Key` on every call to `mobile_api.py` | — (calls will 503 if unset) |
| `MCP_GATEWAY_KEY` | Shared secret required on `/mcp` in http mode. If unset, `/mcp` is unauthenticated — fine for stdio/local use, do not expose the http transport beyond localhost without setting this | — |

`mobile_api.py` must already be running (`uvicorn mobile_api:app --host 0.0.0.0 --port 8000`) before this gateway can serve any tool that touches account/positions/orders/watchlist/screener data.

## Tools

`get_health`, `get_account`, `get_positions`, `get_orders`, `place_order`,
`cancel_order`, `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist`,
`get_screener` — same shape as the `mobile_api.py` endpoints they proxy (see
the repo root `AGENTS.md` for the REST reference). Each returns the raw JSON
`mobile_api.py` returned, as MCP text content.

## Connecting a client

**stdio (Claude Desktop / Gemini CLI style config):**
```json
{
  "mcpServers": {
    "falcone-capital": {
      "command": "/absolute/path/to/mcp_gateway/mcp_gateway",
      "args": ["--transport=stdio"],
      "env": {
        "MOBILE_API_BASE_URL": "http://localhost:8000",
        "MOBILE_API_KEY": "<same key as mobile_api.py's .env>"
      }
    }
  }
}
```

**HTTP (e.g. a design agent building a landing page that wants live
portfolio/screener numbers to show as example data):** point it at
`http://<host>:8090/mcp` with header `X-API-Key: <MCP_GATEWAY_KEY>`, using the
MCP streamable-HTTP transport. A single `get_screener` or `get_account` call
gives it real numbers to design around instead of hand-typed placeholders.

## Is an MCP server the right layer here at all?

For a design agent, arguably not — an MCP server is the right layer for an
*agent* that reasons about which tool to call and when. A landing page design
tool usually just wants a fixed JSON payload to prototype against once, not a
tool-calling loop; for that, pointing it straight at the existing
`mobile_api.py` REST endpoints (already documented in `AGENTS.md`) is simpler
and needs no MCP client library at all. Where MCP genuinely earns its keep is
multi-step agentic use — Claude/Gemini/another LLM deciding on its own to
check positions, place an order, and update the watchlist as part of a larger
task. That's the case this gateway is built for.
