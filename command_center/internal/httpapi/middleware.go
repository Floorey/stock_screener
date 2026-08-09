package httpapi

import (
	"errors"
	"net/http"
	"runtime/debug"
	"strings"
	"time"
)

// statusRecorder captures the status code for request logging.
type statusRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(b []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	n, err := r.ResponseWriter.Write(b)
	r.bytes += n
	return n, err
}

func (s *Server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		rec := &statusRecorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)

		if rec.status == 0 {
			rec.status = http.StatusOK
		}
		s.log.Debug("http",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"bytes", rec.bytes,
			"took", time.Since(started))
	})
}

// recoverPanic keeps a bug in one handler from taking down the whole service.
func (s *Server) recoverPanic(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				if s.metrics != nil {
					s.metrics.HTTP().Panic()
				}
				s.log.Error("panic in handler",
					"path", r.URL.Path,
					"panic", rec,
					"stack", string(debug.Stack()))
				s.writeError(w, http.StatusInternalServerError,
					errors.New("internal server error"))
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// recordMetrics feeds the Prometheus collector. It sits outside recoverPanic so
// a recovered panic is already reflected as a 500 in the status recorder,
// instead of having to guess the outcome of a request that never returned.
func (s *Server) recordMetrics(next http.Handler) http.Handler {
	if s.metrics == nil {
		return next
	}
	stats := s.metrics.HTTP()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer stats.Begin()()

		started := time.Now()
		rec := &statusRecorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)

		status := rec.status
		if status == 0 {
			status = http.StatusOK
		}
		stats.Observe(r.Method, s.routeLabel(r.URL.Path), status,
			time.Since(started))
	})
}

// routeLabel maps a request path to the route pattern that served it. Using the
// raw path would let any client mint new Prometheus time series by requesting
// garbage; anything unrecognised collapses into a single "other" bucket.
func (s *Server) routeLabel(path string) string {
	switch path {
	case "/api/health", "/api/series":
		return path
	case s.metricsPath:
		return path
	}

	const prefix = "/api/series/"
	if rest, ok := strings.CutPrefix(path, prefix); ok {
		if name, action, found := strings.Cut(rest, "/"); found && name != "" {
			switch action {
			case "latest", "history", "refresh":
				return prefix + "{name}/" + action
			}
		}
	}
	return "other"
}
