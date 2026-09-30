package gateway

import (
	"fmt"
	"sync"
	"testing"
)

func TestDecodedPolicyCacheIsolationAndBound(t *testing.T) {
	s := &DatabaseStore{}
	p := DefaultPolicy()
	s.rememberPolicy("a", p)
	p.Rules["SECRET"] = Allow
	got, ok := s.decodedPolicy("a", 1)
	if !ok || got.Rules["SECRET"] != Block {
		t.Fatal("cache aliases inserted policy")
	}
	got.Rules["SECRET"] = Allow
	again, _ := s.decodedPolicy("a", 1)
	if again.Rules["SECRET"] != Block {
		t.Fatal("cache aliases returned policy")
	}
	if _, ok = s.decodedPolicy("a", 2); ok {
		t.Fatal("wrong version returned")
	}
	if _, ok = s.decodedPolicy("b", 1); ok {
		t.Fatal("cross tenant cache hit")
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			for n := 0; n < 300; n++ {
				tenant := fmt.Sprintf("%d-%d", worker, n)
				s.rememberPolicy(tenant, DefaultPolicy())
				s.decodedPolicy(tenant, 1)
			}
		}(i)
	}
	wg.Wait()
	if len(s.decodedPolicies) > 1024 {
		t.Fatal("cache exceeds tenant bound")
	}
}
