"""Small authenticated demo CLI, reading generated .env without printing its keys."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("chat", "submit"):
        sub = commands.add_parser(name)
        sub.add_argument("text")
        sub.add_argument("--model", default="mock")
        if name == "chat":
            sub.add_argument("--stream", action="store_true")
    commands.add_parser("job").add_argument("id")
    sub = commands.add_parser("policy")
    sub.add_argument("--file", type=Path, help="PUT policy JSON with its current version; omit to GET")
    args = parser.parse_args()
    env_file = Path(__file__).resolve().parents[1] / ".env"
    config = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if line and not line.startswith("#"))
    config.update(os.environ)
    key = next(k for k, v in json.loads(config["API_KEYS"]).items() if v == "demo")
    body = None
    method = None
    if args.command in ("chat", "submit"):
        path = "/v1/chat/completions" if args.command == "chat" else "/v1/jobs"
        body = {"model": args.model, "messages": [{"role": "user", "content": args.text}], "stream": getattr(args, "stream", False)}
    elif args.command == "job":
        path = "/v1/jobs/" + args.id
    else:
        path = "/v1/policy"
        if args.file:
            body = json.loads(args.file.read_text())
            path, method, key = "/admin/policies/demo", "PUT", config["ADMIN_KEY"]
    req = urllib.request.Request(args.url + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=65) as response:
            if "event-stream" in response.headers.get("Content-Type", ""):
                for line in response:
                    print(line.decode().rstrip(), flush=True)
            else:
                print(json.dumps(json.load(response), indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as error:
        with error:
            print(json.dumps({"status": error.code, "response": json.load(error)}, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
