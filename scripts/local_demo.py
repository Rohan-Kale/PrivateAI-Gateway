"""Start isolated loopback-only services, test them, optionally measure them, then clean up."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.load import run
from benchmarks.detection import evaluate


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "local-demo.json")
    args = parser.parse_args()
    os.chdir(ROOT)
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    env = os.environ.copy()
    api_key = secrets.token_urlsafe(32)
    detector_port, provider_port, gateway_port = port(), port(), port()
    env.update(STORE_MODE="memory", API_KEYS=json.dumps({api_key: "demo"}), ADMIN_KEY=secrets.token_urlsafe(32),
               DETECTOR_KEY=secrets.token_urlsafe(32), VAULT_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
               HOST="127.0.0.1", DETECTOR_URL=f"http://127.0.0.1:{detector_port}", PROVIDER_URL=f"http://127.0.0.1:{provider_port}",
               LISTEN_ADDR=f"127.0.0.1:{gateway_port}", GATEWAY_URL=f"http://127.0.0.1:{gateway_port}",
               MAX_CONCURRENCY="256", MOCK_DELAY_MS="10", TEST_QUEUE="0", PYTHONPATH=str(ROOT),
               GOMODCACHE=str(ROOT / ".cache" / "gomod"), GOCACHE=str(ROOT / ".cache" / "gobuild"))
    executable = work / ("privateai.exe" if os.name == "nt" else "privateai")
    subprocess.run(["go", "build", "-o", str(executable), "./cmd/privateai"], env=env, check=True)
    processes = []
    try:
        with (work / "local-services.log").open("w", encoding="utf-8") as logs:
            for command, extra in [([sys.executable, "-m", "detector.server"], {"PORT": str(detector_port)}),
                                   ([sys.executable, "-m", "mock.provider"], {"PORT": str(provider_port)}),
                                   ([str(executable)], {})]:
                processes.append(subprocess.Popen(command, env={**env, **extra}, stdout=logs, stderr=logs))
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urllib.request.urlopen(env["GATEWAY_URL"] + "/readyz", timeout=1):
                        break
                except OSError:
                    if any(p.poll() is not None for p in processes) or time.monotonic() > deadline:
                        raise RuntimeError("services failed to start; inspect work/local-services.log")
                    time.sleep(.1)
            subprocess.run([sys.executable, "tests/integration_http.py"], env=env, check=True)
            if args.benchmark:
                report = {"environment": {"storage": "memory (not Redis/PostgreSQL)", "provider": "local deterministic echo, synthetic 10ms delay",
                                          "gateway_max_concurrency": 256, "network": "loopback", "streaming": "buffered output inspection",
                                          "go_version": subprocess.check_output(["go", "version"], env=env, text=True).strip()},
                          "detection": evaluate(), "loads": []}
                for concurrency, repeat, stream in [(1, False, False), (32, False, False), (200, False, False), (32, True, False), (32, False, True)]:
                    result = run(env["GATEWAY_URL"], api_key, count=args.requests, concurrency=concurrency, repeat=repeat, stream=stream)
                    report["loads"].append(result)
                    print(json.dumps({k: v for k, v in result.items() if k != "samples"}), flush=True)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print("Saved", args.output)
    finally:
        for proc in reversed(processes):
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
