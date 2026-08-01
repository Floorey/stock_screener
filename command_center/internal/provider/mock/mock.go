// Package mock is a synthetic data source so the dashboard runs end to end
// without broker credentials. It is deterministic per instance (seeded) and
// deliberately injects occasional failures so error handling and the "buffer
// keeps last valid state" behaviour are exercised during development.
package mock

import (
	"context"
	"errors"
	"math"
	"math/rand"
	"sync"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// Provider implements provider.BalanceSource and provider.OrderbookSource.
type Provider struct {
	mu sync.Mutex
	rr *rand.Rand

	equity float64
	cash   float64
	start  float64
	price  map[string]float64

	// FailureRate is the probability [0,1) that a call returns an error.
	FailureRate float64
}

// New returns a mock provider seeded with seed. seed == 0 uses the wall clock.
func New(seed int64) *Provider {
	if seed == 0 {
		seed = time.Now().UnixNano()
	}
	const startEquity = 100_000.0
	return &Provider{
		rr:          rand.New(rand.NewSource(seed)),
		equity:      startEquity,
		cash:        startEquity * 0.35,
		start:       startEquity,
		price:       map[string]float64{},
		FailureRate: 0.02,
	}
}

var errSimulated = errors.New("mock: simulated upstream failure")

func (p *Provider) shouldFail() bool {
	return p.FailureRate > 0 && p.rr.Float64() < p.FailureRate
}

// Balance returns a random-walking account snapshot.
func (p *Provider) Balance(ctx context.Context) (provider.Balance, error) {
	if err := ctx.Err(); err != nil {
		return provider.Balance{}, err
	}
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.shouldFail() {
		return provider.Balance{}, errSimulated
	}

	p.equity *= 1 + p.rr.NormFloat64()*0.0009
	p.cash *= 1 + p.rr.NormFloat64()*0.0002

	return provider.Balance{
		Equity:      round2(p.equity),
		Cash:        round2(p.cash),
		BuyingPower: round2(p.cash * 4),
		PnLDay:      round2(p.equity - p.start),
		Currency:    "USD",
		Account:     "MOCK-PAPER",
		Ts:          time.Now().UTC(),
	}, nil
}

// Orderbook returns a synthetic depth snapshot around a random-walking mid.
func (p *Provider) Orderbook(ctx context.Context, symbol string) (provider.Orderbook, error) {
	if err := ctx.Err(); err != nil {
		return provider.Orderbook{}, err
	}
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.shouldFail() {
		return provider.Orderbook{}, errSimulated
	}
	return p.buildBook(symbol), nil
}

// buildBook advances the synthetic mid and renders a book. Caller holds the lock.
func (p *Provider) buildBook(symbol string) provider.Orderbook {
	mid, ok := p.price[symbol]
	if !ok {
		mid = 400 + p.rr.Float64()*100
	}
	mid *= 1 + p.rr.NormFloat64()*0.0004
	p.price[symbol] = mid

	const depth = 10
	tick := math.Max(0.01, math.Round(mid*0.00002*100)/100)

	book := provider.Orderbook{
		Symbol: symbol,
		Bids:   make([]provider.Level, 0, depth),
		Asks:   make([]provider.Level, 0, depth),
		Ts:     time.Now().UTC(),
	}
	for i := 0; i < depth; i++ {
		off := tick * float64(i+1)
		book.Bids = append(book.Bids, provider.Level{
			Price: round2(mid - off),
			Size:  math.Round(50 + p.rr.Float64()*450),
		})
		book.Asks = append(book.Asks, provider.Level{
			Price: round2(mid + off),
			Size:  math.Round(50 + p.rr.Float64()*450),
		})
	}
	return book
}

func round2(v float64) float64 { return math.Round(v*100) / 100 }

// OrderbookStream returns a synthetic push source, so "mode": "stream" can be
// exercised end to end without broker credentials.
func (p *Provider) OrderbookStream(symbols []string) (provider.Streamer, error) {
	if len(symbols) == 0 {
		return nil, errors.New("mock: at least one symbol is required for streaming")
	}
	return &stream{
		provider: p,
		symbols:  append([]string(nil), symbols...),
		interval: 250 * time.Millisecond,
	}, nil
}

// stream emits synthetic orderbook updates on a fixed cadence.
type stream struct {
	provider *Provider
	symbols  []string
	interval time.Duration
}

// Run implements provider.Streamer.
func (s *stream) Run(ctx context.Context, emit func(value any, ts time.Time)) error {
	if emit == nil {
		return errors.New("mock: emit callback must not be nil")
	}
	ticker := time.NewTicker(s.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			// No failure injection here: a dropped connection is the
			// interesting failure mode for a stream, and that is covered by
			// the runner's reconnect test rather than by random noise.
			for _, symbol := range s.symbols {
				s.provider.mu.Lock()
				book := s.provider.buildBook(symbol)
				s.provider.mu.Unlock()
				emit(book, book.Ts)
			}
		}
	}
}
