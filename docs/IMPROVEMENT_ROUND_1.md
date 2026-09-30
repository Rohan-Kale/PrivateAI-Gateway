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

Rebuild the isolated stack, run the exposure suite, then the load and fault experiments. Preserve existing work/evidence before rerunning; published baseline reports are immutable. Never combine v1 and v2 fault trials into a single success rate.

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
