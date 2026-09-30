"""Freeze independently labeled synthetic exposure cases before evaluating a detector.

This is a generated challenge set, not a held-out real-world credential dataset.
Labels describe secrets regardless of what the current recognizers support.
"""
import argparse
import base64
import json
from pathlib import Path
import random
import string
from experiments.common import write_report


def build(seed=73129, per_family=50):
    rng = random.Random(seed)
    alphabet = string.ascii_letters + string.digits
    def token(n=30):
        return "".join(rng.choice(alphabet) for _ in range(n))
    cases = []
    for i in range(per_family):
        secret = "sk-" + token()
        key = token(40)
        definitions = [
            ("api_key_prefix", ["Use " + secret], [secret]),
            ("github_token", ["Bearer ghp_" + key], ["ghp_" + key]),
            ("github_fine_grained", ["github_pat_" + key], ["github_pat_" + key]),
            ("aws_access_id", ["AKIA" + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(16))], None),
            ("credential_assignment", ["PASSWORD = '" + key + "'"], [key]),
            ("private_key", ["-----BEGIN PRIVATE KEY-----\n" + key + "\n-----END PRIVATE KEY-----"], [key]),
            ("url_encoded", [secret.replace("-", "%2D")], [secret.replace("-", "%2D"), secret]),
            ("base64_encoded", [base64.b64encode(secret.encode()).decode()], [base64.b64encode(secret.encode()).decode(), secret]),
            ("split_messages", [secret[:10], secret[10:]], [secret]),
            ("generic_unlabeled", [key], [key]),
            ("jwt", ["eyJhbGciOiJIUzI1NiJ9." + base64.urlsafe_b64encode(json.dumps({"sub":token(8)}).encode()).decode().rstrip("=") + "." + key], None),
            ("unicode_context", ["🌍 秘密 " + secret], [secret]),
        ]
        for family, contents, needles in definitions:
            cases.append({"id":f"{family}-{i:04}","family":family,"label":"secret","messages":[{"role":"user","content":s} for s in contents],"exposure_needles":needles or contents})
        for family, text in [("ordinary_prose", f"Explain worker retry behavior for item {i}."),
                             ("random_identifier", "Request identifier " + token(40)),
                             ("documented_placeholder", "Documentation example: api_key=YOUR_API_KEY_HERE"),
                             ("public_contact", "Public project contact maintainer@example.org"),
                             ("version_number", f"Release version 2.{i}.0 has no credentials."),
                             ("quoted_detection_rule", "The detector recognizes the word password, not every sentence containing it.")]:
            cases.append({"id":f"benign-{family}-{i:04}","family":family,"label":"benign","messages":[{"role":"user","content":text}],"exposure_needles":[]})
    rng.shuffle(cases)
    return {"schema_version":1,"name":"synthetic-exposure-v1","seed":seed,"per_family":per_family,"synthetic_only":True,"held_out":False,"cases":cases}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("experiments/fixtures/secrets-v1.json"))
    parser.add_argument("--seed",type=int,default=73129)
    parser.add_argument("--per-family",type=int,default=50)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite a frozen corpus; choose a new version")
    write_report(args.output,build(args.seed,args.per_family))
