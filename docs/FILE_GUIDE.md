# File-by-file reference

Start with [LEARNING_GUIDE.md](LEARNING_GUIDE.md) for the concepts. This reference explains the files you will see in the repository, what uses them, and which ones are historical results. Paths in the first column are relative to the repository root.

## Root and build configuration

| File | Purpose |
|---|---|
| `README.md` | Main entry point, quickstart, feature list, API overview, links to design and historical measurements. |
| `go.mod` | Go module name, minimum language/toolchain version, and dependency versions. It makes package imports and dependency resolution reproducible. |
| `go.sum` | Checksums for downloaded Go dependency versions. It helps detect altered dependency content; it is not a vulnerability report. |
| `Dockerfile` | Builds the Go executables in a compiler stage, provides an integration-test stage, and copies the gateway into a small non-root runtime image. |
| `Dockerfile.python` | Packages Python detector/mock/agents/tests/experiments. It generates synthetic fixtures inside the image and normally starts the detector. |
| `compose.yaml` | Ordinary local demo services, credentials wiring, volumes, health checks, loopback ports, and optional integration test containers. |
| `.env.example` | Names and placeholder formats of required settings; it contains no working deployment credentials. |
| `.gitignore` | Keeps real `.env` values, caches, scratch files, raw fake-secret fixtures, and local-only measurements out of Git. |
| `.dockerignore` | Keeps secrets, Git history, build caches, scratch files, and generated credential fixtures out of Docker build context. |
| `.gitattributes` | Standardizes text line endings across Windows/Linux and marks image formats as binary. |
| `requirements-dev.txt` | Python development/configuration tooling versions. Runtime detector/agents use the standard library. |

## Go executable entry points

| File | Purpose |
|---|---|
| `cmd/privateai/main.go` | Reads/validates environment settings; connects storage; assembles detector/provider clients, vault, engine, API, and optional broker; starts the HTTP server; runs worker loops in `worker` mode; handles shutdown. |
| `cmd/policybench/main.go` | Runs randomized paired direct-PostgreSQL versus warm-policy-cache measurements. It never invokes the detector or model and cleans up its own temporary tenant. |

## Go application internals

`internal/` is Go's restricted-import convention: these packages belong to this module's application rather than a public general-purpose SDK.

| File | Purpose |
|---|---|
| `internal/gateway/types.go` | Shared request/message/policy/result/job types, interfaces, entity kinds, limits, and named error values. Its JSON tags define the external field names. |
| `internal/gateway/http.go` | Routes, bearer authentication, strict JSON decoding, status codes, policy/job endpoints, readiness/liveness/metrics, and client SSE serialization. |
| `internal/gateway/engine.go` | The privacy pipeline: admission, policy lookup, input detection/transformation, cache handling, vault persistence, provider inference, output inspection, authorized restoration. |
| `internal/gateway/clients.go` | HTTP detector and model-provider clients, pooling/deadlines, response-size bounds, and SSE collection/termination checks. |
| `internal/gateway/crypto.go` | AES-GCM encryption/decryption, associated-data scope binding, HMAC cache keys, and random request/token IDs. |
| `internal/gateway/store.go` | In-memory development store and actual PostgreSQL/Redis store; versioned policy reads/writes, cache selection, TTL values, and database-only policy benchmark baseline. |
| `internal/gateway/queue.go` | Encrypted job submission/status, Redis Lua operations, consumer groups, retry budget, idle recovery, dead-letter metadata, worker/timestamp result metadata, and first-attempt queue-wait observations. |
| `internal/gateway/metrics.go` | A thread-safe fixed-bucket Prometheus histogram implementation with count and sum; no individual prompt or sample retention. |
| `internal/gateway/engine_test.go` | Unit tests for policies, tokens, isolation, malformed spans, output inspection, admission, HTTP/SSE, concurrency, and small Go microbenchmarks. |
| `internal/gateway/queue_test.go` | Uses miniredis to test encrypted jobs/results, tenant isolation, three-attempt failure, immediate block, malformed jobs, abandoned-job recovery, and queue capacity. |
| `internal/gateway/database_test.go` | Optional real PostgreSQL/Redis test for conditional updates and cache-version correctness. Skips without explicit test connection URLs. |
| `internal/gateway/metrics_test.go` | Verifies cumulative histogram buckets/counts reflect real observations. |

