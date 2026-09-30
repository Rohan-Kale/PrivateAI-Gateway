"""Generate local development secrets without printing them or overwriting an existing file."""
import base64
import json
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
values = {
    "POSTGRES_PASSWORD": secrets.token_hex(24),
    "REDIS_PASSWORD": secrets.token_hex(24),
    "API_KEYS": json.dumps({secrets.token_urlsafe(32): "demo", secrets.token_urlsafe(32): "other"}, separators=(",", ":")),
    "ADMIN_KEY": secrets.token_urlsafe(32),
    "DETECTOR_KEY": secrets.token_urlsafe(32),
    "VAULT_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    "PROVIDER_URL": "http://mock:8002",
    "PROVIDER_KEY": "",
    "MAX_CONCURRENCY": "32",
}
with target.open("x", encoding="utf-8") as file:
    file.write("# Generated local secrets. Do not commit.\n")
    file.writelines(f"{key}={value}\n" for key, value in values.items())
try:
    target.chmod(0o600)
except OSError:
    pass
print("Created .env. Keep it private; existing files are never overwritten.")
