"""Local deterministic echo provider. Synthetic latency, never a model-quality benchmark."""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mock.activity import Activity


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/stats":return self.stats()
        self.send_response(200 if self.path == "/healthz" else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path == "/stats/reset":
            return self.stats(200 if self.server.activity.reset() else 409)
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                raise ValueError()
            self.connection.settimeout(5)
            request = json.loads(self.rfile.read(size))
            text = "Echo: " + "\n".join(m["content"] for m in request["messages"])
        except (ValueError, KeyError, TypeError):
            self.send_error(400)
            return
        with self.server.activity.measure():
            self.respond(request,text)

    def stats(self,code=200):
        body=json.dumps(self.server.activity.snapshot()).encode()
        self.send_response(code);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)

    def respond(self,request,text):
        time.sleep(float(os.environ.get("MOCK_DELAY_MS", "10")) / 1000)
        self.send_response(200)
        if request.get("stream"):
            frames = []
            for start in range(0, len(text), 7):
                frame = {"choices": [{"delta": {"content": text[start:start + 7]}}]}
                frames.append(("data: " + json.dumps(frame) + "\n\n").encode())
            frames.append(b"data: [DONE]\n\n")
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(sum(map(len, frames))))
            self.end_headers()
            for frame in frames:
                self.wfile.write(frame)
                self.wfile.flush()
        else:
            body = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class Server(ThreadingHTTPServer):
    request_queue_size = 1024
    daemon_threads = True

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.activity=Activity()


if __name__ == "__main__":
    Server((os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8002"))), Handler).serve_forever()
