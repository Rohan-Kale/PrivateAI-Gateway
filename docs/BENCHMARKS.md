# Measured benchmark report

## Environment and method

Measured on 2026-09-29 (UTC timestamps embedded in the raw JSON), Windows 11, AMD Ryzen 7 7800X3D, 16 logical CPUs, Go 1.26.6, Python 3.14.7. The gateway, detector, mock provider, and client ran on the same machine over loopback. The gateway allowed up to 256 concurrent inferences. Storage was the **memory backend**, not Redis or PostgreSQL. The provider was a deterministic echo service with **10 ms of synthetic delay**, not a real LLM.

Each scenario used 10 warmup requests and 2,000 measured requests. The closed-loop Python thread pool synchronizes the first wave with a barrier and records peak simultaneous in-flight client calls. Latency begins when a client worker starts its request and includes the HTTP response read; waiting in the harness's task queue is excluded. All-response percentiles include errors; success throughput counts only HTTP 200. Raw per-request samples and status counts are retained.

These are short synthetic burst tests. Parallel scenarios last around one second; there are no confidence intervals, repeated-run distribution, sustained-arrival guarantees, real-model token throughput, or distributed capacity claims. A higher concurrency setting increases observed tail latency.

## HTTP results

| Scenario | Configured concurrency | Observed peak | HTTP 200 / requests | Seconds | Successful requests/s | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Unique prompts | 1 | 1 | 2000/2000 | 33.402 | 59.9 | 11.86 | 34.33 | 36.32 |
| Unique prompts | 32 | 32 | 2000/2000 | 1.012 | 1976.9 | 14.67 | 20.54 | 30.17 |
| Unique prompts | 200 | 200 | 2000/2000 | 0.838 | 2387.2 | 37.35 | 387.45 | 745.14 |
| Repeated prompt, warm cache | 32 | 32 | 2000/2000 | 0.679 | 2945.6 | 10.02 | 16.43 | 20.34 |
| SSE, buffered inspection | 32 | 32 | 2000/2000 | 1.082 | 1848.1 | 15.83 | 24.09 | 34.99 |

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

- True positives: **13**
- False positives: **0**
- False negatives: **3**
- Precision on this corpus: **100.00%**
- Recall on this corpus: **81.25%**

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
