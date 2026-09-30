"""Time an actual fresh-host trial through a completed job on that exact worker.

Requires an SSH-reachable Linux host and a gateway sharing an isolated test queue.
No VM, elapsed duration, or manual baseline is simulated by this program.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from experiments.common import demo_key,http,provenance,write_report


def ssh(host,command):
    # Host is a separate argv argument; the command is always a fixed internal string.
    if host.startswith("-") or any(c.isspace() for c in host):raise ValueError("invalid SSH destination")
    return subprocess.check_output(["ssh","-o","BatchMode=yes",host,command],text=True,timeout=30).strip()


def trial(args):
    output=Path(args.output)
    if output.exists():raise ValueError("refusing to overwrite trial evidence")
    fingerprint=hashlib.sha256(ssh(args.host,"cat /etc/machine-id").encode()).hexdigest()
    # This verifies only absence of prior project configuration. Fresh disk-image
    # provenance must also be supplied by the operator and is recorded explicitly.
    ssh(args.host,"test ! -e /etc/privateai/worker.env")
    hardware=ssh(args.host,"uname -r; getconf _NPROCESSORS_ONLN; head -1 /proc/meminfo; cat /etc/os-release")
    metadata={**provenance(),"experiment":"fresh-worker-provision-v1","mode":args.mode,"host_machine_id_sha256":fingerprint,"base_image_sha256":args.base_image_sha256,"host_metadata":hardware,"image_freshness":"operator attestation plus absence of /etc/privateai/worker.env","workload":"complete one queued synthetic request on the provisioned worker","warm_cache":args.warm_cache}
    input("Fresh-host prerequisites checked. Press Enter to start the real timer.")
    start=time.perf_counter();record={**metadata,"completed":False}
    try:
        if args.mode=="manual":
            print("Perform the documented manual setup now in another terminal. Match the automated role options exactly.")
            input("When the worker is running, press Enter to verify its first job (timer continues).")
        else:
            if not args.inventory or not args.vars_file:raise ValueError("ansible mode requires --inventory and --vars-file")
            subprocess.run(["ansible-playbook","-i",args.inventory,"ansible/provision.yml","--limit",args.limit,"-e","@"+args.vars_file],check=True)
        worker=ssh(args.host,"sudo -n docker inspect --format '{{.Config.Hostname}}' privateai-worker")
        key=demo_key();status,data=http(args.gateway+"/v1/jobs",{"model":"mock","messages":[{"role":"user","content":"Synthetic provisioning readiness probe"}]},key)
        if status!=202:raise RuntimeError("readiness job could not be enqueued")
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            status,result=http(args.gateway+"/v1/jobs/"+data["id"],key=key)
            if status!=200:raise RuntimeError("readiness polling failed")
            if result["status"]!="queued":break
            time.sleep(.5)
        if result["status"]!="completed" or result.get("worker")!=worker:
            raise RuntimeError("job did not complete on the intended worker; stop competing workers and retry on a fresh host")
        record.update(completed=True,seconds_to_first_job=time.perf_counter()-start,job_id=data["id"],worker=worker)
    except (Exception,KeyboardInterrupt) as error:
        record.update(failed_after_seconds=time.perf_counter()-start,error_type=type(error).__name__)
        raise
    finally:
        write_report(output,record)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--mode",choices=["manual","ansible"],required=True);p.add_argument("--host",required=True);p.add_argument("--base-image-sha256",required=True);p.add_argument("--warm-cache",action="store_true");p.add_argument("--inventory");p.add_argument("--vars-file");p.add_argument("--limit",default="worker-01");p.add_argument("--gateway",default=os.environ.get("GATEWAY_URL","http://127.0.0.1:18080"));p.add_argument("--output",required=True);a=p.parse_args()
    if len(a.base_image_sha256)!=64 or any(c not in "0123456789abcdef" for c in a.base_image_sha256):p.error("--base-image-sha256 must be a SHA-256 hex digest")
    trial(a)