## Python runtime services and agents

| File | Purpose |
|---|---|
| `detector/__init__.py` | Marks the detector as an importable Python package and describes its scope. |
| `detector/core.py` | Regex recognizers, Luhn checking, overlap merging, and conversion to UTF-8 byte offsets. It does not choose allow/redact/tokenize/block. |
| `detector/server.py` | Authenticated internal `/detect` HTTP service around `core.detect`; request bounds, JSON responses, health endpoint, and persistent connections. |
| `mock/provider.py` | Deterministic echo model replacement with configurable artificial delay and JSON/SSE output. It is not an actual LLM. |
| `agents/__init__.py` | Python package declaration for the read-only engineering agents. |
| `agents/common.py` | Sanitizes advisory inputs/outputs and optionally obtains a summary through the authenticated gateway. |
| `agents/issue_triage.py` | Classifies supplied issue JSON into an advisory label/priority/reproduction flag and saves a report. No issue modifications. |
| `agents/pr_check.py` | Reads a provided diff or a full-base-commit Git diff; checks added lines; produces findings without executing changed code or modifying the PR. |

## Ordinary tests and examples

| File | Purpose |
|---|---|
| `tests/test_python.py` | Detector and agent unit tests: entity types, Unicode positions, overlaps, private keys, bounds, and safe agent reporting. |
| `tests/test_experiments.py` | Experiment correctness tests: deterministic/balanced assignments, cross-message exposure accounting, uncertainty intervals, and refusal to report a speedup from an incomplete human session. Fixture numbers in unit tests are not actual trial results. |
| `tests/integration_http.py` | Black-box API tests against a running stack: actions, restoration, stream reconstruction, authentication, policy conflicts, cache behavior, and optional distributed job/tenant isolation. |
| `examples/policy.json` | An editable sample policy. Its version must match the current policy before an update succeeds. |
| `examples/issue.json` | A synthetic GitHub issue-event-shaped object for running the triage CLI. |
| `examples/change.diff` | A small harmless diff for exercising the PR-check CLI. |

## Historical baseline benchmarks

These remain separate from the newer claim experiments so earlier results are not silently overwritten.

| File | Purpose |
|---|---|
| `benchmarks/__init__.py` | Package declaration. |
| `benchmarks/load.py` | Short synchronous HTTP load harness with warmups, a thread pool, first-wave synchronization, status counts, percentiles, and raw samples. |
| `benchmarks/detection.py` | Small 20-example exact-span/kind synthetic evaluation including three intentionally unsupported examples. This is not the newer provider-exposure test. |
| `benchmarks/report.py` | Renders the previously recorded local measurements into the historical benchmark document. It does not rerun measurements. |

## New claim experiments

| File | Purpose |
|---|---|
| `experiments/__init__.py` | Package declaration and statement that targets require evidence. |
| `experiments/common.py` | UTC timestamps, commit/runtime provenance, file fingerprints, JSON report writing, authenticated HTTP, demo-key selection, and percentile utility. |
| `experiments/corpus.py` | Deterministic independently labeled synthetic secret/benign corpus generator. Refuses to overwrite an existing frozen corpus. |
| `experiments/fixtures/manifest.json` | Corpus name, seed, size, and canonical fingerprint. Raw credential-like fixture values are not tracked. |
| `experiments/recorder.py` | **Test-only** authenticated provider that records incoming synthetic prompts so the leak test checks actual exposure. Its fixed harmless response keeps input and output detection separate. |
| `experiments/secrets.py` | Checks the frozen corpus, installs a temporary test policy, runs every case through the gateway, inspects provider records, restores policy, and calculates prevention/false-block rates. |
| `experiments/soak.py` | Sustained asynchronous job load from 200 clients; polls results, records worker/timing metadata, saves compressed observations, and reports errors and percentiles. |
| `experiments/run.py` | Local Compose controller with a fixed experiment project name. Prepares services, routes to the recorder temporarily, runs tests, samples resources, injects/restores faults, and saves evidence. |
| `experiments/compose.yaml` | Experiment overrides: independent host ports, larger test Redis cap, three-worker setup via controller, recording provider, separate loadgen, probes, Alertmanager, receiver, and policy-benchmark container. |
| `experiments/recording.yaml` | Narrow override directing the experiment gateway to the recording provider only during the leak test. |
| `experiments/probe.py` | Converts dependency readiness HTTP checks into Prometheus gauge observations. Datastore failures appear through gateway/worker readiness. |
| `experiments/prometheus.yml` | Five-second scrape/evaluation experiment settings, worker discovery, probe scraping, and Alertmanager wiring. |
| `experiments/alerts.yml` | Short-pending-period controlled-fault rules. These are separate from the ordinary demo alerts. |
| `experiments/alertmanager.yml` | Sends experiment notifications only to the local receipt recorder; no external email/chat is sent. |
| `experiments/receiver.py` | Records actual incoming webhook receipt timestamps and exposes them to the controller. |
| `experiments/triage.py` | Interactive randomized matched-case human study, including review/correction time. Saves partial sessions but reports no speedup until complete. |
| `experiments/provision.py` | Real fresh-host manual/Ansible timer. Checks an SSH host, records image/hardware provenance, runs/waits for setup, and verifies the exact new worker completed a queued job. |

