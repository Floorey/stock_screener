package metrics

import (
	"io"
	"math"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// scrape renders a collector into a string.
func scrape(t *testing.T, c *Collector) string {
	t.Helper()
	var sb strings.Builder
	if _, err := c.WriteTo(&sb); err != nil {
		t.Fatalf("write scrape: %v", err)
	}
	return sb.String()
}

// sampleValue returns the value of the first line matching name+labels.
func sampleValue(t *testing.T, out, prefix string) float64 {
	t.Helper()
	for _, line := range strings.Split(out, "\n") {
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		rest := strings.TrimPrefix(line, prefix)
		// Guard against cc_series_last_seq matching cc_series_last_seq_foo.
		if rest == "" || (rest[0] != ' ' && rest[0] != '{') {
			continue
		}
		idx := strings.LastIndex(line, " ")
		v, err := strconv.ParseFloat(line[idx+1:], 64)
		if err != nil {
			t.Fatalf("parse value of %q: %v", line, err)
		}
		return v
	}
	t.Fatalf("no sample starting with %q in:\n%s", prefix, out)
	return 0
}

func mustCollector(t *testing.T, store *buffer.Store) *Collector {
	t.Helper()
	c, err := NewCollector(store)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestFormatValueHandlesSpecialFloats(t *testing.T) {
	cases := map[float64]string{
		0:                        "0",
		1.5:                      "1.5",
		-0.0005:                  "-0.0005",
		math.NaN():               "NaN",
		math.Inf(1):              "+Inf",
		math.Inf(-1):             "-Inf",
		float64(1_234_567_890.5): "1.2345678905e+09",
	}
	for in, want := range cases {
		if got := formatValue(in); got != want {
			t.Errorf("formatValue(%v) = %q, want %q", in, got, want)
		}
	}
}

func TestEncoderEscapesAndDropsEmptyLabels(t *testing.T) {
	r := newRegistry()
	r.metric("cc_test", "gauge", "a \\ backslash\nand a newline").
		add(1, Label{"kept", `say "hi"\n`}, Label{"dropped", ""})

	var sb strings.Builder
	if _, err := r.WriteTo(&sb); err != nil {
		t.Fatal(err)
	}
	out := sb.String()

	if strings.Contains(out, "\n\n") || strings.Count(out, "\n") != 3 {
		t.Errorf("expected exactly HELP + TYPE + one sample line, got:\n%s", out)
	}
	if !strings.Contains(out, `# HELP cc_test a \\ backslash\nand a newline`) {
		t.Errorf("HELP not escaped:\n%s", out)
	}
	if !strings.Contains(out, `cc_test{kept="say \"hi\"\\n"} 1`) {
		t.Errorf("label not escaped or empty label not dropped:\n%s", out)
	}
}

// A second declaration of the same family must reuse the first one: two HELP
// blocks for one metric name make Prometheus reject the whole scrape.
func TestEncoderDeclaresEachFamilyOnce(t *testing.T) {
	r := newRegistry()
	r.metric("cc_test", "gauge", "help").add(1, Label{"a", "1"})
	r.metric("cc_test", "gauge", "help").add(2, Label{"a", "2"})

	var sb strings.Builder
	if _, err := r.WriteTo(&sb); err != nil {
		t.Fatal(err)
	}
	if n := strings.Count(sb.String(), "# TYPE cc_test "); n != 1 {
		t.Errorf("got %d TYPE lines, want 1:\n%s", n, sb.String())
	}
}

func TestEncoderSkipsEmptyFamilies(t *testing.T) {
	r := newRegistry()
	r.metric("cc_empty", "gauge", "no samples")

	var sb strings.Builder
	if _, err := r.WriteTo(&sb); err != nil {
		t.Fatal(err)
	}
	if sb.Len() != 0 {
		t.Errorf("empty family should render nothing, got:\n%s", sb.String())
	}
}

func TestSeriesHealthIsExposed(t *testing.T) {
	store := buffer.NewStore()
	series, err := buffer.NewSeries("balance", 8, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	series.Publish(provider.Balance{Equity: 100, Currency: "USD"}, time.Now())
	series.Fail(errTest)
	series.Fail(errTest)

	out := scrape(t, mustCollector(t, store))

	if got := sampleValue(t, out, `cc_series_updates_total{series="balance"}`); got != 1 {
		t.Errorf("updates = %v, want 1", got)
	}
	if got := sampleValue(t, out, `cc_series_errors_total{series="balance"}`); got != 2 {
		t.Errorf("errors = %v, want 2", got)
	}
	if got := sampleValue(t, out, `cc_series_consecutive_errors{series="balance"}`); got != 2 {
		t.Errorf("consecutive errors = %v, want 2", got)
	}
	if got := sampleValue(t, out, `cc_series_capacity{series="balance"}`); got != 8 {
		t.Errorf("capacity = %v, want 8", got)
	}
	if got := sampleValue(t, out, `cc_series_interval_seconds{series="balance"}`); got != 5 {
		t.Errorf("interval = %v, want 5", got)
	}
	if !strings.Contains(out, `cc_series_info{series="balance",mode="poll",interval="5s"} 1`) {
		t.Errorf("series info missing or wrong:\n%s", out)
	}
}

// A push-driven series has no cadence to miss, so cc_series_stale can never
// fire for it — staleness_seconds is what an alert has to use there.
func TestStreamedSeriesReportsModeStream(t *testing.T) {
	store := buffer.NewStore()
	series, err := buffer.NewSeries("orderbook", 4, 0)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}

	out := scrape(t, mustCollector(t, store))

	if !strings.Contains(out, `cc_series_info{series="orderbook",mode="stream"} 1`) {
		t.Errorf("stream mode not reported:\n%s", out)
	}
	if got := sampleValue(t, out, `cc_series_interval_seconds{series="orderbook"}`); got != 0 {
		t.Errorf("interval = %v, want 0 for a streamed series", got)
	}
	if got := sampleValue(t, out, `cc_series_stale{series="orderbook"}`); got != 0 {
		t.Errorf("stale = %v, want 0", got)
	}
}

// A source that never produced a single sample must still show a growing age,
// otherwise a broker that is down from the start silently alerts on nothing.
func TestStalenessCountsFromStartBeforeFirstSample(t *testing.T) {
	store := buffer.NewStore()
	series, err := buffer.NewSeries("balance", 4, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}

	c := mustCollector(t, store)
	c.started = time.Unix(1000, 0)
	c.now = func() time.Time { return time.Unix(1090, 0) }

	out := scrape(t, c)

	if got := sampleValue(t, out, `cc_series_staleness_seconds{series="balance"}`); got != 90 {
		t.Errorf("staleness = %v, want 90", got)
	}
	if got := sampleValue(t, out, `cc_series_last_update_timestamp_seconds{series="balance"}`); got != 0 {
		t.Errorf("last update = %v, want 0", got)
	}
	if got := sampleValue(t, out, `cc_series_stale{series="balance"}`); got != 1 {
		t.Errorf("stale = %v, want 1", got)
	}
}

func TestStalenessUsesLastSampleTimestamp(t *testing.T) {
	store := buffer.NewStore()
	series, err := buffer.NewSeries("balance", 4, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	series.Publish(provider.Balance{Equity: 1}, time.Unix(1050, 0))

	c := mustCollector(t, store)
	c.started = time.Unix(1000, 0)
	c.now = func() time.Time { return time.Unix(1070, 0) }

	out := scrape(t, c)

	if got := sampleValue(t, out, `cc_series_staleness_seconds{series="balance"}`); got != 20 {
		t.Errorf("staleness = %v, want 20", got)
	}
	if got := sampleValue(t, out, `cc_series_last_update_timestamp_seconds{series="balance"}`); got != 1050 {
		t.Errorf("last update = %v, want 1050", got)
	}
}

func TestBalancePayloadIsCharted(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("balance", 4, time.Second)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	series.Publish(provider.Balance{
		Equity:      101_250.5,
		Cash:        35_000,
		BuyingPower: 70_000,
		PnLDay:      -1_250.5,
		Currency:    "USD",
		Account:     "acct-1",
		Ts:          time.Unix(1700, 0),
	}, time.Unix(1700, 0))

	out := scrape(t, mustCollector(t, store))
	const labels = `{series="balance",account="acct-1",currency="USD"}`

	if got := sampleValue(t, out, "cc_account_equity"+labels); got != 101_250.5 {
		t.Errorf("equity = %v", got)
	}
	if got := sampleValue(t, out, "cc_account_pnl_day"+labels); got != -1_250.5 {
		t.Errorf("pnl_day = %v", got)
	}
	if got := sampleValue(t, out, "cc_account_buying_power"+labels); got != 70_000 {
		t.Errorf("buying power = %v", got)
	}
}

func TestOrderbookPayloadIsCharted(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("orderbook", 4, 0)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	series.Publish(provider.Orderbook{
		Symbol: "SPY",
		Bids:   []provider.Level{{Price: 99, Size: 3}, {Price: 98, Size: 5}},
		Asks:   []provider.Level{{Price: 101, Size: 2}},
		Ts:     time.Unix(1700, 0),
	}, time.Unix(1700, 0))

	out := scrape(t, mustCollector(t, store))
	const labels = `{series="orderbook",symbol="SPY"}`

	if got := sampleValue(t, out, "cc_orderbook_bid_price"+labels); got != 99 {
		t.Errorf("bid = %v", got)
	}
	if got := sampleValue(t, out, "cc_orderbook_ask_price"+labels); got != 101 {
		t.Errorf("ask = %v", got)
	}
	if got := sampleValue(t, out, "cc_orderbook_mid_price"+labels); got != 100 {
		t.Errorf("mid = %v", got)
	}
	if got := sampleValue(t, out, "cc_orderbook_spread"+labels); got != 2 {
		t.Errorf("spread = %v", got)
	}
	if got := sampleValue(t, out, "cc_orderbook_spread_bps"+labels); got != 200 {
		t.Errorf("spread_bps = %v", got)
	}
	if !strings.Contains(out, `cc_orderbook_levels{series="orderbook",symbol="SPY",side="bid"} 2`) {
		t.Errorf("bid depth missing:\n%s", out)
	}
	if !strings.Contains(out, `cc_orderbook_levels{series="orderbook",symbol="SPY",side="ask"} 1`) {
		t.Errorf("ask depth missing:\n%s", out)
	}
}

// An empty book must not report a bid of 0 — a fake price is worse than a gap.
func TestEmptyOrderbookOmitsPrices(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("orderbook", 4, 0)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	series.Publish(provider.Orderbook{Symbol: "SPY"}, time.Unix(1700, 0))

	out := scrape(t, mustCollector(t, store))

	for _, name := range []string{
		"cc_orderbook_bid_price", "cc_orderbook_ask_price",
		"cc_orderbook_mid_price", "cc_orderbook_spread",
	} {
		if strings.Contains(out, name+"{") {
			t.Errorf("%s should be absent for an empty book:\n%s", name, out)
		}
	}
	if !strings.Contains(out, `cc_orderbook_levels{series="orderbook",symbol="SPY",side="bid"} 0`) {
		t.Errorf("level count should still be reported:\n%s", out)
	}
}

func TestHTTPHistogramIsCumulative(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("balance", 4, time.Second)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	c := mustCollector(t, store)

	c.HTTP().Observe("GET", "/api/health", 200, 2*time.Millisecond)
	c.HTTP().Observe("GET", "/api/health", 200, 40*time.Millisecond)
	c.HTTP().Observe("GET", "/api/health", 500, 3*time.Second)

	out := scrape(t, c)
	const labels = `{method="GET",route="/api/health"`

	if got := sampleValue(t, out, `cc_http_request_duration_seconds_bucket`+labels+`,le="0.001"}`); got != 0 {
		t.Errorf("le=0.001 = %v, want 0", got)
	}
	if got := sampleValue(t, out, `cc_http_request_duration_seconds_bucket`+labels+`,le="0.0025"}`); got != 1 {
		t.Errorf("le=0.0025 = %v, want 1", got)
	}
	if got := sampleValue(t, out, `cc_http_request_duration_seconds_bucket`+labels+`,le="0.05"}`); got != 2 {
		t.Errorf("le=0.05 = %v, want 2", got)
	}
	if got := sampleValue(t, out, `cc_http_request_duration_seconds_bucket`+labels+`,le="+Inf"}`); got != 3 {
		t.Errorf("le=+Inf = %v, want 3 (must equal the observation count)", got)
	}
	if got := sampleValue(t, out, `cc_http_request_duration_seconds_count`+labels+`}`); got != 3 {
		t.Errorf("count = %v, want 3", got)
	}
	if got := sampleValue(t, out, `cc_http_requests_total{method="GET",route="/api/health",status="500"}`); got != 1 {
		t.Errorf("500 count = %v, want 1", got)
	}
}

func TestInFlightReturnsToZero(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("balance", 4, time.Second)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	c := mustCollector(t, store)

	done := c.HTTP().Begin()
	if got := sampleValue(t, scrape(t, c), "cc_http_requests_in_flight"); got != 1 {
		t.Errorf("in flight = %v, want 1", got)
	}
	done()
	done() // idempotent: a double release must not push the gauge negative
	if got := sampleValue(t, scrape(t, c), "cc_http_requests_in_flight"); got != 0 {
		t.Errorf("in flight = %v, want 0", got)
	}
}

// Scrapes run concurrently with the pollers writing into the buffer and with
// request middleware recording latencies. Run with -race where cgo is
// available; even without it this catches unsynchronised map access.
func TestConcurrentScrapeAndWrites(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("orderbook", 64, 0)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	c := mustCollector(t, store)

	const rounds = 200
	var wg sync.WaitGroup
	wg.Add(3)

	go func() {
		defer wg.Done()
		for i := 0; i < rounds; i++ {
			series.Publish(provider.Orderbook{
				Symbol: "SPY",
				Bids:   []provider.Level{{Price: float64(i), Size: 1}},
				Asks:   []provider.Level{{Price: float64(i) + 1, Size: 1}},
			}, time.Now())
		}
	}()
	go func() {
		defer wg.Done()
		for i := 0; i < rounds; i++ {
			release := c.HTTP().Begin()
			c.HTTP().Observe("GET", "/api/series/{name}/latest", 200, time.Millisecond)
			release()
		}
	}()
	go func() {
		defer wg.Done()
		for i := 0; i < rounds; i++ {
			if _, err := c.WriteTo(io.Discard); err != nil {
				t.Errorf("scrape: %v", err)
				return
			}
		}
	}()

	wg.Wait()

	if got := sampleValue(t, scrape(t, c), "cc_http_requests_in_flight"); got != 0 {
		t.Errorf("in flight = %v, want 0 after all requests finished", got)
	}
}

var errTest = testError("upstream unavailable")

type testError string

func (e testError) Error() string { return string(e) }
