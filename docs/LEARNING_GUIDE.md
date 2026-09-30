# Understanding PrivateAI Gateway, from the first request to the evidence

This guide explains the project as an engineering system. Read it alongside [the file-by-file reference](FILE_GUIDE.md), [experiment instructions](EXPERIMENTS.md), and [security limitations](SECURITY.md). It distinguishes implemented behavior, measured behavior, and capabilities that still need human/host validation.

## 1. The problem the gateway addresses

An application may send a prompt containing a customer's email, an account number, or a credential to a model provider. If the application calls the provider directly, the provider sees that content immediately. A privacy gateway sits between them and decides what content may cross that boundary.

PrivateAI Gateway accepts a limited chat HTTP request, identifies the tenant, inspects the text, applies that tenant's policy, calls the configured provider with the resulting text, checks the output, and returns a response. It does not train a model. It does not make an arbitrary provider private. It also cannot protect secrets that its recognizers fail to identify.

There are three separate questions:

1. **Functionality:** Does block/redact/tokenize work for recognized entities?
2. **Security effectiveness:** Which sensitive values does the detector miss or incorrectly label?
3. **Operational performance:** How quickly and reliably does the complete service handle its workload?

A passing unit test can establish a behavior without answering the other two questions. The new experiments exist to avoid confusing them.

## 2. One concrete request

Suppose the client submits `Please summarize this for alice@example.com` using the demo tenant's API key.

1. The HTTP API checks the bearer key and derives `demo` from server configuration. A client cannot impersonate another tenant by supplying a tenant name in a header.
2. It rejects unsupported fields and oversized requests. It acquires an inference slot; if all slots are occupied, the synchronous API returns 429.
3. The policy store reads the current PostgreSQL version for `demo`. It can then use the Redis policy document for that exact version.
4. The Python detector returns an EMAIL span: the start and end positions of the address in the UTF-8 bytes. It does not choose the action.
5. The Go policy engine sees EMAIL=tokenize. It substitutes a random token such as `<PAI_randomhex>` and stores an encrypted mapping from that token to the address.
6. The model provider receives `Please summarize this for <PAI_randomhex>`. The normal mock simply echoes it. A real compatible provider could generate a new answer instead.
7. The complete provider output is inspected. If it contains a newly generated sensitive value, the output policy applies too.
8. If `restore` is true, only tokens belonging to this request and tenant are replaced with their original values. The authenticated client sees its authorized address again.

If the policy were EMAIL=redact, the provider would receive `[REDACTED_EMAIL]` and no mapping would exist. If EMAIL=block, the provider would not be called. If EMAIL=allow, it would receive the address unchanged. These are intentionally different decisions.

## 3. Why each technology is present

| Technology | Its job here | What it does not establish by itself |
|---|---|---|
| Go | HTTP gateway, policy execution, provider client, worker loops, encryption, concurrency limits | Merely using goroutines does not prove a 200-request capacity claim. |
| Python | Lexical detection, mock/recording services, developer agents, experiment controllers and analysis | A regex-based detector is not a trained ML classifier; a deterministic agent is not necessarily an LLM agent. |
| HTTP and JSON | A small interoperable boundary between client, gateway, detector, and provider | Internal HTTP is not encrypted transport; remote links need TLS. |
| PostgreSQL | Durable, authoritative policy documents and versions | It does not store raw prompts or perform inference. |
| Redis | Fast key/value lookups, expiring encrypted data, and stream-based work delivery | It does not make execution exactly once or guarantee faster end-to-end policy lookup. |
| Docker | Reproducible service images with separate processes/filesystems | Containers are not separate physical machines. |
| Compose | Starts and connects the local collection of services, health checks, volumes, and replicas | It is not Kubernetes and does not prove cluster behavior. |
| Kubernetes | Describes pods, replicas, services, storage, probes, disruption budgets, and gateway autoscaling | Rendering YAML is not proof of successful live deployment. |
| Prometheus | Scrapes numeric measurements and evaluates alert rules | It does not itself prove notification delivery or manufacture percentile observations. |
| Alertmanager | Groups/routs firing alerts to the configured local experiment webhook | A local receipt is not the same as a person receiving an email or SMS. |
| Ansible | Applies repeatable host configuration and starts a worker service | A syntax check is not a provisioning-time benchmark. |
| KVM/libvirt | Optional hardware-assisted Linux virtualization support on an explicitly selected host | Installing tools does not create a fresh VM or demonstrate nested virtualization performance. |
| Git/GitHub | Version history, remote source hosting, CI runs, and reviewable checkpoints | Pushed code is not a continuously hosted API. |
| WSL | Runs a local Linux environment on this Windows machine | It is still this computer, not cloud infrastructure. |

The Go libraries `pgx` and `go-redis` speak the database protocols. `miniredis` supplies an in-process Redis-compatible server for unit tests; the Docker experiments use the real Redis server. PyYAML checks configuration syntax. The optional `ansible.posix` collection provides a filesystem mount module.

