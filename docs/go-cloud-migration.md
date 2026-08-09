# Kubernetes Hardware Sizing & Go Migration Evaluation

Working notes for taking `stock_screener` to a Kubernetes cluster with a Go-based gateway for AI-agent (MCP) access. Written on branch `claude1` so the analysis and decision travel with the repo across machines.

Polished, designed versions of both reports (published as Artifacts):
- Hardware sizing (Python-only baseline): https://claude.ai/code/artifact/a1bd658f-3c3a-408b-91c6-fbefdbee8b37
- Go middleware vs. full rewrite: https://claude.ai/code/artifact/8830ad4b-3624-4759-86f5-468dbe2a02f2

**Decision: Option A (Go gateway, Streamlit stays) — approved.**

---

## 1. Baseline: current Python-only hardware footprint

Four distinct workloads live in this one repo, not one:

| Component | CPU req/limit | Mem req/limit | Replicas | Notes |
|---|---|---|---|---|
| `streamlit-ui` (`app.py`, 13 tabs) | 500m / 2000m | 512Mi / 1.5Gi | 1 | I/O-bound scanning; CPU bursts from PDF/matplotlib reports and options/VaR math |
| Background scanner (`falcone_server.py --scanner`) | 100m / 500m | 128Mi / 256Mi | 1 | Ticks a 60-symbol universe every 5 min, sleeps otherwise |
| MCP servers (`mcp_server.py`, `falcone_server.py`) | 100m / 500m each | 128Mi / 256Mi each | n/a | Default to **stdio transport** — not cluster-addressable without a Streamable HTTP/SSE wrapper |
| One-off CLI scripts | 250m / 1000m | 256Mi / 512Mi | ephemeral | Better modeled as Kubernetes `Job`s |

**Baseline totals:** ~0.6 vCPU / 640Mi request, ~2.5 vCPU / 1.75Gi limit.

**Storage:** all state is flat JSON (`screener_cache.json`, `watchlist.json`, `execution_logs.json`, `active_pairs.json`) with no file locking — safe with one writer, will race with more than one.

**Statefulness ceiling:** Streamlit's `session_state` lives in server-process memory, so the web terminal is capped at 1 replica (or needs `sessionAffinity: ClientIP`) until state is externalized.

**Security note:** `mcp_config.json` carries live Alpaca paper-trading keys in plaintext and is not gitignored (unlike `.env`) — already committed to `origin/master` history. Rotate before any further container/CI work touches this repo.

**Container image:** ~500–650MB (glibc-based slim base recommended — `cryptography`/`curl_cffi` need prebuilt wheels, avoid Alpine/musl). Dev `.venv` runs Python 3.14.6; pin the image to 3.12 unless prebuilt wheels for 3.14 are confirmed.

Full detail, including per-source egress requirements (Yahoo Finance, Alpaca, Wikipedia, GitHub, SEC EDGAR, Polymarket, Reddit) and cluster sizing (dev: 1×2vCPU/4GB node; small prod: 3×2vCPU/4GB nodes), is in the published artifact linked above.

---

## 2. Key discovery: a Go backend was already attempted

