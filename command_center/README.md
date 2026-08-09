# Command Center (Go Backend)

Trading dashboard backend. Go service that buffers broker data in memory and
serves it to a browser frontend. The browser never talks to a broker API
directly — that is the whole point of the buffer layer: one poller per data
source, one configurable interval, no rate-limit surprises no matter how many
tabs are open.

## Status

MVP steps 1–3 are done:

- [x] 1. HTTP server skeleton (`net/http`, Go 1.22 routing, graceful shutdown)
- [x] 2. Buffered polling system (ring buffer, per-endpoint interval, backoff)
- [x] 3. Both core endpoints: balance (REST poll) + orderbook (Alpaca websocket
      stream, with a REST fallback)
- [ ] 4. Websocket push of new samples to connected clients
- [ ] 5. Embedded terminal (websocket + `creack/pty`, bash-first / WSL2)
- [ ] 6. Frontend: HTML/JS + uPlot charts

The buffer already exposes a `Subscribe` fan-out, so step 4 plugs in without
touching the data layer.

Alongside that roadmap, a Prometheus endpoint plus a provisioned Grafana stack
is in place — see [Metrics and Grafana](#metrics-and-grafana). It is not the
step-6 frontend; it is the operational view of the same buffer, and it works
today without waiting for the UI.

## Layout

```
command_center/
├── cmd/server/main.go            # wiring, config, signals, graceful shutdown
├── configs/
│   ├── config.example.json       # mock provider, everything polled
│   ├── config.stream.json        # mock provider, orderbook streamed
│   └── config.alpaca.json        # Alpaca: balance polled, orderbook streamed
├── deploy/                       # Prometheus + Grafana, pre-provisioned
│   ├── docker-compose.yml
│   ├── prometheus/               # scrape config + alert rules
│   └── grafana/                  # datasource, dashboard provider, dashboards
└── internal/
    ├── buffer/                   # ring buffer + series + registry  ← core
    │   ├── ring.go               # fixed-capacity ring, Latest/Last/Since
    │   ├── series.go             # ring + health status + subscriber fan-out
    │   └── store.go              # name → series registry
    ├── config/                   # JSON config + env overrides + validation
    ├── httpapi/                  # REST handlers, request log, panic recovery
    ├── metrics/                  # Prometheus exposition, hand-rolled
    ├── poller/                   # scheduled fetch loop, timeout, backoff
    ├── streamer/                 # push sources: reconnect, backoff, supervision
    └── provider/                 # broker interfaces + payload types
        ├── alpaca/               # REST balance + market data websocket
        └── mock/                 # synthetic source, no credentials needed
```

Only dependency: `github.com/gorilla/websocket` (used as a client here, as the
server side in step 4, and for the pty terminal in step 5). The Prometheus
exposition format is written by hand in `internal/metrics` rather than pulling
in a client library — it is a few hundred lines of printing floats with labels,
and it keeps the dependency list where it is.

## Run

```bash
go run ./cmd/server -config configs/config.example.json
```

Defaults (mock provider, `127.0.0.1:8080`) apply without a config file. Env
overrides: `CC_ADDR`, `CC_PROVIDER`, `CC_LOG_LEVEL`, `CC_METRICS_ENABLED`,
`CC_METRICS_PATH`, plus `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`, `ALPACA_DATA_URL`, `ALPACA_STREAM_URL`
and `ALPACA_FEED` — credentials are env-only and are never read from the config
file, matching the Python side of the repo.

Against the live paper account:

```bash
go run ./cmd/server -config configs/config.alpaca.json
```

## Data sources

**Balance** — `GET /v2/account` on the trading API, polled. Low frequency by
nature: at the default 15s interval it uses 4 of Alpaca's 200 requests per
minute. `pnl_day` is derived as `equity - last_equity`; Alpaca has no day-PnL
field.

**Orderbook** — the market data websocket, so the high-frequency side costs no
REST budget at all. Equities subscribe to the `quotes` channel (top of book;
Alpaca does not publish equity depth), crypto pairs like `BTC/USD` subscribe to
`orderbooks` and get real depth. Alpaca permits one market data connection per
account, so it is deliberately one connection for all symbols of a series.

A REST orderbook path exists as a fallback for setups without streaming
(`"mode": "poll"`), but it burns one request per poll — prefer the stream.

Feed selection: `iex` is the free feed, `sip` requires a paid subscription.
Note that equity quote sizes are reported in round lots (1 = 100 shares) and are
passed through unchanged.

## REST API

| Method | Path                          | Purpose                                     |
| ------ | ----------------------------- | ------------------------------------------- |
| GET    | `/api/health`                 | uptime + list of stale/failing series       |
| GET    | `/api/series`                 | status of every series                      |
| GET    | `/api/series/{name}/latest`   | newest buffered sample                      |
| GET    | `/api/series/{name}/history`  | `?n=100` last N, or `?since=42` gap by seq  |
| POST   | `/api/series/{name}/refresh`  | control command: force one out-of-band poll |
| GET    | `/metrics`                    | Prometheus exposition (path configurable)   |

`refresh` on a streamed series returns 409 — a push source updates itself.

Every sample carries a monotonic `seq`. A reconnecting websocket client will
send its last seen `seq` and get exactly the gap back via `Since` — as far as
the ring still reaches.

## Metrics and Grafana

`/metrics` serves the Prometheus text format, rendered from the same ring
buffers the REST API reads. **A scrape never reaches a broker API**, so the
interval is free to match the fastest series rather than a rate-limit budget.

```bash
docker compose -f deploy/docker-compose.yml up -d   # Prometheus + Grafana
```

Two dashboards are provisioned into a **Command Center** folder — *Trading*
(equity, day PnL, top of book, spread) and *Pipeline Health* (freshness, error
behaviour, buffer fill, request latency). Full setup notes, including the
`CC_ADDR=0.0.0.0:8080` you need so a container can reach the server, are in
[deploy/README.md](deploy/README.md).

What is exposed:

| Prefix                | Covers                                                     |
| --------------------- | ---------------------------------------------------------- |
| `cc_series_*`         | per-series health: updates, errors, staleness, buffer fill  |
| `cc_account_*`        | newest balance snapshot: equity, cash, buying power, day PnL |
| `cc_orderbook_*`      | newest book: best bid/ask, size, mid, spread, spread in bps |
| `cc_http_*`           | request counts by route and status, latency histogram        |
| `cc_go_*`, `cc_build_info`, `cc_uptime_seconds` | runtime and build metadata |

Two design points worth knowing:

- **Freshness is a first-class metric, not an afterthought.** The buffer keeps
  its last valid value when a fetch fails, which is the right behaviour for a
  dashboard and the wrong one for a monitor: the number on screen stays put
  while it silently ages. `cc_series_staleness_seconds` is what tells the two
  apart, and it counts from process start for a series that never produced a
  sample at all — so a source that was broken from the first second still
  alerts instead of being invisible.
- **Labels are bounded.** The `route` label carries the route *pattern*
  (`/api/series/{name}/latest`), never the raw path, and anything unrouted
  collapses into `other`. Otherwise any client could mint unlimited Prometheus
  series by requesting garbage URLs.

The business gauges dispatch on the payload type rather than the series name, so
a second orderbook series or a renamed one is picked up without code changes. An
empty side of the book emits no price at all rather than a zero — a fake price
is worse than a gap.

Switch it off with `"metrics": {"enabled": false}` or `CC_METRICS_ENABLED=false`;
the route then does not exist (404) and no request metrics are recorded.

## Error handling

- Every fetch returns `(value, error)`; nothing is swallowed.
- A failed poll is logged and recorded on the series (`errors`,
  `consecutive_errors`, `last_error`). **The buffer keeps its last valid
  value** — a broken upstream degrades freshness, it never blanks the dashboard
  and never kills the process.
- Consecutive errors trigger exponential backoff up to 2 min, so a failing or
  rate-limiting API is not hammered. Stream reconnects use the same ceiling plus
  jitter, and reset once a connection has held for 30s.
- Permanent failures (bad credentials, missing entitlement) are marked with
  `provider.ErrPermanent` and stop the reconnect loop instead of retrying
  forever. HTTP 401/403 map to `alpaca.ErrAuth` / `ErrForbidden`, 429 to
  `ErrRateLimited`; a 500 stays retryable.
- Manual refresh is coalesced (`ErrBusy` → HTTP 202, `queued: false`), so a
  user mashing the refresh button cannot turn into an API burst.
- Slow websocket consumers get samples dropped and counted, never block the
  poller.
- Handler panics are recovered and logged per request.

## Config

Per series: `enabled`, `mode` (`poll` | `stream`), `interval`, `timeout`,
`capacity` (ring size = history depth), `symbols`. Capacity × interval is the
retained window — e.g. orderbook `1s` × `1800` = 30 min of depth snapshots.

Top level: `metrics.enabled` (default true) and `metrics.path` (default
`/metrics`). A path that does not start with `/`, or that would shadow `/api/`,
is rejected at startup rather than silently ignored.

## Tests

```bash
go test ./...
```

Covers ring overwrite/wrap semantics, `Since` gap replay, "keep last valid
state on error", subscriber drop-instead-of-block, and registry errors. For the
broker layer: account JSON parsing (Alpaca returns money as strings), day-PnL
derivation, HTTP status → sentinel mapping, and the websocket protocol against a
fake Alpaca server (auth, subscribe, quote and depth decoding, permanent vs.
retryable errors, clean shutdown on context cancellation). For the supervisor:
reconnect after transient errors, giving up on permanent ones, and backoff
growth with its cap. For metrics: exposition escaping, one HELP/TYPE block per
family, staleness before the first sample, payload gauges for balance and
orderbook (including an empty book emitting no price), cumulative histogram
buckets, and the route label collapsing unknown paths instead of leaking them.
