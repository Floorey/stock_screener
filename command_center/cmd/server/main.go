// Command server runs the trading command center backend.
//
// MVP stage: HTTP server + buffered polling system. The websocket push layer,
// the embedded terminal and the frontend follow on top of these primitives.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/config"
	"github.com/Floorey/stock_screener/command_center/internal/httpapi"
	"github.com/Floorey/stock_screener/command_center/internal/poller"
	"github.com/Floorey/stock_screener/command_center/internal/provider"
	"github.com/Floorey/stock_screener/command_center/internal/provider/mock"
)

func main() {
	if err := run(); err != nil {
		slog.Error("fatal", "err", err)
		os.Exit(1)
	}
}

func run() error {
	configPath := flag.String("config", "", "path to JSON config file (optional)")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		return fmt.Errorf("config: %w", err)
	}

	log := newLogger(cfg.LogLevel)
	slog.SetDefault(log)

	store := buffer.NewStore()
	pollers := poller.NewManager()

	if err := wireSeries(cfg, store, pollers, log); err != nil {
		return err
	}

	api, err := httpapi.NewServer(store, pollers, log)
	if err != nil {
		return fmt.Errorf("http api: %w", err)
	}

	srv := &http.Server{
		Addr:              cfg.Addr,
		Handler:           api.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
	}

	// Signal-aware root context: everything below shuts down with it.
	ctx, stop := signal.NotifyContext(context.Background(),
		os.Interrupt, syscall.SIGTERM)
	defer stop()

	pollers.Start(ctx)

	errCh := make(chan error, 1)
	go func() {
		log.Info("http server listening", "addr", cfg.Addr, "provider", cfg.Provider)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("listen: %w", err)
			return
		}
		errCh <- nil
	}()

	select {
	case err := <-errCh:
		if err != nil {
			return err
		}
	case <-ctx.Done():
		log.Info("shutdown signal received")
	}

	shutdownCtx, cancel := context.WithTimeout(
		context.Background(), cfg.ShutdownTimeout.Duration)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Error("http shutdown", "err", err)
	}
	stop()
	pollers.Wait()
	log.Info("stopped cleanly")
	return nil
}

// wireSeries builds one buffer.Series (and, in poll mode, one poller) per
// configured and enabled data source.
func wireSeries(cfg config.Config, store *buffer.Store, pollers *poller.Manager, log *slog.Logger) error {
	balanceSrc, bookSrc, err := buildProvider(cfg, log)
	if err != nil {
		return err
	}

	for name, sc := range cfg.Series {
		if !sc.Enabled {
			log.Info("series disabled", "series", name)
			continue
		}

		series, err := buffer.NewSeries(name, sc.Capacity, sc.Interval.Duration)
		if err != nil {
			return fmt.Errorf("series %s: %w", name, err)
		}
		if err := store.Register(series); err != nil {
			return err
		}

		if sc.Mode == "stream" {
			// Streaming sources are attached in the websocket stage; the buffer
			// already exists so consumers can subscribe today.
			log.Info("series registered in stream mode (no poller)", "series", name)
			continue
		}

		fetcher, err := fetcherFor(name, sc, balanceSrc, bookSrc)
		if err != nil {
			return err
		}

		p, err := poller.New(series, fetcher, poller.Options{
			Interval:   sc.Interval.Duration,
			Timeout:    sc.FetchTimeout(),
			MaxBackoff: 2 * time.Minute,
		}, log)
		if err != nil {
			return err
		}
		if err := pollers.Add(p); err != nil {
			return err
		}
	}

	if len(store.Names()) == 0 {
		return errors.New("no series enabled")
	}
	return nil
}

func buildProvider(cfg config.Config, log *slog.Logger) (provider.BalanceSource, provider.OrderbookSource, error) {
	switch cfg.Provider {
	case "mock":
		m := mock.New(0)
		log.Info("using mock provider (no broker credentials required)")
		return m, m, nil
	case "alpaca":
		// Implemented in the next step (endpoint by endpoint).
		return nil, nil, errors.New("provider alpaca: not implemented yet, use provider=mock")
	default:
		return nil, nil, fmt.Errorf("unknown provider %q", cfg.Provider)
	}
}

// fetcherFor maps a series name to the provider call that feeds it.
func fetcherFor(name string, sc config.SeriesConfig, balanceSrc provider.BalanceSource, bookSrc provider.OrderbookSource) (provider.Fetcher, error) {
	switch name {
	case config.SeriesBalance:
		if balanceSrc == nil {
			return nil, errors.New("series balance: provider has no balance source")
		}
		return provider.FetchFunc(func(ctx context.Context) (any, error) {
			return balanceSrc.Balance(ctx)
		}), nil

	case config.SeriesOrderbook:
		if bookSrc == nil {
			return nil, errors.New("series orderbook: provider has no orderbook source")
		}
		if len(sc.Symbols) == 0 {
			return nil, errors.New("series orderbook: at least one symbol required")
		}
		// MVP: one symbol per series. Multi-symbol becomes one series per symbol.
		symbol := sc.Symbols[0]
		return provider.FetchFunc(func(ctx context.Context) (any, error) {
			return bookSrc.Orderbook(ctx, symbol)
		}), nil

	default:
		return nil, fmt.Errorf("series %s: no fetcher mapping", name)
	}
}

func newLogger(level string) *slog.Logger {
	var lvl slog.Level
	switch level {
	case "debug":
		lvl = slog.LevelDebug
	case "warn":
		lvl = slog.LevelWarn
	case "error":
		lvl = slog.LevelError
	default:
		lvl = slog.LevelInfo
	}
	return slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: lvl}))
}
