package buffer

import (
	"errors"
	"fmt"
	"sort"
	"sync"
)

// ErrUnknownSeries is returned when a series name is not registered.
var ErrUnknownSeries = errors.New("buffer: unknown series")

// ErrDuplicateSeries is returned when a name is registered twice.
var ErrDuplicateSeries = errors.New("buffer: series already registered")

// Store is the registry of all series. It is the single source of truth the
// HTTP and websocket layers read from.
type Store struct {
	mu     sync.RWMutex
	series map[string]*Series
}

// NewStore returns an empty store.
func NewStore() *Store {
	return &Store{series: make(map[string]*Series)}
}

// Register adds a series under its name.
func (s *Store) Register(series *Series) error {
	if series == nil {
		return errors.New("buffer: cannot register nil series")
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.series[series.Name()]; exists {
		return fmt.Errorf("%w: %s", ErrDuplicateSeries, series.Name())
	}
	s.series[series.Name()] = series
	return nil
}

// Get looks up a series by name.
func (s *Store) Get(name string) (*Series, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	series, ok := s.series[name]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownSeries, name)
	}
	return series, nil
}

// Names returns all registered series names, sorted.
func (s *Store) Names() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	names := make([]string, 0, len(s.series))
	for name := range s.series {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// Statuses returns the health snapshot of every series, sorted by name.
func (s *Store) Statuses() []Status {
	s.mu.RLock()
	all := make([]*Series, 0, len(s.series))
	for _, series := range s.series {
		all = append(all, series)
	}
	s.mu.RUnlock()

	out := make([]Status, 0, len(all))
	for _, series := range all {
		out = append(out, series.Status())
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}
