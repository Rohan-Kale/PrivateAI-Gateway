"""Small, auditable baseline detector. Not a claim of comprehensive DLP coverage."""
from __future__ import annotations

import re

PATTERNS = [
    ("SECRET", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\Z)")),
    ("SECRET", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b")),
    ("SECRET", re.compile(r"(?i)\b(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*[\"']?([^\s\"',;]{8,})")),
    ("EMAIL", re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")),
    ("SSN", re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)")),
    ("CREDIT_CARD", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+1[ .-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[ .-]?[2-9]\d{2}[ .-]?\d{4}(?!\d)")),
]
PRIORITY = {"SECRET": 0, "SSN": 1, "CREDIT_CARD": 2, "EMAIL": 3, "PHONE": 4}


def luhn(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit() and c.isascii()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    return sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d
               for i, d in enumerate(reversed(digits))) % 10 == 0


def detect(text: str) -> list[dict]:
    if len(text.encode("utf-8")) > 262144:
        raise ValueError("text exceeds 256 KiB")
    candidates = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            if kind == "CREDIT_CARD" and not luhn(match.group()):
                continue
            candidates.append((match.start(), match.end(), kind))
    # Merge intersecting detections into their union, using the highest-priority
    # kind. No lower-priority portion of an overlapping secret is left exposed.
    merged = []
    for start, end, kind in sorted(candidates):
        if merged and start < merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(end, previous[1]), min(kind, previous[2], key=PRIORITY.get))
        else:
            merged.append((start, end, kind))
    offsets = [0]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode("utf-8")))
    return [{"start": offsets[s], "end": offsets[e], "kind": k} for s, e, k in merged]
