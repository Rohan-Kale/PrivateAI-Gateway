# Claim experiments: how to collect evidence without inventing results

Targets (99%, 200 clients, 35%, 40%, 120 seconds, 20→5 minutes) are hypotheses, not defaults. Reports retain misses, errors, negative improvements, and incomplete human trials. Experiments do not rewrite the README's historical results.

## Local stack

Run from the repository root on Linux with Docker Engine and Compose 2.24.4+:

```sh
python3 scripts/bootstrap.py  # once; skip if .env already exists
python3 -m experiments.run prepare
python3 -m experiments.run secrets
python3 -m experiments.run policy
python3 -m experiments.run soak --seconds 900
python3 -m experiments.run faults --fault-repeats 3
python3 -m experiments.run stop
```

`python3 -m experiments.run all` runs these phases continuously. On Windows use the Ubuntu WSL environment with its Linux Docker Engine. Keep the WSL session alive during the run. Docker Desktop and Docker inside Ubuntu have different engines/image stores; check which daemon your CLI is using. The experiment project is named `privateai-evidence`; it has separate database volumes and ports 18080 (gateway), 19090 (Prometheus), 18003 (synthetic recorder), and 18010 (local webhook receipts). It does not modify the ordinary `privateai` Compose project's data.

Outputs go to ignored `work/evidence/`. Publish reviewed reports in `results/` after checking provenance. Do not commit `.env`, raw credential fixtures, or human identifiers. The test recorder must only receive synthetic data. Images are built sequentially because multiple Compose services share image tags.

After the soak finishes, `python3 -m experiments.summarize` checks compressed request counts against the reported outcomes and writes resource summaries with input fingerprints. Read [CLAIMS_REPORT.md](CLAIMS_REPORT.md) for the recorded September 30 results, including unsuccessful hypotheses.

## 1. Secret exposure

`experiments/corpus.py` deterministically generates 900 cases: 600 secret cases in 12 families and 300 benign cases in six families. The corpus includes supported prefixes, private keys, credential assignments, generic unlabeled strings, JWTs, encodings, and values split across messages. The corpus does not import detector recognizers. It is nevertheless a generated challenge corpus, not a blinded real-world holdout.

Git stores the generator, seed, labels, and `fixtures/manifest.json` canonical SHA-256. Raw fake credentials are generated during Docker builds and ignored by Git to avoid secret-scanner alerts. `secrets.py` verifies the fingerprint before measuring. For a changed evaluation set, create a new corpus version rather than overwriting the original fingerprint.

The controller temporarily directs only the experiment gateway to `recorder.py`, sets a cache-disabled policy with SECRET=block, sends each case, and checks the actual provider-bound messages. Cross-message fragments are joined for the exposure check. It restores the original policy and mock routing in `finally` blocks. It never tunes detector patterns during a run.

A valid 403 with no provider call counts as prevention. A successful provider call counts as prevention only if no labeled secret representation reached it. Infrastructure errors are invalid outcomes, not credited protection. Reports include a Wilson interval, per-case records, and false blocks on benign inputs. Percentage targets are not passed when outcomes are invalid.

This measures **preventing provider exposure**, not merely recognizing substrings and not protection against all conceivable encodings. The recorder returns a harmless fixed response so output inspection does not obscure input exposure.

## 2. Sustained queued workload

`soak.py` runs in a separate load-generator container on the same physical machine. It maintains 200 closed-loop clients for 900 seconds; each submits a unique job, polls it to completion/failure, and submits the next. There are three worker containers with 80 slots each. The model is explicitly a **mock with a 1,000 ms artificial delay**. This is a gateway/queue experiment, not model-speed evidence.

Reports include terminal statuses, completions per worker, p50/p95/p99 end-to-end latency, per-minute outcomes, queue wait, service time, and observed peak outstanding clients. Compressed per-request JSONL samples preserve raw measurements. `run.py` separately records Docker CPU/memory counters and Prometheus queue depth, aggregate inference inflight, and worker count every approximately five seconds.

Two hundred outstanding clients are not automatically two hundred simultaneously executing model calls. Inspect `resources.jsonl`'s inflight series before making that stronger claim. All containers share hardware, so this is not multi-host scaling evidence. Polling adds client latency. Work started before the 900-second deadline is allowed to drain afterwards; throughput includes drain time. Redis has a 1 GiB no-eviction cap for this experiment; it can still fill and fail, which the report must preserve.

## 3. Policy cache comparison

`cmd/policybench` bypasses the provider entirely. It creates one temporary tenant, runs eight paired rounds with randomized mode order, warms each mode for 200 lookups, and measures 2,000 lookups per mode per round. It checks every returned policy's version and default action.

- Baseline: one authoritative PostgreSQL version+document read, followed by validation.
- Current treatment: the authoritative PostgreSQL version check plus a warm decoded process-cache hit and validation, with Redis backing cold process reads.
- Legacy cached mode: the authoritative PostgreSQL version check plus a warm Redis hit, JSON decoding, and validation.

