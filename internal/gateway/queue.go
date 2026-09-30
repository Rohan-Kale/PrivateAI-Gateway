package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

const streamName = "inference:jobs"
const groupName = "inference-workers"
const jobTTL = 24 * time.Hour

type Broker struct {
	Redis *redis.Client
	Vault *Vault
}

func (b *Broker) Submit(ctx context.Context, tenant string, r Request) (string, error) {
	j := Job{ID: newID(), Tenant: tenant, Request: r, Created: time.Now().UTC()}
	raw, _ := json.Marshal(j)
	payload, e := b.Vault.Seal("queue:"+j.ID, string(raw))
	if e != nil {
		return "", e
	}
	stateKey := "job:" + tenant + ":" + j.ID
	state, e := b.Vault.Seal(stateKey, `{"status":"queued"}`)
	if e != nil {
		return "", e
	}
	// Capacity check and enqueue are atomic. Never trim pending/unprocessed entries.
	n, e := b.Redis.Eval(ctx, `if redis.call('XLEN',KEYS[1]) >= 10000 then return 0 end
 redis.call('SET',KEYS[2],ARGV[3],'EX',86400)
 redis.call('XADD',KEYS[1],'*','id',ARGV[1],'payload',ARGV[2])
 return 1`, []string{streamName, stateKey}, j.ID, payload, state).Int()
	if e != nil {
		return "", e
	}
	if n == 0 {
		return "", ErrBusy
	}
	return j.ID, nil
}
func (b *Broker) Result(ctx context.Context, tenant, id string) (JobResult, error) {
	key := "job:" + tenant + ":" + id
	raw, e := b.Redis.Get(ctx, key).Result()
	if e == redis.Nil {
		return JobResult{}, ErrNotFound
	}
	if e != nil {
		return JobResult{}, e
	}
	raw, e = b.Vault.Open(key, raw)
	if e != nil {
		return JobResult{}, e
	}
	var r JobResult
	e = json.Unmarshal([]byte(raw), &r)
	return r, e
}
func (b *Broker) finish(ctx context.Context, msg redis.XMessage, j Job, r JobResult) error {
	key := "job:" + j.Tenant + ":" + j.ID
	raw, _ := json.Marshal(r)
	sealed, e := b.Vault.Seal(key, string(raw))
	if e != nil {
		return e
	}
	return b.Redis.Eval(ctx, `redis.call('SET',KEYS[1],ARGV[1],'EX',86400)
 redis.call('XACK',KEYS[2],ARGV[2],ARGV[3])
 redis.call('XDEL',KEYS[2],ARGV[3])
 redis.call('DEL',KEYS[3])
 return 1`, []string{key, streamName, "attempt:" + j.ID}, sealed, groupName, msg.ID).Err()
}
func (b *Broker) process(ctx context.Context, e *Engine, msg redis.XMessage) {
	id, _ := msg.Values["id"].(string)
	sealed, _ := msg.Values["payload"].(string)
	raw, err := b.Vault.Open("queue:"+id, sealed)
	var j Job
	if err != nil || json.Unmarshal([]byte(raw), &j) != nil || j.ID != id || !identifier.MatchString(j.Tenant) {
		// Retain only a stream ID in the bounded dead-letter stream, never the payload.
		_ = b.Redis.Eval(ctx, `redis.call('XADD','inference:dead','MAXLEN','~',1000,'*','source',ARGV[1]); redis.call('XACK',KEYS[1],ARGV[2],ARGV[1]); redis.call('XDEL',KEYS[1],ARGV[1]); return 1`, []string{streamName}, msg.ID, groupName).Err()
		e.Metrics.Failed.Add(1)
		return
	}
	if prior, er := b.Result(ctx, j.Tenant, j.ID); er == nil && (prior.Status == "completed" || prior.Status == "failed") {
		_ = b.finish(ctx, msg, j, prior)
		return
	}
	attempt, er := b.Redis.Incr(ctx, "attempt:"+j.ID).Result()
	if er != nil {
		return
	}
	_ = b.Redis.Expire(ctx, "attempt:"+j.ID, jobTTL).Err()
	runCtx, cancel := context.WithTimeout(ctx, 55*time.Second)
	defer cancel()
	var result Result
	if time.Since(j.Created) > jobTTL {
		err = errors.New("job expired")
	} else {
		result, err = e.Run(runCtx, j.Tenant, j.Request)
	}
	if err != nil {
		if attempt < 3 && !errors.Is(err, ErrBlocked) && time.Since(j.Created) <= jobTTL {
			return
		}
		reason := "inference failed"
		if errors.Is(err, ErrBlocked) {
			reason = "policy blocked content"
		}
		if b.finish(ctx, msg, j, JobResult{Status: "failed", Error: reason}) == nil {
			e.Metrics.Failed.Add(1)
		}
		return
	}
	if b.finish(ctx, msg, j, JobResult{Status: "completed", Result: &result}) == nil {
		e.Metrics.Completed.Add(1)
	}
}
func (b *Broker) Worker(ctx context.Context, e *Engine, name string) error {
	err := b.Redis.XGroupCreateMkStream(ctx, streamName, groupName, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		return err
	}
	cursor := "0-0"
	for ctx.Err() == nil {
		pending, next, er := b.Redis.XAutoClaim(ctx, &redis.XAutoClaimArgs{Stream: streamName, Group: groupName, Consumer: name, MinIdle: 90 * time.Second, Start: cursor, Count: 1}).Result()
		if er == nil {
			cursor = next
			for _, m := range pending {
				b.process(ctx, e, m)
			}
		}
		entries, er := b.Redis.XReadGroup(ctx, &redis.XReadGroupArgs{Group: groupName, Consumer: name, Streams: []string{streamName, ">"}, Count: 1, Block: time.Second}).Result()
		if er != nil && er != redis.Nil {
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(time.Second):
			}
			continue
		}
		for _, s := range entries {
			for _, m := range s.Messages {
				b.process(ctx, e, m)
			}
		}
	}
	return nil
}
func WorkerName(host string, n int) string { return host + "-" + newID() + "-" + strconv.Itoa(n) }
