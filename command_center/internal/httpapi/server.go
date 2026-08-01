// Package httpapi exposes the buffered data over REST. Read paths serve from
// the in-memory buffer only — a browser request never reaches a broker API.
package httpapi

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/Floorey/stock_screener/command_center/internal/buffer"
	"github.com/Floorey/stock_screener/command_center/internal/poller"
)

// Server holds the dependencies of the HTTP layer.
type Server struct {
	store   *buffer.Store
	pollers *poller.Manager
	log     *slog.Logger
	started time.Time
}

// NewServer wires the HTTP layer. store is required; pollers may be nil if no
// pull-based source is configured.
func NewServer(store *buffer.Store, pollers *poller.Manager, log *slog.Logger) (*Server, error) {
	if store == nil {
		return nil, errors.New("httpapi: store must not be nil")
	}
	if log == nil {
		log = slog.Default()
	}
	return &Server{store: store, pollers: pollers, log: log, started: time.Now()}, nil
}

// Handler returns the root handler with all routes and middleware applied.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("GET /api/series", s.handleSeriesList)
	mux.HandleFunc("GET /api/series/{name}/latest", s.handleLatest)
	mux.HandleFunc("GET /api/series/{name}/history", s.handleHistory)
	mux.HandleFunc("POST /api/series/{name}/refresh", s.handleRefresh)

	return s.recoverPanic(s.logRequests(mux))
}

type errorBody struct {
	Error string `json:"error"`
}

func writeJSON(w http.ResponseWriter, log *slog.Logger, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		// Response is already partially written; only logging is left.
		log.Error("encode response", "err", err)
	}
}

func (s *Server) writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, s.log, status, errorBody{Error: err.Error()})
}

// series resolves the {name} path value, writing a 404 if unknown.
func (s *Server) series(w http.ResponseWriter, r *http.Request) (*buffer.Series, bool) {
	name := r.PathValue("name")
	series, err := s.store.Get(name)
	if err != nil {
		s.writeError(w, http.StatusNotFound, err)
		return nil, false
	}
	return series, true
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	statuses := s.store.Statuses()
	degraded := make([]string, 0)
	for _, st := range statuses {
		if st.Stale || st.ConsecutiveErrors > 0 {
			degraded = append(degraded, st.Name)
		}
	}
	status := "ok"
	if len(degraded) > 0 {
		status = "degraded"
	}
	writeJSON(w, s.log, http.StatusOK, map[string]any{
		"status":   status,
		"uptime":   time.Since(s.started).Round(time.Second).String(),
		"series":   len(statuses),
		"degraded": degraded,
		"time":     time.Now().UTC(),
	})
}

func (s *Server) handleSeriesList(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, s.log, http.StatusOK, map[string]any{
		"series": s.store.Statuses(),
	})
}

func (s *Server) handleLatest(w http.ResponseWriter, r *http.Request) {
	series, ok := s.series(w, r)
	if !ok {
		return
	}
	sample, ok := series.Latest()
	if !ok {
		s.writeError(w, http.StatusServiceUnavailable,
			errors.New("no data buffered yet for "+series.Name()))
		return
	}
	writeJSON(w, s.log, http.StatusOK, map[string]any{
		"series": series.Name(),
		"status": series.Status(),
		"sample": sample,
	})
}

func (s *Server) handleHistory(w http.ResponseWriter, r *http.Request) {
	series, ok := s.series(w, r)
	if !ok {
		return
	}

	q := r.URL.Query()
	var samples []buffer.Sample

	if raw := q.Get("since"); raw != "" {
		since, err := strconv.ParseUint(raw, 10, 64)
		if err != nil {
			s.writeError(w, http.StatusBadRequest,
				errors.New("invalid since parameter: "+raw))
			return
		}
		samples = series.Since(since)
	} else {
		n := 0 // 0 = everything buffered
		if raw := q.Get("n"); raw != "" {
			parsed, err := strconv.Atoi(raw)
			if err != nil || parsed < 0 {
				s.writeError(w, http.StatusBadRequest,
					errors.New("invalid n parameter: "+raw))
				return
			}
			n = parsed
		}
		samples = series.History(n)
	}

	writeJSON(w, s.log, http.StatusOK, map[string]any{
		"series":  series.Name(),
		"status":  series.Status(),
		"count":   len(samples),
		"samples": samples,
	})
}

// handleRefresh is a control command: force one out-of-band poll.
func (s *Server) handleRefresh(w http.ResponseWriter, r *http.Request) {
	series, ok := s.series(w, r)
	if !ok {
		return
	}
	if s.pollers == nil {
		s.writeError(w, http.StatusNotImplemented,
			errors.New("no poller manager configured"))
		return
	}

	err := s.pollers.Trigger(series.Name())
	switch {
	case errors.Is(err, poller.ErrBusy):
		// Not an error condition for the caller: a refresh is already on its way.
		writeJSON(w, s.log, http.StatusAccepted, map[string]any{
			"series": series.Name(),
			"queued": false,
			"note":   "refresh already pending",
		})
	case err != nil:
		s.writeError(w, http.StatusBadRequest, err)
	default:
		writeJSON(w, s.log, http.StatusAccepted, map[string]any{
			"series": series.Name(),
			"queued": true,
		})
	}
}
