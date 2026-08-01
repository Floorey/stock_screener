// Package streamer supervises push-based data sources. It is the streaming
// counterpart to internal/poller: same contract towards the buffer, but the
// upstream decides when a datapoint exists.
package streamer

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"math/rand"
	"sync"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// Options tunes the reconnect behaviour.
type Options struct {
	// MinBackoff is the delay after the first failed connection.
	MinBackoff time.Duration
	// MaxBackoff caps the exponential growth.
	MaxBackoff time.Duration
	// StableAfter is how long a connection must hold before the backoff is
	// considered recovered and reset to MinBackoff.
	StableAfter time.Duration
}

func (o *Options) applyDefaults() {
	if o.MinBackoff <= 0 {
		o.MinBackoff = time.Second
	}
	if o.MaxBackoff < o.MinBackoff {
		o.MaxBackoff = 2 * time.Minute
	}
	if o.StableAfter <= 0 {
		o.StableAfter = 30 * time.Second
	}
}

// Runner keeps one Streamer connected and feeds its output into a Series.
type Runner struct {
	series *buffer.Series
	stream provider.Streamer
	opts   Options
	log    *slog.Logger
	rr     *rand.Rand
}

// New creates a runner. series and stream are required.
func New(series *buffer.Series, stream provider.Streamer, opts Options, log *slog.Logger) (*Runner, error) {
	if series == nil {
		return nil, errors.New("streamer: series must not be nil")
	}
	if stream == nil {
		return nil, fmt.Errorf("streamer %s: stream must not be nil", series.Name())
	}
	if log == nil {
		log = slog.Default()
	}
	opts.applyDefaults()

	return &Runner{
		series: series,
		stream: stream,
		opts:   opts,
		log:    log.With("series", series.Name()),
		rr:     rand.New(rand.NewSource(time.Now().UnixNano())),
	}, nil
}

// Name returns the series name this runner feeds.
func (r *Runner) Name() string { return r.series.Name() }

// Run connects and reconnects until ctx is cancelled. It returns an error only
// when the upstream is permanently broken (bad credentials, missing
// entitlement); in that case the series keeps its last valid data and is marked
// failed, but the service stays up.
func (r *Runner) Run(ctx context.Context) error {
	r.log.Info("stream runner started")
	defer r.log.Info("stream runner stopped")

	attempt := 0
	for {
		if ctx.Err() != nil {
			return nil
		}

		connectedAt := time.Now()
		err := r.stream.Run(ctx, r.emit)
		uptime := time.Since(connectedAt)

		if ctx.Err() != nil {
			return nil // shutdown, not a failure
		}

		switch {
		case err == nil:
			// Clean disconnect: upstream closed the connection.
			r.log.Warn("stream closed by upstream, reconnecting", "uptime", uptime)
		case errors.Is(err, provider.ErrPermanent):
			r.series.Fail(err)
			r.log.Error("stream failed permanently, giving up", "err", err)
			return err
		default:
			r.series.Fail(err)
			r.log.Warn("stream error, reconnecting",
				"err", err,
				"uptime", uptime,
				"consecutive_errors", r.series.ConsecutiveErrors())
		}

		// A connection that held long enough counts as healthy, so a nightly
		// disconnect does not inherit yesterday's backoff.
		if uptime >= r.opts.StableAfter {
			attempt = 0
		}

		delay := r.backoff(attempt)
		attempt++
		r.log.Info("reconnecting", "in", delay, "attempt", attempt)

		select {
		case <-ctx.Done():
			return nil
		case <-time.After(delay):
		}
	}
}

// emit publishes one datapoint. Publish clears the error streak, so a
// reconnected stream marks the series healthy again on its first message.
func (r *Runner) emit(value any, ts time.Time) {
	if value == nil {
		return
	}
	r.series.Publish(value, ts)
}

// backoff returns the delay before reconnect attempt n (0-based), with jitter
// so multiple streams do not retry in lockstep.
func (r *Runner) backoff(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	factor := math.Pow(2, float64(min(attempt, 16)))
	delay := time.Duration(float64(r.opts.MinBackoff) * factor)
	if delay > r.opts.MaxBackoff || delay <= 0 {
		delay = r.opts.MaxBackoff
	}
	// +/- 20% jitter
	jitter := 1 + (r.rr.Float64()*0.4 - 0.2)
	return time.Duration(float64(delay) * jitter)
}

// Manager owns all stream runners and their lifecycle. It mirrors
// poller.Manager so main.go treats both source kinds the same way.
type Manager struct {
	mu      sync.RWMutex
	runners map[string]*Runner
	wg      sync.WaitGroup
}

// NewManager returns an empty manager.
func NewManager() *Manager {
	return &Manager{runners: make(map[string]*Runner)}
}

// Add registers a runner under its series name.
func (m *Manager) Add(r *Runner) error {
	if r == nil {
		return errors.New("streamer: cannot add nil runner")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.runners[r.Name()]; exists {
		return fmt.Errorf("streamer: %s already registered", r.Name())
	}
	m.runners[r.Name()] = r
	return nil
}

// Len reports how many runners are registered.
func (m *Manager) Len() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.runners)
}

// Start runs every registered runner in its own goroutine.
func (m *Manager) Start(ctx context.Context) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	for _, r := range m.runners {
		r := r
		m.wg.Add(1)
		go func() {
			defer m.wg.Done()
			if err := r.Run(ctx); err != nil {
				// Logged, not fatal: one dead feed must not stop the service.
				r.log.Error("stream runner exited", "err", err)
			}
		}()
	}
}

// Wait blocks until all runners have returned.
func (m *Manager) Wait() { m.wg.Wait() }
