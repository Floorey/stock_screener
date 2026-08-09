// Package alpaca implements the broker interfaces against the Alpaca API.
//
// Balance comes from the trading REST API on a low-frequency poll. The
// orderbook is served by the market data websocket (see stream.go) so the
// high-frequency side costs no REST calls at all; the REST orderbook here
// exists only as a fallback for setups where streaming is not available.
package alpaca

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/provider"
)

// Errors returned by the client. ErrAuth and ErrForbidden are permanent — no
// amount of retrying fixes wrong credentials — while ErrRateLimited is the
// signal to back off.
var (
	ErrAuth        = errors.New("alpaca: authentication failed")
	ErrForbidden   = errors.New("alpaca: forbidden (check account entitlements)")
	ErrRateLimited = errors.New("alpaca: rate limited")
)

// Config holds everything the client needs. Credentials come from the
// environment via internal/config and are never logged.
type Config struct {
	KeyID     string
	SecretKey string
	// BaseURL is the trading API root, e.g. https://paper-api.alpaca.markets.
	BaseURL string
	// DataURL is the market data REST root, e.g. https://data.alpaca.markets.
	DataURL string
	// StreamURL is the market data websocket root,
	// e.g. wss://stream.data.alpaca.markets.
	StreamURL string
	// Feed is the equity data feed: "iex" (free) or "sip" (paid).
	Feed string
	// Timeout bounds a single REST call.
	Timeout time.Duration
}

// Client talks to the Alpaca REST APIs.
type Client struct {
	cfg  Config
	http *http.Client
}

// NewClient validates the configuration and returns a client.
func NewClient(cfg Config) (*Client, error) {
	if cfg.KeyID == "" || cfg.SecretKey == "" {
		return nil, errors.New("alpaca: API key and secret are required")
	}
	if cfg.BaseURL == "" {
		return nil, errors.New("alpaca: base URL is required")
	}
	if cfg.DataURL == "" {
		return nil, errors.New("alpaca: data URL is required")
	}
	if cfg.Feed == "" {
		cfg.Feed = "iex"
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 10 * time.Second
	}
	cfg.BaseURL = strings.TrimRight(cfg.BaseURL, "/")
	cfg.DataURL = strings.TrimRight(cfg.DataURL, "/")
	cfg.StreamURL = strings.TrimRight(cfg.StreamURL, "/")

	return &Client{
		cfg:  cfg,
		http: &http.Client{Timeout: cfg.Timeout},
	}, nil
}

// APIError carries the HTTP status and a bounded snippet of the response body,
// so a failing call is diagnosable from the log without leaking credentials.
type APIError struct {
	StatusCode int
	Endpoint   string
	Body       string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("alpaca: %s returned %d: %s", e.Endpoint, e.StatusCode, e.Body)
}

// Unwrap maps HTTP statuses onto the sentinel errors above so callers can use
// errors.Is instead of comparing status codes.
func (e *APIError) Unwrap() error {
	switch e.StatusCode {
	case http.StatusUnauthorized:
		return ErrAuth
	case http.StatusForbidden:
		return ErrForbidden
	case http.StatusTooManyRequests:
		return ErrRateLimited
	default:
		return nil
	}
}

// get performs an authenticated GET and decodes the JSON body into out.
func (c *Client) get(ctx context.Context, endpoint string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return fmt.Errorf("alpaca: build request: %w", err)
	}
	req.Header.Set("APCA-API-KEY-ID", c.cfg.KeyID)
	req.Header.Set("APCA-API-SECRET-KEY", c.cfg.SecretKey)
	req.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("alpaca: request failed: %w", err)
	}
	defer resp.Body.Close()

	// Bound the read: a broken proxy must not be able to exhaust our memory.
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return fmt.Errorf("alpaca: read response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return &APIError{
			StatusCode: resp.StatusCode,
			Endpoint:   redactPath(endpoint),
			Body:       snippet(body),
		}
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("alpaca: decode %s: %w", redactPath(endpoint), err)
	}
	return nil
}

func snippet(body []byte) string {
	const max = 300
	s := strings.TrimSpace(string(body))
	if len(s) > max {
		s = s[:max] + "..."
	}
	return s
}

// redactPath strips the query string, which can carry symbols but also any
// future token parameters.
func redactPath(endpoint string) string {
	if i := strings.IndexByte(endpoint, '?'); i >= 0 {
		return endpoint[:i]
	}
	return endpoint
}

// number accepts both JSON numbers and the quoted numbers the trading API
// returns for money fields ("100000.00").
type number float64

func (n *number) UnmarshalJSON(data []byte) error {
	s := strings.Trim(string(data), `"`)
	if s == "" || s == "null" {
		*n = 0
		return nil
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return fmt.Errorf("invalid number %s: %w", string(data), err)
	}
	*n = number(v)
	return nil
}

type accountResponse struct {
	AccountNumber string `json:"account_number"`
	Currency      string `json:"currency"`
	Status        string `json:"status"`
	Cash          number `json:"cash"`
	Equity        number `json:"equity"`
	LastEquity    number `json:"last_equity"`
	BuyingPower   number `json:"buying_power"`
}