## 4. Detection versus policy

`detector/core.py` searches for known patterns. It recognizes a selection of email, North American phone, SSN, payment-card, API-key, credential-assignment, and private-key formats. A Luhn checksum reduces some card-number false positives, but a checksum is not proof that a number is sensitive.

The detector reports **where** something appears and **what kind** it appears to be. `engine.go` decides **what to do** based on policy. This separation lets an administrator change actions without changing Python recognizers.

Offsets are in UTF-8 bytes because Go slices strings by bytes. An emoji may occupy multiple bytes. If Python returned character positions and Go used them as byte positions, the gateway could corrupt a string or mask the wrong content. The detector converts positions; the gateway checks bounds, ordering, kinds, and UTF-8 boundaries again before applying them.

The larger exposure experiment demonstrates the baseline's limits. Of 600 synthetic secret cases, 350 were prevented and 250 reached the recording provider. Recognizable documentation placeholders also caused 50 of 300 benign cases to be blocked. Those are real test results, not a claim that the software protects 58.3% of arbitrary real-world secrets. The corpus deliberately includes difficult unsupported forms and is not representative of every application.

An unlabeled high-entropy string can be a harmless request identifier or a secret. No simple regex can always know its meaning. Improving this requires a defined threat model, context-aware detection, representative negative examples, and another evaluation dataset—not merely adding enough rules to pass the existing fixture file.

## 5. Encryption and reversible tokens

Redaction destroys the original in the provider-bound text. Tokenization keeps a temporary way to restore it for an authorized response. The token itself is random and does not encode the private value.

`crypto.go` uses AES-256-GCM. Encryption hides the value; GCM authentication detects changes to the ciphertext. Associated data binds a vault mapping to a tenant/request scope, so a ciphertext copied to another scope fails authentication. Each encryption uses a fresh random nonce.

Redis stores the encrypted mapping for ten minutes. There is no public endpoint to convert arbitrary tokens back to values. Restoration uses only the current request's mapping, and replacement is simultaneous so restored text is not recursively treated as another token.

The encryption key is configuration, not a committed source constant. The `.env` helper generates random keys for local use. Encryption does not protect against an attacker controlling the gateway process and its keys. The current design also has no seamless multi-key rotation; read the retention/rotation limitations before changing a key in a running stack.

## 6. PostgreSQL policies and the caching tradeoff

A policy has a default action, optional entity-specific rules, a restoration flag, a response-cache TTL, and a version. The version is an optimistic concurrency check: an editor must submit the version it read. If another editor has updated the policy, the first editor's stale write returns 409 instead of overwriting the newer policy.

The normal cached read does:

```text
PostgreSQL: read current version
Redis: read document cached under tenant + version
Go: decode and validate document
```

This avoids serving an old cached policy after a newer version has been observed. It also adds a Redis network operation. For a tiny policy and a fast local database, reading the whole row directly can be faster:

```text
PostgreSQL: read current version + document
Go: decode and validate document
```

That is exactly what `cmd/policybench` compares. It does not time model generation or the detector. The first measured run found a negative median improvement (roughly -76%): the cached treatment took longer. This is not a failed experiment; it is evidence that the proposed 35% speedup claim is unsupported for this workload.

The response cache is different from the policy cache. It caches safe inference output under an HMAC of tenant, policy version, and request. Tokenized requests bypass it so restored private values and request-specific token mappings are not reused. Even a response-cache hit still checks policy version and inspects input.

## 7. Synchronous requests versus queue jobs

`POST /v1/chat/completions` keeps the client request open until inference completes. Go handles many requests concurrently, but a bounded channel acts as admission control. Concurrency is bounded even though goroutines are lightweight.

`POST /v1/jobs` returns a job ID quickly. The encrypted request waits in a Redis Stream. A worker claims it, loads the current policy, performs the same inference engine, stores an encrypted result, acknowledges the stream entry, and deletes the completed stream item. The client polls its own tenant's result endpoint.

Consumer groups track delivery and pending jobs. If a worker stops after claiming a job, another worker can reclaim it after 90 seconds. Inference has a shorter deadline. Failed work is retried up to three times; policy blocks terminate immediately. Bad encrypted payloads go to a small dead-letter record containing only the source ID.

This is **at-least-once execution**. If a worker calls the model successfully and crashes before committing its result, recovery may call the model again. A Redis transaction cannot undo or atomically commit an external provider's side effect. Exactly-once billing would need a separate provider idempotency design.

The new result metadata records the worker identity and enqueue/start/finish timestamps. That lets experiments distinguish queue wait, service duration, and client-observed latency, and verify that multiple worker containers actually processed requests.

## 8. Streaming, precisely

The provider client can consume Server-Sent Events (SSE). Each event carries a JSON text delta. The implementation requires a final `[DONE]` marker, bounds total size, and treats a truncated provider stream as failure.

It then scans the **complete** generated output before releasing client events. That catches patterns split across provider chunks. After inspection and restoration, it emits Unicode-safe SSE deltas to the client.

