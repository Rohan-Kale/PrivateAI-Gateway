import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone


def utc():
    return datetime.now(timezone.utc).isoformat()


def provenance():
    commit = os.environ.get("EVIDENCE_COMMIT")
    dirty = None
    if not commit:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        except (OSError, subprocess.CalledProcessError):
            commit = "unknown"
    return {"commit": commit, "working_tree_dirty": dirty, "timestamp_utc": utc(), "python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count()}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def http(url, body=None, key=None, method=None, timeout=65):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw.decode()
        return response.status, value


def demo_key():
    return next(k for k, t in json.loads(os.environ["API_KEYS"]).items() if t == "demo")


def percentile(values, fraction):
    import math
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None
