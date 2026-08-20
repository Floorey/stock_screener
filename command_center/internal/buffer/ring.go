// Package buffer implements the in-memory data layer of the command center.
//
// Every data source (balance, orderbook, ...) owns exactly one Series. A Series
// is a fixed-size ring buffer plus health status plus a fan-out to subscribers.
// Producers (pollers, broker websocket readers) write into it, consumers (REST
// handlers, websocket clients) read from it. Nothing in the frontend ever talks
// to a broker API directly.
package buffer

import (
	"errors"
	"fmt"
	"sync"
	"time"
)

// ErrInvalidCapacity is returned when a ring is created with a non-positive size.
var ErrInvalidCapacity = errors.New("buffer: capacity must be > 0")

// Sample is one datapoint in a series. Value holds the provider specific
// payload (e.g. provider.Balance) and must be JSON serialisable.
type Sample struct {
	Seq   uint64    `json:"seq"`
	Ts    time.Time `json:"ts"`
	Value any       `json:"value"`
}

// Ring is a fixed-capacity ring buffer of Samples. It overwrites the oldest
// entry once full and is safe for concurrent use.
type Ring struct {
	mu   sync.RWMutex
	buf  []Sample
	next int    // index of the next write
	size int    // number of valid entries, <= len(buf)
	seq  uint64 // monotonic counter, never reset
}

// NewRing returns a ring with the given capacity.
func NewRing(capacity int) (*Ring, error) {
	if capacity <= 0 {
		return nil, fmt.Errorf("%w (got %d)", ErrInvalidCapacity, capacity)
	}
	return &Ring{buf: make([]Sample, capacity)}, nil
}

// Append stores value with the given timestamp and returns the created sample.
func (r *Ring) Append(value any, ts time.Time) Sample {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.seq++
	s := Sample{Seq: r.seq, Ts: ts, Value: value}
	r.buf[r.next] = s
	r.next = (r.next + 1) % len(r.buf)
	if r.size < len(r.buf) {
		r.size++
	}
	return s
}

// Latest returns the newest sample. ok is false while the ring is still empty.
func (r *Ring) Latest() (Sample, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if r.size == 0 {
		return Sample{}, false
	}
	idx := (r.next - 1 + len(r.buf)) % len(r.buf)
	return r.buf[idx], true
}

// Last returns up to n samples, oldest first. n <= 0 or n > size returns
// everything currently buffered.
func (r *Ring) Last(n int) []Sample {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if n <= 0 || n > r.size {
		n = r.size
	}
	out := make([]Sample, 0, n)
	start := (r.next - n + len(r.buf)) % len(r.buf)
	for i := 0; i < n; i++ {
		out = append(out, r.buf[(start+i)%len(r.buf)])
	}
	return out
}

// Since returns all buffered samples with Seq > seq, oldest first. A client
// that reconnects passes the last seq it saw and gets exactly the gap back —
// as far as the ring still reaches.
func (r *Ring) Since(seq uint64) []Sample {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]Sample, 0, r.size)
	start := (r.next - r.size + len(r.buf)) % len(r.buf)
	for i := 0; i < r.size; i++ {
		s := r.buf[(start+i)%len(r.buf)]
		if s.Seq > seq {
			out = append(out, s)
		}
	}
	return out
}

// Len reports the number of buffered samples.
func (r *Ring) Len() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.size
}

// Cap reports the ring capacity.
func (r *Ring) Cap() int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return len(r.buf)
}
