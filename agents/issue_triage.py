"""Classify GitHub issue-event JSON; write an advisory artifact, never post or label."""
import argparse
import json
from pathlib import Path
from agents.common import summary


def triage(issue):
    text = (str(issue.get("title", "")) + "\n" + str(issue.get("body", ""))).lower()
    security = any(word in text for word in ("credential leak", "pii leak", "security", "bypass", "vulnerability"))
    bug = any(word in text for word in ("crash", "error", "broken", "fails", "bug", "timeout"))
    labels = ["security" if security else "bug" if bug else "documentation" if "docs" in text or "documentation" in text else "enhancement"]
    return {"issue_number": issue.get("number"), "labels": labels, "priority": "high" if security else "normal",
            "needs_reproduction": bug and not any(word in text for word in ("steps to reproduce", "reproduction:")),
            "mode": "deterministic-advisory", "actions_performed": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("event", type=Path)
    parser.add_argument("--output", type=Path, default=Path("triage-report.json"))
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    issue = event.get("issue", event)
    result = triage(issue)
    if args.llm:
        result["advisory_summary"] = summary(str(issue.get("title", "")) + "\n" + str(issue.get("body", "")))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
