"""Inspect a diff as data. No repository code is executed and no PR is modified."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from detector.core import detect
from agents.common import summary


def check(diff):
    findings = []
    file = "unknown"
    line = 0
    changed = set()
    for text in diff.splitlines():
        if text.startswith("+++ b/"):
            file = text[6:]
            changed.add(file)
        elif text.startswith("@@"):
            match = re.search(r"\+(\d+)", text)
            if match:
                line = int(match.group(1)) - 1
        elif text.startswith("+") and not text.startswith("+++"):
            line += 1
            content = text[1:]
            if any(s["kind"] == "SECRET" for s in detect(content)):
                findings.append({"file": file, "line": line, "severity": "error", "rule": "possible-secret", "message": "Possible credential in added code; inspect without copying its value."})
            if re.search(r"privileged:\s*true|verify\s*=\s*False|insecure_skip_verify:\s*true", content, re.I):
                findings.append({"file": file, "line": line, "severity": "error", "rule": "unsafe-runtime", "message": "Privileged execution or disabled certificate validation."})
        elif text.startswith(" "):
            line += 1
    source = any(p.endswith((".go", ".py")) for p in changed)
    tests = any("test" in p for p in changed)
    if source and not tests:
        findings.append({"severity": "warning", "rule": "tests-not-updated", "message": "Source changed without test changes; review test coverage."})
    return {"passed": not any(f["severity"] == "error" for f in findings), "findings": findings,
            "files_changed": len(changed), "mode": "read-only", "actions_performed": []}


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", type=Path)
    source.add_argument("--base")
    parser.add_argument("--output", type=Path, default=Path("pr-report.json"))
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    if args.base:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", args.base):
            parser.error("--base must be a full commit SHA")
        diff = subprocess.run(["git", "diff", "--no-ext-diff", "--no-textconv", args.base + "...HEAD", "--"], check=True, capture_output=True, text=True, encoding="utf-8").stdout
    else:
        diff = args.diff.read_text(encoding="utf-8")
    result = check(diff)
    if args.llm:
        result["advisory_summary"] = summary(diff)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
