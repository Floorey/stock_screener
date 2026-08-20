package buffer

import (
	"errors"
	"testing"
	"time"
)

func TestNewRingRejectsBadCapacity(t *testing.T) {
	if _, err := NewRing(0); !errors.Is(err, ErrInvalidCapacity) {
		t.Fatalf("want ErrInvalidCapacity, got %v", err)
	}
}

func TestRingOverwritesOldest(t *testing.T) {
	r, err := NewRing(3)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	for i := 1; i <= 5; i++ {
		r.Append(i, now)
	}

	if got := r.Len(); got != 3 {
		t.Fatalf("len = %d, want 3", got)
	}
	latest, ok := r.Latest()
	if !ok || latest.Value != 5 || latest.Seq != 5 {
		t.Fatalf("latest = %+v, ok = %v", latest, ok)
	}

	got := r.Last(0)
	want := []int{3, 4, 5}
	if len(got) != len(want) {
		t.Fatalf("last = %d samples, want %d", len(got), len(want))
	}
	for i, s := range got {
		if s.Value != want[i] {
			t.Errorf("last[%d] = %v, want %v", i, s.Value, want[i])
		}
	}
}

func TestRingSinceReturnsGapOnly(t *testing.T) {
	r, _ := NewRing(10)
	now := time.Now()
	for i := 1; i <= 5; i++ {
		r.Append(i, now)
	}

	got := r.Since(3)
	if len(got) != 2 {
		t.Fatalf("since(3) = %d samples, want 2", len(got))
	}
	if got[0].Seq != 4 || got[1].Seq != 5 {
		t.Fatalf("since(3) seqs = %d,%d want 4,5", got[0].Seq, got[1].Seq)
	}
	if len(r.Since(99)) != 0 {
		t.Error("since(future seq) should be empty")
	}
}

func TestSeriesFailKeepsLastValidState(t *testing.T) {
	s, err := NewSeries("balance", 4, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	s.Publish(42, time.Now())
	s.Fail(errors.New("api down"))
	s.Fail(errors.New("api still down"))

	latest, ok := s.Latest()
	if !ok || latest.Value != 42 {
		t.Fatalf("buffer lost its last valid value: %+v", latest)
	}
	st := s.Status()
	if st.Errors != 2 || st.ConsecutiveErrors != 2 || st.Updates != 1 {
		t.Fatalf("unexpected status: %+v", st)
	}
	if st.LastError != "api still down" {
		t.Errorf("last error = %q", st.LastError)
	}

	s.Publish(43, time.Now())
	if got := s.ConsecutiveErrors(); got != 0 {
		t.Errorf("consecutive errors after recovery = %d, want 0", got)
	}
}

func TestSubscriptionDropsInsteadOfBlocking(t *testing.T) {
	s, _ := NewSeries("orderbook", 8, time.Second)
	sub := s.Subscribe(1)
	defer sub.Close()

	for i := 0; i < 5; i++ {
		s.Publish(i, time.Now()) // consumer never reads
	}

	if got := sub.Dropped(); got != 4 {
		t.Fatalf("dropped = %d, want 4", got)
	}
	if got := <-sub.C; got.Value != 0 {
		t.Fatalf("queued sample = %v, want 0", got.Value)
	}
}

func TestStoreRejectsDuplicates(t *testing.T) {
	store := NewStore()
	s1, _ := NewSeries("balance", 2, time.Second)
	s2, _ := NewSeries("balance", 2, time.Second)

	if err := store.Register(s1); err != nil {
		t.Fatal(err)
	}
	if err := store.Register(s2); !errors.Is(err, ErrDuplicateSeries) {
		t.Fatalf("want ErrDuplicateSeries, got %v", err)
	}
	if _, err := store.Get("nope"); !errors.Is(err, ErrUnknownSeries) {
		t.Fatalf("want ErrUnknownSeries, got %v", err)
	}
}
