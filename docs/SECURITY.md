# Security model and known gaps

This is a portfolio reference implementation. Use synthetic inputs for public demonstrations. No detector accuracy, production readiness, regulatory compliance, or protection against arbitrary secret exfiltration is claimed.

## Trust boundaries

- Client keys identify tenants. Only a separate administrator key changes policy. Caller-supplied tenant headers are ignored.
- The gateway, detector, workers, and secret configuration are trusted. The model provider sees transformed inputs and its output is untrusted.
- Redis holds encrypted prompts, token mappings, cache values, and job results. Tenant-scoped authenticated encryption prevents moving ciphertext between tenants/requests/cache entries. Redis policy documents contain rules but no prompt data.
- PostgreSQL holds policies only. There is no raw-prompt audit table. Request bodies and provider error bodies are not logged.
- Tenant keys are configured centrally in JSON and compared in constant time. This is not OAuth, delegated authorization, key rotation infrastructure, or per-user authorization. Anyone possessing a tenant key has that tenant's access, including its completed jobs.
- The environment key protects data at rest in Redis, not memory, swap, process inspection, compromised hosts, or plaintext service traffic.

## Detection scope

Recognizers cover common email patterns, North American phone formats, selected US SSNs, Luhn-checked card numbers, selected key prefixes, credential assignments, private-key blocks, and structurally plausible JWTs. Secret inspection includes up to two URL/base64 decoding layers for encoded tokens of at most 4,096 characters. Findings cover the original encoded token. JWT signature validity is not checked. General names, addresses, international phone formats, arbitrary opaque strings, deeper/custom obfuscation, and multilingual semantic PII remain outside reliable coverage.

Individual messages and concatenated input content are inspected; cross-boundary SECRET spans are projected onto original messages. This covers recognizable fragments, not arbitrary reconstruction instructions. Output is scanned as a whole to avoid chunk-boundary evasion. False positives are possible, including accidental matches at concatenated boundaries: a valid Luhn sequence is also not proof that a value is an actual card. Three exact assignment placeholders are exempted as documented in [IMPROVEMENT_ROUND_1.md](IMPROVEMENT_ROUND_1.md); their names alone cannot prove they were never used as real passwords. Configuring `allow` intentionally permits recognized content to leave the gateway. Policy `restore: true` intentionally reveals original tokenized values to the authenticated tenant.

The 20-example benchmark is synthetic and not held out. Its results are a fixture check, not an estimate of real-world precision or recall. Improvements should use a separately labeled evaluation set with representative negative examples and error analysis.

## Bounds and failure behavior

Requests have at most 64 messages and 64 KiB of combined message content; the JSON body is limited to 128 KiB. Provider output is limited to 256 KiB; inference has a 55-second deadline. A configured per-process concurrency bound rejects excess inference with 429. The Redis queue admits at most 10,000 uncompleted entries.

Detector/storage/provider failures return generic errors and do not forward unchecked input or partial unchecked output. The public schema rejects unknown top-level fields, non-text content, and unsupported roles. There is no model/tool option passthrough. Provider redirects are disabled.

The Python HTTP servers are small internal services using the standard library, not internet-facing hardened servers. They run behind service-network isolation and gateway admission limits. They do not implement global thread admission, a request-rate limit, or an external reverse proxy. Do not expose them directly to untrusted networks.

## Deployment boundaries

Compose publishes only loopback gateway/Prometheus ports. Kubernetes defaults to ClusterIP/headless services with no public Ingress. Its NetworkPolicy limits inbound traffic to the namespace; it does not isolate applications within that namespace or restrict egress. These manifests assume a trusted demo namespace and a network plugin that enforces policies.

PostgreSQL/Redis links use plaintext within the demo network. For remote worker hosts use verified TLS (`sslmode=verify-full`, `rediss://`, HTTPS detector/provider URLs) and a secret manager. Terminate client TLS at an authenticated ingress or proxy before exposing the gateway. Mount CA certificates as needed. Do not place provider credentials in URLs.

Prometheus and health endpoints are unauthenticated internal endpoints. The admin API shares the gateway port but uses a distinct key. Add ingress restrictions, key lifecycle management, per-tenant quotas, audit metadata, tested backup/restore, image digest pinning and vulnerability scanning before any production consideration.

## Retention and key rotation

Token mappings expire after ten minutes. Job statuses/results expire after 24 hours; response-cache TTL is policy-controlled. TTL expiry is not cryptographic erasure of backups, AOF history, or memory copies. Unprocessed stream entries remain encrypted until consumed and acknowledged; there is no autonomous offline queue sweeper.

All replicas must share the same current vault key. This implementation has no key-ID envelope or multi-key rotation. To rotate, stop intake, drain or discard outstanding jobs deliberately, delete affected cache/vault/result keys according to your retention policy, update secrets across replicas, and restart. Do not claim seamless rotation or backwards decryption support.

## Agents

Agents inspect issue text/diffs as untrusted data. Their default operation is deterministic and read-only. Optional model summaries are sanitized, bounded advisory strings; they are never executed or used to choose privileged actions. The GitHub workflows use `pull_request`, not privileged `pull_request_target`, and request only read access. Synthetic test credentials can trigger the PR scanner; inspect such findings manually rather than automatically dismissing them.
