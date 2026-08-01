package alpaca

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func testClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)

	c, err := NewClient(Config{
		KeyID:     "key",
		SecretKey: "secret",
		BaseURL:   srv.URL,
		DataURL:   srv.URL,
		StreamURL: "wss://example.invalid",
		Feed:      "iex",
		Timeout:   5 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestNewClientRequiresCredentials(t *testing.T) {
	if _, err := NewClient(Config{BaseURL: "x", DataURL: "y"}); err == nil {
		t.Fatal("want error for missing credentials")
	}
}

func TestBalanceParsesStringNumbers(t *testing.T) {
	var gotKey, gotSecret, gotPath string
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("APCA-API-KEY-ID")
		gotSecret = r.Header.Get("APCA-API-SECRET-KEY")
		gotPath = r.URL.Path
		w.Write([]byte(`{
			"account_number": "PA123",
			"currency": "USD",
			"status": "ACTIVE",
			"cash": "12345.67",
			"equity": "100500.25",
			"last_equity": "100000.00",
			"buying_power": "49382.68"
		}`))
	}))

	bal, err := c.Balance(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	if gotPath != "/v2/account" {
		t.Errorf("path = %q, want /v2/account", gotPath)
	}
	if gotKey != "key" || gotSecret != "secret" {
		t.Errorf("credentials not sent: key=%q secret=%q", gotKey, gotSecret)
	}
	if bal.Equity != 100500.25 || bal.Cash != 12345.67 || bal.BuyingPower != 49382.68 {
		t.Errorf("unexpected balance: %+v", bal)
	}
	// Day PnL is derived: equity - last_equity.
	if diff := bal.PnLDay - 500.25; diff > 0.001 || diff < -0.001 {
		t.Errorf("pnl_day = %v, want 500.25", bal.PnLDay)
	}
	if bal.Currency != "USD" || bal.Account != "PA123" {
		t.Errorf("unexpected metadata: %+v", bal)
	}
}

func TestBalanceMarksNonActiveAccount(t *testing.T) {
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"account_number":"PA1","status":"ACCOUNT_UPDATED","equity":"10","last_equity":"10"}`))
	}))

	bal, err := c.Balance(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if bal.Account != "PA1 (ACCOUNT_UPDATED)" {
		t.Errorf("account = %q, want the status appended", bal.Account)
	}
}

func TestErrorStatusesMapToSentinels(t *testing.T) {
	cases := []struct {
		status int
		want   error
	}{
		{http.StatusUnauthorized, ErrAuth},
		{http.StatusForbidden, ErrForbidden},
		{http.StatusTooManyRequests, ErrRateLimited},
	}

	for _, tc := range cases {
		status := tc.status
		c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			w.Write([]byte(`{"message":"nope"}`))
		}))

		_, err := c.Balance(context.Background())
		if !errors.Is(err, tc.want) {
			t.Errorf("status %d: err = %v, want %v", status, err, tc.want)
		}

		var apiErr *APIError
		if !errors.As(err, &apiErr) || apiErr.StatusCode != status {
			t.Errorf("status %d: want APIError with that status, got %v", status, err)
		}
	}
}

func TestServerErrorIsNotPermanent(t *testing.T) {
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))

	_, err := c.Balance(context.Background())
	if err == nil {
		t.Fatal("want error")
	}
	// A 500 must stay retryable — it maps to no sentinel.
	if errors.Is(err, ErrAuth) || errors.Is(err, ErrForbidden) {
		t.Errorf("500 must not map to a permanent error: %v", err)
	}
}

func TestOrderbookFromStockQuote(t *testing.T) {
	var gotPath, gotFeed string
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotFeed = r.URL.Query().Get("feed")
		w.Write([]byte(`{"symbol":"SPY","quote":{
			"t":"2026-07-31T15:30:00.123456789Z",
			"bp":439.5,"bs":2,"ap":439.55,"as":3
		}}`))
	}))

	book, err := c.Orderbook(context.Background(), "SPY")
	if err != nil {
		t.Fatal(err)
	}
	if gotPath != "/v2/stocks/SPY/quotes/latest" {
		t.Errorf("path = %q", gotPath)
	}
	if gotFeed != "iex" {
		t.Errorf("feed = %q, want iex", gotFeed)
	}
	if len(book.Bids) != 1 || len(book.Asks) != 1 {
		t.Fatalf("want one level per side, got %+v", book)
	}
	if book.Bids[0].Price != 439.5 || book.Asks[0].Price != 439.55 {
		t.Errorf("unexpected prices: %+v", book)
	}
	if spread, ok := book.Spread(); !ok || spread < 0.049 || spread > 0.051 {
		t.Errorf("spread = %v (ok=%v), want ~0.05", spread, ok)
	}
	if book.Ts.IsZero() {
		t.Error("timestamp not parsed")
	}
}

func TestOrderbookRejectsEmptyQuote(t *testing.T) {
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"symbol":"SPY","quote":{"bp":0,"ap":0}}`))
	}))

	if _, err := c.Orderbook(context.Background(), "SPY"); err == nil {
		t.Fatal("want error for an empty quote")
	}
}

func TestOrderbookCryptoHasDepth(t *testing.T) {
	var gotPath string
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		w.Write([]byte(`{"orderbooks":{"BTC/USD":{
			"t":"2026-07-31T15:30:00Z",
			"b":[{"p":60000,"s":1.5},{"p":59999,"s":2}],
			"a":[{"p":60001,"s":1.1},{"p":60002,"s":3}]
		}}}`))
	}))

	book, err := c.Orderbook(context.Background(), "BTC/USD")
	if err != nil {
		t.Fatal(err)
	}
	if gotPath != "/v1beta3/crypto/us/latest/orderbooks" {
		t.Errorf("path = %q, want the crypto endpoint", gotPath)
	}
	if len(book.Bids) != 2 || len(book.Asks) != 2 {
		t.Fatalf("want two levels per side, got %+v", book)
	}
	if mid, ok := book.Mid(); !ok || mid != 60000.5 {
		t.Errorf("mid = %v (ok=%v), want 60000.5", mid, ok)
	}
}

func TestOrderbookStreamRejectsMixedSymbols(t *testing.T) {
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))

	if _, err := c.OrderbookStream([]string{"SPY", "BTC/USD"}); err == nil {
		t.Fatal("want error when mixing equity and crypto symbols")
	}
	if _, err := c.OrderbookStream(nil); err == nil {
		t.Fatal("want error for empty symbol list")
	}
}

func TestStreamEndpointDependsOnAssetClass(t *testing.T) {
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))

	stocks, err := c.OrderbookStream([]string{"SPY"})
	if err != nil {
		t.Fatal(err)
	}
	if got := stocks.(*Stream).url; got != "wss://example.invalid/v2/iex" {
		t.Errorf("stocks endpoint = %q", got)
	}

	crypto, err := c.OrderbookStream([]string{"BTC/USD"})
	if err != nil {
		t.Fatal(err)
	}
	if got := crypto.(*Stream).url; got != "wss://example.invalid/v1beta3/crypto/us" {
		t.Errorf("crypto endpoint = %q", got)
	}
}
