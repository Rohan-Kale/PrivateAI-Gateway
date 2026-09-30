package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type detectorFunc func(context.Context, string) ([]Span, error)

func (f detectorFunc) Detect(c context.Context, s string) ([]Span, error) { return f(c, s) }

type providerFunc func(context.Context, Request) (string, error)

func (f providerFunc) Infer(c context.Context, r Request) (string, error) { return f(c, r) }
func testDetector(_ context.Context, s string) ([]Span, error) {
	var spans []Span
	for _, pair := range [][2]string{{"alice@example.com", "EMAIL"}, {"sk-testsecret0123456789", "SECRET"}} {
		if i := strings.Index(s, pair[0]); i >= 0 {
			spans = append(spans, Span{i, i + len(pair[0]), pair[1]})
		}
	}
	return spans, nil
}
func setup(t testing.TB) (*Engine, *MemoryStore) {
	t.Helper()
	s := NewMemoryStore()
	p := DefaultPolicy()
	p.Version = 0
	if _, err := s.PutPolicy(context.Background(), "demo", p); err != nil {
		t.Fatal(err)
	}
	v, err := NewVault([]byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	return NewEngine(s, detectorFunc(testDetector), providerFunc(func(_ context.Context, r Request) (string, error) { return r.Messages[0].Content, nil }), v, 256), s
}
func request(text string) Request {
	return Request{Model: "mock", Messages: []Message{{Role: "user", Content: text}}}
}

func TestActions(t *testing.T) {
	for _, a := range []Action{Allow, Redact, Tokenize, Block} {
		t.Run(string(a), func(t *testing.T) {
			e, s := setup(t)
			p, _ := s.Policy(context.Background(), "demo")
			p.Rules["EMAIL"] = a
			_, _ = s.PutPolicy(context.Background(), "demo", p)
			var upstream string
			e.Provider = providerFunc(func(_ context.Context, r Request) (string, error) {
				upstream = r.Messages[0].Content
				return upstream, nil
			})
			result, err := e.Run(context.Background(), "demo", request("🌍 alice@example.com"))
			if a == Block {
				if !errors.Is(err, ErrBlocked) || upstream != "" {
					t.Fatal("block did not prevent upstream")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if a == Redact && strings.Contains(result.Content, "alice@") {
				t.Fatal("redaction failed")
			}
			if a == Tokenize {
				if strings.Contains(upstream, "alice@") || !strings.Contains(upstream, "<PAI_") || result.Content != "🌍 alice@example.com" {
					t.Fatal("token roundtrip failed")
				}
				s.mu.Lock()
				defer s.mu.Unlock()
				for _, entry := range s.values {
					if strings.Contains(entry.value, "alice@") {
						t.Fatal("raw token value persisted")
					}
				}
			}
			if a == Allow && result.Content != "🌍 alice@example.com" {
				t.Fatal("allow changed text")
			}
		})
	}
}
func TestVaultScopeAndTamper(t *testing.T) {
	e, _ := setup(t)
	sealed, err := e.Vault.Seal("tenant:request", "private")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = e.Vault.Open("other:request", sealed); err == nil {
		t.Fatal("cross-scope decrypt")
	}
	if _, err = e.Vault.Open("tenant:request", sealed[:len(sealed)-3]+"abc"); err == nil {
		t.Fatal("tampering accepted")
	}
}
func TestMalformedSpansFailClosed(t *testing.T) {
	for _, span := range []Span{{-1, 2, "EMAIL"}, {0, 99, "EMAIL"}, {1, 2, "EMAIL"}, {0, 4, "UNKNOWN"}} {
		_, err := transform("🌍", []Span{span}, DefaultPolicy(), map[string]string{})
		if err == nil {
			t.Fatalf("accepted %#v", span)
		}
	}
	_, err := transform("abcdef", []Span{{0, 4, "EMAIL"}, {2, 6, "EMAIL"}}, DefaultPolicy(), map[string]string{})
	if err == nil {
		t.Fatal("overlap accepted")
	}
}
func TestCacheIsolationAndPolicyChanges(t *testing.T) {
	e, s := setup(t)
	var calls atomic.Int64
	e.Provider = providerFunc(func(_ context.Context, r Request) (string, error) { calls.Add(1); return "safe", nil })
	ctx := context.Background()
	for i := 0; i < 2; i++ {
		result, err := e.Run(ctx, "demo", request("hello"))
		if err != nil {
			t.Fatal(err)
		}
		if result.Cached != (i == 1) {
			t.Fatal("cache status")
		}
	}
	p, _ := s.Policy(ctx, "demo")
	_, _ = s.PutPolicy(ctx, "demo", p)
	_, _ = e.Run(ctx, "demo", request("hello"))
	p.Version = 0
	_, _ = s.PutPolicy(ctx, "other", p)
	_, _ = e.Run(ctx, "other", request("hello"))
	if calls.Load() != 3 {
		t.Fatal("cache policy/tenant isolation")
	}
}
func TestDetectorOutageNeverCallsProvider(t *testing.T) {
	e, _ := setup(t)
	e.Detector = detectorFunc(func(context.Context, string) ([]Span, error) { return nil, errors.New("offline") })
	e.Provider = providerFunc(func(context.Context, Request) (string, error) { t.Fatal("called provider"); return "", nil })
	if _, err := e.Run(context.Background(), "demo", request("hello")); err == nil {
		t.Fatal("failed open")
	}
}
func TestOutputIsInspected(t *testing.T) {
	e, _ := setup(t)
	e.Provider = providerFunc(func(context.Context, Request) (string, error) { return "sk-testsecret0123456789", nil })
	if _, err := e.Run(context.Background(), "demo", request("hello")); !errors.Is(err, ErrBlocked) {
		t.Fatal("unsafe output escaped")
	}
}
func TestOutputTokensNotRestored(t *testing.T) {
	e, s := setup(t)
	p, _ := s.Policy(context.Background(), "demo")
	p.Rules["EMAIL"] = Tokenize
	_, _ = s.PutPolicy(context.Background(), "demo", p)
	e.Provider = providerFunc(func(context.Context, Request) (string, error) { return "alice@example.com", nil })
	r, err := e.Run(context.Background(), "demo", request("hello"))
	if err != nil || r.Content != "[REDACTED_EMAIL]" {
		t.Fatal("generated PII restored", err)
	}
}
func TestConcurrentRequests(t *testing.T) {
	e, _ := setup(t)
	var wg sync.WaitGroup
	for i := 0; i < 200; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, err := e.Run(context.Background(), "demo", request(fmt.Sprintf("hello %d", i)))
			if err != nil {
				t.Error(err)
			}
		}(i)
	}
	wg.Wait()
}
func TestAdmissionLimit(t *testing.T) {
	e, _ := setup(t)
	e.slots = make(chan struct{}, 1)
	e.slots <- struct{}{}
	if _, err := e.Run(context.Background(), "demo", request("hello")); !errors.Is(err, ErrBusy) {
		t.Fatal("limit not enforced")
	}
}
func TestMemoryExpiryAndVersionConflict(t *testing.T) {
	_, s := setup(t)
	_ = s.Set(context.Background(), "expired", "x", -time.Second)
	if _, err := s.Get(context.Background(), "expired"); !errors.Is(err, ErrNotFound) {
		t.Fatal("expired value returned")
	}
	p := DefaultPolicy()
	p.Version = 0
	if _, err := s.PutPolicy(context.Background(), "demo", p); !errors.Is(err, ErrConflict) {
		t.Fatal("stale policy accepted")
	}
}
func TestHTTPAuthAndStrictInput(t *testing.T) {
	e, _ := setup(t)
	api := (&API{Engine: e, Keys: map[string]string{"demo-test-key-1234": "demo"}, AdminKey: "admin-test-key-1234"}).Handler()
	for _, tt := range []struct {
		body, key string
		status    int
	}{{`{"model":"mock","messages":[{"role":"user","content":"hello"}]}`, "", 401}, {`{"model":"mock","messages":[{"role":"user","content":"hello"}],"tools":[]}`, "demo-test-key-1234", 400}, {`{"model":"mock","messages":[{"role":"user","content":"sk-testsecret0123456789"}]}`, "demo-test-key-1234", 403}} {
		r := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(tt.body))
		r.Header.Set("Authorization", "Bearer "+tt.key)
		w := httptest.NewRecorder()
		api.ServeHTTP(w, r)
		if w.Code != tt.status {
			t.Fatalf("got %d want %d", w.Code, tt.status)
		}
	}
	r := httptest.NewRequest("PUT", "/admin/policies/demo", strings.NewReader(`{}`))
	r.Header.Set("Authorization", "Bearer demo-test-key-1234")
	w := httptest.NewRecorder()
	api.ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal("tenant changed policy")
	}
}
func TestSSECollectionAndTermination(t *testing.T) {
	payload := "data: {\"choices\":[{\"delta\":{\"content\":\"alice@\"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"example.com\"}}]}\n\ndata: [DONE]\n\n"
	got, err := collectSSE(strings.NewReader(payload))
	if err != nil || got != "alice@example.com" {
		t.Fatal(got, err)
	}
	if _, err = collectSSE(strings.NewReader(strings.ReplaceAll(payload, "data: [DONE]", ""))); err == nil {
		t.Fatal("truncated stream accepted")
	}
}
func TestHTTPProviderStreaming(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req Request
		_ = json.NewDecoder(r.Body).Decode(&req)
		if !req.Stream {
			t.Error("stream flag lost")
		}
		fmt.Fprint(w, "data: {\"choices\":[{\"delta\":{\"content\":\"🌍\"}}]}\n\ndata: [DONE]\n\n")
	}))
	defer server.Close()
	p := HTTPProvider{URL: server.URL, Client: server.Client()}
	req := request("hello")
	req.Stream = true
	if got, err := p.Infer(context.Background(), req); err != nil || got != "🌍" {
		t.Fatal(got, err)
	}
}
func BenchmarkRedact(b *testing.B) {
	p := DefaultPolicy()
	text := strings.Repeat("a", 256) + "alice@example.com"
	spans := []Span{{256, len(text), "EMAIL"}}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, err := transform(text, spans, p, map[string]string{})
		if err != nil {
			b.Fatal(err)
		}
	}
}
func BenchmarkVaultRoundTrip(b *testing.B) {
	e, _ := setup(b)
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		s, err := e.Vault.Seal("scope", "alice@example.com")
		if err != nil {
			b.Fatal(err)
		}
		if _, err = e.Vault.Open("scope", s); err != nil {
			b.Fatal(err)
		}
	}
}
