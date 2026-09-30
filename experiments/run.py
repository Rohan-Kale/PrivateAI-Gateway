"""Controller for an isolated local Compose experiment project. Never touches the demo project."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from experiments.common import http, provenance, utc, write_report

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=["docker","compose","-p","privateai-evidence","-f","compose.yaml","-f","experiments/compose.yaml"]
OUT=ROOT/"work/evidence"


def command(args,**kwargs):
    return subprocess.run(args,cwd=ROOT,check=True,**kwargs)


def ready(timeout=120):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            if http("http://127.0.0.1:18080/readyz",timeout=3)[0]==200:return
        except OSError:pass
        time.sleep(1)
    raise RuntimeError("experiment gateway did not become ready")


def sample(stop):
    with (OUT/"resources.jsonl").open("w",encoding="utf-8") as file:
        while not stop.is_set():
            row={"timestamp_utc":utc()}
            try:
                ids=command(COMPOSE+["ps","-q"],capture_output=True,text=True).stdout.split()
                if ids:
                    output=command(["docker","stats","--no-stream","--format","{{json .}}",*ids],capture_output=True,text=True).stdout
                    row["containers"]=[json.loads(line) for line in output.splitlines()]
                for name,query in [("queue_depth","max(privateai_queue_depth)"),("inflight","sum(privateai_inflight)"),("worker_count",'count(up{job="privateai-worker"} == 1)')]:
                    from urllib.parse import urlencode
                    code,data=http("http://127.0.0.1:19090/api/v1/query?"+urlencode({"query":query}),timeout=5)
                    row[name]=data.get("data",{}).get("result",[]) if code==200 else None
            except (OSError,ValueError,subprocess.CalledProcessError) as error:row["sampling_error"]=type(error).__name__
            file.write(json.dumps(row)+"\n");file.flush();stop.wait(5)


def secrets():
    recording=COMPOSE+["-f","experiments/recording.yaml"]
    try:
        command(recording+["up","-d","--no-deps","--wait","gateway"]);ready()
        command(COMPOSE+["run","--rm","loadgen","python","-m","experiments.secrets"])
    finally:
        command(COMPOSE+["up","-d","--no-deps","--wait","gateway"]);ready()


def restore_service(service):
    # Compose rejects --scale for a service not selected by this invocation.
    args=["up","--no-deps","-d","--wait"]
    if service=="worker":args += ["--scale","worker=3"]
    command(COMPOSE+args+[service],stdout=subprocess.DEVNULL)
    ready()


def faults(repeats=3,resume=False):
    report_path=OUT/"faults.json"
    previous=json.loads(report_path.read_text()) if resume and report_path.exists() else {}
    records=previous.get("records",[])
    metadata={**provenance(),"experiment":"fault-to-local-webhook-v1","receiver":"local Alertmanager webhook; not email/SMS delivery"}
    if previous:metadata["resumed_from_commit"]=previous.get("commit")
    def save():write_report(report_path,{**metadata,"records":records})
    # Stop commands target only this isolated project, with restoration in finally.
    for service in ("worker","detector","postgres","redis"):
        for trial in range(repeats):
            if any(r["service"]==service and r["trial"]==trial and r.get("restoration_complete",True) for r in records):continue
            ready();time.sleep(20)  # healthy scrape/evaluation baseline after prior restoration
            injection=utc();mono=time.monotonic();receipt=None
            try:
                command(COMPOSE+["stop","-t","2",service],stdout=subprocess.DEVNULL)
                stopped=utc();end=time.monotonic()+150
                while time.monotonic()<end:
                    code,data=http("http://127.0.0.1:18010/",timeout=5)
                    if code==200:
                        for item in data["receipts"]:
                            if item["received_at"]<=injection:continue
                            for alert in item.get("alerts",[]):
                                labels=alert.get("labels",{})
                                matches=(labels.get("service")==service or service in ("postgres","redis") and labels.get("service")=="gateway" or service=="worker" and labels.get("alertname")=="PrivateAIWorkerUnavailable")
                                # Reject repeat notifications for an alert that began before this fault.
                                if matches and alert["status"]=="firing" and datetime.fromisoformat(alert["startsAt"].replace("Z","+00:00"))>=datetime.fromisoformat(injection):
                                    receipt=item;break
                            if receipt:break
                    if receipt:break
                    time.sleep(1)
                latency=None if receipt is None else (datetime.fromisoformat(receipt["received_at"])-datetime.fromisoformat(injection)).total_seconds()
                records.append({"service":service,"trial":trial,"injection_requested_at":injection,"stop_completed_at":stopped,"receipt":receipt,"detection_seconds":latency,"within_120_seconds":latency is not None and latency<=120,"restoration_complete":False})
                save()
            finally:
                restore_service(service)
            records[-1]["restoration_complete"]=True
            save()
    return records


def main():
    p=argparse.ArgumentParser();p.add_argument("phase",choices=["prepare","secrets","policy","soak","faults","all","stop"]);p.add_argument("--seconds",type=int,default=900);p.add_argument("--fault-repeats",type=int,default=3);p.add_argument("--resume-faults",action="store_true");a=p.parse_args()
    os.chdir(ROOT);OUT.mkdir(parents=True,exist_ok=True)
    os.environ["EVIDENCE_COMMIT"]=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    if a.phase=="stop":command(COMPOSE+["stop"]);return
    if a.phase in ("prepare","all"):
        # Build shared image tags once to avoid concurrent tag exports on Docker 29.
        command(COMPOSE+["build","gateway"])
        command(COMPOSE+["build","detector"])
        command(COMPOSE+["up","--no-build","-d","--wait","--scale","worker=3"])
        ready();write_report(OUT/"environment.json",{**provenance(),"worker_replicas":3,"docker_version":subprocess.check_output(["docker","version","--format","{{.Server.Version}}"],text=True).strip(),"provider":"mock","mock_delay_ms":1000,"project":"privateai-evidence"})
    if a.phase in ("secrets","all"):secrets()
    if a.phase in ("policy","all"):command(COMPOSE+["run","--build","--rm","policybench"])
    if a.phase in ("soak","all"):
        stop=threading.Event();sampler=threading.Thread(target=sample,args=(stop,));sampler.start()
        try:command(COMPOSE+["run","--rm","loadgen","python","-m","experiments.soak","--seconds",str(a.seconds)])
        finally:stop.set();sampler.join(timeout=30)
    if a.phase in ("faults","all"):faults(a.fault_repeats,a.resume_faults)


if __name__=="__main__":main()
