# Claim validation: September 30, 2026

These are observations from a local experiment, not universal performance or security guarantees. The raw reports and compressed request samples are in [results/claims-2026-09-30](../results/claims-2026-09-30/). Reproduce the protocols using [EXPERIMENTS.md](EXPERIMENTS.md).

## Environment and provenance

The gateway, detector, and load images were built from the experiment implementation at `e668a5f2e2f894b2fd1691c82589616e3c4dbe14`. Subsequent changes added human trial tools, optional Ansible roles, explanatory documentation, and report analysis; they did not change the measured inference implementation. The fault controller records the later source checkout revision. The existing unrelated README whitespace edit remained uncommitted. Container provenance records an explicit source revision but cannot independently assess the host's dirty working tree (`working_tree_dirty: null`).

All services ran locally in Docker Engine 29.1.3 inside Ubuntu WSL, with 16 logical CPUs and approximately 15.18 GiB visible memory. This was one physical computer, not a cloud or multi-host Kubernetes deployment. PostgreSQL and Redis were real servers. The sustained-load provider was a mock with a fixed 1,000 ms delay; no paid external model was used.

## Secret exposure: 99% target not met

The independently labeled deterministic challenge corpus contains **900 cases: 600 secret cases across 12 families and 300 benign cases across six families**. It is synthetic and not a blinded real-world holdout. The gateway used SECRET=block, default=redact, restoration disabled, and response caching disabled. The authenticated recording provider captured what actually crossed the gateway boundary.

- Prevented exposure: **350/600 = 58.33%**.
- Secret exposure: **250/600 = 41.67%**.
- Wilson 95% interval for the observed prevention proportion: **54.35–62.21%**; corpus construction limits generalization.
- False blocks: **50/300 = 16.67%** of benign cases.
- Invalid/infrastructure outcomes: **0**.

Each family contains 50 cases. API-key prefixes, classic GitHub tokens, fine-grained GitHub tokens, AWS access IDs, credential assignments, private-key blocks, and Unicode-context recognizable credentials were all blocked in this corpus. URL encoding, base64 encoding, split-message values, generic unlabeled secrets, and JWTs were all exposed. The 50 documented-placeholder benign cases were all falsely blocked. Other benign families were ordinary prose, random identifiers, public contact information, version numbers, and quoted detection rules.

Do not change the résumé claim to “99%” by silently removing unsupported cases. These findings establish concrete detection gaps and a baseline for future evaluation. Preserve this corpus and use a separate holdout when improving recognizers. The manifest hashes canonical JSON; the result's `corpus_sha256` hashes the generated file bytes, so these two fingerprints intentionally differ.

## Sustained queue workload: 200 clients supported in this local test

Three worker containers each had 80 processing slots. A separate load-generator container kept **200 closed-loop clients** active for **900 seconds**, then drained outstanding work. PostgreSQL and Redis backed policy and queue operations throughout.

| Observation | Actual result |
|---|---:|
| Completed jobs / submitted attempts | 142,880 / 142,880 |
| Reported client/job failures | 0 |
| Elapsed time including drain and completion polling | 905.162 s |
| Completion throughput over that elapsed time | 157.850 jobs/s |
| Client latency p50 / p95 / p99 | 1.262 / 1.289 / 1.335 s |
| First-attempt queue wait p50 / p95 / p99 | 0.952 / 1.668 / 5.201 ms |
| Worker service time p50 / p95 / p99 | 1.089 / 1.133 / 1.140 s |
| Jobs completed by the three workers | 47,665 / 47,629 / 47,586 |
| Resource samples / sampling errors | 125 / 0 |
| Sampled Redis stream depth minimum / maximum | 69 / 200 entries |
| Sampled worker count | 3 throughout |

The final resource sample still saw 69 stream entries because scraping and sampling precede final drain completion. Stream depth includes claimed work, not only jobs waiting to start. Completed request samples were independently counted from the compressed raw file and matched all 142,880 reported completions. No accumulating queue beyond the 200-client workload was observed; a closed-loop test inherently slows new arrivals when clients wait.

