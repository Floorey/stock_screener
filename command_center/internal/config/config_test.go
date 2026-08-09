package config

import (
	"strings"
	"testing"
)

func TestMetricsAreEnabledByDefault(t *testing.T) {
	cfg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.Metrics.Enabled {
		t.Error("metrics should be on by default")
	}
	if cfg.Metrics.Path != "/metrics" {
		t.Errorf("path = %q, want /metrics", cfg.Metrics.Path)
	}
}

func TestMetricsEnvOverrides(t *testing.T) {
	t.Setenv("CC_METRICS_ENABLED", "false")
	t.Setenv("CC_METRICS_PATH", "/internal/prom")

	cfg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Metrics.Enabled {
		t.Error("CC_METRICS_ENABLED=false was ignored")
	}
	if cfg.Metrics.Path != "/internal/prom" {
		t.Errorf("path = %q, want /internal/prom", cfg.Metrics.Path)
	}
}

// A typo in an env var must stop the server, not silently leave metrics on.
func TestMalformedMetricsEnvIsRejected(t *testing.T) {
	t.Setenv("CC_METRICS_ENABLED", "yes-please")

	if _, err := Load(""); err == nil {
		t.Fatal("expected an error for an unparsable CC_METRICS_ENABLED")
	}
}

func TestMetricsPathIsValidated(t *testing.T) {
	cases := map[string]string{
		"metrics":         "must start with",
		"/api/metrics":    "collides",
		"/api/series/foo": "collides",
	}
	for path, want := range cases {
		cfg := Default()
		cfg.Metrics.Path = path
		err := cfg.Validate()
		if err == nil {
			t.Errorf("path %q was accepted, want an error", path)
			continue
		}
		if !strings.Contains(err.Error(), want) {
			t.Errorf("path %q: error %q does not mention %q", path, err, want)
		}
	}
}

// A disabled endpoint has no path to validate.
func TestMetricsPathIgnoredWhenDisabled(t *testing.T) {
	cfg := Default()
	cfg.Metrics.Enabled = false
	cfg.Metrics.Path = "nonsense"

	if err := cfg.Validate(); err != nil {
		t.Errorf("disabled metrics should not be validated: %v", err)
	}
}
