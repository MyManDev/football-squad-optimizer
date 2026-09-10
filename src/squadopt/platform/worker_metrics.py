"""A worker-owned Prometheus listener; no counters are shared with the API process."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


@contextmanager
def serve_worker_metrics(
    render: Callable[[], str], *, host: str = "127.0.0.1", port: int = 9091
) -> Iterator[ThreadingHTTPServer]:
    """Serve only process liveness and a snapshot of this worker's metrics."""

    started = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                body, status = b"ok\n", 200
            elif self.path == "/metrics":
                try:
                    process_metrics = (
                        "# TYPE process_cpu_seconds_total counter\n"
                        f"process_cpu_seconds_total {time.process_time()}\n"
                        "# TYPE advice_worker_uptime_seconds gauge\n"
                        f"advice_worker_uptime_seconds {time.monotonic() - started}\n"
                    )
                    body, status = (render() + process_metrics).encode("utf-8"), 200
                except (OSError, ValueError):
                    body, status = b"Worker metrics are temporarily unavailable.\n", 503
            else:
                body, status = b"Not found.\n", 404
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    listener = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    listener.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        listener.join(timeout=2)
