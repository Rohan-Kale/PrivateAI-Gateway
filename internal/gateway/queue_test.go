package gateway

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func testBroker(t *testing.T) (*Broker, *Engine) {
	t.Helper()
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	e, _ := setup(t)
	return &Broker{Redis: client, Vault: e.Vault}, e
}
func take(t *testing.T, b *Broker) redis.XMessage {
	t.Helper()
	ctx := context.Background()
	if err := b.Redis.XGroupCreateMkStream(ctx, streamName, groupName, "0").Err(); err != nil {
		t.Fatal(err)
	}
	entries, err := b.Redis.XReadGroup(ctx, &redis.XReadGroupArgs{Group: groupName, Consumer: "test", Streams: []string{streamName, ">"}, Count: 1}).Result()
	if err != nil {
		t.Fatal(err)
	}
	return entries[0].Messages[0]
}
func TestQueueEncryptedDeliveryAndTenantIsolation(t *testing.T) {
	b, e := testBroker(t)
	ctx := context.Background()
	id, err := b.Submit(ctx, "demo", request("alice@example.com"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = b.Result(ctx, "other", id); !errors.Is(err, ErrNotFound) {
		t.Fatal("job leaked across tenants")
	}
	msg := take(t, b)
	if strings.Contains(msg.Values["payload"].(string), "alice@") {
		t.Fatal("raw queued prompt")
	}
	b.process(ctx, e, msg)
	result, err := b.Result(ctx, "demo", id)
	if err != nil || result.Status != "completed" || result.Result.Content != "[REDACTED_EMAIL]" {
		t.Fatal(result, err)
	}
	if n := b.Redis.XLen(ctx, streamName).Val(); n != 0 {
		t.Fatal("completed job not removed")
	}
	if n := b.Redis.XPending(ctx, streamName, groupName).Val().Count; n != 0 {
		t.Fatal("completed job not acknowledged")
	}
	raw := b.Redis.Get(ctx, "job:demo:"+id).Val()
	if strings.Contains(raw, "REDACTED") {
		t.Fatal("unencrypted result")
	}
}
func TestQueueRetryLimit(t *testing.T) {
	b, e := testBroker(t)
	e.Provider = providerFunc(func(context.Context, Request) (string, error) { return "", errors.New("upstream unavailable") })
	ctx := context.Background()
	id, err := b.Submit(ctx, "demo", request("hello"))
	if err != nil {
		t.Fatal(err)
	}
	msg := take(t, b)
	for i := 0; i < 3; i++ {
		b.process(ctx, e, msg)
		result, err := b.Result(ctx, "demo", id)
		if err != nil {
			t.Fatal(err)
		}
		if i < 2 && result.Status != "queued" {
			t.Fatal("failed before retry budget")
		}
		if i == 2 && result.Status != "failed" {
			t.Fatal("retry budget not bounded")
		}
	}
}
func TestQueueBlockNotRetried(t *testing.T) {
	b, e := testBroker(t)
	ctx := context.Background()
	id, err := b.Submit(ctx, "demo", request("sk-testsecret0123456789"))
	if err != nil {
		t.Fatal(err)
	}
	b.process(ctx, e, take(t, b))
	r, _ := b.Result(ctx, "demo", id)
	if r.Status != "failed" || r.Error != "policy blocked content" {
		t.Fatal(r)
	}
}
func TestQueuePoisonMessageIsDiscarded(t *testing.T) {
	b, e := testBroker(t)
	ctx := context.Background()
	_ = b.Redis.XAdd(ctx, &redis.XAddArgs{Stream: streamName, Values: map[string]any{"id": "bad", "payload": "invalid"}}).Err()
	b.process(ctx, e, take(t, b))
	if b.Redis.XLen(ctx, streamName).Val() != 0 || b.Redis.XLen(ctx, "inference:dead").Val() != 1 {
		t.Fatal("poison job not dead-lettered")
	}
}
func TestWorkerReclaimsAbandonedJob(t *testing.T) {
	b, e := testBroker(t)
	ctx := context.Background()
	id, err := b.Submit(ctx, "demo", request("recover me"))
	if err != nil {
		t.Fatal(err)
	}
	msg := take(t, b)
	if err = b.Redis.Do(ctx, "XCLAIM", streamName, groupName, "crashed", 0, msg.ID, "IDLE", 91000).Err(); err != nil {
		t.Fatal(err)
	}
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- b.Worker(runCtx, e, "replacement") }()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		r, _ := b.Result(ctx, "demo", id)
		if r.Status == "completed" {
			cancel()
			if err := <-done; err != nil {
				t.Fatal(err)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("pending job was not reclaimed")
}
func TestQueueCapacityDoesNotTrimPending(t *testing.T) {
	b, _ := testBroker(t)
	ctx := context.Background()
	pipe := b.Redis.Pipeline()
	for i := 0; i < 10000; i++ {
		pipe.XAdd(ctx, &redis.XAddArgs{Stream: streamName, Values: map[string]any{"id": "fixture"}})
	}
	if _, err := pipe.Exec(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Submit(ctx, "demo", request("hello")); !errors.Is(err, ErrBusy) {
		t.Fatal("queue did not reject excess work")
	}
	if b.Redis.XLen(ctx, streamName).Val() != 10000 {
		t.Fatal("pending entries were trimmed")
	}
}
