// policybench compares cache hits against direct PostgreSQL reads, outside inference.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/Rohan-Kale/PrivateAI-Gateway/internal/gateway"
	"math/rand"
	"os"
	"runtime"
	"sort"
	"time"
)

func median(v []float64) float64 {
	x := append([]float64(nil), v...)
	sort.Float64s(x)
	n := len(x)
	if n%2 == 0 {
		return (x[n/2-1] + x[n/2]) / 2
	}
	return x[n/2]
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "policy experiment failed:", err)
		os.Exit(1)
	}
}
func run() error {
	rounds := flag.Int("rounds", 8, "paired rounds")
	samples := flag.Int("samples", 2000, "lookups per mode per round")
	seed := flag.Int64("seed", 73129, "randomized mode-order seed")
	output := flag.String("output", "/results/policy.json", "report path")
	flag.Parse()
	if *rounds < 2 || *samples < 1 {
		return fmt.Errorf("need at least 2 rounds and 1 sample")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	s, err := gateway.NewDatabaseStore(ctx, os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL"))
	if err != nil {
		return fmt.Errorf("cannot connect to test stores")
	}
	defer s.Close()
	tenant := fmt.Sprintf("policybench_%d", time.Now().UnixNano())
	p := gateway.DefaultPolicy()
	p.Version = 0
	p, err = s.PutPolicy(ctx, tenant, p)
	if err != nil {
		return err
	}
	defer func() {
		_, _ = s.DB.Exec(context.Background(), "DELETE FROM policies WHERE tenant=$1", tenant)
		_ = s.Redis.Del(context.Background(), "policy:"+tenant+":1").Err()
	}()
	rng := rand.New(rand.NewSource(*seed))
	records := []map[string]any{}
	effects := []float64{}
	for round := 0; round < *rounds; round++ {
		order := []bool{true, false}
		rng.Shuffle(2, func(i, j int) { order[i], order[j] = order[j], order[i] })
		medians := map[bool]float64{}
		for _, cached := range order {
			s.DisablePolicyCache = !cached
			for i := 0; i < 200; i++ {
				if _, err = s.Policy(ctx, tenant); err != nil {
					return err
				}
			}
			values := make([]float64, *samples)
			for i := range values {
				start := time.Now()
				got, er := s.Policy(ctx, tenant)
				values[i] = float64(time.Since(start).Nanoseconds()) / 1000
				if er != nil || got.Version != p.Version || got.Default != p.Default {
					return fmt.Errorf("lookup correctness failed")
				}
			}
			medians[cached] = median(values)
			records = append(records, map[string]any{"round": round, "cached": cached, "median_us": medians[cached], "samples_us": values})
		}
		effects = append(effects, 100*(medians[false]-medians[true])/medians[false])
	}
	report := map[string]any{"schema_version": 1, "experiment": "policy-cache-paired-v2", "timestamp_utc": time.Now().UTC(), "commit": os.Getenv("EVIDENCE_COMMIT"), "go": runtime.Version(), "cpus": runtime.NumCPU(), "seed": *seed, "rounds": *rounds, "samples_per_mode": *samples, "warmups_per_mode": 200, "baseline": "one PostgreSQL version+document read; validated JSON", "treatment": "PostgreSQL version check plus warm decoded process cache; Redis backs cold process reads; validated policy", "provider": "not involved", "records": records, "paired_improvement_percent": effects, "median_improvement_percent": median(effects), "target_percent": 35, "target_met": median(effects) >= 35}
	b, _ := json.MarshalIndent(report, "", "  ")
	return os.WriteFile(*output, append(b, '\n'), 0644)
}
