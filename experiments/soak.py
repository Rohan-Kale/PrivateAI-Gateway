"""Closed-loop sustained queue load from a separate container; no hidden retries."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import threading
import time
import uuid
from experiments.common import demo_key, http, percentile, provenance, write_report


def run(url,seconds,concurrency,output,poll_seconds=.25):
    if seconds<=0 or concurrency<1:raise ValueError("positive duration/concurrency required")
    provider_stats_url=os.environ.get("PROVIDER_STATS_URL")
    if provider_stats_url:
        code,provider_before=http(provider_stats_url+"/reset",{},timeout=5)
        if code!=200:raise RuntimeError("mock provider is busy; cannot start an isolated concurrency measurement")
    key=demo_key();barrier=threading.Barrier(concurrency+1);lock=threading.Lock()
    started=deadline=0.;active=peak=0;rows=0
    statuses=Counter();workers=Counter();latencies=[];waits=[];services=[];minute_bins={}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    samples=output.with_suffix(".samples.jsonl.gz")
    identity=uuid.uuid4().hex
    def client(number,stream):
        nonlocal active,peak,rows
        barrier.wait(timeout=60);sequence=0
        while time.monotonic()<deadline:
            sequence+=1;begin=time.monotonic();job=None;worker=None;queue_wait=service=None
            with lock:active+=1;peak=max(peak,active)
            try:
                code,data=http(url+"/v1/jobs",{"model":"mock","messages":[{"role":"user","content":f"Synthetic soak {identity} client {number} request {sequence}"}]},key)
                if code!=202:status=f"submit_{code}"
                else:
                    job=data["id"];status="timeout"
                    while time.monotonic()-begin<120:
                        code,data=http(url+"/v1/jobs/"+job,key=key,timeout=10)
                        if code!=200:status=f"poll_{code}";break
                        if data["status"]!="queued":
                            status=data["status"];worker=data.get("worker")
                            if data.get("started_at") and data.get("enqueued_at") and data.get("finished_at"):
                                parse=lambda s:datetime.fromisoformat(s.replace("Z","+00:00"))
                                queue_wait=(parse(data["started_at"])-parse(data["enqueued_at"])).total_seconds()
                                service=(parse(data["finished_at"])-parse(data["started_at"])).total_seconds()
                            break
                        time.sleep(poll_seconds)
            except (OSError,TimeoutError,ValueError,KeyError):status="transport_or_protocol_error"
            elapsed=time.monotonic()-begin
            record={"offset_seconds":begin-started,"client":number,"sequence":sequence,"job_id":job,"status":status,"latency_seconds":elapsed,"worker":worker,"queue_wait_seconds":queue_wait,"service_seconds":service}
            with lock:
                active-=1;rows+=1;statuses[status]+=1;latencies.append(elapsed)
                if worker:workers[worker]+=1
                if queue_wait is not None:waits.append(queue_wait);services.append(service)
                minute=int((begin-started)//60);bucket=minute_bins.setdefault(minute,Counter());bucket[status]+=1
                stream.write(json.dumps(record)+"\n")
    with gzip.open(samples,"wt",encoding="utf-8") as stream:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures=[pool.submit(client,i,stream) for i in range(concurrency)]
            started=time.monotonic();deadline=started+seconds;barrier.wait(timeout=60)
            while any(not f.done() for f in futures):
                time.sleep(min(5,seconds))
                with lock:print(json.dumps({"elapsed_seconds":round(time.monotonic()-started,1),"outstanding":active,"statuses":dict(statuses)}),flush=True)
            for f in futures:f.result()
    elapsed=time.monotonic()-started
    summary=lambda values:{"p50":percentile(values,.5),"p95":percentile(values,.95),"p99":percentile(values,.99)}
    report={**provenance(),"experiment":"sustained-queue-v1","provider":"mock with configured synthetic delay","mock_delay_ms":os.environ.get("MOCK_DELAY_MS"),"storage":"PostgreSQL and Redis","topology":"separate load-generator container on the same physical host; not separate hardware","duration_seconds_requested":seconds,"elapsed_with_drain_seconds":elapsed,"configured_clients":concurrency,"peak_outstanding_clients":peak,"requests":rows,"statuses":dict(statuses),"successful_jobs_per_second":statuses["completed"]/elapsed,"worker_completions":dict(workers),"latency_seconds":summary(latencies),"queue_wait_seconds":summary(waits),"service_seconds":summary(services),"per_minute_statuses":minute_bins,"poll_interval_seconds":poll_seconds,"samples_file":samples.name,"target_conditions":{"at_least_15_minutes":seconds>=900,"at_least_200_clients":peak>=200,"multiple_workers_observed":len(workers)>=2,"all_jobs_completed":statuses["completed"]==rows},"limitations":"Closed-loop client concurrency; not proof of 200 simultaneous provider executions. Inspect Prometheus inflight data. Polling adds latency. No inference retries in the generator."}
    if provider_stats_url:
        code,provider_after=http(provider_stats_url,timeout=5)
        if code!=200:raise RuntimeError("provider concurrency measurement unavailable")
        report["provider_execution"]={"before":provider_before,"after":provider_after,"scope":"mock execution from artificial delay through response write; synchronized in one provider process"}
        report["target_conditions"]["at_least_200_simultaneous_mock_executions"]=provider_after["peak_active"]>=200
    write_report(output,report);return report


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--url",default=os.environ.get("GATEWAY_URL","http://gateway:8080"));p.add_argument("--seconds",type=int,default=900);p.add_argument("--concurrency",type=int,default=200);p.add_argument("--output",default="/results/soak.json");a=p.parse_args();print(json.dumps(run(a.url,a.seconds,a.concurrency,a.output),indent=2))
