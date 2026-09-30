"""Dependency-free internal HTTP service. Run behind the gateway's admission limit."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from detector.core import detect


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_):
        pass  # Never log request bodies or URLs supplied by clients.

    def reply(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/healthz" else 404, {"status": "alive"})

    def do_POST(self):
        if self.path != "/detect":
            return self.reply(404, {"error": "not found"})
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.key):
            return self.reply(401, {"error": "unauthorized"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                return self.reply(413, {"error": "invalid length"})
            self.connection.settimeout(5)
            request = json.loads(self.rfile.read(size))
            if set(request) != {"text"} or not isinstance(request["text"], str):
                raise ValueError("invalid request")
            self.reply(200, {"spans": detect(request["text"])})
        except (ValueError, TypeError, UnicodeError, TimeoutError):
            self.reply(400, {"error": "invalid request"})


class Server(ThreadingHTTPServer):
    request_queue_size = 1024
    daemon_threads = True


def main():
    key = os.environ.get("DETECTOR_KEY", "")
    if len(key) < 16:
        raise SystemExit("DETECTOR_KEY requires at least 16 characters")
    server = Server((os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8001"))), Handler)
    server.key = key
    server.serve_forever()


if __name__ == "__main__":
    main()
