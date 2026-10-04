"""Append a separate Grafana credential to existing local config, never print it."""
from pathlib import Path
import secrets


def main():
    target = Path(__file__).resolve().parents[1] / ".env"
    if not target.exists():
        raise SystemExit("Run python scripts/bootstrap.py first.")
    contents = target.read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in contents.splitlines()
                  if line and not line.startswith("#") and "=" in line)
    if "GRAFANA_ADMIN_PASSWORD" in values:
        if len(values["GRAFANA_ADMIN_PASSWORD"]) < 16:
            raise SystemExit("Set a Grafana password of at least 16 characters in .env.")
        print("Grafana credential already exists; no changes made.")
        return
    with target.open("a", encoding="utf-8") as file:
        if contents and not contents.endswith("\n"):
            file.write("\n")
        file.write("GRAFANA_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
    print("Added Grafana password to ignored .env. Login: admin; read password locally from .env.")


if __name__ == "__main__":
    main()
