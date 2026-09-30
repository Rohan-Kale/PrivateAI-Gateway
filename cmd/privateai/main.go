package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/Rohan-Kale/PrivateAI-Gateway/internal/gateway"
)

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}
func main() {
	if err := run(); err != nil {
		log.Print("startup or runtime failure: ", err)
		os.Exit(1)
	}
}
func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	var keys map[string]string
	if err := json.Unmarshal([]byte(os.Getenv("API_KEYS")), &keys); err != nil || len(keys) == 0 {
		return errors.New("API_KEYS JSON required")
	}
	for k, t := range keys {
		if len(k) < 16 || len(t) == 0 {
			return errors.New("API_KEYS requires keys of at least 16 characters and nonempty tenants")
		}
	}
	admin := os.Getenv("ADMIN_KEY")
	detectorKey := os.Getenv("DETECTOR_KEY")
	if len(admin) < 16 || len(detectorKey) < 16 {
		return errors.New("ADMIN_KEY and DETECTOR_KEY require at least 16 characters")
	}
	if _, exists := keys[admin]; exists {
		return errors.New("admin key must differ from tenant keys")
	}
	key, err := base64.StdEncoding.DecodeString(os.Getenv("VAULT_KEY"))
	if err != nil {
		return errors.New("invalid VAULT_KEY base64")
	}
	vault, err := gateway.NewVault(key)
	if err != nil {
		return err
	}
	concurrency, err := strconv.Atoi(env("MAX_CONCURRENCY", "32"))
	if err != nil || concurrency < 1 || concurrency > 1024 {
		return errors.New("MAX_CONCURRENCY must be 1-1024")
	}
	var store gateway.Store
	var broker *gateway.Broker
	if env("STORE_MODE", "database") == "memory" {
		m := gateway.NewMemoryStore()
		for _, t := range keys {
			if _, err := m.Policy(ctx, t); err == nil {
				continue
			}
			p := gateway.DefaultPolicy()
			p.Version = 0
			p.Rules["EMAIL"] = gateway.Tokenize
			if _, err := m.PutPolicy(ctx, t, p); err != nil {
				return err
			}
		}
		store = m
		log.Print("development memory storage: no persistence or distributed queues")
	} else {
		startCtx, c := context.WithTimeout(ctx, 10*time.Second)
		defer c()
		s, err := gateway.NewDatabaseStore(startCtx, os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL"))
		if err != nil {
			return errors.New("database/Redis connection failed")
		}
		store = s
		hostname, _ := os.Hostname()
		broker = &gateway.Broker{Redis: s.Redis, Vault: vault, WorkerID: hostname}
	}
	defer store.Close()
	client := gateway.NewHTTPClient()
	e := gateway.NewEngine(store, gateway.HTTPDetector{URL: env("DETECTOR_URL", "http://127.0.0.1:8001"), Key: detectorKey, Client: client}, gateway.HTTPProvider{URL: env("PROVIDER_URL", "http://127.0.0.1:8002"), Key: os.Getenv("PROVIDER_KEY"), Client: client}, vault, concurrency)
	api := &gateway.API{Engine: e, Broker: broker, Keys: keys, AdminKey: admin}
	mux := api.Handler()
	workerMode := len(os.Args) > 1 && os.Args[1] == "worker"
	var workers sync.WaitGroup
	if workerMode {
		if broker == nil {
			return errors.New("worker requires database storage")
		}
		host, _ := os.Hostname()
		for n := 0; n < concurrency; n++ {
			workers.Add(1)
			go func(n int) {
				defer workers.Done()
				if err := broker.Worker(ctx, e, gateway.WorkerName(host, n)); err != nil {
					log.Print("worker startup failed")
					stop()
				}
			}(n)
		}
		// Worker port exposes only health/readiness/metrics, never public inference or admin APIs.
		internal := http.NewServeMux()
		for _, path := range []string{"/healthz", "/readyz", "/metrics"} {
			internal.Handle(path, mux)
		}
		mux = internal
	}
	server := &http.Server{Addr: env("LISTEN_ADDR", ":8080"), Handler: mux, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 65 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	done := make(chan error, 1)
	go func() { log.Print("listening on ", server.Addr); done <- server.ListenAndServe() }()
	select {
	case <-ctx.Done():
	case err := <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			stop()
			return err
		}
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdown)
	workers.Wait()
	return nil
}
