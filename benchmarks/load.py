"""Closed-loop HTTP load harness. All responses, including errors, appear in results."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import time
import threading
import urllib.error
import urllib.request


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def run(url, key, count=500, concurrency=32, repeat=False, stream=False):
    nonce = str(time.time_ns())
    barrier = threading.Barrier(min(count, concurrency))
    lock = threading.Lock()
    active = peak = 0

    def one(i):
        nonlocal active, peak
        body = {"model": "mock", "messages": [{"role": "user", "content": "Synthetic load " + nonce + ("" if repeat else " " + str(i))}], "stream": stream}
        req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        if 0 <= i < min(count, concurrency):
            barrier.wait(timeout=30)
        with lock:
            active += 1
            peak = max(peak, active)
        start = time.perf_counter()
        first_byte = None
        try:
            with urllib.request.urlopen(req, timeout=65) as response:
                response.read(1)
                first_byte = (time.perf_counter() - start) * 1000
                rest = response.read()
                code = response.status
                if stream and b"data: [DONE]" not in rest:
                    code = "incomplete_stream"
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
        except (OSError, TimeoutError):
            code = "transport_error"
        finally:
            with lock:
                active -= 1
        return code, (time.perf_counter() - start) * 1000, first_byte

    warmup = [one(-i - 1) for i in range(10)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, range(count)))
    elapsed = time.perf_counter() - started
    latencies = [x[1] for x in results]
    successful = [x for x in results if x[0] == 200]
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "harness": "stdlib urllib, closed-loop thread pool; latency starts when each worker begins its request",
        "requests": count, "concurrency": concurrency, "warmup_requests": 10,
        "peak_inflight_client_requests": peak,
        "warmup_statuses": dict(Counter(str(x[0]) for x in warmup)),
        "repeat_prompt": repeat, "stream": stream, "elapsed_seconds": elapsed,
        "statuses": dict(Counter(str(x[0]) for x in results)),
        "successful_requests_per_second": len(successful) / elapsed,
        "all_response_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99)},
        "successful_first_byte_ms": {"p50": percentile([x[2] for x in successful], .5), "p95": percentile([x[2] for x in successful], .95)},
        "samples": [{"status": str(code), "latency_ms": latency, "first_byte_ms": first} for code, latency, first in results],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("results/local-load.json"))
    args = parser.parse_args()
    if args.requests < 1 or not 1 <= args.concurrency <= 1000:
        parser.error("requests must be positive and concurrency must be 1-1000")
    result = run(args.url, os.environ["GATEWAY_API_KEY"], args.requests, args.concurrency, args.repeat, args.stream)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
