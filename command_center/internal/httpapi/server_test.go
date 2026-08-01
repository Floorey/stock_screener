package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/poller"
)

func testHandler(t *testing.T, store *buffer.Store, pollers *poller.Manager) http.Handler {
	t.Helper()
	srv, err := NewServer(store, pollers, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	return srv.Handler()
}

func do(t *testing.T, h http.Handler, method, path string) (int, map[string]any) {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, path, nil))

	var body map[string]any
	if rec.Body.Len() > 0 {
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatalf("decode response for %s %s: %v (%s)", method, path, err, rec.Body.String())
		}
	}
	return rec.Code, body
}

func TestLatestReturns503BeforeFirstSample(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("balance", 4, time.Second)
	if err := store.Register(series); err != nil {
		t.Fatal(err)
	}
	h := testHandler(t, store, poller.NewManager())

	if code, _ := do(t, h, http.MethodGet, "/api/series/balance/latest"); code != http.StatusServiceUnavailable {
		t.Errorf("code = %d, want 503", code)
	}

	series.Publish(map[string]any{"equity": 100}, time.Now())
	code, body := do(t, h, http.MethodGet, "/api/series/balance/latest")
	if code != http.StatusOK {
		t.Fatalf("code = %d, want 200", code)
	}
	if _, ok := body["sample"]; !ok {
		t.Errorf("response has no sample: %v", body)
	}
}

func TestUnknownSeriesReturns404(t *testing.T) {
	h := testHandler(t, buffer.NewStore(), poller.NewManager())
	if code, _ := do(t, h, http.MethodGet, "/api/series/nope/latest"); code != http.StatusNotFound {
		t.Errorf("code = %d, want 404", code)
	}
}

func TestHistoryRejectsBadParameters(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("orderbook", 8, time.Second)
	_ = store.Register(series)
	series.Publish(1, time.Now())
	series.Publish(2, time.Now())
	h := testHandler(t, store, poller.NewManager())

	if code, _ := do(t, h, http.MethodGet, "/api/series/orderbook/history?n=abc"); code != http.StatusBadRequest {
		t.Errorf("n=abc: code = %d, want 400", code)
	}
	if code, _ := do(t, h, http.MethodGet, "/api/series/orderbook/history?since=-1"); code != http.StatusBadRequest {
		t.Errorf("since=-1: code = %d, want 400", code)
	}

	code, body := do(t, h, http.MethodGet, "/api/series/orderbook/history?since=1")
	if code != http.StatusOK {
		t.Fatalf("code = %d, want 200", code)
	}
	if count, _ := body["count"].(float64); count != 1 {
		t.Errorf("count = %v, want 1 (only the sample after seq 1)", body["count"])
	}
}

// A streamed series has no poller: refreshing it is a conflict, not a 400 with
// an internal message leaking out.
func TestRefreshOnStreamedSeriesReturns409(t *testing.T) {
	store := buffer.NewStore()
	series, _ := buffer.NewSeries("orderbook", 8, 0)
	_ = store.Register(series)
	h := testHandler(t, store, poller.NewManager())

	code, body := do(t, h, http.MethodPost, "/api/series/orderbook/refresh")
	if code != http.StatusConflict {
		t.Fatalf("code = %d, want 409", code)
	}
	msg, _ := body["error"].(string)
	if msg == "" {
		t.Fatal("no error message returned")
	}
	if want := "stream-driven"; !strings.Contains(msg, want) {
		t.Errorf("error = %q, want it to mention %q", msg, want)
	}
}

func TestHealthReportsDegradedSeries(t *testing.T) {
	store := buffer.NewStore()
	healthy, _ := buffer.NewSeries("balance", 4, time.Minute)
	broken, _ := buffer.NewSeries("orderbook", 4, time.Minute)
	_ = store.Register(healthy)
	_ = store.Register(broken)

	healthy.Publish(1, time.Now())
	broken.Publish(1, time.Now())
	broken.Fail(errAPIDown)

	h := testHandler(t, store, poller.NewManager())
	code, body := do(t, h, http.MethodGet, "/api/health")
	if code != http.StatusOK {
		t.Fatalf("code = %d, want 200", code)
	}
	if body["status"] != "degraded" {
		t.Errorf("status = %v, want degraded", body["status"])
	}
	degraded, _ := body["degraded"].([]any)
	if len(degraded) != 1 || degraded[0] != "orderbook" {
		t.Errorf("degraded = %v, want [orderbook]", body["degraded"])
	}
}

var errAPIDown = errors.New("api down")
