package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync/atomic"
	"time"
	"unicode/utf8"
)

type Metrics struct {
	Requests     atomic.Int64
	Errors       atomic.Int64
	Blocked      atomic.Int64
	CacheHits    atomic.Int64
	Active       atomic.Int64
	Jobs         atomic.Int64
	Completed    atomic.Int64
	Failed       atomic.Int64
	Nanos        atomic.Int64
	QueueWait    Histogram
	PolicyLookup Histogram
}
type Engine struct {
	Store    Store
	Detector Detector
	Provider Provider
	Vault    *Vault
	Metrics  *Metrics
	slots    chan struct{}
}

func NewEngine(s Store, d Detector, p Provider, v *Vault, concurrency int) *Engine {
	return &Engine{Store: s, Detector: d, Provider: p, Vault: v, Metrics: &Metrics{}, slots: make(chan struct{}, concurrency)}
}

// transform validates untrusted byte offsets before slicing UTF-8 content.
func transform(text string, spans []Span, p Policy, mapping map[string]string) (string, error) {
	sort.Slice(spans, func(i, j int) bool { return spans[i].Start < spans[j].Start })
	end := 0
	for _, s := range spans {
		if !Kinds[s.Kind] || s.Start < end || s.Start < 0 || s.End <= s.Start || s.End > len(text) || !utf8.ValidString(text[:s.Start]) || !utf8.ValidString(text[:s.End]) {
			return "", errors.New("invalid detector spans")
		}
		if p.Action(s.Kind) == Block {
			return "", ErrBlocked
		}
		end = s.End
	}
	var b strings.Builder
	end = 0
	for _, s := range spans {
		b.WriteString(text[end:s.Start])
		original := text[s.Start:s.End]
		switch p.Action(s.Kind) {
		case Allow:
			b.WriteString(original)
		case Redact:
			b.WriteString("[REDACTED_" + s.Kind + "]")
		case Tokenize:
			token := "<PAI_" + newID() + ">"
			mapping[token] = original
			b.WriteString(token)
		default:
			return "", errors.New("invalid policy action")
		}
		end = s.End
	}
	b.WriteString(text[end:])
	return b.String(), nil
}
func (e *Engine) Run(ctx context.Context, tenant string, req Request) (result Result, err error) {
	started := time.Now()
	e.Metrics.Requests.Add(1)
	defer func() {
		e.Metrics.Nanos.Add(time.Since(started).Nanoseconds())
		if err != nil {
			e.Metrics.Errors.Add(1)
			if errors.Is(err, ErrBlocked) {
				e.Metrics.Blocked.Add(1)
			}
		}
	}()
	if err = req.Validate(); err != nil {
		return result, err
	}
	select {
	case e.slots <- struct{}{}:
		defer func() { <-e.slots }()
	default:
		return result, ErrBusy
	}
	e.Metrics.Active.Add(1)
	defer e.Metrics.Active.Add(-1)
	policyStarted := time.Now()
	p, err := e.Store.Policy(ctx, tenant)
	e.Metrics.PolicyLookup.Observe(time.Since(policyStarted).Seconds())
	if err != nil {
		return result, err
	}
	if err = p.Validate(); err != nil {
		return result, err
	}
	id := newID()
	scope := tenant + ":" + id
	result = Result{ID: id, Model: req.Model, PolicyVersion: p.Version}
	original, _ := json.Marshal(req)
	cacheKey := "cache:" + e.Vault.Hash(fmt.Sprintf("%s:%d:%s", tenant, p.Version, original))
	mapping := map[string]string{}
	clean := req
	clean.Messages = append([]Message(nil), req.Messages...)
	inputSpans, err := e.inputSpans(ctx, req.Messages)
	if err != nil {
		return result, err
	}
	for i, m := range clean.Messages {
		if strings.Contains(m.Content, "<PAI_") {
			return result, errors.New("reserved token prefix")
		}
		var er error
		clean.Messages[i].Content, er = transform(m.Content, inputSpans[i], p, mapping)
		if er != nil {
			return result, er
		}
	}
	if len(mapping) == 0 && p.CacheSeconds > 0 {
		if sealed, er := e.Store.Get(ctx, cacheKey); er == nil {
			cached, er := e.Vault.Open(cacheKey, sealed)
			if er != nil {
				return result, er
			}
			result.Content = cached
			result.Cached = true
			e.Metrics.CacheHits.Add(1)
			return result, nil
		} else if !errors.Is(er, ErrNotFound) {
			return result, er
		}
	}
	if len(mapping) > 0 {
		b, _ := json.Marshal(mapping)
		sealed, er := e.Vault.Seal(scope, string(b))
		if er != nil {
			return result, er
		}
		if er = e.Store.Set(ctx, "vault:"+scope, sealed, 10*time.Minute); er != nil {
			return result, er
		}
	}
	output, err := e.Provider.Infer(ctx, clean)
	if err != nil {
		return result, err
	}
	// Output is scanned in full before any response byte is released. Provider-created
	// PII has no authorization for restoration and is redacted for tokenize actions.
	spans, err := e.Detector.Detect(ctx, output)
	if err != nil {
		return result, err
	}
	outPolicy := clonePolicy(p)
	if outPolicy.Default == Tokenize {
		outPolicy.Default = Redact
	}
	for k, a := range outPolicy.Rules {
		if a == Tokenize {
			outPolicy.Rules[k] = Redact
		}
	}
	output, err = transform(output, spans, outPolicy, map[string]string{})
	if err != nil {
		return result, err
	}
	if len(mapping) > 0 && p.Restore {
		sealed, er := e.Store.Get(ctx, "vault:"+scope)
		if er != nil {
			return result, er
		}
		raw, er := e.Vault.Open(scope, sealed)
		if er != nil {
			return result, er
		}
		var saved map[string]string
		if er = json.Unmarshal([]byte(raw), &saved); er != nil {
			return result, er
		}
		// Simultaneous replacement prevents recursively interpreting original text as tokens.
		pairs := make([]string, 0, 2*len(saved))
		for token, value := range saved {
			pairs = append(pairs, token, value)
		}
		output = strings.NewReplacer(pairs...).Replace(output)
	}
	result.Content = output
	if len(mapping) == 0 && p.CacheSeconds > 0 {
		sealed, er := e.Vault.Seal(cacheKey, output)
		if er != nil {
			return result, er
		}
		if er = e.Store.Set(ctx, cacheKey, sealed, time.Duration(p.CacheSeconds)*time.Second); er != nil {
			return result, er
		}
	}
	return result, nil
}