Docker resource peaks and the full time series are retained. CPU percentages are relative to one logical CPU; peaks across containers are not simultaneous totals. The one-off load-generator container was not included in the Compose service resource sample. Prometheus's summed inflight gauge reached 239 because separately scraped worker values describe different instants; it is not evidence of 239 concurrent provider calls. The defensible claim is **200 sustained clients**, not an exact synchronized provider-concurrency measurement.

## Policy lookup: 35% speedup target not met

Eight randomized paired rounds measured 2,000 lookups per mode after 200 warmups per mode, for **16,000 measured lookups per mode**. The provider was not involved. Both paths checked authoritative PostgreSQL state and validated the document.

- Direct PostgreSQL mode: median of round medians **207.048 µs**.
- PostgreSQL-version-check plus warm Redis mode: median of round medians **366.101 µs**.
- Median paired improvement: **−75.936%**; the cached path was roughly **76% slower** relative to the direct path.
- Every paired round favored the direct read; paired improvement ranged from −82.850% to −64.509%.

The extra Redis operation outweighed the saved document fetch for this small local policy. The metric is policy retrieval latency, separate from inference. These numbers do not establish behavior for larger policies, remote databases, or a different consistency design.

## Fault-to-notification measurements

The controller stops one service at a time and measures from immediately before the stop command to receipt at the local Alertmanager webhook. The experiment uses five-second scraping/evaluation and ten-second alert pending periods. Worker faults stop all three worker containers. PostgreSQL/Redis faults surface through readiness checks. Service restoration happens after each trial.

| Stopped service | Trial 1 | Trial 2 | Trial 3 |
|---|---:|---:|---:|
| All three workers | 15.775 s | 12.044 s | 11.779 s |
| Detector | No fresh receipt within 150 s | 19.835 s | 18.332 s |
| PostgreSQL | 18.983 s | 18.627 s | 18.262 s |
| Redis | 18.851 s | 18.710 s | 18.458 s |

**11/12 recorded trials delivered a matching notification within 120 seconds.** Successful receipts ranged from 11.779 to 19.835 seconds. The all-faults-within-two-minutes claim is therefore not established. All twelve recorded trials completed service restoration.

An initial controller attempt successfully measured three worker faults, then failed while restoring the detector: Compose rejected a worker-scaling option when only the detector service was selected. The original log and worker report are preserved. Commit `5ba8931` fixes restoration and saves observations before recovery; the remaining trials resumed from that checkpoint. The earlier interrupted detector attempt has raw receipts but is not one of the twelve completed/restored trials above.

In the resumed detector trial that timed out, a read-only query confirmed Prometheus was firing, but no fresh matching firing notification reached the receiver. A resolved notification appeared after recovery. Retained Alertmanager notification state across the interrupted/restarted stack is a possible explanation; the exact cause was not isolated, so the miss remains a failure. Later detector trials passed. This demonstrates why seeing a firing rule is insufficient evidence of notification delivery.

Local webhook delivery is not email/SMS delivery or a universal fault-detection guarantee. Healthy baseline waits were 20 seconds; monitoring state after interrupted experiments deserves a stricter recovery check in a future protocol.

## Human triage and fresh-host provisioning: not measured

The 40% triage improvement and 20→5 minute provisioning claims remain **unsupported**. Interactive tools are implemented, but no human baseline, reviewed triage session, or equivalent fresh-host provisioning pair has been collected. Scripts explicitly preserve incomplete/failing trials instead of generating a speedup.

The Ansible additions implement optional KVM/libvirt checks, a named Docker bridge/subnet, and mounting an existing filesystem into the worker. CI validates syntax; actual host execution, nested virtualization behavior, and idempotence remain unverified. No guest VM is created automatically.

## What can be stated now

“Built a Go privacy gateway with configurable allow/redact/tokenize/block policies and encrypted, request-scoped reversible tokenization.”

“Validated 200 sustained queue clients for 15 minutes across three local workers with real PostgreSQL/Redis, completing 142,880 mock-provider jobs without reported failures; p95 end-to-end latency was 1.289 seconds.”

The detection and cache findings should be presented as measured limitations and engineering tradeoffs. Kubernetes manifests are provided and rendered in CI, but these measurements came from Compose, not a live Kubernetes cluster.
