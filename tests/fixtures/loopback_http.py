"""A canned HTTP answer served on the loopback interface, for tests that need http.client itself.

A fake opener can raise whatever a test writes into it, which is how a reader came to be
tested against an ``IncompleteRead`` that ``http.client`` never raises for a bounded read of
a body sent with ``Content-Length``. The tests that make a claim about what the standard
library does with a response cut short use this instead: a socket in the same process,
bound to 127.0.0.1, that sends the bytes it is given and hangs up. Nothing leaves the
machine.
"""

import socket
import threading
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

#: A urllib opener with no proxy handler, so a proxy set on the machine running the tests
#: cannot stand between the reader and the loopback server.
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class Loopback:
    """Where the server listens, and how many requests it has answered."""

    url: str
    answered: list[bytes] = field(default_factory=list)


def status_head(**headers: str) -> bytes:
    """A 200 status line and the given headers, ready to be followed by a body."""

    lines = ["HTTP/1.1 200 OK", "Connection: close"]
    lines += [f"{name.replace('_', '-')}: {value}" for name, value in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


@contextmanager
def serving(answer: bytes) -> Iterator[Loopback]:
    """Answer every connection with ``answer`` and then close it, until the block ends."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    loopback = Loopback(url=f"http://127.0.0.1:{listener.getsockname()[1]}")
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(5.0)
                request = b""
                # The whole request head is read before answering, so the close below is a
                # clean end of stream rather than a reset over unread bytes.
                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                # Counted before the answer goes out, so a test that asserts the count once
                # its read has failed never races this thread.
                loopback.answered.append(request)
                connection.sendall(answer)
                connection.shutdown(socket.SHUT_WR)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield loopback
    finally:
        stop.set()
        thread.join(timeout=5.0)
        listener.close()
