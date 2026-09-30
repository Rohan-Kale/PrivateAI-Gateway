# First improvement round

The [September 30 baseline](CLAIMS_REPORT.md) and its raw files remain unchanged. Targets remain hypotheses; changes below do not establish a new percentage until evaluated.

## Implemented changes

- Detection inspects URL/base64 representations up to two decoding layers and 4,096 characters per encoded token. Findings cover the original encoded token so a policy can remove the actual transmitted representation. This is bounded inspection, not arbitrary recursive deobfuscation.
- Structurally plausible JWTs with JSON headers/payloads are treated as secrets. Signature verification is not performed; the scanner identifies potential disclosure, not token authenticity.
- Only three exact assignment placeholders (`YOUR_API_KEY_HERE`, `YOUR_PASSWORD_HERE`, `YOUR_TOKEN_HERE`) are exempted. Adjacent real credentials and placeholder suffixes remain scanned. These are lexical conventions, not proof a literal could never be used as a password.
- The gateway additionally scans concatenated message content. SECRET spans crossing boundaries are projected back onto the original messages, merged with individual detections, and processed under the existing allow/redact/tokenize/block policy. Roles and message structure remain intact. This adds one detector call to multi-message requests and can introduce boundary-related false positives; it needs measurement.
- The mock provider directly counts simultaneous executions under a lock. A soak starts only after an idle counter reset and records the ending count/peak. This is a mock execution measurement, distinct from client concurrency and sampled Prometheus sums.
- Fault protocol v2 checks gateway health, clear Prometheus and Alertmanager state, and actual delivery of the previous matched notification's resolution. The state must remain healthy for 15 seconds. A timeout prevents another injection; it is not recorded as successful detection. The Alertmanager inspection port is bound to local loopback only.

## Evaluation design

The original 900 cases are now a development/regression set because their failures informed these changes. A separate 640-case synthetic validation corpus uses distinct templates, 400 secret cases and 240 benign cases, and a frozen canonical fingerprint. Its author knows the implementation: **it is not a blinded independent holdout**. Opaque random secrets remain in both datasets alongside benign opaque identifiers. No entropy-only blocking rule was introduced to inflate prevention at the expense of benign traffic.

The validation set includes nested encodings, fully percent-encoded values, encoded private keys, three-message fragments, Unicode fragments, JWT context, and benign encoded prose. The generator does not import detector code. Raw synthetic credential fixtures remain ignored by Git and are generated inside the Python image; only the generator and manifest are committed.

## Measured detection and instrumentation checkpoint

The gateway and Python images built from `05dd83f` produced these actual results:

| Test | Prevention | Benign false blocks | Invalid outcomes |
|---|---:|---:|---:|
| Original development/regression corpus | 550/600 = 91.67% | 0/300 | 0 |
| Distinct synthetic validation corpus | 360/400 = 90.00% | 0/240 | 0 |

The original baseline was 350/600 prevented and 50/300 benign blocked. Remaining exposures in both new evaluations are the opaque, unlabeled family. In the validation corpus, benign bare identifiers have the same observable form as these opaque secrets. Reaching 99% by blocking every opaque identifier would conceal a false-positive tradeoff; these results do not justify a 99% claim.

A separate **60-second instrumentation smoke test**, not a new 15-minute capacity result, completed all 9,611 jobs. The single mock provider's synchronized counter observed a peak of exactly 200 active executions and returned to zero. Raw reports live in [results/improvement-round-1](../results/improvement-round-1/), with short-load samples under `smoke/`. The short report retains its older generic client-concurrency warning; its additional `provider_execution` field supplies the direct mock observation. All runs use synthetic content and a mock provider, not a real model.

Rebuild the isolated stack, run the exposure suite, then the load and fault experiments. Preserve existing work/evidence before rerunning; published baseline reports are immutable. Never combine v1 and v2 fault trials into a single success rate.

## Completed sustained run

The updated stack built from `22f7e04` maintained 200 closed-loop clients for 900 seconds and drained in 905.107 seconds total. **142,813/142,813 jobs completed**, with zero reported failures. Actual throughput over that elapsed time was 157.786 jobs/s. Client p50/p95/p99 latency was **1.260/1.273/1.283 seconds**. Queue-wait p95/p99 was **1.305/1.826 milliseconds**.

The mock's synchronized counter started at zero, recorded **142,813 executions and a peak of 200 simultaneously active executions**, and finished at zero active calls with the same reset epoch. This establishes an observed peak, not that all 200 model calls remained continuously active throughout the run. The provider used a synthetic one-second delay. Three workers processed jobs with real PostgreSQL and Redis on one physical host.

All 142,813 compressed samples were counted independently and matched the report. There were 126 resource samples with no sampling errors; worker count remained three and sampled stream depth stayed within 145–200 entries. The final sample precedes full drain; stream depth includes claimed jobs. Server resource samples exclude the one-off load-generator container. Raw data is under `results/improvement-round-1/sustained/`. Do not infer a causal latency improvement from comparison with the earlier separate load run; this was not a paired inference-latency experiment.

## Completed fault protocol v2