Consequently, this is buffered streaming compatibility. The first event waits for full generation. It is incorrect to call it low-latency token pass-through. Immediate streaming would require a carefully evaluated incremental detector, a buffering strategy, and decisions about secrets too long to fit within the retained window.

## 9. Metrics, alerts, and evidence

Counters accumulate occurrences: requests, errors, blocks, cache hits, job completion/failure. Gauges describe a current state: admitted inference count and queue depth. Histograms place observations into cumulative latency buckets and retain a sum/count.

The added `privateai_policy_lookup_seconds` histogram measures store calls separately. `privateai_queue_wait_seconds` measures first-attempt time from enqueue to worker processing. Queue depth counts uncompleted stream entries, including delivered pending work. It is not identical to the number of jobs that have never been claimed.

Prometheus pulls `/metrics` periodically. Alert rules examine those time series and may require a condition to remain true for a pending interval. Alertmanager then sends a notification. Total receipt latency includes scrape scheduling, evaluation scheduling, the pending interval, routing/grouping, and delivery—not just the rule's `for` field.

The fault experiment stops a service in the isolated Compose project, records the injection timestamp, and waits for the local webhook receiver's actual receipt timestamp. Repeated or old notifications are filtered. A missing notification is recorded as a failure. This tests the configured local monitoring chain; it is not a guarantee for every future deployment.

## 10. Reading the sustained-load report

The load generator runs as its own container and keeps 200 clients active for 15 minutes. Each client has one outstanding job and waits for its result before sending another. This is a closed-loop experiment. It does not simulate a fixed external arrival rate that continues while the server falls behind.

The provider deliberately sleeps for one second and returns deterministic text. That creates a controlled service time without a paid model. Three workers have 80 slots each. The test reports real PostgreSQL/Redis behavior, but all processes still share one physical machine.

- **Successful jobs/second:** completed jobs divided by elapsed time, including final drain.
- **p50:** half of observed jobs finished within this duration.
- **p95/p99:** useful tail-latency descriptions; they are not guarantees for every request.
- **Queue growth:** whether pending work accumulates over time.
- **Peak outstanding clients:** client-side concurrency, distinct from actual provider calls executing simultaneously.
- **Per-worker completions:** evidence that the replicas did useful work.
- **Resource samples:** CPU/memory and sampled inflight/queue measurements; sampling can miss short peaks.

Compressed JSONL retains individual observations. Errors remain in the report. If polling fails after submission, the job could still finish later; client failure is not silently reclassified as success. The mock's fixed response time and same-host topology must accompany any résumé number derived from this experiment.

## 11. The engineering agents and human timing

The issue agent classifies issue text into a label, priority, and reproduction-needed flag using deterministic rules. The PR agent scans added diff lines for credential patterns and unsafe configuration and notes source changes without test changes. Neither posts comments, changes labels, merges code, or executes diff content.

Optional model assistance creates a bounded, sanitized advisory summary through the gateway. The prose is not treated as commands. The default deterministic mode is reproducible and works without model credentials.

The triage experiment times a person reading and reviewing cases, with or without the suggestion. It includes corrections and stops only after the correct synthetic label/priority is entered. A script running in 1 ms says nothing about a human saving 40% of triage time. The human experiment is intentionally interactive and has no fabricated result until someone completes it.

## 12. Provisioning, KVM, networking, and mounts

Ansible connects to a selected Ubuntu host over SSH and converges it toward a declared configuration. The base worker role installs Docker, writes a private environment file, pulls a selected image, and manages a systemd service. Handlers restart the service when configuration changes.

Optional roles add KVM/libvirt host support, an explicitly named bridge/subnet, and an existing filesystem mounted under `/srv/privateai/`. They reject conflicting configuration and do not format disks. The mount is accessible inside the worker container but is not required by the Redis-backed inference engine.

The provisioning timer requires a real SSH target. Manual mode waits while a human performs setup; automated mode invokes Ansible. Both end only when a job completes on the specific new worker. Identical fresh images, equivalent cache conditions, and repeated trials matter. A second idempotent Ansible run is useful, but it is not comparable to first-time manual setup.

## 13. Repository history and honest presentation

Changes are committed at testable checkpoints and pushed to GitHub. GitHub CI can validate behavior on another Linux machine, but it does not turn the API into a hosted product. The original repository was empty, so no earlier application was replaced. A user-edited README line has been left untouched during this phase.

Raw credential-like fixtures initially triggered GitHub push protection even though they were synthetic. The corrected design commits a deterministic generator and fingerprint instead. No secret-scanning exception was used. The amended unpublished commit replaced the blocked one; outgoing history was verified before pushing.

In an interview, emphasize the engineering decisions and their evidence: scope-bound encrypted restoration; authoritative policy version checks; at-least-once queue recovery; output-inspection latency tradeoffs; a benchmark that revealed slower cache reads; and an exposure corpus that found real detector gaps. Explaining an honest negative result is more defensible than quoting an unsupported target.
