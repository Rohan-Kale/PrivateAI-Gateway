package gateway

import (
	"context"
	"errors"
	"os"
	"testing"
)

// Run against an initialized throwaway database; this test only deletes its own tenant.
func TestPostgresPolicyCASAndCacheVersion(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	url := os.Getenv("TEST_REDIS_URL")
	if dsn == "" || url == "" {
		t.Skip("requires TEST_DATABASE_URL and TEST_REDIS_URL")
	}
	for _, mode := range []string{"direct", "legacy_redis", "decoded"} {
		t.Run(mode, func(t *testing.T) {
			ctx := context.Background()
			s, err := NewDatabaseStore(ctx, dsn, url)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			s.DisablePolicyCache = mode == "direct"
			s.DisableDecodedPolicyCache = mode == "legacy_redis"
			tenant := "test_" + newID()
			defer func() { _, _ = s.DB.Exec(ctx, "DELETE FROM policies WHERE tenant=$1", tenant) }()
			p := DefaultPolicy()
			p.Version = 0
			p, err = s.PutPolicy(ctx, tenant, p)
			if err != nil {
				t.Fatal(err)
			}
			if p.Version != 1 {
				t.Fatal("unexpected initial version")
			}
			if _, err = s.Policy(ctx, tenant); err != nil {
				t.Fatal(err)
			}
			p.Default = Block
			// A different process/store updates policy while this store has a warm L1.
			other, err := NewDatabaseStore(ctx, dsn, url)
			if err != nil {
				t.Fatal(err)
			}
			defer other.Close()
			updated, err := other.PutPolicy(ctx, tenant, p)
			if err != nil || updated.Version != 2 {
				t.Fatal(updated, err)
			}
			if _, err = s.PutPolicy(ctx, tenant, p); !errors.Is(err, ErrConflict) {
				t.Fatal("stale write accepted")
			}
			current, err := s.Policy(ctx, tenant)
			if err != nil || current.Default != Block || current.Version != 2 {
				t.Fatal("cache returned revoked policy", current, err)
			}
			_, err = s.DB.Exec(ctx, "DELETE FROM policies WHERE tenant=$1", tenant)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = s.Policy(ctx, tenant); !errors.Is(err, ErrNotFound) {
				t.Fatal("deleted policy served from warm cache", err)
			}
		})
	}
}
