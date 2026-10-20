"""Tiny stdlib-only demo app.

MODE=server : HTTP backend. GET /stock returns 200 after an adjustable delay.
              POST /admin/delay?ms=N (localhost only) changes the delay.
MODE=client : load generator that calls TARGET and exposes Prometheus metrics
              (demo_requests_total, demo_request_duration_seconds) on :9100.
"""
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODE = os.environ.get("MODE", "client")
NAME = os.environ.get("NAME", "probe")


def run_server():
    state = {"delay_ms": int(os.environ.get("DELAY_MS", "0"))}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/stock":
                time.sleep(state["delay_ms"] / 1000.0)
                self._send(200, "ok\n")
            elif path == "/healthz":
                self._send(200, "ok\n")
            elif path == "/admin/delay":
                self._send(200, "delay_ms=%d\n" % state["delay_ms"])
            else:
                self._send(404, "not found\n")

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/admin/delay" and self.client_address[0] in ("127.0.0.1", "::1"):
                state["delay_ms"] = max(0, int(parse_qs(url.query).get("ms", ["0"])[0]))
                self._send(200, "delay_ms=%d\n" % state["delay_ms"])
            else:
                self._send(403, "forbidden\n")

    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


BUCKETS = [0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
RESULTS = ["ok", "http_error", "dns_error", "timeout", "conn_error"]
lock = threading.Lock()
counts = {r: 0 for r in RESULTS}
hist = [0] * (len(BUCKETS) + 1)
hist_sum = 0.0
hist_count = 0


def record(result, seconds):
    global hist_sum, hist_count
    with lock:
        counts[result] += 1
        hist_sum += seconds
        hist_count += 1
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                hist[i] += 1
                break
        else:
            hist[-1] += 1


def render_metrics(target_host):
    labels = 'app="%s",target="%s"' % (NAME, target_host)
    out = ["# TYPE demo_requests_total counter"]
    with lock:
        for result in RESULTS:
            out.append('demo_requests_total{%s,result="%s"} %d' % (labels, result, counts[result]))
        out.append("# TYPE demo_request_duration_seconds histogram")
        cumulative = 0
        for i, bound in enumerate(BUCKETS):
            cumulative += hist[i]
            out.append('demo_request_duration_seconds_bucket{%s,le="%s"} %d' % (labels, bound, cumulative))
        out.append('demo_request_duration_seconds_bucket{%s,le="+Inf"} %d' % (labels, hist_count))
        out.append("demo_request_duration_seconds_sum{%s} %f" % (labels, hist_sum))
        out.append("demo_request_duration_seconds_count{%s} %d" % (labels, hist_count))
    return "\n".join(out) + "\n"


def classify(target, timeout):
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            response.read()
            return "ok" if response.status < 500 else "http_error"
    except urllib.error.HTTPError:
        return "http_error"
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, socket.gaierror):
            return "dns_error"
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            return "timeout"
        return "conn_error"
    except TimeoutError:
        return "timeout"
    except Exception:
        return "conn_error"


def run_client():
    target = os.environ["TARGET"]
    host = urlparse(target).hostname
    timeout = float(os.environ.get("TIMEOUT", "2"))
    interval = float(os.environ.get("INTERVAL", "0.25"))
    workers = int(os.environ.get("WORKERS", "2"))

    def worker():
        while True:
            started = time.time()
            result = classify(target, timeout)
            record(result, time.time() - started)
            time.sleep(interval)

    for _ in range(workers):
        threading.Thread(target=worker, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = render_metrics(host).encode() if self.path == "/metrics" else b"ok\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("0.0.0.0", 9100), Handler).serve_forever()


if __name__ == "__main__":
    run_server() if MODE == "server" else run_client()
