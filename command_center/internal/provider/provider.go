// Package provider defines the broker-facing interfaces and the payload types
// that end up in the ring buffers. Adding a broker means implementing these
// interfaces — nothing above this layer knows about Alpaca or any other API.
package provider

import (
	"context"
	"time"
)

// Balance is the account snapshot shown in the header of the dashboard.
type Balance struct {
	Equity      float64   `json:"equity"`
	Cash        float64   `json:"cash"`
	BuyingPower float64   `json:"buying_power"`
	PnLDay      float64   `json:"pnl_day"`
	Currency    string    `json:"currency"`
	Account     string    `json:"account,omitempty"`
	Ts          time.Time `json:"ts"`
}

// Level is one price level of the orderbook.
type Level struct {
	Price float64 `json:"price"`
	Size  float64 `json:"size"`
}

// Orderbook is a top-of-book / depth snapshot for one symbol.
type Orderbook struct {
	Symbol string    `json:"symbol"`
	Bids   []Level   `json:"bids"` // descending by price
	Asks   []Level   `json:"asks"` // ascending by price
	Ts     time.Time `json:"ts"`
}

// Mid returns the mid price. ok is false when either side is empty.
func (o Orderbook) Mid() (float64, bool) {
	if len(o.Bids) == 0 || len(o.Asks) == 0 {
		return 0, false
	}
	return (o.Bids[0].Price + o.Asks[0].Price) / 2, true
}

// Spread returns the absolute top-of-book spread. ok is false when either side
// is empty.
func (o Orderbook) Spread() (float64, bool) {
	if len(o.Bids) == 0 || len(o.Asks) == 0 {
		return 0, false
	}
	return o.Asks[0].Price - o.Bids[0].Price, true
}

// Fetcher is a pull-based data source; one call, one datapoint. Implementations
// return (value, error) and never panic on API failures.
type Fetcher interface {
	// Fetch returns the current value of the series. The returned value is
	// stored in the ring buffer as-is.
	Fetch(ctx context.Context) (any, error)
}

// FetchFunc adapts a function to Fetcher.
type FetchFunc func(ctx context.Context) (any, error)

// Fetch implements Fetcher.
func (f FetchFunc) Fetch(ctx context.Context) (any, error) { return f(ctx) }

// Streamer is a push-based data source (broker websocket). Run blocks until ctx
// is cancelled or an unrecoverable error occurs; every received datapoint is
// handed to emit. Used to bypass REST rate limits entirely where the broker
// supports it.
type Streamer interface {
	Run(ctx context.Context, emit func(value any, ts time.Time)) error
}

// BalanceSource provides account balance snapshots.
type BalanceSource interface {
	Balance(ctx context.Context) (Balance, error)
}

// OrderbookSource provides orderbook snapshots for a symbol.
type OrderbookSource interface {
	Orderbook(ctx context.Context, symbol string) (Orderbook, error)
}
