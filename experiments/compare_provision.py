"""Compare real completed fresh-host trials; do not invent a manual baseline."""
import argparse
import json
import math
from pathlib import Path
import statistics
from experiments.common import digest, write_report


def compare(rows):
    if not rows or any(not r.get("completed") for r in rows):raise ValueError("all supplied trials must be completed; report failed attempts separately")
    fields=("base_image_sha256","warm_cache","configuration_profile")
    if any(any(k not in r for k in fields) for r in rows):raise ValueError("missing comparison conditions")
    conditions={tuple(r[k] for k in fields) for r in rows}
    if len(conditions)!=1:raise ValueError("image, cache state, and configuration profile must match")
    identities=[r.get("host_machine_id_sha256") for r in rows]
    if None in identities or len(set(identities))!=len(rows):raise ValueError("each trial needs a distinct fresh-host identity")
    groups={m:[] for m in ("manual","ansible")}
    for row in rows:
        seconds=row.get("seconds_to_first_job")
        if row.get("mode") not in groups or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<=0:
            raise ValueError("invalid trial mode or elapsed duration")
        groups[row["mode"]].append(seconds)
    if any(len(values)<3 for values in groups.values()):raise ValueError("at least three completed fresh-host trials per mode required")
    summary={m:{"trials":len(values),"median_seconds":statistics.median(values),"min_seconds":min(values),"max_seconds":max(values)} for m,values in groups.items()}
    manual=summary["manual"]["median_seconds"];automated=summary["ansible"]["median_seconds"]
    return {"experiment":"provision-comparison-v1","conditions":dict(zip(fields,next(iter(conditions)))),"modes":summary,"median_reduction_percent":100*(manual-automated)/manual,"limitations":"Operator-attested equivalent configuration/freshness; no inference about unsubmitted attempts. Include failure counts and raw trials when publishing."}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('reports',nargs='+',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise SystemExit('refusing to overwrite evidence')
    result=compare([json.loads(p.read_text(encoding='utf-8')) for p in args.reports])
    result['inputs']=[{'file':p.name,'sha256':digest(p)} for p in args.reports]
    write_report(args.output,result)
