package metrics

import (
	"strconv"
	"sync"
	"time"
)

// LatencyBuckets are the cumulative histogram bounds for request duration, in
// seconds. Tuned for a service that answers from memory: most requests land in
// the first few buckets, and anything past 1s means the process is in trouble.
var LatencyBuckets = []float64{
	0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5,
}

// requestKey is the label set of the latency histogram.
type requestKey struct {
	method string
	route  string
}

// statusKey adds the response status for the request counter.
type statusKey struct {
	method string
	route  string
	status int
}

// HTTPStats records request counts, response statuses and latencies. The route
// label is the matched route pattern, never the raw path — that keeps the
// series count bounded no matter what a client requests.
//
// Safe for concurrent use.
type HTTPStats struct {
	mu       sync.Mutex
	requests map[statusKey]uint64
	count    map[requestKey]uint64
	sum      map[requestKey]float64
	buckets  map[requestKey][]uint64
	inFlight int64
	panics   uint64
}

// NewHTTPStats returns an empty recorder.
func NewHTTPStats() *HTTPStats {
	return &HTTPStats{
		requests: make(map[statusKey]uint64),
		count:    make(map[requestKey]uint64),
		sum:      make(map[requestKey]float64),
		buckets:  make(map[requestKey][]uint64),
	}
}

// Begin marks a request as in flight. The returned function must be deferred by
// the caller so the gauge also drops back on a panicking handler.
func (h *HTTPStats) Begin() func() {
	h.mu.Lock()
	h.inFlight++
	h.mu.Unlock()

	var once sync.Once
	return func() {
		once.Do(func() {
			h.mu.Lock()
			h.inFlight--
			h.mu.Unlock()
		})
	}
}

// Observe records one finished request.
func (h *HTTPStats) Observe(method, route string, status int, d time.Duration) {
	rk := requestKey{method: method, route: route}
	sk := statusKey{method: method, route: route, status: status}
	secs := d.Seconds()

	h.mu.Lock()
	defer h.mu.Unlock()

	h.requests[sk]++
	h.count[rk]++
	h.sum[rk] += secs

	b, ok := h.buckets[rk]
	if !ok {
		b = make([]uint64, len(LatencyBuckets))
		h.buckets[rk] = b
	}
	// Cumulative histogram: a sample counts in its own bucket and every wider
	// one, so the rendering loop can just read the running total.
	for i, bound := range LatencyBuckets {
		if secs <= bound {
			b[i]++
		}
	}
}

// Panic counts a handler panic that the recovery middleware caught.
func (h *HTTPStats) Panic() {
	h.mu.Lock()
	h.panics++
	h.mu.Unlock()
}

// collect renders the HTTP families into the registry.
func (h *HTTPStats) collect(r *registry) {
	h.mu.Lock()
	requests := make(map[statusKey]uint64, len(h.requests))
	for k, v := range h.requests {
		requests[k] = v
	}
	count := make(map[requestKey]uint64, len(h.count))
	for k, v := range h.count {
		count[k] = v
	}
	sum := make(map[requestKey]float64, len(h.sum))
	for k, v := range h.sum {
		sum[k] = v
	}
	buckets := make(map[requestKey][]uint64, len(h.buckets))
	for k, v := range h.buckets {
		cp := make([]uint64, len(v))
		copy(cp, v)
		buckets[k] = cp
	}
	inFlight := h.inFlight
	panics := h.panics
	h.mu.Unlock()

	total := r.metric("cc_http_requests_total", "counter",
		"Total HTTP requests handled, by method, route and response status.")
	for _, k := range sortedKeys(requests, lessStatusKey) {
		total.add(float64(requests[k]),
			Label{"method", k.method},
			Label{"route", k.route},
			Label{"status", strconv.Itoa(k.status)},
		)
	}

	dur := r.metric("cc_http_request_duration_seconds", "histogram",
		"HTTP request duration in seconds, by method and route.")
	for _, k := range sortedKeys(count, lessRequestKey) {
		labels := []Label{{"method", k.method}, {"route", k.route}}
		bucketLabels := func(le string) []Label {
			return append(append([]Label{}, labels...), Label{"le", le})
		}
		for i, bound := range LatencyBuckets {
			dur.addSuffixed("_bucket", float64(buckets[k][i]),
				bucketLabels(formatValue(bound))...)
		}
		// The +Inf bucket must equal the observation count by definition.
		dur.addSuffixed("_bucket", float64(count[k]), bucketLabels("+Inf")...)
		dur.addSuffixed("_sum", sum[k], labels...)
		dur.addSuffixed("_count", float64(count[k]), labels...)
	}

	r.metric("cc_http_requests_in_flight", "gauge",
		"HTTP requests currently being handled.").add(float64(inFlight))

	r.metric("cc_http_handler_panics_total", "counter",
		"Handler panics caught by the recovery middleware.").add(float64(panics))
}

func lessRequestKey(a, b requestKey) bool {
	if a.route != b.route {
		return a.route < b.route
	}
	return a.method < b.method
}

func lessStatusKey(a, b statusKey) bool {
	if a.route != b.route {
		return a.route < b.route
	}
	if a.method != b.method {
		return a.method < b.method
	}
	return a.status < b.status
}
