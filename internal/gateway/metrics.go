package gateway

import (
	"fmt"
	"io"
	"sync"
)

var histogramBounds = [...]float64{.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 120, 300}

// Histogram keeps a consistent snapshot without retaining individual request data.
type Histogram struct {
	mu      sync.Mutex
	count   uint64
	sum     float64
	buckets [len(histogramBounds)]uint64
}

func (h *Histogram) Observe(seconds float64) {
	if seconds < 0 {
		seconds = 0
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.count++
	h.sum += seconds
	for i, b := range histogramBounds {
		if seconds <= b {
			h.buckets[i]++
		}
	}
}
func (h *Histogram) Write(w io.Writer, name string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	fmt.Fprintf(w, "# TYPE %s histogram\n", name)
	for i, b := range histogramBounds {
		fmt.Fprintf(w, "%s_bucket{le=\"%g\"} %d\n", name, b, h.buckets[i])
	}
	fmt.Fprintf(w, "%s_bucket{le=\"+Inf\"} %d\n%s_sum %g\n%s_count %d\n", name, h.count, name, h.sum, name, h.count)
}
