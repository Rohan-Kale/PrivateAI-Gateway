package gateway

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type API struct {
	Engine   *Engine
	Broker   *Broker
	Keys     map[string]string
	AdminKey string
}

func jsonReply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func fail(w http.ResponseWriter, code int, message string) {
	jsonReply(w, code, map[string]string{"error": message})
}
func decode(w http.ResponseWriter, r *http.Request, v any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 128*1024)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return errors.New("extra JSON data")
	}
	return nil
}
func token(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return ""
	}
	return strings.TrimPrefix(h, "Bearer ")
}
func (a *API) tenant(r *http.Request) (string, bool) {
	provided := token(r)
	for k, t := range a.Keys {
		if subtle.ConstantTimeCompare([]byte(k), []byte(provided)) == 1 {
			return t, true
		}
	}
	return "", false
}
func (a *API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { jsonReply(w, 200, map[string]string{"status": "alive"}) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, c := context.WithTimeout(r.Context(), 2*time.Second)
		defer c()
		if a.Engine.Store.Ping(ctx) != nil {
			fail(w, 503, "storage unavailable")
			return
		}
		if _, e := a.Engine.Detector.Detect(ctx, ""); e != nil {
			fail(w, 503, "detector unavailable")
			return
		}
		jsonReply(w, 200, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		m := a.Engine.Metrics
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		m.QueueWait.Write(w, "privateai_queue_wait_seconds")
		m.PolicyLookup.Write(w, "privateai_policy_lookup_seconds")
		if a.Broker != nil {
			ctx, cancel := context.WithTimeout(r.Context(), time.Second)
			n, err := a.Broker.Redis.XLen(ctx, streamName).Result()
			cancel()
			if err == nil {
				fmt.Fprintf(w, "# TYPE privateai_queue_depth gauge\nprivateai_queue_depth %d\n", n)
			}
		}
		fmt.Fprintf(w, "# TYPE privateai_requests_total counter\nprivateai_requests_total %d\n# TYPE privateai_errors_total counter\nprivateai_errors_total %d\n# TYPE privateai_blocked_total counter\nprivateai_blocked_total %d\n# TYPE privateai_cache_hits_total counter\nprivateai_cache_hits_total %d\n# TYPE privateai_inflight gauge\nprivateai_inflight %d\n# TYPE privateai_request_duration_seconds summary\nprivateai_request_duration_seconds_sum %f\nprivateai_request_duration_seconds_count %d\n# TYPE privateai_jobs_enqueued_total counter\nprivateai_jobs_enqueued_total %d\n# TYPE privateai_jobs_completed_total counter\nprivateai_jobs_completed_total %d\n# TYPE privateai_jobs_failed_total counter\nprivateai_jobs_failed_total %d\n", m.Requests.Load(), m.Errors.Load(), m.Blocked.Load(), m.CacheHits.Load(), m.Active.Load(), float64(m.Nanos.Load())/1e9, m.Requests.Load(), m.Jobs.Load(), m.Completed.Load(), m.Failed.Load())
	})
	mux.HandleFunc("PUT /admin/policies/{tenant}", func(w http.ResponseWriter, r *http.Request) {
		if subtle.ConstantTimeCompare([]byte(token(r)), []byte(a.AdminKey)) != 1 {
			fail(w, 401, "unauthorized")
			return
		}
		tenant := r.PathValue("tenant")
		if !identifier.MatchString(tenant) {
			fail(w, 400, "invalid tenant")
			return
		}
		var p Policy
		if decode(w, r, &p) != nil || p.Validate() != nil {
			fail(w, 400, "invalid policy")
			return
		}
		ctx, c := context.WithTimeout(r.Context(), 5*time.Second)
		defer c()
		updated, e := a.Engine.Store.PutPolicy(ctx, tenant, p)
		if errors.Is(e, ErrConflict) {
			fail(w, 409, "policy version conflict")
			return
		}
		if e != nil {
			fail(w, 503, "policy storage unavailable")
			return
		}
		jsonReply(w, 200, updated)
	})
	mux.HandleFunc("GET /v1/policy", a.auth(func(w http.ResponseWriter, r *http.Request, t string) {
		p, e := a.Engine.Store.Policy(r.Context(), t)
		if e != nil {
			fail(w, 503, "policy unavailable")
			return
		}
		jsonReply(w, 200, p)
	}))
	mux.HandleFunc("POST /v1/chat/completions", a.auth(func(w http.ResponseWriter, r *http.Request, t string) {
		var req Request
		if decode(w, r, &req) != nil || req.Validate() != nil {
			fail(w, 400, "invalid request; only model, messages and stream are supported")
			return
		}
		ctx, c := context.WithTimeout(r.Context(), 55*time.Second)
		defer c()
		res, e := a.Engine.Run(ctx, t, req)
		if e != nil {
			switch {
			case errors.Is(e, ErrBlocked):
				fail(w, 403, "policy blocked content")
			case errors.Is(e, ErrBusy):
				w.Header().Set("Retry-After", "1")
				fail(w, 429, "capacity exhausted")
			default:
				fail(w, 502, "inference unavailable")
			}
			return
		}
		w.Header().Set("X-Request-ID", res.ID)
		w.Header().Set("Cache-Control", "no-store")
		if req.Stream {
			emitSSE(w, r, res)
			return
		}
		jsonReply(w, 200, map[string]any{"id": res.ID, "object": "chat.completion", "model": res.Model, "choices": []any{map[string]any{"index": 0, "message": Message{Role: "assistant", Content: res.Content}, "finish_reason": "stop"}}, "cached": res.Cached, "policy_version": res.PolicyVersion})
	}))
	mux.HandleFunc("POST /v1/jobs", a.auth(func(w http.ResponseWriter, r *http.Request, t string) {
		if a.Broker == nil {
			fail(w, 503, "queue requires Redis backend")
			return
		}
		var req Request
		if decode(w, r, &req) != nil || req.Validate() != nil || req.Stream {
			fail(w, 400, "invalid non-streaming request")
			return
		}
		id, e := a.Broker.Submit(r.Context(), t, req)
		if errors.Is(e, ErrBusy) {
			fail(w, 429, "queue full")
			return
		}
		if e != nil {
			fail(w, 503, "queue unavailable")
			return
		}
		a.Engine.Metrics.Jobs.Add(1)
		w.Header().Set("Location", "/v1/jobs/"+id)
		jsonReply(w, 202, map[string]string{"id": id, "status": "queued"})
	}))
	mux.HandleFunc("GET /v1/jobs/{id}", a.auth(func(w http.ResponseWriter, r *http.Request, t string) {
		if a.Broker == nil {
			fail(w, 503, "queue requires Redis backend")
			return
		}
		id := r.PathValue("id")
		if len(id) != 32 || !identifier.MatchString(id) {
			fail(w, 404, "job not found")
			return
		}
		res, e := a.Broker.Result(r.Context(), t, id)
		if errors.Is(e, ErrNotFound) {
			fail(w, 404, "job not found")
			return
		}
		if e != nil {
			fail(w, 503, "queue unavailable")
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		jsonReply(w, 200, res)
	}))
	return mux
}
func (a *API) auth(fn func(http.ResponseWriter, *http.Request, string)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		t, ok := a.tenant(r)
		if !ok {
			fail(w, 401, "unauthorized")
			return
		}
		ctx, c := context.WithTimeout(r.Context(), 60*time.Second)
		defer c()
		fn(w, r.WithContext(ctx), t)
	}
}
func emitSSE(w http.ResponseWriter, r *http.Request, res Result) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set("X-Stream-Mode", "buffered-inspection")
	f, ok := w.(http.Flusher)
	if !ok {
		fail(w, 500, "streaming unsupported")
		return
	}
	runes := []rune(res.Content)
	for start := 0; start < len(runes); start += 32 {
		if r.Context().Err() != nil {
			return
		}
		end := start + 32
		if end > len(runes) {
			end = len(runes)
		}
		data, _ := json.Marshal(map[string]any{"id": res.ID, "object": "chat.completion.chunk", "model": res.Model, "choices": []any{map[string]any{"index": 0, "delta": map[string]string{"content": string(runes[start:end])}, "finish_reason": nil}}})
		if _, e := fmt.Fprintf(w, "data: %s\n\n", data); e != nil {
			return
		}
		f.Flush()
	}
	data, _ := json.Marshal(map[string]any{"id": res.ID, "choices": []any{map[string]any{"index": 0, "delta": map[string]string{}, "finish_reason": "stop"}}})
	fmt.Fprintf(w, "data: %s\n\ndata: [DONE]\n\n", data)
	f.Flush()
}