Branch `origin/claude/trading-dashboard-go-websocket-a99a18` (PRs #1–#14) contains **`command_center`** — a real, tested Go backend (stdlib `net/http` + `gorilla/websocket`, not Gin) implementing the data-connection piece: a buffered polling/ring-buffer layer with an Alpaca REST + websocket provider. MVP steps 1–3 of a planned 6 are done.

| Package | Impl | Tests |
|---|---:|---:|
| `internal/buffer` (ring, series, registry) | 403 | 244 |
| `internal/config` | 269 | – |
| `internal/httpapi` | 261 | 280 |
| `internal/poller` | 226 | – |
| `internal/provider` + mock | 268 | – |
| `internal/provider/alpaca` (REST + websocket) | 687 | 978 |
| `internal/streamer` | 212 | 434 |
| `cmd/server/main.go` | 276 | – |
| **Total** | **~2,600** | **~1,940** |

It went through merge → revert → re-apply → revert (PRs #7–#14) with no stated technical reason, then was removed entirely by a later `WIP-Backup … Rollback auf 22.07` reset. **It's absent from current `master`/`claude1` but fully recoverable:**

```bash
git checkout origin/claude/trading-dashboard-go-websocket-a99a18 -- command_center
```

This is the calibration point used for the Go-effort estimates below, and the basis of Option A's data layer.

---

## 3. Option A (approved) — Go gateway, Streamlit stays

**3 pods:**

1. **`streamlit-ui`** (Python, unchanged) — same sizing as §1. 1 replica.
2. **`go-gateway`** (Go) — recovered `command_center`, extended with:
   - MCP tool surface: ports the 8 `@mcp.tool()` functions currently split across `mcp_server.py` and `falcone_server.py`
   - Scanner poller: subsumes `falcone_server.py --scanner` (`command_center`'s poller/buffer was built for exactly this)
   - Fundamentals/index-data client: **no Go `yfinance` equivalent exists** — this hits Yahoo's endpoints directly and is the single biggest unknown in the estimate
3. **`state-store`** (Postgres or Redis, stock image, no custom code) — replaces the flat JSON files, now load-bearing since a second writer (the Go gateway) exists.

Keep `net/http`, not Gin — `command_center` is already stdlib-routed and working; a router swap is ~150–200 lines of pure churn with no functional gain.

### New Go code required

| Component | Impl | Tests | Total |
|---|---:|---:|---:|
| MCP tool surface (8 tools) | 600 | 450 | 1,050 |
| Fundamentals/index data client | 800 | 500 | 1,300 |
| API wiring, health/readiness probes, secrets | 250 | 100 | 350 |
| State-store client (Go side) | 400 | 200 | 600 |
| State-store adapter (Python side) | 130 | – | 130 |
| **New code subtotal** | **2,180** | **1,250** | **3,430** |

### Effort estimate (build/migration tokens, not runtime AI-agent cost)

Methodology: LOC × explicit tokens-per-line band (60 / 120 / 220 for fresh generation with test-fix iteration; 15 / 25 / 40 for recovery/review of existing code) — presented as low–mid–high, not a false-precise single number.

| | Low | Mid | High |
|---|---:|---:|---:|
| New code (3,430 LOC) | 206K | 412K | 755K |
| Recovery/review of `command_center` (2,600 LOC) | 39K | 65K | 104K |
| **Option A total** | **245K** | **~480K** | **860K** |

### Hardware delta (added to §1 baseline)

| | Request | Limit |
|---|---|---|
| `go-gateway` + `state-store` | +250m CPU / +320Mi mem | +500m CPU / +770Mi mem |
| Images | +15–25MB (Go, distroless) + ~200MB (stock Postgres/Redis) | |

---

## 4. Option B — full rewrite (not chosen)

Kept for reference; revisit only incrementally, never as one big-bang rewrite, starting with the I/O/integration bucket where `command_center` already proves the pattern.

Repo total: **14,472 Python lines** across 30 application files (corrected — an earlier `wc -l app.py *.py` in this session double-counted `app.py` via glob overlap and misquoted 17,120).

| Bucket | Python | × | Go total |
|---|---:|---:|---:|
| Thin utilities | 901 | 1.3 | 1,757 |
| Pure calc (options/arbitrage) | 582 | 1.4 | 1,304 |
| Calc + PDF reports | 1,337 | 1.6 | 3,209 |
| I/O / streaming integrations | 2,229 | 2.2 | 8,582 |
| MCP tool wrapper | 137 | 1.5 | 309 |
| PDF/SEC analyzer | 348 | 1.8 | 939 |
| Screener (scrape+fetch+score) | 543 | 1.8 | 1,563 |
| **Backend subtotal** | **6,077** | | **17,663** |
| Gin API glue (UI logic already counted above) | 8,395 † | 0.5 | 6,300 |
| Frontend rebuild (React/HTMX+CSS) | 8,395 † | — | 8,000–16,000 |

† `app.py` + 6 `*_ui.py` files feed both rows — once as thin API glue, once as what a new frontend has to replace. This bucket has **zero Go prior art** in the repo and is the largest source of uncertainty.

**Total: ~2.0M low / ~5.0M mid / ~10.5M high tokens** — roughly 10× Option A, and near steady-state hardware is only reached after a shadow/parity-testing period where both stacks run in parallel (higher near-term footprint, not lower).

---

## 5. Next steps (Option A)

1. Recover `command_center`: `git checkout origin/claude/trading-dashboard-go-websocket-a99a18 -- command_center`, re-run its existing test suite to confirm it still passes.
2. Stand it up against the paper account (`configs/config.alpaca.json`, same `ALPACA_*` env vars the Python side already uses); confirm balance polling + orderbook streaming both work end to end.
3. Add the MCP tool surface — start with the 5 tools in `mcp_server.py` (no streaming) before the 3 in `falcone_server.py` (needs the scanner poller wired in).
