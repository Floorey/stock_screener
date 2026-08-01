package streamer

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// scriptedStream returns the given results on successive Run calls, emitting
// one value before each non-nil error.
type scriptedStream struct {
	mu      sync.Mutex
	results []error
	calls   int
	emitted int
}

func (s *scriptedStream) Run(ctx context.Context, emit func(any, time.Time)) error {
	s.mu.Lock()
	idx := s.calls
	s.calls++
	var err error
	if idx < len(s.results) {
		err = s.results[idx]
	}
	s.mu.Unlock()

	emit(idx, time.Now())
	s.mu.Lock()
	s.emitted++
	s.mu.Unlock()

	if err != nil {
		return err
	}
	// Last scripted step: stay connected until shutdown.
	<-ctx.Done()
	return nil
}

func (s *scriptedStream) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

func TestRunnerReconnectsAfterTransientError(t *testing.T) {
	series, err := buffer.NewSeries("orderbook", 16, 0)
	if err != nil {
		t.Fatal(err)
	}
	stream := &scriptedStream{results: []error{
		errors.New("connection reset"),
		errors.New("connection reset again"),
		nil, // third attempt holds
	}}

	runner, err := New(series, stream, Options{
		MinBackoff:  5 * time.Millisecond,
		MaxBackoff:  20 * time.Millisecond,
		StableAfter: time.Hour, // never treat these as stable
	}, testLogger())
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() { done <- runner.Run(ctx) }()

	deadline := time.After(2 * time.Second)
	for stream.callCount() < 3 {
		select {
		case <-deadline:
			t.Fatalf("only %d connection attempts", stream.callCount())
		case <-time.After(5 * time.Millisecond):
		}
	}

	cancel()
	if err := <-done; err != nil {
		t.Fatalf("runner returned %v, want nil after cancellation", err)
	}

	st := series.Status()
	if st.Errors != 2 {
		t.Errorf("errors = %d, want 2", st.Errors)
	}
	// Each attempt emitted one value, and the successful reconnect cleared the
	// error streak.
	if st.Updates < 3 {
		t.Errorf("updates = %d, want at least 3", st.Updates)
	}
	if st.ConsecutiveErrors != 0 {
		t.Errorf("consecutive errors = %d, want 0 after recovery", st.ConsecutiveErrors)
	}
	if _, ok := series.Latest(); !ok {
		t.Error("series lost its buffered data")
	}
}

func TestRunnerGivesUpOnPermanentError(t *testing.T) {
	series, _ := buffer.NewSeries("orderbook", 8, 0)
	stream := &scriptedStream{results: []error{
		errors.New("wrapped: " + provider.ErrPermanent.Error()),
	}}
	// Use a properly wrapped error rather than a lookalike string.
	stream.results[0] = errors.Join(provider.ErrPermanent, errors.New("bad credentials"))

	runner, err := New(series, stream, Options{
		MinBackoff:  time.Millisecond,
		MaxBackoff:  time.Millisecond,
		StableAfter: time.Hour,
	}, testLogger())
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	runErr := runner.Run(ctx)
	if !errors.Is(runErr, provider.ErrPermanent) {
		t.Fatalf("runner err = %v, want provider.ErrPermanent", runErr)
	}
	if got := stream.callCount(); got != 1 {
		t.Errorf("connection attempts = %d, want 1 (no retry on permanent errors)", got)
	}
	if st := series.Status(); st.Errors != 1 {
		t.Errorf("errors = %d, want 1", st.Errors)
	}
}

func TestRunnerPublishesIntoSeries(t *testing.T) {
	series, _ := buffer.NewSeries("orderbook", 8, 0)
	stream := &scriptedStream{results: []error{nil}}

	runner, _ := New(series, stream, Options{}, testLogger())

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	_ = runner.Run(ctx)

	sample, ok := series.Latest()
	if !ok {
		t.Fatal("nothing published")
	}
	if sample.Value != 0 {
		t.Errorf("value = %v, want 0", sample.Value)
	}
}

func TestBackoffGrowsAndIsCapped(t *testing.T) {
	series, _ := buffer.NewSeries("orderbook", 4, 0)
	runner, err := New(series, &scriptedStream{}, Options{
		MinBackoff: 100 * time.Millisecond,
		MaxBackoff: time.Second,
	}, testLogger())
	if err != nil {
		t.Fatal(err)
	}

	// Jitter is +/-20%, so compare against the bounds rather than exact values.
	first := runner.backoff(0)
	if first < 80*time.Millisecond || first > 120*time.Millisecond {
		t.Errorf("attempt 0 backoff = %v, want ~100ms", first)
	}
	third := runner.backoff(2)
	if third < 320*time.Millisecond || third > 480*time.Millisecond {
		t.Errorf("attempt 2 backoff = %v, want ~400ms", third)
	}
	for _, attempt := range []int{10, 20, 100} {
		if got := runner.backoff(attempt); got > 1200*time.Millisecond {
			t.Errorf("attempt %d backoff = %v, want capped at ~1s", attempt, got)
		}
	}
}

func TestNewValidatesArguments(t *testing.T) {
	series, _ := buffer.NewSeries("orderbook", 4, 0)
	if _, err := New(nil, &scriptedStream{}, Options{}, testLogger()); err == nil {
		t.Error("want error for nil series")
	}
	if _, err := New(series, nil, Options{}, testLogger()); err == nil {
		t.Error("want error for nil stream")
	}
}

func TestManagerRejectsDuplicates(t *testing.T) {
	series, _ := buffer.NewSeries("orderbook", 4, 0)
	r1, _ := New(series, &scriptedStream{}, Options{}, testLogger())
	r2, _ := New(series, &scriptedStream{}, Options{}, testLogger())

	m := NewManager()
	if err := m.Add(r1); err != nil {
		t.Fatal(err)
	}
	if err := m.Add(r2); err == nil {
		t.Error("want error when registering the same series twice")
	}
	if m.Len() != 1 {
		t.Errorf("len = %d, want 1", m.Len())
	}
}
