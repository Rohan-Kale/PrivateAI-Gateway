"""Exact span/kind scores on a small synthetic corpus, including known unsupported types."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from detector.core import detect

CORPUS = [
    ("Contact alice@example.com", [("EMAIL", "alice@example.com")]),
    ("🌍 bob+tag@example.org", [("EMAIL", "bob+tag@example.org")]),
    ("Phone 212-555-1234", [("PHONE", "212-555-1234")]),
    ("Call (415) 555-0100", [("PHONE", "(415) 555-0100")]),
    ("SSN 123-45-6789", [("SSN", "123-45-6789")]),
    ("Card 4111 1111 1111 1111", [("CREDIT_CARD", "4111 1111 1111 1111")]),
    ("sk-" + "a" * 24, [("SECRET", "sk-" + "a" * 24)]),
    ("ghp_" + "x" * 24, [("SECRET", "ghp_" + "x" * 24)]),
    ("AKIA" + "A" * 16, [("SECRET", "AKIA" + "A" * 16)]),
    ("password=" + "samplepass123", [("SECRET", "password=" + "samplepass123")]),
    ("-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----", [("SECRET", "-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----")]),
    ("alice@example.com / 123-45-6789", [("EMAIL", "alice@example.com"), ("SSN", "123-45-6789")]),
    ("ordinary text", []), ("version 1.2.3", []), ("order 1111111111111111", []),
    ("Invalid SSN 000-00-0000", []), ("invalid card 4111 1111 1111 1112", []),
    ("International +44 20 7946 0958", [("PHONE", "+44 20 7946 0958")]),
    ("Name: Jane Doe", [("PERSON", "Jane Doe")]),
    ("IP: 192.0.2.1", [("IP_ADDRESS", "192.0.2.1")]),
]


def evaluate():
    tp = fp = fn = 0
    cases = []
    started = time.perf_counter()
    for index, (text, expected) in enumerate(CORPUS):
        wanted = set()
        for kind, value in expected:
            start = text.index(value)
            wanted.add((kind, len(text[:start].encode()), len(text[:start + len(value)].encode())))
        found = {(s["kind"], s["start"], s["end"]) for s in detect(text)}
        tp += len(found & wanted)
        fp += len(found - wanted)
        fn += len(wanted - found)
        cases.append({"case": index, "expected": sorted(wanted), "found": sorted(found)})
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "corpus": "synthetic-v1, 20 examples; 3 deliberately unsupported challenge examples; not held out",
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else 0, "recall": tp / (tp + fn) if tp + fn else 0,
            "elapsed_seconds": time.perf_counter() - started, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/local-detection.json"))
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))