All **12/12** recorded trials received a fresh matching local webhook notification within 120 seconds and restored the service. Receipt latencies:

| Stopped service | Trial 1 | Trial 2 | Trial 3 |
|---|---:|---:|---:|
| All three workers | 18.313 s | 14.556 s | 14.496 s |
| Detector | 19.441 s | 19.001 s | 18.646 s |
| PostgreSQL | 14.268 s | 14.855 s | 14.395 s |
| Redis | 19.002 s | 19.017 s | 19.005 s |

Every record includes the verified baseline and its wait time. These trials apply to sequential service outages beginning with clear evaluation/routing state and verified delivery of the previous matched resolution. Monitoring-process restart behavior and arbitrary compound failures were not tested. The original 11/12 result and missed notification remain in the historical baseline; v2 does not prove that the exact interrupted-stack failure has been eliminated in every scenario.

## Policy comparisons

The initial two-arm optimized-cache run measured **2.843% median improvement versus direct PostgreSQL**, across eight paired rounds of 2,000 measured lookups per mode. The median of round medians was 191.589 microseconds for direct reads and 185.803 microseconds for decoded-cache reads. One round favored direct reads. This is not a 35% improvement claim.

The follow-up three-arm comparison additionally measures the previous Redis-only document-cache implementation under the same randomized workload. Its distinct baseline must accompany any improvement reported against that older implementation. The direct-PostgreSQL target is retained separately.

That completed v3 run (`e8f794e`) measured **44.550% median paired latency reduction versus the previous Redis path** and **3.281% median paired improvement versus direct PostgreSQL**. Every legacy comparison favored the optimization (43.491–46.322%); one direct-read comparison favored the baseline. Median round medians were 335.341 microseconds (legacy Redis), 192.217 microseconds (direct PostgreSQL), and 185.783 microseconds (decoded cache). Each of the three modes had 16,000 measured samples after warmups. `target_met` remains false for the original 35%-versus-direct target.

A defensible statement is: "Reduced policy lookup latency 44.6% versus the previous Redis-backed implementation using a bounded decoded cache while retaining authoritative PostgreSQL version checks." It would be incorrect to say Redis caching is 44.6% faster than direct PostgreSQL.

## Evidence and verification

Raw JSON reports, compressed per-job samples, resource time series, and append-only alert receipts are under `results/improvement-round-1/`; `SHA256SUMS` fingerprints their exact bytes. `smoke/` and `sustained/` retain separate load runs. Alert receipt history can include earlier events; the fault records identify the exact fresh matching receipts used for this protocol. Runtime images for detection/faults came from `05dd83f`, the updated sustained run from `22f7e04`, and the three-arm benchmark from `e8f794e`. Uncommitted report/README edits did not change those executable paths.

Local Go tests/vet and 28 Python tests passed. The three-arm checkpoint passed [GitHub CI run 36736798964](https://github.com/Rohan-Kale/PrivateAI-Gateway/actions/runs/36736798964), including race tests, real PostgreSQL/Redis integration, all three cache-mode correctness checks, and deployment validation. Human time savings and fresh-host provisioning duration remain unmeasured.

## New files

| File | Purpose |
|---|---|
| `detector/representations.py` | Bounded decoding and JWT structure inspection, returning original text spans. |
| `internal/gateway/input.go` | Message-boundary detection, span validation, projection, and overlap merging. |
| `internal/gateway/input_test.go` | Split-message policies, restoration, and invalid-span rejection. |
| `mock/activity.py` | Thread-safe provider execution counters and idle-only reset. |
| `tests/test_detector_representations.py` | Encodings, UTF-8 source spans, JWT negatives, placeholders, and benign identifiers. |
| `experiments/validation_corpus.py` | Independent synthetic templates with a fixed seed and no detector imports. |
| `experiments/fixtures/validation-v2/manifest.json` | Frozen validation dataset fingerprint and size. |

## Remaining decisions and studies

Policy caching now uses a decoded process cache after the authoritative version check, with Redis backing cold process reads. This preserves existing freshness semantics. Cached maps are copied, versions/tenants must match, and capacity is bounded at 1,024 tenants per process. The paired benchmark labels this new treatment explicitly; its speedup must still be measured. Tests check isolation, capacity, external updates, and deletion of a previously cached policy.

Human triage and manual provisioning timing still require actual participants/fresh hosts. No speedup or duration is assumed for those studies.

The issue agent now exposes matched signals and review steps without echoing credential values. Study v2 separates the participant's rubric from the issue body: v1 accidentally fed the rubric's word "security" to the classifier. No human measurements were collected under v1. Existing synthetic cases are development examples and cannot establish independent classification accuracy.

Provisioning reports separate setup and first-job verification time and record an operator-defined `--profile` (default `worker-only`). Use an identical profile describing the enabled KVM/network/mount features for both modes. `python -m experiments.compare_provision REPORTS... --output COMPARISON.json` requires three completed trials per mode, matching image/cache/profile conditions, and unique fresh-host identities. It computes medians/ranges/reduction rather than assuming a baseline. Profiles and image freshness remain operator attestations; publish all failed attempts too.
