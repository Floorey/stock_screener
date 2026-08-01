package alpaca

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/provider"
	"github.com/gorilla/websocket"
)

// fakeStreamServer plays the Alpaca websocket protocol. behave receives the
// upgraded connection after the greeting has been sent.
func fakeStreamServer(t *testing.T, behave func(t *testing.T, conn *websocket.Conn)) string {
	t.Helper()

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
			return
		}
		defer conn.Close()

		if err := conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"success","msg":"connected"}]`)); err != nil {
			return
		}
		behave(t, conn)
	}))
	t.Cleanup(srv.Close)

	return "ws" + strings.TrimPrefix(srv.URL, "http")
}

func newTestStream(url string, symbols []string, crypto bool) *Stream {
	return &Stream{
		url:     url,
		keyID:   "key",
		secret:  "secret",
		symbols: symbols,
		crypto:  crypto,
		log:     discardLogger(),
	}
}

// readAction reads one client frame and returns the decoded action message.
func readAction(t *testing.T, conn *websocket.Conn) map[string]any {
	t.Helper()
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("read action: %v", err)
	}
	var msg map[string]any
	if err := json.Unmarshal(data, &msg); err != nil {
		t.Fatalf("decode action: %v", err)
	}
	return msg
}

func TestStreamHandshakeAndQuote(t *testing.T) {
	url := fakeStreamServer(t, func(t *testing.T, conn *websocket.Conn) {
		auth := readAction(t, conn)
		if auth["action"] != "auth" || auth["key"] != "key" || auth["secret"] != "secret" {
			t.Errorf("unexpected auth message: %v", auth)
		}
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"success","msg":"authenticated"}]`))

		sub := readAction(t, conn)
		if sub["action"] != "subscribe" {
			t.Errorf("unexpected subscribe message: %v", sub)
		}
		// Equities subscribe to quotes, not orderbooks.
		if _, ok := sub["quotes"]; !ok {
			t.Errorf("want quotes subscription, got %v", sub)
		}
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"subscription","quotes":["SPY"]}]`))

		_ = conn.WriteMessage(websocket.TextMessage, []byte(`[
			{"T":"q","S":"SPY","bp":439.5,"bs":2,"ap":439.55,"as":3,"t":"2026-07-31T15:30:00Z"}
		]`))
		// Give the client time to process, then hang up.
		time.Sleep(100 * time.Millisecond)
	})

	s := newTestStream(url, []string{"SPY"}, false)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	books := make(chan provider.Orderbook, 4)
	_ = s.Run(ctx, func(value any, ts time.Time) {
		if b, ok := value.(provider.Orderbook); ok {
			books <- b
		}
	})

	select {
	case book := <-books:
		if book.Symbol != "SPY" {
			t.Errorf("symbol = %q", book.Symbol)
		}
		if len(book.Bids) != 1 || book.Bids[0].Price != 439.5 || book.Bids[0].Size != 2 {
			t.Errorf("unexpected bids: %+v", book.Bids)
		}
		if len(book.Asks) != 1 || book.Asks[0].Price != 439.55 {
			t.Errorf("unexpected asks: %+v", book.Asks)
		}
	default:
		t.Fatal("no orderbook emitted")
	}
}

func TestStreamCryptoOrderbookDepth(t *testing.T) {
	url := fakeStreamServer(t, func(t *testing.T, conn *websocket.Conn) {
		readAction(t, conn)
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"success","msg":"authenticated"}]`))

		sub := readAction(t, conn)
		if _, ok := sub["orderbooks"]; !ok {
			t.Errorf("crypto must subscribe to orderbooks, got %v", sub)
		}
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"subscription","orderbooks":["BTC/USD"]}]`))

		_ = conn.WriteMessage(websocket.TextMessage, []byte(`[
			{"T":"o","S":"BTC/USD","t":"2026-07-31T15:30:00Z",
			 "b":[{"p":60000,"s":1.5},{"p":59999,"s":2}],
			 "a":[{"p":60001,"s":1.1}]}
		]`))
		time.Sleep(100 * time.Millisecond)
	})

	s := newTestStream(url, []string{"BTC/USD"}, true)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	books := make(chan provider.Orderbook, 4)
	_ = s.Run(ctx, func(value any, ts time.Time) {
		if b, ok := value.(provider.Orderbook); ok {
			books <- b
		}
	})

	select {
	case book := <-books:
		if len(book.Bids) != 2 || len(book.Asks) != 1 {
			t.Fatalf("depth not preserved: %+v", book)
		}
		if book.Bids[1].Price != 59999 || book.Bids[1].Size != 2 {
			t.Errorf("unexpected second bid level: %+v", book.Bids[1])
		}
	default:
		t.Fatal("no orderbook emitted")
	}
}

func TestStreamAuthFailureIsPermanent(t *testing.T) {
	url := fakeStreamServer(t, func(t *testing.T, conn *websocket.Conn) {
		readAction(t, conn)
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"error","code":402,"msg":"auth failed"}]`))
		time.Sleep(50 * time.Millisecond)
	})

	s := newTestStream(url, []string{"SPY"}, false)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := s.Run(ctx, func(any, time.Time) {})
	if !errors.Is(err, provider.ErrPermanent) {
		t.Fatalf("err = %v, want provider.ErrPermanent", err)
	}
}

func TestStreamConnectionLimitIsRetryable(t *testing.T) {
	url := fakeStreamServer(t, func(t *testing.T, conn *websocket.Conn) {
		readAction(t, conn)
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"error","code":406,"msg":"connection limit exceeded"}]`))
		time.Sleep(50 * time.Millisecond)
	})

	s := newTestStream(url, []string{"SPY"}, false)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := s.Run(ctx, func(any, time.Time) {})
	if err == nil {
		t.Fatal("want an error")
	}
	// Another process holding the single allowed connection is temporary.
	if errors.Is(err, provider.ErrPermanent) {
		t.Fatalf("406 must stay retryable, got %v", err)
	}
}

func TestStreamStopsOnContextCancel(t *testing.T) {
	url := fakeStreamServer(t, func(t *testing.T, conn *websocket.Conn) {
		readAction(t, conn)
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"success","msg":"authenticated"}]`))
		readAction(t, conn)
		_ = conn.WriteMessage(websocket.TextMessage,
			[]byte(`[{"T":"subscription","quotes":["SPY"]}]`))
		// Then stay silent until the client goes away.
		time.Sleep(3 * time.Second)
	})

	s := newTestStream(url, []string{"SPY"}, false)
	ctx, cancel := context.WithCancel(context.Background())

	done := make(chan error, 1)
	go func() { done <- s.Run(ctx, func(any, time.Time) {}) }()

	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("cancellation must not be reported as an error: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Run did not return after context cancellation")
	}
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func TestStreamRejectsNilEmit(t *testing.T) {
	s := newTestStream("ws://example.invalid", []string{"SPY"}, false)
	if err := s.Run(context.Background(), nil); err == nil {
		t.Fatal("want error for nil emit callback")
	}
}