Both retain the same policy-version consistency guarantee. This is deliberately not a weakened cache that skips version checks. Median improvement is `(baseline - treatment) / baseline * 100`; negative values mean the cache is slower. Reports include every duration, paired effects, runtime, commit, and sample sizes. The test removes only its own tenant and cache key.

The current v3 benchmark randomizes all three modes within each round and reports two distinct comparisons: decoded versus direct PostgreSQL, and decoded versus the previous Redis path. `target_met` still refers to the original direct-PostgreSQL comparison. A gain against the legacy path must never be relabeled as a gain against direct PostgreSQL. Historical v1/v2 reports preserve their original two-mode protocols.

## 4. Human issue triage

```sh
python -m experiments.triage --participant participant-01 --output work/evidence/triage-01.json
```

This is an interactive **human** experiment. No code can legitimately invent a human's baseline. Twenty-four synthetic issues form 12 matched pairs; each pair assigns one issue to manual triage and the other to agent-assisted triage. Assignment and presentation order are reproducibly randomized by a pseudonym. Do not use an email as the participant ID.

Timing starts before reading and agent proposal generation. You choose a label and priority. Incorrect classifications require correction while the timer continues. Each completed decision is saved with elapsed time, mistakes, proposal, and mode. Interrupted sessions remain explicitly incomplete and do not report a speedup. A complete single-participant trial gives an exploratory median comparison, not a general productivity estimate. Repeat with additional participants and independently curated issues for a stronger claim.

## 5. Actual alert receipt

`run.py faults` stops the experiment worker service, detector, PostgreSQL, and Redis, one at a time, and restores each in a `finally` block. Each fault is repeated three times by default. Do not run this against production or alongside the load test. The controller's Compose project is fixed to the isolated experiment namespace.

Prometheus scrapes every five seconds, evaluates every five seconds, and the experiment alerts use a ten-second pending period. Alertmanager sends to `receiver.py`, which records local receipt timestamps. The controller rejects stale notifications whose alert start precedes the fault. Latency begins before the stop command and ends at receipt; missing receipts time out and remain failures.

This validates a **local webhook delivery path**. It does not measure email/SMS delivery, every fault type, or production detection guarantees. Datastore failures are detected indirectly through gateway readiness. The original production-like alert file is separate; results only apply to the experiment's configured intervals and rules.

If the controller is interrupted, preserve its logs and report, restore the same isolated stack, and use `python3 -m experiments.run faults --resume-faults` to skip already completed/restored trials. Do not reuse this flag for an unrelated environment or changed alert configuration. New reports persist receipt evidence before attempting restoration, so a restoration failure cannot erase the measured observation.

## 6. Fresh-host provisioning

The worker role now composes optional `kvm`, `networking`, and `filesystem` roles:

- KVM installs and enables libvirt, checks `/dev/kvm`, validates capabilities, and grants only explicitly named operators access. It configures a virtualization host; it does not create guests automatically.
- Networking creates a named Docker bridge with an explicit subnet and rejects a conflicting existing subnet. Firewall management remains opt-in with an explicit SSH CIDR.
- Filesystem mounting accepts an existing filesystem/NFS source, refuses conflicting fstab entries, mounts under `/srv/privateai/`, and never formats a disk. The mount is made available to the worker container; the inference engine does not otherwise require local disk persistence.

Install `ansible/requirements.yml` with `ansible-galaxy collection install -r ansible/requirements.yml`. Defaults leave these host changes disabled. Ubuntu 24.04 and 26.04 are permitted. Syntax checks do not establish host-level idempotence or timing.

Prepare equivalent fresh Linux guests from the same recorded base image, with SSH access and an isolated queue containing **only the worker under test**. Keep package/image caches equivalent. Manually configured SSH/network access is a prerequisite outside the timed interval. Use the same enabled role options in both modes. Supply the base-image SHA-256 and a pseudonymous trial filename.

```sh
python -m experiments.provision --mode manual --host user@HOST \
  --base-image-sha256 IMAGE_SHA256 --output work/evidence/manual-01.json
python -m experiments.provision --mode ansible --host user@FRESH_HOST \
  --base-image-sha256 IMAGE_SHA256 --inventory ansible/inventory.ini \
  --vars-file ansible/secrets.yml --output work/evidence/ansible-01.json
```

Set `API_KEYS` and `GATEWAY_URL` in the control shell; keep secret files private. The automated mode expects noninteractive Ansible/SSH credentials (use a Vault password helper/environment when needed). The manual mode waits for your actual setup work. Both verify that a queued request completes on the intended new worker before stopping the timer. They record a hash of the machine ID and refuse an existing project environment file, but fresh-image attestation still depends on the operator. A failed run records elapsed failure time and never counts as a completed provisioning measurement.

Do at least several paired repetitions and report medians/ranges. No 20-minute manual baseline or five-minute automation result is assumed. Run Ansible a second time separately to check idempotence; that warm rerun is not a fresh-host provisioning trial.
