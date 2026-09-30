"""TEST ONLY: records synthetic provider-bound requests in memory. Never deploy with real data."""
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self,*args): pass
    def reply(self,status,data):
        body=json.dumps(data).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=="/healthz":return self.reply(200,{"status":"ready"})
        if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+self.server.key):return self.reply(401,{"error":"unauthorized"})
        with self.server.lock:
            if self.path=="/records":return self.reply(200,{"records":list(self.server.records)})
        self.reply(404,{"error":"not found"})
    def do_POST(self):
        if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+self.server.key):return self.reply(401,{"error":"unauthorized"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if not 0<size<=131072:raise ValueError()
            self.connection.settimeout(5);data=json.loads(self.rfile.read(size))
            with self.server.lock:
                if self.path=="/reset":self.server.records.clear();return self.reply(200,{"ok":True})
                if self.path!="/v1/chat/completions":return self.reply(404,{"error":"not found"})
                if len(self.server.records)>=10000:return self.reply(503,{"error":"record limit reached"})
                self.server.records.append(data)
            self.reply(200,{"choices":[{"message":{"role":"assistant","content":"Synthetic request received."}}]})
        except (ValueError,TypeError,TimeoutError):self.reply(400,{"error":"invalid request"})


if __name__=="__main__":
    key=os.environ["RECORDER_KEY"]
    if len(key)<16:raise SystemExit("RECORDER_KEY must be at least 16 characters")
    ThreadingHTTPServer.request_queue_size=256
    server=ThreadingHTTPServer((os.environ.get("HOST","0.0.0.0"),int(os.environ.get("PORT","8003"))),Handler)
    server.key=key;server.lock=threading.Lock();server.records=[];server.serve_forever()
