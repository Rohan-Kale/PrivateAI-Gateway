"""Classify GitHub issue-event JSON; write an advisory artifact, never post or label."""
import argparse
import json
import re
from pathlib import Path
from agents.common import summary


def triage(issue):
    text = (str(issue.get("title", "")) + "\n" + str(issue.get("body", ""))).lower()
    vocabulary={"security":("credential leak","pii leak","security","bypass","vulnerability","cross-tenant","private result","raw customer token","without its required replacement"),
                "bug":("crash","crashes","error","broken","fails","bug","timeout","expired","twice"),
                "documentation":("docs","documentation","readme","deployment guide","troubleshooting")}
    signals={label:[word for word in words if re.search(r"(?<!\w)"+re.escape(word)+r"(?!\w)",text)] for label,words in vocabulary.items()}
    security=bool(signals["security"]);bug=bool(signals["bug"])
    labels = ["security" if security else "bug" if bug else "documentation" if signals["documentation"] else "enhancement"]
    needs_reproduction=(bug or security) and not any(word in text for word in ("steps to reproduce", "reproduction:"))
    return {"issue_number": issue.get("number"), "labels": labels, "priority": "high" if security else "normal",
            "needs_reproduction": needs_reproduction,
            "matched_signals":{label:words for label,words in signals.items() if words},
            "review_required":True,
            "reason":"Security signals take precedence over bug and documentation signals; unmatched reports default to enhancement for review.",
            "review_steps":(["Confirm the reported behavior and proposed label."]+
                            (["Request reproducible steps using synthetic or redacted data, expected behavior, observed behavior, and version."] if needs_reproduction else [])),
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
