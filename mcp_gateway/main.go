// Command mcp_gateway exposes this project's mobile_api.py REST endpoints as
// MCP tools, so any MCP client (Claude, Gemini CLI, a design agent building a
// landing page, etc.) can call them without knowing the REST shape.
//
// It does not reimplement the Alpaca/screener/watchlist business logic: every
// tool is a thin proxy that calls mobile_api.py over HTTP. mobile_api.py stays
// the single source of truth; this binary only translates MCP <-> REST.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

type config struct {
	mobileAPIBaseURL string
	mobileAPIKey     string
	gatewayKey       string
}

var (
	cfg        config
	httpClient = &http.Client{Timeout: 15 * time.Second}
)

func main() {
	transport := flag.String("transport", "stdio", "MCP transport: stdio or http")
	addr := flag.String("addr", ":8090", "listen address for http transport")
	flag.Parse()

	loadDotEnv(".env")
	loadDotEnv("../.env")

	cfg = config{
		mobileAPIBaseURL: getenv("MOBILE_API_BASE_URL", "http://localhost:8000"),
		mobileAPIKey:     os.Getenv("MOBILE_API_KEY"),
		gatewayKey:       os.Getenv("MCP_GATEWAY_KEY"),
	}
	if cfg.mobileAPIKey == "" {
		log.Println("warning: MOBILE_API_KEY is not set - every proxied call to mobile_api.py will get a 503")
	}

	mcpServer := buildMCPServer()

	switch *transport {
	case "stdio":
		log.Println("mcp_gateway: serving MCP over stdio")
		if err := server.ServeStdio(mcpServer); err != nil {
			log.Fatalf("stdio server error: %v", err)
		}
	case "http":
		runHTTP(mcpServer, *addr)
	default:
		log.Fatalf("unknown --transport %q (want stdio or http)", *transport)
	}
}

func runHTTP(mcpServer *server.MCPServer, addr string) {
	if cfg.gatewayKey == "" {
		log.Println("warning: MCP_GATEWAY_KEY is not set - the http transport is unauthenticated, do not expose it beyond localhost")
	}

	streamable := server.NewStreamableHTTPServer(mcpServer)

	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Logger(), gin.Recovery())

	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "mobile_api_base_url": cfg.mobileAPIBaseURL})
	})

	mcpGroup := router.Group("/mcp")
	mcpGroup.Use(requireGatewayKey())
	mcpGroup.Any("", gin.WrapH(streamable))

	log.Printf("mcp_gateway: serving MCP over streamable HTTP on %s (endpoint /mcp)", addr)
	if err := router.Run(addr); err != nil {
		log.Fatalf("http server error: %v", err)
	}
}

// requireGatewayKey is Gin middleware gating the /mcp endpoint behind the same
// shared-secret pattern mobile_api.py uses for X-API-Key: skipped (open) only
// when MCP_GATEWAY_KEY was never configured, matching a local/dev default.
func requireGatewayKey() gin.HandlerFunc {
	return func(c *gin.Context) {
		if cfg.gatewayKey == "" {
			c.Next()
			return
		}
		if c.GetHeader("X-API-Key") != cfg.gatewayKey {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "invalid or missing X-API-Key header"})
			return
		}
		c.Next()
	}
}

