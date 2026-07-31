package buffer

import (
	"sync"
	"time"
)

// Status is the health snapshot of a series. It is what the UI uses to decide
// whether the number on screen can still be trusted.
type Status struct {
	Name              string    `json:"name"`
	Interval          string    `json:"interval"`
	Capacity          int       `json:"capacity"`
	Buffered          int       `json:"buffered"`
	Subscribers       int       `json:"subscribers"`
	Updates           uint64    `json:"updates"`
	Errors            uint64    `json:"errors"`
	ConsecutiveErrors int       `json:"consecutive_errors"`
	LastUpdate        time.Time `json:"last_update"`
	LastError         string    `json:"last_error,omitempty"`
	LastErrorAt       time.Time `json:"last_error_at"`
	Stale             bool      `json:"stale"`
	LastSeq           uint64    `json:"last_seq"`
}

// Subscription is a live feed of new samples of one series. The channel is
// closed when the subscription is cancelled via Close.
type Subscription struct {
	C chan Sample

	series  *Series
	once    sync.Once
	dropped uint64
}

// Close cancels the subscription. It is safe to call more than once.
func (s *Subscription) Close() {
	s.once.Do(func() {
		s.series.unsubscribe(s)
		close(s.C)
	})
}

// Dropped reports how many samples were discarded because the consumer did not
// keep up. A slow websocket client never blocks the producer.
func (s *Subscription) Dropped() uint64 {
	s.series.mu.RLock()
	defer s.series.mu.RUnlock()
	return s.dropped
}

// Series couples a ring buffer with health bookkeeping and subscriber fan-out.
type Series struct {
	name     string
	interval time.Duration
	ring     *Ring

	mu          sync.RWMutex
	subs        map[*Subscription]struct{}
	updates     uint64
	errCount    uint64
	consecutive int
	lastUpdate  time.Time
	lastErr     string
	lastErrAt   time.Time
}

// NewSeries creates a series. interval is the expected update cadence and is
// used purely for staleness reporting; it may be 0 for push-driven sources
// (e.g. a broker websocket) where no fixed cadence exists.
func NewSeries(name string, capacity int, interval time.Duration) (*Series, error) {
	ring, err := NewRing(capacity)
	if err != nil {
		return nil, err
	}
	return &Series{
		name:     name,
		interval: interval,
		ring:     ring,
		subs:     make(map[*Subscription]struct{}),
	}, nil
}

// Name returns the series identifier used in config, REST paths and WS messages.
func (s *Series) Name() string { return s.name }

// Interval returns the configured update cadence (0 if push-driven).
func (s *Series) Interval() time.Duration { return s.interval }

// Publish appends a new datapoint and pushes it to all subscribers. It also
// clears the consecutive error counter — a successful update means the source
// has recovered.
func (s *Series) Publish(value any, ts time.Time) Sample {
	if ts.IsZero() {
		ts = time.Now().UTC()
	}
	sample := s.ring.Append(value, ts.UTC())

	s.mu.Lock()
	s.updates++
	s.consecutive = 0
	s.lastUpdate = sample.Ts
	subs := make([]*Subscription, 0, len(s.subs))
	for sub := range s.subs {
		subs = append(subs, sub)
	}
	s.mu.Unlock()

	for _, sub := range subs {
		select {
		case sub.C <- sample:
		default:
			// Consumer is behind. Drop rather than block the poller.
			s.mu.Lock()
			sub.dropped++
			s.mu.Unlock()
		}
	}
	return sample
}

// Fail records a fetch error. The buffer intentionally keeps its last valid
// state — a failing API degrades the freshness of the dashboard, it does not
// blank it out and it never kills the service.
func (s *Series) Fail(err error) {
	if err == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.errCount++
	s.consecutive++
	s.lastErr = err.Error()
	s.lastErrAt = time.Now().UTC()
}

// ConsecutiveErrors reports the current error streak, used for backoff.
func (s *Series) ConsecutiveErrors() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.consecutive
}

// Latest returns the newest buffered sample.
func (s *Series) Latest() (Sample, bool) { return s.ring.Latest() }

// History returns up to n buffered samples, oldest first.
func (s *Series) History(n int) []Sample { return s.ring.Last(n) }

// Since returns buffered samples newer than seq, oldest first.
func (s *Series) Since(seq uint64) []Sample { return s.ring.Since(seq) }

// Subscribe registers a live consumer. depth is the per-client queue length;
// values <= 0 fall back to 1.
func (s *Series) Subscribe(depth int) *Subscription {
	if depth <= 0 {
		depth = 1
	}
	sub := &Subscription{C: make(chan Sample, depth), series: s}

	s.mu.Lock()
	s.subs[sub] = struct{}{}
	s.mu.Unlock()
	return sub
}

func (s *Series) unsubscribe(sub *Subscription) {
	s.mu.Lock()
	delete(s.subs, sub)
	s.mu.Unlock()
}

// Status returns the current health snapshot.
func (s *Series) Status() Status {
	s.mu.RLock()
	defer s.mu.RUnlock()

	st := Status{
		Name:              s.name,
		Capacity:          s.ring.Cap(),
		Buffered:          s.ring.Len(),
		Subscribers:       len(s.subs),
		Updates:           s.updates,
		Errors:            s.errCount,
		ConsecutiveErrors: s.consecutive,
		LastUpdate:        s.lastUpdate,
		LastError:         s.lastErr,
		LastErrorAt:       s.lastErrAt,
	}
	if s.interval > 0 {
		st.Interval = s.interval.String()
		// Two missed cycles (plus a grace second) count as stale.
		st.Stale = s.lastUpdate.IsZero() ||
			time.Since(s.lastUpdate) > 2*s.interval+time.Second
	}
	if latest, ok := s.ring.Latest(); ok {
		st.LastSeq = latest.Seq
	}
	return st
}
