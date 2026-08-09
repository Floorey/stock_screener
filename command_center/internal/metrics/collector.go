package metrics

import (
	"errors"
	"io"
	"runtime"
	"runtime/debug"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// Collector turns the in-memory state of the command center into a Prometheus
// scrape. It reads the same buffer the REST API reads and never touches a
// broker API — a scrape costs nothing in rate-limit budget, which is why it is
// safe to point Grafana at it every few seconds.
type Collector struct {
	store   *buffer.Store
	http    *HTTPStats
	started time.Time

	// now is injectable so staleness can be asserted in tests.
	now func() time.Time
}

// NewCollector wires a collector to the series registry.
func NewCollector(store *buffer.Store) (*Collector, error) {
	if store == nil {
		return nil, errors.New("metrics: store must not be nil")
	}
	return &Collector{
		store:   store,
		http:    NewHTTPStats(),
		started: time.Now(),
		now:     time.Now,
	}, nil
}

// HTTP returns the request recorder the HTTP middleware writes to.
func (c *Collector) HTTP() *HTTPStats { return c.http }

// WriteTo renders one scrape.
func (c *Collector) WriteTo(w io.Writer) (int64, error) {
	r := newRegistry()

	c.collectProcess(r)
	c.collectSeries(r)
	c.http.collect(r)

	return r.WriteTo(w)
}

func (c *Collector) collectProcess(r *registry) {
	r.metric("cc_uptime_seconds", "gauge",
		"Seconds since the command center started.").
		add(c.now().Sub(c.started).Seconds())

	r.metric("cc_start_time_seconds", "gauge",
		"Unix timestamp of process start.").
		add(float64(c.started.UnixNano()) / 1e9)

	r.metric("cc_go_goroutines", "gauge",
		"Number of goroutines currently running.").
		add(float64(runtime.NumGoroutine()))

	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	r.metric("cc_go_memstats_heap_alloc_bytes", "gauge",
		"Heap bytes allocated and still in use.").add(float64(mem.HeapAlloc))
	r.metric("cc_go_memstats_sys_bytes", "gauge",
		"Total bytes obtained from the OS.").add(float64(mem.Sys))
	r.metric("cc_go_gc_cycles_total", "counter",
		"Completed garbage collection cycles.").add(float64(mem.NumGC))

	info := r.metric("cc_build_info", "gauge",
		"Build metadata; the value is always 1, read the labels.")
	goVersion, revision := buildInfo()
	info.add(1, Label{"go_version", goVersion}, Label{"revision", revision})
}

// buildInfo reads the Go version and, when the binary was built from a git
// checkout, the commit it came from. Both are best effort.
func buildInfo() (goVersion, revision string) {
	goVersion = runtime.Version()
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return goVersion, ""
	}
	if bi.GoVersion != "" {
		goVersion = bi.GoVersion
	}
	for _, s := range bi.Settings {
		if s.Key == "vcs.revision" {
			revision = s.Value
		}
	}
	return goVersion, revision
}

// collectSeries emits the health of every buffered series plus the business
// values of its newest sample. Health first: a dashboard that shows a price
// without showing whether that price is still fresh is worse than no dashboard.
func (c *Collector) collectSeries(r *registry) {
	statuses := c.store.Statuses()
	now := c.now()

	info := r.metric("cc_series_info", "gauge",
		"Series metadata; the value is always 1, read the labels.")
	interval := r.metric("cc_series_interval_seconds", "gauge",
		"Configured poll cadence; 0 for push-driven (streamed) series.")
	updates := r.metric("cc_series_updates_total", "counter",
		"Samples successfully published into the series buffer.")
	errs := r.metric("cc_series_errors_total", "counter",
		"Failed fetches for the series. The buffer keeps its last valid value.")
	consecutive := r.metric("cc_series_consecutive_errors", "gauge",
		"Current error streak. Drives the producer's exponential backoff.")
	buffered := r.metric("cc_series_buffered_samples", "gauge",
		"Samples currently held in the ring buffer.")
	capacity := r.metric("cc_series_capacity", "gauge",
		"Ring buffer size; capacity times interval is the retained window.")
	subscribers := r.metric("cc_series_subscribers", "gauge",
		"Live consumers subscribed to the series fan-out.")
	lastUpdate := r.metric("cc_series_last_update_timestamp_seconds", "gauge",
		"Unix timestamp of the newest sample; 0 if none was ever published.")
	staleness := r.metric("cc_series_staleness_seconds", "gauge",
		"Age of the newest sample. Measured from process start while a series "+
			"has never produced one, so a source that never came up still alerts.")
	stale := r.metric("cc_series_stale", "gauge",
		"1 when the series missed two update cycles. Always 0 for streamed "+
			"series, which have no fixed cadence — alert on staleness there.")
	lastSeq := r.metric("cc_series_last_seq", "gauge",
		"Monotonic sequence number of the newest sample.")
	lastError := r.metric("cc_series_last_error_timestamp_seconds", "gauge",
		"Unix timestamp of the most recent fetch error; 0 if there was none.")

	for _, st := range statuses {
		name := Label{"series", st.Name}

		mode := "poll"
		if st.Interval == "" {
			mode = "stream"
		}
		info.add(1, name, Label{"mode", mode}, Label{"interval", st.Interval})

		if d, err := time.ParseDuration(st.Interval); err == nil {
			interval.add(d.Seconds(), name)
		} else {
			interval.add(0, name)
		}

		updates.add(float64(st.Updates), name)
		errs.add(float64(st.Errors), name)
		consecutive.add(float64(st.ConsecutiveErrors), name)
		buffered.add(float64(st.Buffered), name)
		capacity.add(float64(st.Capacity), name)
		subscribers.add(float64(st.Subscribers), name)
		lastSeq.add(float64(st.LastSeq), name)
		stale.add(boolValue(st.Stale), name)

		if st.LastUpdate.IsZero() {
			lastUpdate.add(0, name)
			staleness.add(now.Sub(c.started).Seconds(), name)
		} else {
			lastUpdate.add(timestamp(st.LastUpdate), name)
			staleness.add(now.Sub(st.LastUpdate).Seconds(), name)
		}

		if st.LastErrorAt.IsZero() {
			lastError.add(0, name)
		} else {
			lastError.add(timestamp(st.LastErrorAt), name)
		}
	}

	c.collectPayloads(r)
}

