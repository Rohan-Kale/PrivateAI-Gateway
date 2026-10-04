# Local Grafana dashboard

Grafana visualizes the existing Prometheus metrics. It does not store prompts or
generate benchmark results. The optional Compose overlay leaves the original
demo and evidence stack unchanged unless you explicitly select it.

## Start

For a new checkout, first run `python scripts/bootstrap.py`. For an existing
checkout, keep your existing `.env`.

```sh
python scripts/setup_grafana.py
docker compose -f compose.yaml -f compose.grafana.yaml up -d --build --wait
```

Open [PrivateAI Gateway Overview](http://127.0.0.1:3000/d/privateai-overview).
Sign in as `admin`, using `GRAFANA_ADMIN_PASSWORD` from your local ignored `.env`.
The helper generates a separate password without printing it or changing existing
application credentials. Anonymous access and account signup are disabled. The
port binds to loopback only. No Grafana Cloud account or paid service is needed.

Grafana automatically provisions the Prometheus data source and dashboard from
`monitoring/grafana/`. This uses Grafana's documented
[file provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
and [Docker environment configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/).
The image is pinned to `grafana/grafana:12.4.11` for reproducibility.

## Generate activity and read the panels

```sh
python scripts/client.py chat "Hello, alice@example.com"
python scripts/client.py chat "Explain queues in one sentence"
python scripts/client.py chat "Explain queues in one sentence"
python scripts/client.py submit "Summarize this synthetic document"
python scripts/client.py job JOB_ID
```

Use the returned ID in the last command. Repeating an identical non-tokenized
request within the policy cache lifetime can exercise the response cache. Allow
at least two 15-second scrapes for rates to appear; a longer traffic run makes
charts easier to read. Select a time range covering the activity. Refresh defaults
to 15 seconds. Old benchmark JSON files are not imported as live observations.

| Panel | Interpretation |
|---|---|
| Inference attempts/second | Direct and worker engine attempts, including retries, blocks and cache hits; not unique successful jobs. |
| Active executions | Sum across gateway and workers, each of which observes its own work. |
| Unfinished queued jobs | Maximum of replicas' shared Redis Stream length, not their sum. Includes claimed jobs until completion. |
| Reachable workers / scrape health | Successful metrics scrapes, not provider readiness, configured replica count, or slot count. Missing discovery targets eventually disappear. |
| Policy blocks / other errors | Errors include blocks; the second curve subtracts them to avoid double counting. |
| Queue outcomes | Enqueue, completed and terminal failure rates. Malformed queue entries can also increment terminal failures. |
| Response cache hits | Inference output cache, not policy cache. Tokenized requests bypass this cache. |
| Policy / queue p50, p95, p99 | Histogram estimates. Queue wait covers first attempts only. These are not inference latency percentiles. |
| Approximate mean engine duration | Duration sum divided by request count rates. Count increments at entry and duration at exit, so in-flight boundary effects make this approximate. Includes failures; excludes queue wait. |
| Firing alerts | Prometheus rule states, not notification receipts. No series is normal with no firing alerts if Prometheus is healthy. |

No CPU/RAM, model-token counts, or per-tenant charts are shown because the current
scrape configuration does not collect those measurements. No-traffic histogram
quantiles may be undefined. Missing data is not converted into fabricated zeros.
The default provider remains the local echo mock.

## Verify, edit, and stop

```sh
python scripts/check_grafana.py
# After direct and queued traffic, while a recent scrape window includes it:
python scripts/check_grafana.py --require-traffic
docker compose -f compose.yaml -f compose.grafana.yaml stop grafana
```

The verifier checks authenticated API access, provisioned dashboard content, the
data source, and every panel query through Grafana's Prometheus proxy. It does not
start load tests or alter policies. Dashboard edits belong in
`monitoring/grafana/dashboards/privateai.json`; Grafana polls the files every 30
seconds. UI saving is disabled so the repository remains authoritative. Make a
copy under a different dashboard UID if you want a separate UI-edited dashboard.

Grafana's database uses the `grafanadata` named volume. Changing `.env` after its
first initialization does not reset an existing Grafana account password; use
Grafana's password-change flow. Do not delete database volumes to change a login.
To inspect Grafana startup failures, use Compose logs for the `grafana` service.

This integration runs locally through Compose. It does not deploy Grafana to
Kubernetes or change the previous experiment configuration or measured claims.

When Docker Engine runs directly inside WSL (rather than Docker Desktop), keep a
WSL terminal/session open while viewing the dashboard: WSL can shut down its VM
after the last session exits, even with systemd services. If it stops, rerun the
startup command above inside WSL. Windows localhost forwarding can take a moment
to become available after WSL starts.

## Verification of this addition

Locally verified with Grafana 12.4.11, Prometheus 3.5.0 and three workers:
all 21 panel expressions executed through Grafana's authenticated data-source
proxy. A short synthetic smoke run produced 240 successful direct responses,
120 completed queued jobs and 120 expected policy blocks. The populated-query
check passed, and the browser displayed the metrics and three reachable workers.
This verifies dashboard wiring; it is not a new performance or detection benchmark.
The CI workflow also checks provisioning and query execution on its running stack.
