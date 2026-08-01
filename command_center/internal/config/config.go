// Package config loads the command center configuration from a JSON file with
// environment overrides for secrets. Every problem is reported as an error —
// the server refuses to start on a bad config instead of guessing.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

// Series names known to the system.
const (
	SeriesBalance   = "balance"
	SeriesOrderbook = "orderbook"
)

// Duration wraps time.Duration so intervals can be written as "5s" in JSON.
type Duration struct {
	time.Duration
}

// UnmarshalJSON parses either a duration string ("2s") or a number of seconds.
func (d *Duration) UnmarshalJSON(data []byte) error {
	var raw any
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	switch v := raw.(type) {
	case string:
		parsed, err := time.ParseDuration(v)
		if err != nil {
			return fmt.Errorf("invalid duration %q: %w", v, err)
		}
		d.Duration = parsed
	case float64:
		d.Duration = time.Duration(v * float64(time.Second))
	default:
		return fmt.Errorf("invalid duration value %v", raw)
	}
	return nil
}

// MarshalJSON writes the duration back as a string.
func (d Duration) MarshalJSON() ([]byte, error) {
	return json.Marshal(d.Duration.String())
}

// SeriesConfig describes one buffered data source.
type SeriesConfig struct {
	// Enabled toggles the source without deleting its config.
	Enabled bool `json:"enabled"`
	// Interval is the poll cadence. Ignored when Mode is "stream".
	Interval Duration `json:"interval"`
	// Capacity is the number of samples kept in the ring buffer.
	Capacity int `json:"capacity"`
	// Mode is "poll" (default) or "stream" (source pushes, no polling).
	Mode string `json:"mode"`
	// Timeout bounds a single fetch. Defaults to min(Interval, 10s).
	Timeout Duration `json:"timeout"`
	// Symbols is used by market data series (orderbook).
	Symbols []string `json:"symbols"`
}

// Alpaca holds broker credentials. Values come from the environment, never
// from the config file.
type Alpaca struct {
	KeyID     string `json:"-"`
	SecretKey string `json:"-"`
	BaseURL   string `json:"base_url"`
	DataURL   string `json:"data_url"`
	// StreamURL is the market data websocket root.
	StreamURL string `json:"stream_url"`
	// Feed selects the equity data feed: "iex" (free) or "sip" (paid).
	Feed string `json:"feed"`
}

// Configured reports whether both credentials are present.
func (a Alpaca) Configured() bool {
	return a.KeyID != "" && a.SecretKey != ""
}

// Config is the full server configuration.
type Config struct {
	// Addr is the listen address, e.g. "127.0.0.1:8080".
	Addr string `json:"addr"`
	// Provider selects the data source: "mock" or "alpaca".
	Provider string `json:"provider"`
	// ShutdownTimeout bounds graceful shutdown.
	ShutdownTimeout Duration `json:"shutdown_timeout"`
	// LogLevel is one of debug, info, warn, error.
	LogLevel string `json:"log_level"`
	// Series is keyed by series name (balance, orderbook).
	Series map[string]SeriesConfig `json:"series"`
	// Alpaca holds broker settings; credentials are injected from env.
	Alpaca Alpaca `json:"alpaca"`
}

// Default returns a runnable configuration: mock provider, localhost only.
func Default() Config {
	return Config{
		Addr:            "127.0.0.1:8080",
		Provider:        "mock",
		ShutdownTimeout: Duration{10 * time.Second},
		LogLevel:        "info",
		Series: map[string]SeriesConfig{
			SeriesBalance: {
				Enabled:  true,
				Interval: Duration{15 * time.Second},
				Capacity: 720, // 3h at 15s
				Mode:     "poll",
			},
			SeriesOrderbook: {
				Enabled:  true,
				Interval: Duration{time.Second},
				Capacity: 1800, // 30min at 1s
				Mode:     "poll",
				Symbols:  []string{"SPY"},
			},
		},
		Alpaca: Alpaca{
			BaseURL:   "https://paper-api.alpaca.markets",
			DataURL:   "https://data.alpaca.markets",
			StreamURL: "wss://stream.data.alpaca.markets",
			Feed:      "iex",
		},
	}
}

