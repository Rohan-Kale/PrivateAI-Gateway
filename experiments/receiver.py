"""Local receipt-time recorder for test Alertmanager webhooks; no external messaging."""
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from experiments.common import utc


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({"receipts":self.server.receipts}).encode()
        self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(body)
    def do_POST(self):
        try:
            size=int(self.headers.get("Content-Length","0"))
            if not 0<size<=1048576:raise ValueError()
            self.connection.settimeout(5);data=json.loads(self.rfile.read(size))
            record={"received_at":utc(),"status":data.get("status"),"alerts":[{"status":a.get("status"),"labels":a.get("labels"),"startsAt":a.get("startsAt")} for a in data.get("alerts",[])]}
            with self.server.lock:
                with self.server.path.open("a",encoding="utf-8") as f:f.write(json.dumps(record)+"\n")
                self.server.receipts.append(record)
            self.send_response(200);self.end_headers()
        except (ValueError,TypeError,TimeoutError):self.send_response(400);self.end_headers()


if __name__=="__main__":
    path=Path(os.environ.get("RECEIPTS_FILE","/results/alert-receipts.jsonl"));path.parent.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(("0.0.0.0",8010),Handler);server.path=path;server.lock=threading.Lock();server.receipts=[];server.serve_forever()
