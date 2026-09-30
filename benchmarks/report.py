"""Render the committed measurement JSON into a readable, reproducible report."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / "results/measured-local.json").read_text(encoding="utf-8"))
rows = []
for run in data["loads"]:
    label = "SSE, buffered inspection" if run["stream"] else "Repeated prompt, warm cache" if run["repeat_prompt"] else "Unique prompts"
    rows.append(f"| {label} | {run['concurrency']} | {run['peak_inflight_client_requests']} | {run['statuses'].get('200', 0)}/{run['requests']} | {run['elapsed_seconds']:.3f} | {run['successful_requests_per_second']:.1f} | {run['all_response_latency_ms']['p50']:.2f} | {run['all_response_latency_ms']['p95']:.2f} | {run['all_response_latency_ms']['p99']:.2f} |")
detection = data["detection"]
text = """# Measured benchmark report

## Environment and method

Measured on 2026-09-29 (UTC timestamps embedded in the raw JSON), Windows 11, AMD Ryzen 7 7800X3D, 16 logical CPUs, Go 1.26.6, Python 3.14.7. The gateway, detector, mock provider, and client ran on the same machine over loopback. The gateway allowed up to 256 concurrent inferences. Storage was the **memory backend**, not Redis or PostgreSQL. The provider was a deterministic echo service with **10 ms of synthetic delay**, not a real LLM.

Each scenario used 10 warmup requests and 2,000 measured requests. The closed-loop Python thread pool synchronizes the first wave with a barrier and records peak simultaneous in-flight client calls. Latency begins when a client worker starts its request and includes the HTTP response read; waiting in the harness's task queue is excluded. All-response percentiles include errors; success throughput counts only HTTP 200. Raw per-request samples and status counts are retained.

These are short synthetic burst tests. Parallel scenarios last around one second; there are no confidence intervals, repeated-run distribution, sustained-arrival guarantees, real-model token throughput, or distributed capacity claims. A higher concurrency setting increases observed tail latency.

## HTTP results

| Scenario | Configured concurrency | Observed peak | HTTP 200 / requests | Seconds | Successful requests/s | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
""" + "\n".join(rows) + f"""

All five final scenarios returned 200 for every measured request: 10,000/10,000 total. The SSE path waits for complete model generation and output inspection, so these numbers do not claim low time-to-first-token. The JSON contains first-byte measurements separately.

Data: [final raw measurements](../results/measured-local.json). Reproduce with:

```sh
python scripts/local_demo.py --benchmark --requests 2000 --output results/local-demo.json
```

## Initial failure and repair

The first 500-request-per-scenario run exposed failures under concurrent HTTP load. At configured concurrency 32, only 96/500 uncached requests returned 200; 404 returned 502. At configured concurrency 200, 161/500 returned 200 and 339 returned 502. We preserved [that entire failed run](../results/measured-initial-failures.json).

The Python services initially used HTTP/1.0 connections and the default accept queue. Enabling persistent HTTP/1.1 connections, declaring response lengths, and increasing the accept backlog removed the observed failures in the rerun. This is an observed repair in this environment, not a controlled claim that one setting alone caused all failures. The final harness also added a synchronized first wave and peak-concurrency measurement; the initial run has configured concurrency only.

## Detector fixture evaluation

The synthetic corpus has 20 examples, including three deliberate challenge cases outside the implemented recognizers: an international phone number, a person name, and an IP address. Entity matching requires exact byte spans and kind.

- True positives: **{detection['true_positives']}**
- False positives: **{detection['false_positives']}**
- False negatives: **{detection['false_negatives']}**
- Precision on this corpus: **{100*detection['precision']:.2f}%**
- Recall on this corpus: **{100*detection['recall']:.2f}%**

This is not a held-out or representative dataset. In particular, 100% precision on these few examples does not imply production precision. There is no evidence here for a 99% detection claim. Example-level predictions are in the final raw report and the corpus is in `benchmarks/detection.py`.

```sh
python -m benchmarks.detection --output results/local-detection.json
```

## Go microbenchmarks

An earlier local execution measured the unchanged redaction transform and AES-GCM round trip:

| Operation | ns/op | B/op | allocs/op |
|---|---:|---:|---:|
| Redact one entity in a 273-byte string | 214.8 | 792 | 3 |
| Seal and open one short vault value | 404.6 | 328 | 10 |

These measure only in-process functions, excluding network, detector, Redis, PostgreSQL, and model calls. [Captured output](../results/go-benchmarks.txt). Command:

```sh
go test -bench . -benchmem -run '^$' ./internal/gateway
```

Later verbose local test execution was blocked by Windows Application Control; Linux CI passed race-enabled tests and full container integration. No unmeasured container/cluster/Ansible speedup is reported. See [verification status](VERIFICATION.md).

## Extend the experiment

Use a fresh test tenant and external provider explicitly, report model/configuration and input/output token counts, repeat runs, and collect sustained open-loop arrival rates before making deployment-capacity claims. Separate cache-hit and cache-miss workloads, policy versions, and error counts. Run Redis/PostgreSQL and distributed worker load independently from the memory baseline. Measure actual Ansible cold/warm runs on identified hardware before claiming provisioning-time improvements.
"""
(root / "docs/BENCHMARKS.md").write_text(text, encoding="utf-8")
print("Rendered docs/BENCHMARKS.md from recorded data")