// Load reads the config file at path on top of Default and applies environment
// overrides. An empty path means "defaults + env" only. A missing file at an
// explicitly given path is an error.
func Load(path string) (Config, error) {
	cfg := Default()

	if path != "" {
		data, err := os.ReadFile(path)
		if err != nil {
			return Config{}, fmt.Errorf("read config %s: %w", path, err)
		}
		if err := json.Unmarshal(data, &cfg); err != nil {
			return Config{}, fmt.Errorf("parse config %s: %w", path, err)
		}
	}

	applyEnv(&cfg)

	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func applyEnv(cfg *Config) {
	if v := os.Getenv("CC_ADDR"); v != "" {
		cfg.Addr = v
	}
	if v := os.Getenv("CC_PROVIDER"); v != "" {
		cfg.Provider = v
	}
	if v := os.Getenv("CC_LOG_LEVEL"); v != "" {
		cfg.LogLevel = v
	}
	// Credentials are env-only, matching the Python side of the repo.
	cfg.Alpaca.KeyID = strings.TrimSpace(os.Getenv("ALPACA_API_KEY"))
	cfg.Alpaca.SecretKey = strings.TrimSpace(os.Getenv("ALPACA_SECRET_KEY"))
	if v := strings.TrimSpace(os.Getenv("ALPACA_BASE_URL")); v != "" {
		cfg.Alpaca.BaseURL = strings.TrimRight(v, "/")
	}
	if v := strings.TrimSpace(os.Getenv("ALPACA_DATA_URL")); v != "" {
		cfg.Alpaca.DataURL = strings.TrimRight(v, "/")
	}
	if v := strings.TrimSpace(os.Getenv("ALPACA_STREAM_URL")); v != "" {
		cfg.Alpaca.StreamURL = strings.TrimRight(v, "/")
	}
	if v := strings.TrimSpace(os.Getenv("ALPACA_FEED")); v != "" {
		cfg.Alpaca.Feed = strings.ToLower(v)
	}
}

// Validate checks the configuration for contradictions.
func (c *Config) Validate() error {
	var errs []error

	if strings.TrimSpace(c.Addr) == "" {
		errs = append(errs, errors.New("addr must not be empty"))
	}
	switch c.Provider {
	case "mock", "alpaca":
	default:
		errs = append(errs, fmt.Errorf("unknown provider %q (want mock or alpaca)", c.Provider))
	}
	switch c.LogLevel {
	case "debug", "info", "warn", "error":
	default:
		errs = append(errs, fmt.Errorf("unknown log_level %q", c.LogLevel))
	}
	if c.ShutdownTimeout.Duration <= 0 {
		errs = append(errs, errors.New("shutdown_timeout must be > 0"))
	}
	if len(c.Series) == 0 {
		errs = append(errs, errors.New("no series configured"))
	}

	for name, sc := range c.Series {
		if !sc.Enabled {
			continue
		}
		if sc.Capacity <= 0 {
			errs = append(errs, fmt.Errorf("series %s: capacity must be > 0", name))
		}
		switch sc.Mode {
		case "", "poll":
			if sc.Interval.Duration <= 0 {
				errs = append(errs, fmt.Errorf("series %s: interval must be > 0 in poll mode", name))
			}
			if sc.Timeout.Duration < 0 {
				errs = append(errs, fmt.Errorf("series %s: timeout must not be negative", name))
			}
		case "stream":
			if len(sc.Symbols) == 0 {
				errs = append(errs, fmt.Errorf("series %s: stream mode requires at least one symbol", name))
			}
		default:
			errs = append(errs, fmt.Errorf("series %s: unknown mode %q (want poll or stream)", name, sc.Mode))
		}
	}

	if c.Provider == "alpaca" {
		if !c.Alpaca.Configured() {
			errs = append(errs, errors.New("provider alpaca requires ALPACA_API_KEY and ALPACA_SECRET_KEY"))
		}
		switch c.Alpaca.Feed {
		case "iex", "sip":
		default:
			errs = append(errs, fmt.Errorf("alpaca: unknown feed %q (want iex or sip)", c.Alpaca.Feed))
		}
		if c.Alpaca.StreamURL == "" && c.hasStreamSeries() {
			errs = append(errs, errors.New("alpaca: stream_url is required when a series uses stream mode"))
		}
	}

	return errors.Join(errs...)
}

// hasStreamSeries reports whether any enabled series is push-driven.
func (c *Config) hasStreamSeries() bool {
	for _, sc := range c.Series {
		if sc.Enabled && sc.Mode == "stream" {
			return true
		}
	}
	return false
}

// FetchTimeout returns the effective per-fetch timeout for a series.
func (sc SeriesConfig) FetchTimeout() time.Duration {
	if sc.Timeout.Duration > 0 {
		return sc.Timeout.Duration
	}
	const maxTimeout = 10 * time.Second
	if sc.Interval.Duration > 0 && sc.Interval.Duration < maxTimeout {
		return sc.Interval.Duration
	}
	return maxTimeout
}
