package gateway

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

// MemoryStore is an explicitly selected, single-process development backend.
type MemoryStore struct {
	mu       sync.Mutex
	policies map[string]Policy
	values   map[string]entry
}
type entry struct {
	value   string
	expires time.Time
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{policies: map[string]Policy{}, values: map[string]entry{}}
}
func clonePolicy(p Policy) Policy {
	b, _ := json.Marshal(p)
	var q Policy
	_ = json.Unmarshal(b, &q)
	return q
}
func (m *MemoryStore) Policy(_ context.Context, t string) (Policy, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.policies[t]
	if !ok {
		return Policy{}, ErrNotFound
	}
	return clonePolicy(p), nil
}
func (m *MemoryStore) PutPolicy(_ context.Context, t string, p Policy) (Policy, error) {
	if e := p.Validate(); e != nil {
		return Policy{}, e
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.policies[t].Version != p.Version {
		return Policy{}, ErrConflict
	}
	p.Version++
	m.policies[t] = clonePolicy(p)
	return p, nil
}
func (m *MemoryStore) Get(_ context.Context, k string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.values[k]
	if !ok || time.Now().After(e.expires) {
		delete(m.values, k)
		return "", ErrNotFound
	}
	return e.value, nil
}
func (m *MemoryStore) Set(_ context.Context, k, v string, ttl time.Duration) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for key, e := range m.values {
		if time.Now().After(e.expires) {
			delete(m.values, key)
		}
	}
	m.values[k] = entry{v, time.Now().Add(ttl)}
	return nil
}
func (m *MemoryStore) Ping(context.Context) error { return nil }
func (m *MemoryStore) Close()                     {}

type DatabaseStore struct {
	DB    *pgxpool.Pool
	Redis *redis.Client
	// DisablePolicyCache supplies a direct PostgreSQL baseline without changing consistency.
	DisablePolicyCache bool
	policyMu           sync.RWMutex
	decodedPolicies    map[string]Policy
}

// Returned policies must not alias shared maps. The cache holds at most 1,024
// tenants and is used only after an authoritative database version read.
func copyDecodedPolicy(p Policy) Policy {
	if p.Rules != nil {
		rules := make(map[string]Action, len(p.Rules))
		for kind, action := range p.Rules {
			rules[kind] = action
		}
		p.Rules = rules
	}
	return p
}

func (s *DatabaseStore) decodedPolicy(tenant string, version int64) (Policy, bool) {
	s.policyMu.RLock()
	defer s.policyMu.RUnlock()
	p, ok := s.decodedPolicies[tenant]
	if !ok || p.Version != version {
		return Policy{}, false
	}
	return copyDecodedPolicy(p), true
}

func (s *DatabaseStore) rememberPolicy(tenant string, p Policy) {
	s.policyMu.Lock()
	defer s.policyMu.Unlock()
	if s.decodedPolicies == nil || len(s.decodedPolicies) >= 1024 {
		s.decodedPolicies = make(map[string]Policy)
	}
	s.decodedPolicies[tenant] = copyDecodedPolicy(p)
}

func NewDatabaseStore(ctx context.Context, dsn, redisURL string) (*DatabaseStore, error) {
	db, e := pgxpool.New(ctx, dsn)
	if e != nil {
		return nil, e
	}
	opt, e := redis.ParseURL(redisURL)
	if e != nil {
		db.Close()
		return nil, e
	}
	s := &DatabaseStore{DB: db, Redis: redis.NewClient(opt)}
	if e = s.Ping(ctx); e != nil {
		s.Close()
		return nil, e
	}
	return s, nil
}
func (s *DatabaseStore) Ping(ctx context.Context) error {
	if e := s.DB.Ping(ctx); e != nil {
		return e
	}
	return s.Redis.Ping(ctx).Err()
}
func (s *DatabaseStore) Close() { s.DB.Close(); _ = s.Redis.Close() }
func (s *DatabaseStore) Policy(ctx context.Context, tenant string) (Policy, error) {
	if s.DisablePolicyCache {
		return s.loadPolicy(ctx, tenant)
	}
	// Verify the authoritative version on every request: cache TTL never delays revocation.
	var version int64
	e := s.DB.QueryRow(ctx, "SELECT version FROM policies WHERE tenant=$1", tenant).Scan(&version)
	if e == pgx.ErrNoRows {
		return Policy{}, ErrNotFound
	}
	if e != nil {
		return Policy{}, e
	}
	key := fmt.Sprintf("policy:%s:%d", tenant, version)
	if p, ok := s.decodedPolicy(tenant, version); ok && p.Validate() == nil {
		return p, nil
	}
	if b, e := s.Redis.Get(ctx, key).Result(); e == nil {
		var p Policy
		if json.Unmarshal([]byte(b), &p) == nil && p.Validate() == nil && p.Version == version {
			s.rememberPolicy(tenant, p)
			return p, nil
		}
	}
	p, e := s.loadPolicy(ctx, tenant)
	if e != nil {
		return p, e
	}
	b, _ := json.Marshal(p)
	_ = s.Redis.Set(ctx, fmt.Sprintf("policy:%s:%d", tenant, p.Version), b, time.Minute*5).Err()
	s.rememberPolicy(tenant, p)
	return p, nil
}
func (s *DatabaseStore) loadPolicy(ctx context.Context, tenant string) (Policy, error) {
	var raw []byte
	var p Policy
	e := s.DB.QueryRow(ctx, "SELECT version, document FROM policies WHERE tenant=$1", tenant).Scan(&p.Version, &raw)
	if e == pgx.ErrNoRows {
		return p, ErrNotFound
	}
	if e != nil {
		return p, e
	}
	v := p.Version
	if e = json.Unmarshal(raw, &p); e != nil {
		return p, e
	}
	p.Version = v
	if e = p.Validate(); e != nil {
		return p, e
	}
	return p, nil
}
func (s *DatabaseStore) PutPolicy(ctx context.Context, t string, p Policy) (Policy, error) {
	if e := p.Validate(); e != nil {
		return p, e
	}
	b, _ := json.Marshal(p)
	var v int64
	var e error
	if p.Version == 0 {
		e = s.DB.QueryRow(ctx, "INSERT INTO policies(tenant,version,document) VALUES($1,1,$2) ON CONFLICT DO NOTHING RETURNING version", t, b).Scan(&v)
	} else {
		e = s.DB.QueryRow(ctx, "UPDATE policies SET version=version+1, document=$2, updated_at=now() WHERE tenant=$1 AND version=$3 RETURNING version", t, b, p.Version).Scan(&v)
	}
	if e == pgx.ErrNoRows {
		return p, ErrConflict
	}
	p.Version = v
	return p, e
}
func (s *DatabaseStore) Get(ctx context.Context, k string) (string, error) {
	v, e := s.Redis.Get(ctx, k).Result()
	if e == redis.Nil {
		e = ErrNotFound
	}
	return v, e
}
func (s *DatabaseStore) Set(ctx context.Context, k, v string, ttl time.Duration) error {
	return s.Redis.Set(ctx, k, v, ttl).Err()
}
