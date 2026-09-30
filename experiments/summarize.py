"""Derive compact, reproducible resource summaries without changing raw evidence."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
from experiments.common import digest, percentile, write_report


def memory_bytes(value):
    match = re.fullmatch(r"([0-9.]+)([kKMGT]?i?B)", value.strip())
    if not match:
        raise ValueError(f"unsupported Docker memory unit: {value}")
    number, unit = match.groups()
    powers = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2,
              "GB": 1000**3, "TB": 1000**4, "KiB": 1024,
              "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
    return float(number) * powers[unit]


def summarize(directory):
    directory = Path(directory)
    path = directory / "resources.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    metrics = {}
    for name in ("queue_depth", "inflight", "worker_count"):
        values = [float(r[name][0]["value"][1]) for r in rows if r.get(name)]
        metrics[name] = {"samples": len(values), "first": values[0] if values else None,
                         "last": values[-1] if values else None,
                         "min": min(values) if values else None,
                         "max": max(values) if values else None,
                         "p50": percentile(values, .5), "p95": percentile(values, .95)}
    containers = {}
    for row in rows:
        for container in row.get("containers", []):
            item = containers.setdefault(container["Name"], {"peak_cpu_percent": 0, "peak_memory_bytes": 0})
            item["peak_cpu_percent"] = max(item["peak_cpu_percent"], float(container["CPUPerc"].rstrip("%")))
            item["peak_memory_bytes"] = max(item["peak_memory_bytes"], memory_bytes(container["MemUsage"].split("/")[0]))
    samples = directory / "soak.samples.jsonl.gz"
    counts = Counter()
    with gzip.open(samples, "rt", encoding="utf-8") as stream:
        for line in stream:
            counts[json.loads(line)["status"]] += 1
    soak = json.loads((directory / "soak.json").read_text())
    if dict(counts) != soak["statuses"] or sum(counts.values()) != soak["requests"]:
        raise ValueError("compressed samples disagree with the reported outcomes")
    return {"source_sha256": {p.name: digest(p) for p in (path, samples, directory / "soak.json")},
            "resource_samples": len(rows), "sampling_errors": sum("sampling_error" in r for r in rows),
            "raw_job_samples_verified": sum(counts.values()), "metrics": metrics,
            "containers": containers,
            "limitations": ["Docker CPU percentage is relative to one logical CPU; values can exceed 100%.",
                            "Container peaks are sampled, not continuous maxima, and are not necessarily simultaneous.",
                            "The one-off load-generator container is excluded from compose ps resource samples.",
                            "Prometheus sums asynchronously scraped per-worker gauges; inflight is not a synchronized provider concurrency measurement.",
                            "Queue depth includes work already claimed by workers, not only waiting jobs."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="work/evidence")
    args = parser.parse_args()
    write_report(Path(args.directory) / "resource-summary.json", summarize(args.directory))