// collectPayloads charts the newest value of every series. It dispatches on the
// payload type rather than the series name, so a second orderbook series or a
// renamed one is picked up without touching this code.
func (c *Collector) collectPayloads(r *registry) {
	for _, name := range c.store.Names() {
		series, err := c.store.Get(name)
		if err != nil {
			continue
		}
		sample, ok := series.Latest()
		if !ok {
			continue
		}
		switch v := sample.Value.(type) {
		case provider.Balance:
			collectBalance(r, name, v)
		case *provider.Balance:
			if v != nil {
				collectBalance(r, name, *v)
			}
		case provider.Orderbook:
			collectOrderbook(r, name, v)
		case *provider.Orderbook:
			if v != nil {
				collectOrderbook(r, name, *v)
			}
		}
	}
}

func collectBalance(r *registry, series string, b provider.Balance) {
	labels := []Label{
		{"series", series},
		{"account", b.Account},
		{"currency", b.Currency},
	}
	r.metric("cc_account_equity", "gauge",
		"Account equity from the newest balance snapshot.").add(b.Equity, labels...)
	r.metric("cc_account_cash", "gauge",
		"Account cash from the newest balance snapshot.").add(b.Cash, labels...)
	r.metric("cc_account_buying_power", "gauge",
		"Account buying power from the newest balance snapshot.").
		add(b.BuyingPower, labels...)
	r.metric("cc_account_pnl_day", "gauge",
		"Day PnL, derived as equity minus last_equity.").add(b.PnLDay, labels...)
	if !b.Ts.IsZero() {
		r.metric("cc_account_snapshot_timestamp_seconds", "gauge",
			"Broker-side timestamp of the newest balance snapshot.").
			add(timestamp(b.Ts), Label{"series", series})
	}
}

func collectOrderbook(r *registry, series string, o provider.Orderbook) {
	labels := []Label{{"series", series}, {"symbol", o.Symbol}}

	depth := r.metric("cc_orderbook_levels", "gauge",
		"Price levels in the newest snapshot, per side. Alpaca publishes only "+
			"top of book for equities, real depth for crypto.")
	sided := func(side string) []Label {
		return append(append([]Label{}, labels...), Label{"side", side})
	}
	depth.add(float64(len(o.Bids)), sided("bid")...)
	depth.add(float64(len(o.Asks)), sided("ask")...)

	if len(o.Bids) > 0 {
		r.metric("cc_orderbook_bid_price", "gauge",
			"Best bid price.").add(o.Bids[0].Price, labels...)
		r.metric("cc_orderbook_bid_size", "gauge",
			"Best bid size. Equity quote sizes are round lots (1 = 100 shares).").
			add(o.Bids[0].Size, labels...)
	}
	if len(o.Asks) > 0 {
		r.metric("cc_orderbook_ask_price", "gauge",
			"Best ask price.").add(o.Asks[0].Price, labels...)
		r.metric("cc_orderbook_ask_size", "gauge",
			"Best ask size. Equity quote sizes are round lots (1 = 100 shares).").
			add(o.Asks[0].Size, labels...)
	}

	mid, hasMid := o.Mid()
	if hasMid {
		r.metric("cc_orderbook_mid_price", "gauge",
			"Mid price between best bid and best ask.").add(mid, labels...)
	}
	if spread, ok := o.Spread(); ok {
		r.metric("cc_orderbook_spread", "gauge",
			"Absolute top-of-book spread.").add(spread, labels...)
		if hasMid && mid != 0 {
			r.metric("cc_orderbook_spread_bps", "gauge",
				"Top-of-book spread in basis points of the mid price.").
				add(spread/mid*10_000, labels...)
		}
	}
	if !o.Ts.IsZero() {
		r.metric("cc_orderbook_snapshot_timestamp_seconds", "gauge",
			"Exchange-side timestamp of the newest orderbook snapshot.").
			add(timestamp(o.Ts), labels...)
	}
}

// timestamp converts to fractional Unix seconds, the convention Prometheus uses
// for "*_timestamp_seconds" gauges.
func timestamp(t time.Time) float64 {
	return float64(t.UnixNano()) / 1e9
}

func boolValue(b bool) float64 {
	if b {
		return 1
	}
	return 0
}