## Infrastructure and monitoring

| File | Purpose |
|---|---|
| `migrations/001_init.sql` | Creates the policies table and initial demo policy. Docker/Kubernetes initialization executes it for a new database. |
| `monitoring/prometheus.yml` | Ordinary Compose Prometheus scrape targets and alert-rule file, distinct from experiment settings. |
| `monitoring/alerts.yml` | Availability/error-rate/terminal-job-failure rules for the ordinary demo. Does not itself configure a delivery destination. |
| `kubernetes/kustomization.yaml` | Kustomize entry point: selects the namespace and resource document; can be extended with image/replica overlays. |
| `kubernetes/resources.yaml` | Namespace, application configuration/schema/monitoring ConfigMaps, Services, Deployments, datastore StatefulSets and PVC templates, gateway HPA, disruption budgets, and inbound namespace NetworkPolicy. A declared design, not a record of live deployment. |

## Ansible provisioning

| File | Purpose |
|---|---|
| `ansible/provision.yml` | Top-level playbook, supported OS checks, required settings, safe opt-in defaults, and worker role entry. |
| `ansible/inventory.example.ini` | Template identifying target machines and SSH user; its example IP must be replaced. |
| `ansible/secrets.example.yml` | Template for the worker image/connection/key configuration. Copy privately, fill, and protect it with Ansible Vault. |
| `ansible/requirements.yml` | Pins the optional `ansible.posix` collection used by the mount role. |
| `ansible/roles/worker/tasks/main.yml` | Docker installation, optional subroles, private environment/configuration, image pull, systemd service and optional firewall setup. |
| `ansible/roles/worker/handlers/main.yml` | Service restart action triggered when relevant templates/images change. |
| `ansible/roles/worker/templates/worker.env.j2` | Renders only supplied worker environment values into a mode-0600 target file. |
| `ansible/roles/worker/templates/privateai-worker.service.j2` | systemd unit that launches/stops the restricted worker container, optionally attaching its explicit bridge and data mount. |
| `ansible/roles/kvm/tasks/main.yml` | KVM/libvirt tools/service/capability checks and explicitly authorized operator groups. Does not provision guest images automatically. |
| `ansible/roles/networking/tasks/main.yml` | Creates/checks a dedicated Docker bridge and subnet, refusing a conflicting existing network. |
| `ansible/roles/filesystem/tasks/main.yml` | Validates an existing filesystem source, refuses a conflicting mount, mounts it persistently, and grants the worker UID access. Never formats disks. |

## Helper scripts and automation

