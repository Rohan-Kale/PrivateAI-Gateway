package gateway

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"time"
	"unicode/utf8"
)

var ErrBlocked = errors.New("policy blocked content")
var ErrNotFound = errors.New("not found")
var ErrConflict = errors.New("policy version conflict")
var ErrBusy = errors.New("capacity exhausted")
var identifier = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,64}$`)

type Action string

const (
	Allow    Action = "allow"
	Redact   Action = "redact"
	Tokenize Action = "tokenize"
	Block    Action = "block"
)

var Kinds = map[string]bool{"EMAIL": true, "PHONE": true, "SSN": true, "CREDIT_CARD": true, "SECRET": true}

type Policy struct {
	Version      int64             `json:"version"`
	Default      Action            `json:"default"`
	Rules        map[string]Action `json:"rules"`
	Restore      bool              `json:"restore"`
	CacheSeconds int               `json:"cache_seconds"`
}

func DefaultPolicy() Policy {
	return Policy{Version: 1, Default: Redact, Rules: map[string]Action{"SECRET": Block}, Restore: true, CacheSeconds: 60}
}
func (p Policy) Validate() error {
	valid := func(a Action) bool { return a == Allow || a == Redact || a == Tokenize || a == Block }
	if !valid(p.Default) || p.Version < 0 || p.CacheSeconds < 0 || p.CacheSeconds > 3600 {
		return errors.New("invalid policy")
	}
	for k, a := range p.Rules {
		if !Kinds[k] || !valid(a) {
			return fmt.Errorf("invalid rule %s", k)
		}
	}
	return nil
}
func (p Policy) Action(kind string) Action {
	if a, ok := p.Rules[kind]; ok {
		return a
	}
	return p.Default
}

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}
type Request struct {
	Model    string    `json:"model"`
	Messages []Message `json:"messages"`
	Stream   bool      `json:"stream,omitempty"`
}

func (r Request) Validate() error {
	if len(r.Model) == 0 || len(r.Model) > 128 || len(r.Messages) == 0 || len(r.Messages) > 64 {
		return errors.New("model and 1-64 messages required")
	}
	total := 0
	for _, m := range r.Messages {
		if m.Role != "system" && m.Role != "user" && m.Role != "assistant" {
			return errors.New("unsupported role")
		}
		if !utf8.ValidString(m.Content) {
			return errors.New("invalid UTF-8")
		}
		total += len(m.Content)
	}
	if total > 65536 {
		return errors.New("messages exceed 64 KiB")
	}
	return nil
}

type Span struct {
	Start int    `json:"start"`
	End   int    `json:"end"`
	Kind  string `json:"kind"`
}
type Detector interface {
	Detect(context.Context, string) ([]Span, error)
}
type Provider interface {
	Infer(context.Context, Request) (string, error)
}
type Store interface {
	Policy(context.Context, string) (Policy, error)
	PutPolicy(context.Context, string, Policy) (Policy, error)
	Get(context.Context, string) (string, error)
	Set(context.Context, string, string, time.Duration) error
	Ping(context.Context) error
	Close()
}
type Result struct {
	ID            string `json:"id"`
	Model         string `json:"model"`
	Content       string `json:"content"`
	Cached        bool   `json:"cached"`
	PolicyVersion int64  `json:"policy_version"`
}
type Job struct {
	ID      string    `json:"id"`
	Tenant  string    `json:"tenant"`
	Request Request   `json:"request"`
	Created time.Time `json:"created"`
}
type JobResult struct {
	Status string  `json:"status"`
	Result *Result `json:"result,omitempty"`
	Error  string  `json:"error,omitempty"`
}
