package gateway

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestSplitSecretPolicies(t *testing.T) {
	for _, action := range []Action{Allow, Redact, Tokenize, Block} {
		t.Run(string(action), func(t *testing.T) {
			e, s := setup(t)
			p, _ := s.Policy(context.Background(), "demo")
			p.Rules["SECRET"] = action
			p.CacheSeconds = 0
			s.PutPolicy(context.Background(), "demo", p)
			called := false
			e.Provider = providerFunc(func(_ context.Context, r Request) (string, error) {
				called = true
				value := r.Messages[0].Content + r.Messages[1].Content
				if action != Allow && strings.Contains(value, "sk-testsecret0123456789") {
					t.Fatal("split secret reached provider")
				}
				return value, nil
			})
			r := Request{Model: "mock", Messages: []Message{{Role: "user", Content: "🌍 sk-test"}, {Role: "user", Content: "secret0123456789"}}}
			result, err := e.Run(context.Background(), "demo", r)
			if action == Block {
				if !errors.Is(err, ErrBlocked) || called {
					t.Fatal("split block failed", err)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				if action == Tokenize && result.Content != "🌍 sk-testsecret0123456789" {
					t.Fatal("split restoration failed", result.Content)
				}
			}
		})
	}
}

func TestJoinedDetectorInvalidSpanFailsClosed(t *testing.T) {
	e, _ := setup(t)
	e.Detector = detectorFunc(func(_ context.Context, s string) ([]Span, error) {
		if s == "ab" {
			return []Span{{Start: 0, End: 3, Kind: "SECRET"}}, nil
		}
		return nil, nil
	})
	_, err := e.inputSpans(context.Background(), []Message{{Content: "a"}, {Content: "b"}})
	if err == nil {
		t.Fatal("invalid joined span accepted")
	}
}