// Balance fetches the account snapshot. This is the low-frequency endpoint:
// at the default 15s interval it uses 4 of Alpaca's 200 requests per minute.
func (c *Client) Balance(ctx context.Context) (provider.Balance, error) {
	var acct accountResponse
	if err := c.get(ctx, c.cfg.BaseURL+"/v2/account", &acct); err != nil {
		return provider.Balance{}, err
	}
	if acct.Status != "" && acct.Status != "ACTIVE" {
		// Not fatal — report the numbers but make the state visible in the log.
		// A restricted account still has an equity worth showing.
		return provider.Balance{
			Equity:      float64(acct.Equity),
			Cash:        float64(acct.Cash),
			BuyingPower: float64(acct.BuyingPower),
			PnLDay:      float64(acct.Equity - acct.LastEquity),
			Currency:    acct.Currency,
			Account:     acct.AccountNumber + " (" + acct.Status + ")",
			Ts:          time.Now().UTC(),
		}, nil
	}

	return provider.Balance{
		Equity:      float64(acct.Equity),
		Cash:        float64(acct.Cash),
		BuyingPower: float64(acct.BuyingPower),
		// Alpaca has no day-PnL field; equity minus previous close is the
		// standard derivation.
		PnLDay:   float64(acct.Equity - acct.LastEquity),
		Currency: acct.Currency,
		Account:  acct.AccountNumber,
		Ts:       time.Now().UTC(),
	}, nil
}

type stockQuoteResponse struct {
	Symbol string `json:"symbol"`
	Quote  struct {
		Ts       time.Time `json:"t"`
		BidPrice number    `json:"bp"`
		BidSize  number    `json:"bs"`
		AskPrice number    `json:"ap"`
		AskSize  number    `json:"as"`
	} `json:"quote"`
}

type cryptoOrderbookResponse struct {
	Orderbooks map[string]struct {
		Ts   time.Time `json:"t"`
		Bids []struct {
			Price number `json:"p"`
			Size  number `json:"s"`
		} `json:"b"`
		Asks []struct {
			Price number `json:"p"`
			Size  number `json:"s"`
		} `json:"a"`
	} `json:"orderbooks"`
}

// IsCrypto reports whether a symbol uses the crypto pair notation (BTC/USD).
func IsCrypto(symbol string) bool { return strings.Contains(symbol, "/") }

// Orderbook fetches a book snapshot over REST. Prefer the websocket stream for
// this series — this call exists for setups without streaming and burns one
// request per poll.
//
// For US equities Alpaca's REST exposes top of book only, so the result has a
// single level per side. Crypto returns real depth.
func (c *Client) Orderbook(ctx context.Context, symbol string) (provider.Orderbook, error) {
	if symbol == "" {
		return provider.Orderbook{}, errors.New("alpaca: symbol must not be empty")
	}

	if IsCrypto(symbol) {
		endpoint := fmt.Sprintf("%s/v1beta3/crypto/us/latest/orderbooks?symbols=%s",
			c.cfg.DataURL, url.QueryEscape(symbol))

		var resp cryptoOrderbookResponse
		if err := c.get(ctx, endpoint, &resp); err != nil {
			return provider.Orderbook{}, err
		}
		book, ok := resp.Orderbooks[symbol]
		if !ok {
			return provider.Orderbook{}, fmt.Errorf("alpaca: no orderbook returned for %s", symbol)
		}

		out := provider.Orderbook{
			Symbol: symbol,
			Bids:   make([]provider.Level, 0, len(book.Bids)),
			Asks:   make([]provider.Level, 0, len(book.Asks)),
			Ts:     book.Ts.UTC(),
		}
		for _, l := range book.Bids {
			out.Bids = append(out.Bids, provider.Level{Price: float64(l.Price), Size: float64(l.Size)})
		}
		for _, l := range book.Asks {
			out.Asks = append(out.Asks, provider.Level{Price: float64(l.Price), Size: float64(l.Size)})
		}
		return out, nil
	}

	endpoint := fmt.Sprintf("%s/v2/stocks/%s/quotes/latest?feed=%s",
		c.cfg.DataURL, url.PathEscape(symbol), url.QueryEscape(c.cfg.Feed))

	var resp stockQuoteResponse
	if err := c.get(ctx, endpoint, &resp); err != nil {
		return provider.Orderbook{}, err
	}
	if resp.Quote.BidPrice == 0 && resp.Quote.AskPrice == 0 {
		return provider.Orderbook{}, fmt.Errorf("alpaca: empty quote for %s", symbol)
	}

	return quoteToBook(symbol, resp.Quote.Ts,
		float64(resp.Quote.BidPrice), float64(resp.Quote.BidSize),
		float64(resp.Quote.AskPrice), float64(resp.Quote.AskSize)), nil
}

// quoteToBook turns a top-of-book quote into a one-level orderbook.
//
// Note on sizes: US equity quote sizes are reported in round lots (1 = 100
// shares); they are passed through unchanged so the frontend shows what the
// feed says.
func quoteToBook(symbol string, ts time.Time, bidPrice, bidSize, askPrice, askSize float64) provider.Orderbook {
	book := provider.Orderbook{
		Symbol: symbol,
		Bids:   make([]provider.Level, 0, 1),
		Asks:   make([]provider.Level, 0, 1),
		Ts:     ts.UTC(),
	}
	if book.Ts.IsZero() {
		book.Ts = time.Now().UTC()
	}
	if bidPrice > 0 {
		book.Bids = append(book.Bids, provider.Level{Price: bidPrice, Size: bidSize})
	}
	if askPrice > 0 {
		book.Asks = append(book.Asks, provider.Level{Price: askPrice, Size: askSize})
	}
	return book
}
