package alpaca

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/provider"
	"github.com/gorilla/websocket"
)

// Alpaca websocket error codes worth reacting to specifically.
// See https://docs.alpaca.markets/docs/real-time-stock-pricing-data
const (
	codeAuthFailed        = 402
	codeAuthTimeout       = 404
	codeConnectionLimit   = 406
	codeInsufficientSub   = 409
	codeInsufficientScope = 401
)

const (
	// handshakeTimeout bounds auth and subscribe round trips.
	handshakeTimeout = 15 * time.Second
	// readTimeout is how long we tolerate silence before assuming the
	// connection is dead. Alpaca pings well within this window.
	readTimeout = 60 * time.Second
	// writeTimeout bounds a single frame write.
	writeTimeout = 10 * time.Second
	// maxMessageSize caps a single frame (depth updates are small).
	maxMessageSize = 4 << 20
)

// Stream consumes the Alpaca market data websocket and emits provider.Orderbook
// values. One Run call is one connection lifecycle; reconnecting is the job of
// the supervisor in internal/streamer.
//
// Alpaca allows a single market data connection per account, which is why this
// is deliberately one connection for all subscribed symbols.
type Stream struct {
	url     string
	keyID   string
	secret  string
	symbols []string
	crypto  bool
	log     *slog.Logger
}

// OrderbookStream returns a Streamer for the given symbols. Symbols must be
// either all equities or all crypto pairs — the two live on different
// endpoints. Crypto delivers real depth, equities top of book.
func (c *Client) OrderbookStream(symbols []string) (provider.Streamer, error) {
	if len(symbols) == 0 {
		return nil, errors.New("alpaca: at least one symbol is required for streaming")
	}
	if c.cfg.StreamURL == "" {
		return nil, errors.New("alpaca: stream URL is required for streaming")
	}

	crypto := IsCrypto(symbols[0])
	for _, s := range symbols {
		if IsCrypto(s) != crypto {
			return nil, fmt.Errorf(
				"alpaca: cannot mix crypto and equity symbols in one stream (%v)", symbols)
		}
	}

	endpoint := c.cfg.StreamURL + "/v2/" + c.cfg.Feed
	if crypto {
		endpoint = c.cfg.StreamURL + "/v1beta3/crypto/us"
	}

	return &Stream{
		url:     endpoint,
		keyID:   c.cfg.KeyID,
		secret:  c.cfg.SecretKey,
		symbols: append([]string(nil), symbols...),
		crypto:  crypto,
		log:     slog.Default().With("stream", "alpaca", "endpoint", endpoint),
	}, nil
}

// SetLogger replaces the logger used by the stream.
func (s *Stream) SetLogger(log *slog.Logger) {
	if log != nil {
		s.log = log.With("stream", "alpaca", "endpoint", s.url)
	}
}

// wsEnvelope is the union of the message shapes Alpaca sends. Every frame is a
// JSON array of these; the T field discriminates.
type wsEnvelope struct {
	Type string `json:"T"`

	// control messages
	Msg  string `json:"msg"`
	Code int    `json:"code"`

	// data messages
	Symbol string    `json:"S"`
	Ts     time.Time `json:"t"`

	// quote (equities, crypto quotes)
	BidPrice float64 `json:"bp"`
	BidSize  float64 `json:"bs"`
	AskPrice float64 `json:"ap"`
	AskSize  float64 `json:"as"`

	// orderbook (crypto): full depth per side
	Bids  []wsLevel `json:"b"`
	Asks  []wsLevel `json:"a"`
	Reset bool      `json:"r"`
}

type wsLevel struct {
	Price float64 `json:"p"`
	Size  float64 `json:"s"`
}

// Run connects, authenticates, subscribes and pumps messages into emit until
// ctx is cancelled or the connection breaks. A returned error wrapping
// provider.ErrPermanent means reconnecting is pointless (bad credentials,
// missing entitlement).
func (s *Stream) Run(ctx context.Context, emit func(value any, ts time.Time)) error {
	if emit == nil {
		return errors.New("alpaca: emit callback must not be nil")
	}

	dialer := &websocket.Dialer{
		HandshakeTimeout: handshakeTimeout,
		Proxy:            http.ProxyFromEnvironment,
	}
	conn, resp, err := dialer.DialContext(ctx, s.url, nil)
	if err != nil {
		if resp != nil {
			// A handshake rejection carries the reason in the HTTP status.
			if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
				return fmt.Errorf("%w: websocket handshake rejected with %d",
					provider.ErrPermanent, resp.StatusCode)
			}
			return fmt.Errorf("alpaca: websocket dial failed with %d: %w", resp.StatusCode, err)
		}
		return fmt.Errorf("alpaca: websocket dial: %w", err)
	}
	defer conn.Close()

	conn.SetReadLimit(maxMessageSize)

	// Cancelling ctx unblocks the read loop by closing the connection.
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()

	if err := s.authenticate(conn); err != nil {
		return err
	}
	if err := s.subscribe(conn); err != nil {
		return err
	}
	s.log.Info("stream subscribed", "symbols", s.symbols, "crypto", s.crypto)

	return s.pump(ctx, conn, emit)
}

func (s *Stream) writeJSON(conn *websocket.Conn, v any) error {
	if err := conn.SetWriteDeadline(time.Now().Add(writeTimeout)); err != nil {
		return fmt.Errorf("alpaca: set write deadline: %w", err)
	}
	if err := conn.WriteJSON(v); err != nil {
		return fmt.Errorf("alpaca: write: %w", err)
	}
	return nil
}

