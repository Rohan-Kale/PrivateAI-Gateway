package gateway

import (
	"strings"
	"testing"
)

func TestHistogramBucketsAndCount(t *testing.T) {
	var h Histogram
	h.Observe(.002)
	h.Observe(1.5)
	var out strings.Builder
	h.Write(&out, "test_seconds")
	for _, want := range []string{"test_seconds_bucket{le=\"0.001\"} 0", "test_seconds_bucket{le=\"0.005\"} 1", "test_seconds_bucket{le=\"+Inf\"} 2", "test_seconds_count 2"} {
		if !strings.Contains(out.String(), want) {
			t.Fatal("missing", want)
		}
	}
}
