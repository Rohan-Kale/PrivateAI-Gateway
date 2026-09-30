# Verification record

## Confirmed

- Repository inspection: the GitHub repository was empty, with no commits or existing files to preserve.
- Local Windows build and `go vet ./...` passed.
- Local Go tests passed, including all policy actions, token encryption/tampering/scope, UTF-8 span validation, cache policy/tenant isolation, output inspection, admission bounds, concurrency, streaming parsing, and Redis queue recovery using miniredis. The real PostgreSQL test skips when external test URLs are absent.
- Ten Python detector/agent unit tests passed.
- Local HTTP smoke tests passed with a Python detector, mock provider, and Go gateway using memory storage. The Redis queue case is explicitly skipped in this mode.
- Local measured HTTP load completed 10,000/10,000 requests across five scenarios. Raw results, including an earlier failed run, are retained. See [BENCHMARKS.md](BENCHMARKS.md).
- Compose configuration parsed. Kubernetes Kustomize rendered all 23 objects. YAML consistency checks passed.

## GitHub Linux CI

The deployment checkpoint `fa998578f033d04701bd07cca7968f909c46827e` passed [GitHub Actions run 36648355597](https://github.com/Rohan-Kale/PrivateAI-Gateway/actions/runs/36648355597). [Recorded job/step evidence](../results/ci-checkpoint.json) is included.

That run verified:

1. `go vet` and Go race-enabled tests.
2. Python unit tests.
3. Docker image builds and a healthy full Compose stack.
4. HTTP integration tests against real PostgreSQL/Redis, including policy actions, policy version changes, streaming restoration, cache behavior, queued inference, and tenant job isolation.
5. A dedicated real PostgreSQL test of conditional policy updates and Redis policy-cache version correctness.
6. Prometheus configuration/rule validation with `promtool`.
7. YAML checks, Kubernetes rendering, and Ansible playbook syntax validation.

The local Windows machine had no running Docker Linux engine and no CGO C toolchain for race detection. CI supplied those checks; they are not represented as local test results. A later verbose local Go test invocation was blocked by Windows Application Control; the earlier local test run and Linux CI passed. Any such local command failure is an environment limitation, not a substitute for a passing run.

## Not verified or not measured

- Applying the Kubernetes manifests to a live cluster, HPA behavior, network-policy enforcement, rolling-update behavior, and persistent-volume recovery.
- Executing Ansible against a remote host, provisioning duration, and host-level idempotence.
- External model compatibility, quality, token-generation speed, or provider billing behavior.
- Sustained open-loop throughput, distributed performance, queue-drain rates, Redis/PostgreSQL failover, TLS termination, or production security hardening.
- Real-world PII/secret detection quality. The synthetic benchmark intentionally includes unsupported entity types and must not be generalized to production accuracy.
- Automatic GitHub issue labeling/commenting and PR mutation: these are deliberately not performed. The agent programs produce local/read-only advisory artifacts.

No performance number is supplied for an unmeasured capability.
