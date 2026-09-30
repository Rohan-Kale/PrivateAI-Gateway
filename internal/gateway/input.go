package gateway

import (
	"context"
	"sort"
	"strings"
)

// inputSpans keeps message roles/content intact while additionally inspecting
// concatenated content for SECRET spans crossing message boundaries.
func (e *Engine) inputSpans(ctx context.Context, messages []Message) ([][]Span, error) {
	all := make([][]Span, len(messages))
	var joined strings.Builder
	bounds := []int{0}
	validate := func(text string, spans []Span) error {
		_, err := transform(text, spans, Policy{Default: Allow}, map[string]string{})
		return err
	}
	for i, message := range messages {
		spans, err := e.Detector.Detect(ctx, message.Content)
		if err != nil {
			return nil, err
		}
		if err = validate(message.Content, spans); err != nil {
			return nil, err
		}
		all[i] = spans
		joined.WriteString(message.Content)
		bounds = append(bounds, joined.Len())
	}
	if len(messages) < 2 {
		return all, nil
	}
	spans, err := e.Detector.Detect(ctx, joined.String())
	if err != nil {
		return nil, err
	}
	if err = validate(joined.String(), spans); err != nil {
		return nil, err
	}
	for _, span := range spans {
		if span.Kind != "SECRET" {
			continue
		}
		crosses := false
		for _, boundary := range bounds[1 : len(bounds)-1] {
			if span.Start < boundary && boundary < span.End {
				crosses = true
			}
		}
		if !crosses {
			continue
		}
		for i := range messages {
			start, end := max(span.Start, bounds[i]), min(span.End, bounds[i+1])
			if start < end {
				all[i] = append(all[i], Span{Start: start - bounds[i], End: end - bounds[i], Kind: "SECRET"})
			}
		}
	}
	for i, spans := range all {
		sort.Slice(spans, func(a, b int) bool { return spans[a].Start < spans[b].Start })
		merged := []Span{}
		for _, span := range spans {
			if len(merged) > 0 && span.Start < merged[len(merged)-1].End {
				last := &merged[len(merged)-1]
				last.End = max(last.End, span.End)
				// Newly introduced overlap can only come from a cross-message secret.
				last.Kind = "SECRET"
			} else {
				merged = append(merged, span)
			}
		}
		all[i] = merged
	}
	return all, nil
}