| File | Purpose |
|---|---|
| `scripts/bootstrap.py` | Creates random local credentials in `.env` once, without printing them or overwriting an existing file. |
| `scripts/client.py` | Small authenticated CLI for chat, SSE, jobs, and policy reads/updates; loads local settings. |
| `scripts/local_demo.py` | Builds and launches an isolated loopback memory-store demo, runs smoke tests/optional historical benchmarks, then stops its children. |
| `scripts/k8s_secret.py` | Converts local `.env` values to an ignored Kubernetes Secret manifest. A Kubernetes Secret still needs cluster access controls/encryption at rest. |
| `scripts/check_manifests.py` | Parses configuration YAML, understands Compose override tags, and checks Kubernetes object identity, selectors, probes/resources, ConfigMap references, and schema consistency. |
| `.github/workflows/ci.yml` | Builds/tests Go and Python, checks races, runs real Compose integration/database tests, validates monitoring, checks YAML/Kustomize, and checks Ansible syntax. |
| `.github/workflows/agents.yml` | Runs read-only issue/PR agents and uploads advisory artifacts. It does not label/comment/merge. |

## Documentation and recorded results

| File | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Design invariants, consistency and retry semantics, caching/tokenization, streaming, and monitoring. |
| `docs/SECURITY.md` | Threat boundaries, unsupported detection, endpoint/deployment limits, retention, and key rotation constraints. |
| `docs/DEPLOYMENT.md` | Commands and prerequisites for Compose, Kubernetes, Ansible, and operational drills. |
| `docs/VERIFICATION.md` | Historical test/CI verification and distinctions between confirmed and untested capabilities. |
| `docs/BENCHMARKS.md` | Historical short mock/memory benchmark interpretation and reproducibility instructions. |
| `docs/EXPERIMENTS.md` | Protocols and commands for all six claim experiments, including required human/host inputs. |
| `docs/LEARNING_GUIDE.md` | Conceptual explanation of the whole project, examples, tradeoffs, and interpretation. |
| `docs/FILE_GUIDE.md` | This file-by-file reference. |
| `results/ci-checkpoint.json` | Recorded successful jobs/steps from the earlier GitHub CI checkpoint. |
| `results/go-benchmarks.txt` | Actual earlier transform/encryption microbenchmark output, with scope/limitations. |
| `results/python-tests.txt` | Recorded earlier Python unit-test output; later tests may extend that suite. |
| `results/measured-local.json` | Raw historical 10,000-request mock/memory measurements and small detection corpus results. |
| `results/measured-initial-failures.json` | Preserved first short HTTP load run with concurrency failures, before the connection-handling repair. |

## Files intentionally outside version control

`.env` contains real local keys. `.cache/` holds downloaded/build tooling. `work/` holds logs and scratch work. `work/evidence/` contains current raw experiments: environment, secret-case outcomes, policy timings, compressed load samples, resource time series, and alert receipts. Human triage/provisioning reports appear only after real trials. `experiments/fixtures/secrets-v1.json` contains generated fake credentials and is ignored. None of these should be treated as a source file to publish without review.

The local `.git/` directory contains Git's objects, branches, index, and configuration. Do not edit it by hand. A commit is a source snapshot; a push transfers that history to GitHub. A Docker image is a runnable packaged snapshot; a container is a running instance of that image. Those are different objects with different lifecycles.

## Useful commands and what they actually do

| Command | Meaning |
|---|---|
| `go test ./...` | Compile and run Go tests in this module. External-store tests skip without explicit URLs. |
| `go test -race ./...` | Also instrument memory access to detect data races; requires a supported C toolchain. |
| `go vet ./...` | Static checks for suspicious Go usage; not a security audit. |
| `python -m unittest discover -s tests -v` | Find and execute Python unit tests under `tests/`. |
| `docker compose up --build -d --wait` | Build/start the ordinary demo and wait for health; keeps it running in the background. |
| `python -m experiments.run all` | Run the isolated claim experiments continuously, including a 15-minute load phase and fault drills. |
| `docker compose stop` | Stop services while preserving containers/volumes. |
| `docker compose down -v` | Remove the selected project's containers and volumes; deletes its stored data. |
| `kubectl kustomize kubernetes` | Render manifests locally; it does not deploy anything. |
| `kubectl apply -k kubernetes` | Submit desired resources to the selected live cluster. |
| `ansible-playbook ... --syntax-check` | Parse/check playbook structure without proving remote behavior. |
| `ansible-playbook ... --check` | Ask modules to predict changes where supported; still not an actual provisioning time. |
| `git status` / `git diff` | Inspect local modifications. |
| `git commit` / `git push` | Record a snapshot / transfer committed history to the remote. Neither deploys the application by itself. |
