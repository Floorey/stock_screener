// Package poller drives the buffered data sources. It is the only component
// that talks to broker APIs on a schedule; the frontend never does. One poller
// per series, each with its own interval, timeout and error backoff.
package poller

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"sync"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// ErrBusy is returned by a manual trigger when a refresh is already queued.
var ErrBusy = errors.New("poller: refresh already pending")

// ErrNoPoller is returned when a series has no poller — typically because it is
// fed by a stream, where "refresh" has no meaning.
var ErrNoPoller = errors.New("poller: series is not polled")

// Options configures a single poller.
type Options struct {
	Interval time.Duration
	Timeout  time.Duration
	// MaxBackoff caps the exponential backoff applied after consecutive
	// errors. Zero disables backoff. Keeping this above the rate limit window
	// is what protects us from hammering a failing API.
	MaxBackoff time.Duration
}

// Poller periodically calls a Fetcher and publishes the result into a Series.
type Poller struct {
	series  *buffer.Series
	fetcher provider.Fetcher
	opts    Options
	log     *slog.Logger

	trigger chan struct{} // buffered(1): manual refresh request
}

// New creates a poller. All arguments are required.
func New(series *buffer.Series, fetcher provider.Fetcher, opts Options, log *slog.Logger) (*Poller, error) {
	if series == nil {
		return nil, errors.New("poller: series must not be nil")
	}
	if fetcher == nil {
		return nil, fmt.Errorf("poller %s: fetcher must not be nil", series.Name())
	}
	if opts.Interval <= 0 {
		return nil, fmt.Errorf("poller %s: interval must be > 0", series.Name())
	}
	if opts.Timeout <= 0 {
		opts.Timeout = opts.Interval
	}
	if log == nil {
		log = slog.Default()
	}
	return &Poller{
		series:  series,
		fetcher: fetcher,
		opts:    opts,
		log:     log.With("series", series.Name()),
		trigger: make(chan struct{}, 1),
	}, nil
}

// Name returns the series name this poller feeds.
func (p *Poller) Name() string { return p.series.Name() }

// Trigger requests an immediate out-of-band refresh (REST control command).
// It returns ErrBusy if one is already queued — the request is never allowed to
// stack up into an API burst.
func (p *Poller) Trigger() error {
	select {
	case p.trigger <- struct{}{}:
		return nil
	default:
		return ErrBusy
	}
}

// Run polls until ctx is cancelled. It always returns nil: a data source going
// down degrades one tile of the dashboard, it must not take the service with
// it. Errors are logged and recorded on the series; the buffer keeps its last
// valid state.
func (p *Poller) Run(ctx context.Context) error {
	p.log.Info("poller started",
		"interval", p.opts.Interval, "timeout", p.opts.Timeout)
	defer p.log.Info("poller stopped")

	// First fetch immediately so the dashboard has data on connect.
	p.pollOnce(ctx)

	timer := time.NewTimer(p.nextDelay())
	defer timer.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-p.trigger:
			p.log.Debug("manual refresh")
			p.pollOnce(ctx)
		case <-timer.C:
			p.pollOnce(ctx)
		}

		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		timer.Reset(p.nextDelay())
	}
}

// nextDelay returns the interval, extended by exponential backoff while the
// source is failing.
func (p *Poller) nextDelay() time.Duration {
	streak := p.series.ConsecutiveErrors()
	if streak == 0 || p.opts.MaxBackoff <= 0 {
		return p.opts.Interval
	}
	// 2^(streak-1) * interval, capped.
	factor := math.Pow(2, float64(min(streak, 16)-1))
	delay := time.Duration(float64(p.opts.Interval) * factor)
	if delay > p.opts.MaxBackoff {
		delay = p.opts.MaxBackoff
	}
	if delay < p.opts.Interval {
		delay = p.opts.Interval
	}
	return delay
}

func (p *Poller) pollOnce(ctx context.Context) {
	fetchCtx, cancel := context.WithTimeout(ctx, p.opts.Timeout)
	defer cancel()

	started := time.Now()
	value, err := p.fetcher.Fetch(fetchCtx)
	if err != nil {
		if ctx.Err() != nil {
			return // shutting down, not a data source problem
		}
		p.series.Fail(err)
		p.log.Warn("fetch failed",
			"err", err,
			"consecutive_errors", p.series.ConsecutiveErrors(),
			"took", time.Since(started))
		return
	}
	if value == nil {
		p.series.Fail(errors.New("fetcher returned nil value"))
		p.log.Warn("fetch returned nil value")
		return
	}

	sample := p.series.Publish(value, time.Now().UTC())
	p.log.Debug("published", "seq", sample.Seq, "took", time.Since(started))
}

// Manager owns all pollers and their lifecycle.
type Manager struct {
	mu      sync.RWMutex
	pollers map[string]*Poller
	wg      sync.WaitGroup
}

// NewManager returns an empty manager.
func NewManager() *Manager {
	return &Manager{pollers: make(map[string]*Poller)}
}

// Add registers a poller under its series name.
func (m *Manager) Add(p *Poller) error {
	if p == nil {
		return errors.New("poller: cannot add nil poller")
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.pollers[p.Name()]; exists {
		return fmt.Errorf("poller: %s already registered", p.Name())
	}
	m.pollers[p.Name()] = p
	return nil
}

// Start runs every registered poller in its own goroutine.
func (m *Manager) Start(ctx context.Context) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	for _, p := range m.pollers {
		p := p
		m.wg.Add(1)
		go func() {
			defer m.wg.Done()
			if err := p.Run(ctx); err != nil {
				p.log.Error("poller exited with error", "err", err)
			}
		}()
	}
}

// Wait blocks until all pollers have returned (after ctx cancellation).
func (m *Manager) Wait() { m.wg.Wait() }

// Trigger forces a refresh of one series.
func (m *Manager) Trigger(name string) error {
	m.mu.RLock()
	p, ok := m.pollers[name]
	m.mu.RUnlock()

	if !ok {
		return fmt.Errorf("%w: %s", ErrNoPoller, name)
	}
	return p.Trigger()
}
