"""Prometheus readiness checks, including the gateway/worker dependency probes."""
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from experiments.common import http

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        lines=[]
        for name,url in [("gateway", "http://gateway:8080/readyz"),("worker","http://worker:8080/readyz"),("detector","http://detector:8001/healthz")]:
            try:up=int(http(url,timeout=3)[0]==200)
            except OSError:up=0
            lines.append(f'privateai_dependency_ready{{service="{name}"}} {up}')
        self.send_response(200);self.send_header("Content-Type","text/plain; version=0.0.4");self.end_headers();self.wfile.write(("\n".join(lines)+"\n").encode())
if __name__=="__main__":ThreadingHTTPServer(("0.0.0.0",8011),Handler).serve_forever()
