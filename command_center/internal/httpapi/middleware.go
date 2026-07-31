package httpapi

import (
	"errors"
	"net/http"
	"runtime/debug"
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
