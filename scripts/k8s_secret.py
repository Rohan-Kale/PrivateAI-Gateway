"""Generate an ignored Secret manifest from local .env; never writes credentials to stdout."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if line and not line.startswith("#"))
values["DATABASE_URL"] = f"postgres://privateai:{values['POSTGRES_PASSWORD']}@postgres:5432/privateai?sslmode=disable"
values["REDIS_URL"] = f"redis://:{values['REDIS_PASSWORD']}@redis:6379/0"
target = root / "work" / "privateai-secret.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "privateai-secrets", "namespace": "privateai"}, "type": "Opaque", "stringData": values}, indent=2) + "\n", encoding="utf-8")
try:
    target.chmod(0o600)
except OSError:
    pass
print("Wrote work/privateai-secret.json; keep this ignored file private.")