func buildMCPServer() *server.MCPServer {
	s := server.NewMCPServer(
		"Falcone Capital Terminal",
		"1.0.0",
		server.WithToolCapabilities(true),
	)

	s.AddTool(mcp.NewTool("get_health",
		mcp.WithDescription("Check whether mobile_api.py is reachable and whether Alpaca is configured."),
	), toolProxy("GET", "/health", nil))

	s.AddTool(mcp.NewTool("get_account",
		mcp.WithDescription("Get the Alpaca account: cash, buying power, equity, status."),
	), toolProxy("GET", "/account", nil))

	s.AddTool(mcp.NewTool("get_positions",
		mcp.WithDescription("List currently open portfolio positions."),
	), toolProxy("GET", "/positions", nil))

	s.AddTool(mcp.NewTool("get_orders",
		mcp.WithDescription("List currently open/pending orders."),
	), toolProxy("GET", "/orders", nil))

	s.AddTool(mcp.NewTool("place_order",
		mcp.WithDescription("Place an order on Alpaca."),
		mcp.WithString("symbol", mcp.Required(), mcp.Description("Ticker symbol, e.g. AAPL")),
		mcp.WithNumber("qty", mcp.Required(), mcp.Description("Quantity to buy/sell")),
		mcp.WithString("side", mcp.Required(), mcp.Description("buy or sell")),
		mcp.WithString("order_type", mcp.DefaultString("market"), mcp.Description("market, limit, stop, or stop_limit")),
		mcp.WithNumber("limit_price", mcp.Description("Required if order_type is limit or stop_limit")),
		mcp.WithString("time_in_force", mcp.DefaultString("gtc"), mcp.Description("day, gtc, opg, cls, ioc, or fok")),
	), placeOrderHandler)

	s.AddTool(mcp.NewTool("cancel_order",
		mcp.WithDescription("Cancel an open order by id."),
		mcp.WithString("order_id", mcp.Required()),
	), func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		id, err := req.RequireString("order_id")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}
		return proxyCall(ctx, "DELETE", "/orders/"+id, nil), nil
	})

	s.AddTool(mcp.NewTool("get_watchlist",
		mcp.WithDescription("List tickers currently on the watchlist."),
	), toolProxy("GET", "/watchlist", nil))

	s.AddTool(mcp.NewTool("add_to_watchlist",
		mcp.WithDescription("Add a ticker to the watchlist."),
		mcp.WithString("ticker", mcp.Required()),
	), func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		ticker, err := req.RequireString("ticker")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}
		return proxyCall(ctx, "POST", "/watchlist", map[string]string{"ticker": ticker}), nil
	})

	s.AddTool(mcp.NewTool("remove_from_watchlist",
		mcp.WithDescription("Remove a ticker from the watchlist."),
		mcp.WithString("ticker", mcp.Required()),
	), func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		ticker, err := req.RequireString("ticker")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}
		return proxyCall(ctx, "DELETE", "/watchlist/"+ticker, nil), nil
	})

	s.AddTool(mcp.NewTool("get_screener",
		mcp.WithDescription("Get the top-N cached fundamental screener results, ranked by Long or Short score. Useful for pulling real portfolio/market data into a landing page, report, or dashboard mockup."),
		mcp.WithString("side", mcp.DefaultString("long"), mcp.Description("long or short")),
		mcp.WithNumber("limit", mcp.DefaultNumber(20), mcp.Description("max results, 1-200")),
	), func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		side := req.GetString("side", "long")
		limit := req.GetInt("limit", 20)
		path := fmt.Sprintf("/screener?side=%s&limit=%d", side, limit)
		return proxyCall(ctx, "GET", path, nil), nil
	})

	return s
}

// toolProxy builds a handler for tools that take no arguments.
func toolProxy(method, path string, body any) server.ToolHandlerFunc {
	return func(ctx context.Context, _ mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		return proxyCall(ctx, method, path, body), nil
	}
}

func placeOrderHandler(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	symbol, err := req.RequireString("symbol")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	qty, err := req.RequireFloat("qty")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	side, err := req.RequireString("side")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	body := map[string]any{
		"symbol":        symbol,
		"qty":           qty,
		"side":          side,
		"order_type":    req.GetString("order_type", "market"),
		"time_in_force": req.GetString("time_in_force", "gtc"),
	}
	if lp := req.GetFloat("limit_price", 0); lp != 0 {
		body["limit_price"] = lp
	}
	return proxyCall(ctx, "POST", "/orders", body), nil
}

// proxyCall calls mobile_api.py and turns the response into an MCP tool
// result. It never returns a Go error for a well-formed HTTP error response -
// those become NewToolResultError so the calling agent sees the reason
// instead of a transport-level failure.
func proxyCall(ctx context.Context, method, path string, body any) *mcp.CallToolResult {
	data, status, err := callAPI(ctx, method, path, body)
	if err != nil {
		return mcp.NewToolResultErrorf("could not reach mobile_api.py at %s: %v", cfg.mobileAPIBaseURL, err)
	}
	if status >= 400 {
		return mcp.NewToolResultErrorf("mobile_api.py returned %d: %s", status, string(data))
	}
	return mcp.NewToolResultText(string(data))
}

func callAPI(ctx context.Context, method, path string, body any) ([]byte, int, error) {
	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, 0, err
		}
		reader = bytes.NewReader(b)
	}

	req, err := http.NewRequestWithContext(ctx, method, cfg.mobileAPIBaseURL+path, reader)
	if err != nil {
		return nil, 0, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("X-API-Key", cfg.mobileAPIKey)

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, err
	}
	return data, resp.StatusCode, nil
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// loadDotEnv is a minimal KEY=VALUE .env reader (no external dependency) that
// only sets variables not already present in the environment, mirroring
// python-dotenv's default behavior so a real exported env var always wins.
func loadDotEnv(path string) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return
	}
	f, err := os.Open(abs)
	if err != nil {
		return
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		if _, exists := os.LookupEnv(key); !exists {
			os.Setenv(key, value)
		}
	}
}
