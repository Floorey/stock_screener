package httpapi

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/metrics"
)

func metricsHandler(t *testing.T, path string) (http.Handler, *metrics.Collector) {
	t.Helper()

	store := buffer.NewStore()
	series, err := buffer.NewSeries("balance", 4, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	collector, err := metrics.NewCollector(store)
	if err != nil {
		t.Fatal(err)
	}
	srv, err := NewServer(store, nil, slog.New(slog.NewTextHandler(io.Discard, nil)),
		WithMetrics(collector, path))
	if err != nil {
		t.Fatal(err)
	}
	return srv.Handler(), collector
}

func scrapeBody(t *testing.T, h http.Handler, path string) string {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("GET %s = %d, want 200 (%s)", path, rec.Code, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != metrics.ContentType {
		t.Errorf("Content-Type = %q, want %q", ct, metrics.ContentType)
	}
	return rec.Body.String()
}

func TestMetricsEndpointServesExposition(t *testing.T) {
	h, _ := metricsHandler(t, "/metrics")

	body := scrapeBody(t, h, "/metrics")

	for _, want := range []string{
		"# TYPE cc_uptime_seconds gauge",
		"# TYPE cc_series_updates_total counter",
		`cc_series_info{series="balance",mode="poll",interval="1s"} 1`,
	} {
		if !strings.Contains(body, want) {
			t.Errorf("missing %q in scrape:\n%s", want, body)
		}
	}
}

// Without a metrics option there must be no endpoint at all — not an empty one.
func TestMetricsEndpointAbsentWhenDisabled(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("balance", 4, time.Second)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	h := testHandler(t, store, nil)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if rec.Code != http.StatusNotFound {
		t.Errorf("GET /metrics = %d, want 404 when metrics are off", rec.Code)
	}
}

func TestMetricsPathIsConfigurable(t *testing.T) {
	h, _ := metricsHandler(t, "/internal/prom")
	scrapeBody(t, h, "/internal/prom")
}

func TestWithMetricsRejectsBadPaths(t *testing.T) {
	store := buffer.NewStore()
	collector, err := metrics.NewCollector(store)
	if err != nil {
		t.Fatal(err)
	}
	log := slog.New(slog.NewTextHandler(io.Discard, nil))

	for _, path := range []string{"metrics", "/api/metrics"} {
		if _, err := NewServer(store, nil, log, WithMetrics(collector, path)); err == nil {
			t.Errorf("path %q was accepted, want an error", path)
		}
	}
	if _, err := NewServer(store, nil, log, WithMetrics(nil, "/metrics")); err == nil {
		t.Error("nil collector was accepted, want an error")
	}
}

// Requests must be counted under the route pattern, never the raw path —
// otherwise any client can mint unbounded Prometheus series by guessing URLs.
func TestRequestsAreCountedUnderTheRoutePattern(t *testing.T) {
	h, _ := metricsHandler(t, "/metrics")

	for _, path := range []string{
		"/api/series/balance/latest",
		"/api/series/orderbook/latest", // unknown series: 404, same route label
		"/api/series/balance/history?n=5",
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	}
	// Unroutable garbage collapses into one bucket.
	for _, path := range []string{"/wat", "/api/nope", "/api/series/a/b/c"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	}

	body := scrapeBody(t, h, "/metrics")

	for _, want := range []string{
		`cc_http_requests_total{method="GET",route="/api/series/{name}/latest",status="503"} 1`,
		`cc_http_requests_total{method="GET",route="/api/series/{name}/latest",status="404"} 1`,
		`cc_http_requests_total{method="GET",route="/api/series/{name}/history",status="200"} 1`,
		`cc_http_requests_total{method="GET",route="other",status="404"} 3`,
	} {
		if !strings.Contains(body, want) {
			t.Errorf("missing %q in scrape:\n%s", want, body)
		}
	}
	if strings.Contains(body, `route="/wat"`) {
		t.Errorf("raw path leaked into a label:\n%s", body)
	}
}

func TestRouteLabel(t *testing.T) {
	s := &Server{metricsPath: "/metrics"}
	cases := map[string]string{
		"/api/health":                  "/api/health",
		"/api/series":                  "/api/series",
		"/metrics":                     "/metrics",
		"/api/series/balance/latest":   "/api/series/{name}/latest",
		"/api/series/balance/history":  "/api/series/{name}/history",
		"/api/series/balance/refresh":  "/api/series/{name}/refresh",
		"/api/series//latest":          "other",
		"/api/series/balance/unknown":  "other",
		"/api/series/balance":          "other",
		"/api/series/balance/latest/x": "other",
		"/":                            "other",
	}
	for path, want := range cases {
		if got := s.routeLabel(path); got != want {
			t.Errorf("routeLabel(%q) = %q, want %q", path, got, want)
		}
	}
}

// A panicking handler must show up as a 500 in the request counter and be
// counted separately, not vanish because the request never returned normally.
func TestPanicIsCountedAsServerError(t *testing.T) {
	store := buffer.NewStore()
	collector, err := metrics.NewCollector(store)
	if err != nil {
		t.Fatal(err)
	}
	srv, err := NewServer(store, nil, slog.New(slog.NewTextHandler(io.Discard, nil)),
		WithMetrics(collector, "/metrics"))
	if err != nil {
		t.Fatal(err)
	}

	boom := http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("boom")
	})
	h := srv.recordMetrics(srv.recoverPanic(boom))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/health", nil))
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", rec.Code)
	}

	var sb strings.Builder
	if _, err := collector.WriteTo(&sb); err != nil {
		t.Fatal(err)
	}
	body := sb.String()

	if !strings.Contains(body, `cc_http_requests_total{method="GET",route="/api/health",status="500"} 1`) {
		t.Errorf("panic not counted as 500:\n%s", body)
	}
	if !strings.Contains(body, "cc_http_handler_panics_total 1") {
		t.Errorf("panic counter not incremented:\n%s", body)
	}
	if !strings.Contains(body, "cc_http_requests_in_flight 0") {
		t.Errorf("in-flight gauge stuck after a panic:\n%s", body)
	}
}
