# Grafana stack

Prometheus + Grafana, pre-provisioned against the command center's `/metrics`
endpoint. The Go service is deliberately **not** part of this compose stack: it
owns the broker connections and should not be restarted every time you poke at a
dashboard.

## Start

The server binds `127.0.0.1:8080` by default, which a container cannot reach.
Bind it to all interfaces first:

```bash
CC_ADDR=0.0.0.0:8080 go run ./cmd/server -config configs/config.alpaca.json
```

Then bring up the stack:

```bash
docker compose -f deploy/docker-compose.yml up -d
```

- Grafana: http://localhost:3000 (`admin` / `admin`, override with
  `GRAFANA_USER` / `GRAFANA_PASSWORD`)
- Prometheus: http://localhost:9090

Both ports are published on `127.0.0.1` only. Grafana ships with an unchanged
default password — set a real one before binding either to a public interface.

Two dashboards are provisioned into the **Command Center** folder:

| Dashboard          | Question it answers                                        |
| ------------------ | ---------------------------------------------------------- |
| **Trading**        | What is the account doing, and what does the book look like |
| **Pipeline Health** | Is any of that still fresh enough to act on                |

They are provisioned read-only (`allowUiUpdates: false`). Edits in the UI are
overwritten within 30 seconds — export the JSON and commit it under
`deploy/grafana/dashboards/` to make a change stick.

## Not on Docker Desktop?

`prometheus.yml` scrapes `host.docker.internal:8080`. On a plain Linux host the
`extra_hosts: host-gateway` entry in the compose file makes that name resolve;
if you run the service somewhere else entirely, replace the target with its
address.

## Alerts

`prometheus/alerts.yml` is loaded by Prometheus and visible under **Alerts** at
:9090. Prometheus only *evaluates* rules — delivering them to a chat or a phone
needs an Alertmanager, which this stack does not include. Grafana's own alerting
can use the same expressions if you prefer to stay in one tool.

The rules split into three groups:

- **availability** — the backend is unreachable, or it restarted (which wipes
  the in-memory ring buffers).
- **freshness** — a polled series missed four intervals, a stream went quiet for
  a minute, or a series never produced a single sample after two minutes. This
  group is the point of the whole exercise: a stale number displayed as if it
  were live is the failure mode worth catching.
- **errors** — error streaks, sustained fetch failures, handler panics, 5xx.

One market-data rule (`OrderbookSpreadWide`) is included as a starting point.
Its 50bps threshold is meaningless without knowing the instrument — tune it per
symbol or delete it.

## Turning the endpoint off

```json
"metrics": { "enabled": false }
```

or `CC_METRICS_ENABLED=false`. The route then does not exist at all (404), and
no request metrics are recorded.
