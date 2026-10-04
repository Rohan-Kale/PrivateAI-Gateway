# Deployment and operations

## Docker Compose

1. Run `python scripts/bootstrap.py` once. Keep `.env` private and retain the vault key for decrypting queued jobs/results.
2. Run `docker compose up --build -d --wait`.
3. Exercise requests with `scripts/client.py`. The mock provider keeps the demo offline and deterministic.
4. Run `docker compose --profile test run --rm integration` and `docker compose --profile test run --build --rm database-test`.
5. Inspect health with `docker compose ps` and metrics at `http://127.0.0.1:9090`.

For an automatically provisioned local dashboard, follow [Grafana setup](GRAFANA.md).
The optional `compose.grafana.yaml` overlay adds an authenticated Grafana instance
at `http://127.0.0.1:3000` connected to the same Prometheus service.

`docker compose stop` preserves data. `docker compose down` removes containers and networks but preserves named volumes. `docker compose down -v` **deletes the demo PostgreSQL and Redis data**; use it only for a deliberate reset. PostgreSQL's entrypoint runs `migrations/001_init.sql` only on an empty data directory. Apply later migrations explicitly against existing databases; this project currently has one initial schema migration.

The database role is an all-in-one demo role. For a production-oriented extension separate schema migration ownership from runtime query/update grants. Redis has AOF enabled and a 256 MiB `noeviction` memory cap; when exhausted, writes fail closed. There is no Sentinel/Cluster failover or replicated PostgreSQL configuration here.

## Configuration

| Variable | Purpose |
|---|---|
| `API_KEYS` | JSON mapping of opaque keys to tenant IDs; keys require at least 16 characters |
| `ADMIN_KEY` | Separate policy administrator key |
| `DETECTOR_KEY` | Gateway/worker-to-detector service authentication |
| `VAULT_KEY` | Base64-encoded 32-byte encryption/HMAC key, shared by all replicas |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection URL; use `rediss://` remotely |
| `DETECTOR_URL` | Detector base URL |
| `PROVIDER_URL`, `PROVIDER_KEY` | Chat provider base URL and optional bearer credential |
| `MAX_CONCURRENCY` | Per-process inference/worker limit, 1–1024; default 32 |
| `LISTEN_ADDR` | Go listener, default `:8080` |
| `STORE_MODE` | `database` by default; explicit `memory` for the local smoke harness |

The API deliberately supports only `model`, `messages`, and `stream`. Test an external provider's compatibility before using it. Keep all external service links on TLS and use verified CA chains. Cache identity does not include provider URL; clear response caches or rotate the key when changing providers under an unchanged model name.

## Kubernetes demo

Requirements: a cluster with a default StorageClass, a NetworkPolicy-capable network plugin, and images accessible to all nodes. The HPA additionally needs metrics-server. **The manifests have been rendered and checked, but not exercised against a live cluster in the recorded validation.**

Build and load the demo images into a local cluster, for example with kind:

```sh
docker build -t privateai-gateway:local .
docker build -t privateai-python:local -f Dockerfile.python .
kind load docker-image privateai-gateway:local privateai-python:local
python scripts/k8s_secret.py
kubectl create namespace privateai --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f work/privateai-secret.json
kubectl apply -k kubernetes
kubectl -n privateai rollout status deployment/gateway --timeout=180s
kubectl -n privateai rollout status deployment/worker --timeout=180s
kubectl -n privateai port-forward service/gateway 8080:8080
```

`scripts/k8s_secret.py` reads the generated `.env` and writes an ignored Secret manifest. Kubernetes Secrets are not encrypted merely because they use this API object; configure encryption at rest and restrict RBAC. Do not commit `work/privateai-secret.json`.

For a remote registry, edit the `images` section of a Kustomize overlay with immutable digests and configure registry credentials. Default `:local` images are meant for a local demo only. Never assume a new image with a reused tag will roll out automatically.

Resources include two gateway replicas, two worker replicas, two detector replicas, one mock provider, one Prometheus deployment, PostgreSQL/Redis StatefulSets with 1 GiB PVCs, readiness/liveness probes, resource budgets, a gateway CPU HPA, gateway/worker disruption budgets, and namespace-local inbound network access. There is no public Ingress. Prometheus storage is ephemeral. PostgreSQL and Redis are single-instance demo datastores, not highly available services.

```sh
kubectl -n privateai scale deployment/worker --replicas=4
kubectl -n privateai port-forward service/prometheus 9090:9090
kubectl kustomize kubernetes > work/rendered-kubernetes.yaml
```

The embedded schema ConfigMap must match `migrations/001_init.sql`; the static validator enforces this. NetworkPolicy allows traffic within the namespace, so run it as a dedicated trusted demo namespace. Add narrowly scoped ingress/egress rules and TLS before any broader deployment.

## Ansible worker hosts

This playbook targets **Ubuntu 24.04/26.04** and installs Docker, a root-only environment file, and a restartable systemd inference-worker service. Ansible Vault protects the source secrets file; the runtime environment file contains plaintext secrets with mode 0600. Optional roles configure a Docker bridge, mount an existing filesystem, and install/verify KVM and libvirt. VM creation and cluster enrollment are not implemented. Firewall changes are opt-in and require an explicit SSH management CIDR to avoid accidental lockout.

```sh
python -m pip install -r requirements-dev.txt
ansible-galaxy collection install -r ansible/requirements.yml
cp ansible/inventory.example.ini ansible/inventory.ini
cp ansible/secrets.example.yml ansible/secrets.yml
# Edit both files: actual host, registry image digest, TLS service URLs, and keys.
ansible-vault encrypt ansible/secrets.yml
ansible-playbook -i ansible/inventory.ini ansible/provision.yml --syntax-check
ansible-playbook -i ansible/inventory.ini ansible/provision.yml -e @ansible/secrets.yml --ask-vault-pass --check
ansible-playbook -i ansible/inventory.ini ansible/provision.yml -e @ansible/secrets.yml --ask-vault-pass
```

Use a Linux/WSL control machine for Ansible. Registry authentication, host creation, networking between services, and TLS certificate provisioning are prerequisites. The runtime environment file is root-owned and mode 0600. The worker container drops capabilities, uses a read-only root filesystem, and binds metrics only to host loopback port 8081. Configure a secure scrape path separately.

The example addresses are documentation placeholders; no remote host has been provisioned in the recorded run. Idempotence has not been measured against a real Ubuntu host. The configured image must be pullable before the service can start.

## Failure drills

Use a disposable stack and synthetic content:

1. Stop the detector and verify inference returns 502; `/readyz` returns 503. Cached responses must not bypass detection.
2. Change the email action to `block` and confirm the next request is rejected, even if an earlier policy version populated cache.
3. Submit a job, terminate its worker, and restart a worker. An abandoned pending job is eligible for reclaim after 90 seconds; duplicate provider calls remain possible.
4. Make the mock/provider unavailable. Jobs retry at most three times and end in `failed`; completed jobs remain readable for 24 hours.
5. Try fetching another tenant's job ID. It returns the same 404 as a nonexistent job.

The automated suite covers these invariants at unit and HTTP integration levels. The separate [experiment suite](EXPERIMENTS.md) runs a sustained local queue soak and measures fault-to-webhook receipt. It does not establish production resilience, multi-node Kubernetes behavior, or provisioning speed without fresh-host trials.
