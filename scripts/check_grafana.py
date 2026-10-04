"""Verify provisioned dashboard and every PromQL expression through Grafana's proxy."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--require-traffic", action="store_true",
                        help="Also require request observations and populated latency/rate queries.")
    args = parser.parse_args()
    config = {}
    if (ROOT / ".env").exists():
        config.update(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                      if line and not line.startswith("#") and "=" in line)
    config.update(os.environ)
    password = config.get("GRAFANA_ADMIN_PASSWORD")
    if not password:
        raise SystemExit("Run scripts/setup_grafana.py or set GRAFANA_ADMIN_PASSWORD.")
    auth = base64.b64encode(("admin:" + password).encode()).decode()

    def get(path):
        request = urllib.request.Request(args.url.rstrip("/") + path,
                                         headers={"Authorization": "Basic " + auth})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def query(expression):
        result = get("/api/datasources/proxy/uid/privateai-prometheus/api/v1/query?" +
                     urllib.parse.urlencode({"query": expression}))
        if result.get("status") != "success":
            raise RuntimeError("Prometheus query failed: " + expression)
        return result["data"]["result"]

    assert get("/api/health")["database"] == "ok", "Grafana database unhealthy"
    configured = json.loads((ROOT / "monitoring/grafana/dashboards/privateai.json").read_text())
    loaded = get("/api/dashboards/uid/privateai-overview")
    assert loaded["meta"]["provisioned"], "Dashboard was not file-provisioned"
    assert loaded["dashboard"]["panels"] == configured["panels"], "Loaded dashboard differs from source"
    source = get("/api/datasources/uid/privateai-prometheus")
    assert source["url"] == "http://prometheus:9090" and source["type"] == "prometheus"
    queries = 0
    for panel in configured["panels"]:
        for target in panel.get("targets", []):
            expression = target["expr"].replace("$__rate_interval", "1m")
            result = query(expression)
            # No observations legitimately means no latency/alert series. Never invent zeros.
            if args.require_traffic and "ALERTS{" not in expression:
                assert result, "No data for " + panel["title"]
                assert all(math.isfinite(float(row["value"][1])) for row in result), \
                    "Non-finite data for " + panel["title"]
            queries += 1
    if args.require_traffic:
        observed = query('sum(privateai_requests_total{job=~"privateai-gateway|privateai-worker"})')
        assert observed and float(observed[0]["value"][1]) > 0, "No real request observations"
    print(f"Verified provisioned dashboard, data source, and {queries} live PromQL queries.")


if __name__ == "__main__":
    main()
