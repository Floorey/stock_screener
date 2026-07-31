# Command Center (Go Backend)

Trading dashboard backend. Go service that buffers broker data in memory and
serves it to a browser frontend. The browser never talks to a broker API
directly — that is the whole point of the buffer layer: one poller per data
source, one configurable interval, no rate-limit surprises no matter how many
tabs are open.

## Status

MVP steps 1 + 2 are done:

- [x] 1. HTTP server skeleton (`net/http`, Go 1.22 routing, graceful shutdown)
- [x] 2. Buffered polling system (ring buffer, per-endpoint interval, backoff)
- [ ] 3. Real endpoints: balance (REST poll) + orderbook (broker websocket stream)
- [ ] 4. Websocket push of new samples to connected clients
- [ ] 5. Embedded terminal (websocket + `creack/pty`, bash-first / WSL2)
- [ ] 6. Frontend: HTML/JS + uPlot charts

The buffer already exposes a `Subscribe` fan-out and series can be declared
`"mode": "stream"`, so steps 3 and 4 plug in without touching this layer.

## Layout

```
command_center/
├── cmd/server/main.go            # wiring, config, signals, graceful shutdown
├── configs/config.example.json   # runnable example config
└── internal/
    ├── buffer/                   # ring buffer + series + registry  ← core
    │   ├── ring.go               # fixed-capacity ring, Latest/Last/Since
    │   ├── series.go             # ring + health status + subscriber fan-out
    │   └── store.go              # name → series registry
    ├── config/                   # JSON config + env overrides + validation
    ├── httpapi/                  # REST handlers, request log, panic recovery
    ├── poller/                   # scheduled fetch loop, timeout, backoff
    └── provider/                 # broker interfaces + payload types
        └── mock/                 # synthetic source, no credentials needed
```

## Run

```bash
go run ./cmd/server -config configs/config.example.json
```

Defaults (mock provider, `127.0.0.1:8080`) apply without a config file. Env
overrides: `CC_ADDR`, `CC_PROVIDER`, `CC_LOG_LEVEL`, plus `ALPACA_API_KEY` /
`ALPACA_SECRET_KEY` / `ALPACA_BASE_URL` — credentials are env-only and are never
read from the config file, matching the Python side of the repo.

## REST API

| Method | Path                          | Purpose                                     |
| ------ | ----------------------------- | ------------------------------------------- |
| GET    | `/api/health`                 | uptime + list of stale/failing series       |
| GET    | `/api/series`                 | status of every series                      |
| GET    | `/api/series/{name}/latest`   | newest buffered sample                      |
| GET    | `/api/series/{name}/history`  | `?n=100` last N, or `?since=42` gap by seq  |
| POST   | `/api/series/{name}/refresh`  | control command: force one out-of-band poll |

Every sample carries a monotonic `seq`. A reconnecting websocket client will
send its last seen `seq` and get exactly the gap back via `Since` — as far as
the ring still reaches.

## Error handling

- Every fetch returns `(value, error)`; nothing is swallowed.
- A failed poll is logged and recorded on the series (`errors`,
  `consecutive_errors`, `last_error`). **The buffer keeps its last valid
  value** — a broken upstream degrades freshness, it never blanks the dashboard
  and never kills the process.
- Consecutive errors trigger exponential backoff up to 2 min, so a failing or
  rate-limiting API is not hammered.
- Manual refresh is coalesced (`ErrBusy` → HTTP 202, `queued: false`), so a
  user mashing the refresh button cannot turn into an API burst.
- Slow websocket consumers get samples dropped and counted, never block the
  poller.
- Handler panics are recovered and logged per request.

## Config

Per series: `enabled`, `mode` (`poll` | `stream`), `interval`, `timeout`,
`capacity` (ring size = history depth), `symbols`. Capacity × interval is the
retained window — e.g. orderbook `1s` × `1800` = 30 min of depth snapshots.

## Tests

```bash
go test ./...
```

Covers ring overwrite/wrap semantics, `Since` gap replay, "keep last valid
state on error", subscriber drop-instead-of-block, and registry errors.
