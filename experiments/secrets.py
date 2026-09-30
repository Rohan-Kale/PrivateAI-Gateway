import argparse
import json
import math
import hashlib
import os
from pathlib import Path
from experiments.common import demo_key, digest, http, provenance, write_report


def wilson(successes,n):
    if n==0:return None
    z=1.96;p=successes/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [center-half,center+half]


def exposed(records,needles):
    for record in records:
        texts=[m["content"] for m in record["messages"]]
        if any(needle in text for needle in needles for text in texts+["".join(texts)]):return True
    return False


def evaluate(gateway,recorder,corpus_path,output):
    corpus=json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    canonical=hashlib.sha256(json.dumps(corpus,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    manifest=Path(corpus_path).with_name("manifest.json")
    if manifest.exists() and json.loads(manifest.read_text())["canonical_sha256"]!=canonical:
        raise ValueError("corpus does not match frozen manifest")
    if not corpus.get("synthetic_only"):raise ValueError("recorder is only for synthetic fixtures")
    key=demo_key();recorder_key=os.environ["RECORDER_KEY"]
    status,original=http(gateway+"/v1/policy",key=key)
    if status!=200:raise RuntimeError("policy unavailable")
    policy={"version":original["version"],"default":"redact","rules":{"SECRET":"block"},"restore":False,"cache_seconds":0}
    status,updated=http(gateway+"/admin/policies/demo",policy,os.environ["ADMIN_KEY"],"PUT")
    if status!=200:raise RuntimeError("cannot configure test policy")
    rows=[]
    try:
        for case in corpus["cases"]:
            status,_=http(recorder+"/reset",{},recorder_key)
            if status!=200:raise RuntimeError("cannot reset recorder")
            status,_=http(gateway+"/v1/chat/completions",{"model":"recording-fixture","messages":case["messages"]},key)
            captured,record=http(recorder+"/records",key=recorder_key)
            if captured!=200:raise RuntimeError("cannot read recorder")
            records=record["records"];leaked=exposed(records,case["exposure_needles"])
            valid=(status==403 and not records) or (status==200 and len(records)==1)
            rows.append({"id":case["id"],"family":case["family"],"label":case["label"],"http_status":status,"provider_calls":len(records),"exposed":leaked,"valid_outcome":valid})
    finally:
        original["version"]=updated["version"]
        restore,_=http(gateway+"/admin/policies/demo",original,os.environ["ADMIN_KEY"],"PUT")
        if restore!=200:raise RuntimeError("policy restoration conflicted; restore test tenant manually")
    positive=[r for r in rows if r["label"]=="secret"];negative=[r for r in rows if r["label"]=="benign"]
    prevented=sum(r["valid_outcome"] and not r["exposed"] for r in positive)
    blocks=sum(r["http_status"]==403 for r in negative)
    valid=all(r["valid_outcome"] for r in rows)
    report={**provenance(),"experiment":"secret-exposure-v1","corpus_sha256":digest(corpus_path),"dataset_size":len(rows),"secret_cases":len(positive),"benign_cases":len(negative),"policy":policy,"provider":"recording synthetic provider","storage":os.environ.get("STORE_MODE","database"),"prevented":prevented,"exposed":sum(r["exposed"] for r in positive),"prevented_fraction":prevented/len(positive),"wilson_95":wilson(prevented,len(positive)),"benign_blocked":blocks,"false_block_fraction":blocks/len(negative),"invalid_outcomes":sum(not r["valid_outcome"] for r in rows),"target_met":valid and prevented/len(positive)>=.99,"cases":rows,"limitations":"Generated challenge cases, not a representative held-out corpus. No real credentials. Errors are not credited as successful prevention."}
    report["corpus_canonical_sha256"]=canonical
    report["corpus_name"]=corpus.get("name")
    report["held_out"]=corpus.get("held_out",False)
    write_report(output,report);return report


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--gateway",default=os.environ.get("GATEWAY_URL","http://gateway:8080"));p.add_argument("--recorder",default="http://recorder:8003");p.add_argument("--corpus",default="experiments/fixtures/secrets-v1.json");p.add_argument("--output",default="/results/secrets.json");a=p.parse_args()
    r=evaluate(a.gateway,a.recorder,a.corpus,a.output);print(json.dumps({k:v for k,v in r.items() if k!="cases"},indent=2))