// readEnvelopes reads one frame and decodes the message array.
func (s *Stream) readEnvelopes(conn *websocket.Conn, timeout time.Duration) ([]wsEnvelope, error) {
	if err := conn.SetReadDeadline(time.Now().Add(timeout)); err != nil {
		return nil, fmt.Errorf("alpaca: set read deadline: %w", err)
	}
	_, data, err := conn.ReadMessage()
	if err != nil {
		return nil, fmt.Errorf("alpaca: read: %w", err)
	}
	var msgs []wsEnvelope
	if err := json.Unmarshal(data, &msgs); err != nil {
		return nil, fmt.Errorf("alpaca: decode frame: %w", err)
	}
	return msgs, nil
}

// controlError turns an Alpaca error message into a Go error, marking the
// permanent ones so the supervisor stops retrying.
func controlError(m wsEnvelope) error {
	switch m.Code {
	case codeAuthFailed, codeInsufficientSub, codeInsufficientScope:
		return fmt.Errorf("%w: alpaca stream error %d: %s",
			provider.ErrPermanent, m.Code, m.Msg)
	case codeConnectionLimit:
		// Another process holds the single allowed connection. Retrying is
		// correct, just not quickly.
		return fmt.Errorf("alpaca: connection limit reached (%d): %s", m.Code, m.Msg)
	case codeAuthTimeout:
		return fmt.Errorf("alpaca: auth timeout (%d): %s", m.Code, m.Msg)
	default:
		return fmt.Errorf("alpaca: stream error %d: %s", m.Code, m.Msg)
	}
}

func (s *Stream) authenticate(conn *websocket.Conn) error {
	// The server greets with [{"T":"success","msg":"connected"}] first.
	greeting, err := s.readEnvelopes(conn, handshakeTimeout)
	if err != nil {
		return fmt.Errorf("alpaca: read greeting: %w", err)
	}
	for _, m := range greeting {
		if m.Type == "error" {
			return controlError(m)
		}
	}

	if err := s.writeJSON(conn, map[string]string{
		"action": "auth",
		"key":    s.keyID,
		"secret": s.secret,
	}); err != nil {
		return err
	}

	deadline := time.Now().Add(handshakeTimeout)
	for time.Now().Before(deadline) {
		msgs, err := s.readEnvelopes(conn, handshakeTimeout)
		if err != nil {
			return fmt.Errorf("alpaca: read auth response: %w", err)
		}
		for _, m := range msgs {
			switch {
			case m.Type == "error":
				return controlError(m)
			case m.Type == "success" && m.Msg == "authenticated":
				return nil
			}
		}
	}
	return errors.New("alpaca: timed out waiting for authentication")
}

func (s *Stream) subscribe(conn *websocket.Conn) error {
	req := map[string]any{"action": "subscribe"}
	if s.crypto {
		// Crypto exposes real depth on the orderbooks channel.
		req["orderbooks"] = s.symbols
	} else {
		// Equities: quotes are the top-of-book feed.
		req["quotes"] = s.symbols
	}
	if err := s.writeJSON(conn, req); err != nil {
		return err
	}

	deadline := time.Now().Add(handshakeTimeout)
	for time.Now().Before(deadline) {
		msgs, err := s.readEnvelopes(conn, handshakeTimeout)
		if err != nil {
			return fmt.Errorf("alpaca: read subscription response: %w", err)
		}
		for _, m := range msgs {
			switch m.Type {
			case "error":
				return controlError(m)
			case "subscription":
				return nil
			}
		}
	}
	return errors.New("alpaca: timed out waiting for subscription confirmation")
}

// pump is the steady-state read loop.
func (s *Stream) pump(ctx context.Context, conn *websocket.Conn, emit func(any, time.Time)) error {
	// Pings refresh the read deadline; gorilla answers them automatically.
	conn.SetPingHandler(func(appData string) error {
		_ = conn.SetReadDeadline(time.Now().Add(readTimeout))
		return conn.WriteControl(websocket.PongMessage,
			[]byte(appData), time.Now().Add(writeTimeout))
	})

	for {
		msgs, err := s.readEnvelopes(conn, readTimeout)
		if err != nil {
			if ctx.Err() != nil {
				return nil // shutting down
			}
			return err
		}

		for _, m := range msgs {
			switch m.Type {
			case "q": // quote (equities and crypto)
				if m.BidPrice == 0 && m.AskPrice == 0 {
					continue
				}
				book := quoteToBook(m.Symbol, m.Ts,
					m.BidPrice, m.BidSize, m.AskPrice, m.AskSize)
				emit(book, book.Ts)

			case "o": // crypto orderbook with depth
				book := provider.Orderbook{
					Symbol: m.Symbol,
					Bids:   make([]provider.Level, 0, len(m.Bids)),
					Asks:   make([]provider.Level, 0, len(m.Asks)),
					Ts:     m.Ts.UTC(),
				}
				for _, l := range m.Bids {
					book.Bids = append(book.Bids, provider.Level{Price: l.Price, Size: l.Size})
				}
				for _, l := range m.Asks {
					book.Asks = append(book.Asks, provider.Level{Price: l.Price, Size: l.Size})
				}
				if book.Ts.IsZero() {
					book.Ts = time.Now().UTC()
				}
				emit(book, book.Ts)

			case "error":
				return controlError(m)

			case "success", "subscription":
				s.log.Debug("stream control message", "msg", m.Msg)

			default:
				// Unknown channels (trades, bars, status) are ignored rather
				// than treated as errors — Alpaca adds message types over time.
				s.log.Debug("ignoring message type", "type", m.Type)
			}
		}
	}
}

// Describe returns a human readable description used in logs.
func (s *Stream) Describe() string {
	kind := "quotes"
	if s.crypto {
		kind = "orderbooks"
	}
	return fmt.Sprintf("alpaca %s [%s]", kind, strings.Join(s.symbols, ","))
}
