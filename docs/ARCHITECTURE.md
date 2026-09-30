# Architecture and invariants

## Request path

The gateway resolves a tenant from an API key, validates a bounded text request, and acquires a nonblocking concurrency slot. Saturation returns 429; admitted requests have a 55-second inference deadline. Unknown policies fail closed. Readiness checks storage and an authenticated empty detector request; provider availability is intentionally not part of readiness.

Each message is inspected by the detector. Detections are sorted, overlap-merged in Python, and checked again in Go for valid kinds, non-overlap, bounds, and UTF-8 boundaries. `block` stops processing before provider invocation. `redact` substitutes a type marker; `allow` leaves the detected value intact; `tokenize` substitutes a cryptographically random token.

The provider receives only transformed messages. The complete output is inspected with the same policy, with output-side `tokenize` treated as redaction: newly generated PII is not eligible for restoration. Finally, only tokens from this tenant/request's input vault may be restored when its policy permits it. There is no public detokenization endpoint.

The gateway does not join separate input messages for detection. Obfuscation and secrets intentionally split across messages can evade the lexical detector. Detection is a documented baseline, not a comprehensive data-loss-prevention guarantee.

## Policy consistency

PostgreSQL stores one JSONB document and increasing version per tenant. A new policy uses expected `version: 0`; updates use the version last read. The conditional update returns 409 for a competing or stale writer.

Every inference reads the current version from PostgreSQL before looking in Redis under `policy:<tenant>:<version>`. Redis avoids repeatedly fetching/parsing the JSON document, but **does not eliminate the database round trip**. Old cache entries expire after five minutes and cannot override a newer version read. A request already admitted uses its policy snapshot until completion; policy changes do not cancel in-flight requests. Workers read policy at execution time, so queued requests do not carry stale policy snapshots.

See the [pgx connection-pool API](https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool) for the underlying pooled database client.

## Reversible tokens and cache

- AES-256-GCM uses a fresh random nonce on every write. The 32-byte key is supplied in `VAULT_KEY` as base64.
- A token is `<PAI_` plus 128 random bits encoded as hex plus `>`.
- Vault associated data binds ciphertext to `tenant:requestID`; Redis stores the encrypted mapping with a ten-minute TTL. Request IDs and tokens are random, not derivatives of private values.
- Token restoration is simultaneous, not recursive. Tokens invented by a provider or originating in a different request are not resolved.
- Raw input containing the reserved `<PAI_` prefix is rejected. There is no cross-request token reuse.
- The response-cache key is an HMAC of tenant, policy version, model/messages, and streaming flag. The original request is not stored as a key.
- Cached values are encrypted and tenant/policy separated. Tokenized requests bypass response caching to avoid persisting restored private values or reusing request-specific tokens.
- Cache hits still inspect input, and PostgreSQL still verifies policy version. The detector must be available even for a cached response.
- TTL is configurable from 0 to 3,600 seconds. The model provider URL is deployment configuration, not part of the cache key: flush response-cache keys or rotate the vault key when switching provider identity under the same model name.

The memory store implements the same interfaces for local demonstrations; it is process-local, loses data on restart, and is not a substitute for Redis/PostgreSQL.

## Queue and worker semantics

`POST /v1/jobs` encrypts the complete raw request before storing it in Redis Streams. The queue never puts plaintext prompts or restored results into Redis. Enqueue plus initial job status is a Lua transaction. Admission rejects new jobs once the stream reaches 10,000 entries; pending work is never trimmed to make room.

Workers use a consumer group and `[XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)` to recover entries idle for 90 seconds. Each inference runs for at most 55 seconds. A failed attempt remains pending; the next claim retries it. Three unsuccessful attempts produce a terminal failure. Explicit policy blocks terminate immediately. Malformed encrypted jobs are removed and only their stream IDs are retained in a bounded dead-letter stream.

Result storage, acknowledgement, stream deletion, and retry-counter cleanup are atomic. A previously completed result can suppress a repeated delivery. This is **at-least-once execution**: a crash after a provider responds but before Redis commits the result can cause another provider call. No exactly-once billing guarantee is claimed. There is no provider-side idempotency integration.

Job status and results expire 24 hours after their most recent write. An unprocessed queue entry can remain in the stream while workers are offline; it is rejected as expired when a worker eventually reads it. Redis AOF can retain historical encrypted values until rewrite. Queue/result encryption uses the shared vault key; rotating that key invalidates unfinished jobs and old results.

Worker concurrency is `MAX_CONCURRENCY` per process. Each worker replica has its own admission bound; this is not a global or per-tenant rate limit. Kubernetes can scale the worker Deployment, and Compose can scale the worker service. Kubernetes automatic scaling is CPU-based for the gateway only; queue-depth-driven worker autoscaling is not implemented.

## Streaming

The HTTP provider client accepts SSE deltas and reassembles them through `[DONE]`, bounded to 256 KiB of decoded content and 512 KiB of stream framing. Incomplete streams fail closed. The output scanner then inspects the complete response and restores authorized tokens. The gateway emits valid SSE JSON deltas of up to 32 Unicode code points, followed by a stop event and `[DONE]`.

This is **buffered streaming compatibility**, not immediate pass-through. Time to first event includes the entire model generation and inspection time. It deliberately avoids the false assurance of inspecting individual chunks while a secret spans chunk boundaries. A future incremental mode needs explicit cross-chunk detection semantics and a separately evaluated leakage/latency tradeoff.

## Observability

Metrics contain aggregate counters and duration sum/count, not prompts, tenant labels, tokens, or error payloads. The duration summary supports mean latency; it does not expose server-side p95/p99. Percentiles in the benchmark report are measured by the client. Metric names follow [Prometheus naming guidance](https://prometheus.io/docs/practices/naming/).

Prometheus scrapes gateway and worker instances. Example queries:

```promql
sum(rate(privateai_requests_total[5m]))
sum(rate(privateai_cache_hits_total[5m])) / clamp_min(sum(rate(privateai_requests_total[5m])), 0.001)
sum(rate(privateai_request_duration_seconds_sum[5m])) / clamp_min(sum(rate(privateai_request_duration_seconds_count[5m])), 0.001)
sum(privateai_inflight)
sum(increase(privateai_jobs_failed_total[10m]))
```

Errors include policy blocks and capacity rejections. Authentication failures and invalid HTTP requests are rejected before engine counters increment. Alerting distinguishes availability and terminal job failures but does not include an Alertmanager deployment or notification routing.
