"""The overall deadline over real sockets, with requests and urllib3 unpatched.

Each test runs a small HTTP server on 127.0.0.1 in a background thread. Nothing
leaves the machine, and every token and .netrc entry is a dummy. Pauses use
threading events, because the autouse ``sleeps`` fixture replaces time.sleep.

Timing margins are wide. The old behaviour, which waited for the whole body,
took about four times the deadline in the slow-body case.
"""

import gzip
import json
import socket
import threading
import time

import pytest
import requests

from fork_sync.deadline import Deadline, DeadlineExceeded
from fork_sync.github import GitHubClient

TOKEN = "dummy-token-real-transport-7a2b"
NETRC_PASSWORD = "netrc-password-must-not-be-sent"

DEADLINE = 1.0
# Well under the 4+ seconds the old behaviour took, well over the deadline.
CUT_OFF_BY = 2.5


def pause(seconds):
    threading.Event().wait(seconds)


class LoopbackServer:
    """Serves one request per connection, each in its own thread."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.client_gone = threading.Event()
        self.stopping = threading.Event()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.listener.getsockname()[1]}"

    def _accept(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            try:
                self.requests.append(self._read_request(conn))
                self.handler(conn, self)
                self._wait_for_client_to_close(conn)
            except OSError:
                # Sending failed because the client closed the connection.
                self.client_gone.set()

    @staticmethod
    def _read_request(conn):
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(65536)
        head, _, body = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                length = int(value)
        while len(body) < length:
            body += conn.recv(65536)
        return head.decode("latin-1")

    def _wait_for_client_to_close(self, conn):
        # A kept-alive connection stays open until the test ends.
        conn.settimeout(0.05)
        while not self.stopping.is_set():
            try:
                if not conn.recv(65536):
                    self.client_gone.set()
                    return
            except socket.timeout:
                continue

    def stop(self):
        self.stopping.set()
        self.listener.close()
        self.thread.join(timeout=10)


@pytest.fixture
def serve(monkeypatch):
    # A proxy configured on the machine must not intercept loopback requests.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    servers = []

    def start(handler):
        server = LoopbackServer(handler)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.stop()


@pytest.fixture
def closes(monkeypatch):
    """Record each response the client closes."""
    closed = []
    original = requests.Response.close

    def close(response):
        closed.append(response)
        original(response)

    monkeypatch.setattr(requests.Response, "close", close)
    return closed


def client_for(server, seconds):
    client = GitHubClient(TOKEN)
    client.BASE_URL = server.url
    client.deadline = Deadline(seconds)
    return client


def head(length=None, extra=b""):
    lines = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + extra
    if length is not None:
        lines += b"Content-Length: " + str(length).encode() + b"\r\n"
    return lines + b"\r\n"


def chunk(data):
    return f"{len(data):x}\r\n".encode() + data + b"\r\n"


SLOW_BODY = json.dumps({"login": "demo", "padding": " " * 180}).encode()


def drip_known_length(conn, server):
    conn.sendall(head(len(SLOW_BODY)))
    for byte in SLOW_BODY:
        if server.stopping.is_set():
            return
        pause(0.05)  # Far below the 30-second wait for each read.
        conn.sendall(bytes([byte]))


def drip_chunked(conn, server):
    conn.sendall(head(extra=b"Transfer-Encoding: chunked\r\n"))
    for byte in SLOW_BODY:
        if server.stopping.is_set():
            return
        pause(0.05)
        conn.sendall(chunk(bytes([byte])))
    conn.sendall(b"0\r\n\r\n")


def timed(call):
    started = time.monotonic()
    try:
        call()
    except Exception as error:
        return time.monotonic() - started, error
    return time.monotonic() - started, None


# A. A body that keeps trickling in


@pytest.mark.parametrize("handler", [drip_known_length, drip_chunked], ids=["length", "chunked"])
def test_trickling_body_is_abandoned_at_the_deadline(serve, handler):
    # The whole body would take about 10 seconds to arrive.
    server = serve(handler)

    elapsed, error = timed(client_for(server, DEADLINE).get_authenticated_user)

    assert isinstance(error, DeadlineExceeded)
    assert "while reading a GitHub response" in str(error)
    assert DEADLINE * 0.9 <= elapsed < CUT_OFF_BY
    assert len(server.requests) == 1  # Not retried.


# B. A normal reply


def test_prompt_reply_is_read_in_full(serve):
    # Under 100 items, so this is the only page requested.
    repositories = [{"full_name": f"demo/r{i}", "fork": True} for i in range(99)]
    body = json.dumps(repositories).encode()

    def reply(conn, _server):
        conn.sendall(head(len(body)) + body)

    server = serve(reply)

    assert client_for(server, 30).list_repositories() == repositories


@pytest.mark.parametrize("encoding", ["gzip", "chunked"])
def test_encoded_replies_are_decoded_in_full(serve, encoding):
    expected = {"login": "demo", "items": list(range(5000))}
    body = json.dumps(expected).encode()

    def reply(conn, _server):
        if encoding == "gzip":
            packed = gzip.compress(body)
            conn.sendall(head(len(packed), b"Content-Encoding: gzip\r\n") + packed)
        else:
            pieces = [body[i:i + 1000] for i in range(0, len(body), 1000)]
            conn.sendall(
                head(extra=b"Transfer-Encoding: chunked\r\n")
                + b"".join(chunk(piece) for piece in pieces)
                + b"0\r\n\r\n"
            )

    server = serve(reply)

    assert client_for(server, 30).get_authenticated_user() == expected


def test_reply_without_a_deadline_is_unchanged(serve):
    def reply(conn, _server):
        conn.sendall(head(2) + b"{}")

    server = serve(reply)
    client = GitHubClient(TOKEN)
    client.BASE_URL = server.url

    assert client.get_authenticated_user() == {}


# C. A server that stops sending


def test_stalled_body_is_abandoned_at_the_deadline(serve):
    deadline = 2.0

    def stall(conn, server):
        conn.sendall(head(len(SLOW_BODY)) + SLOW_BODY[:10])
        # Keep sending for most of the time limit, then go silent. A wait fixed
        # when the request started would run a second past the deadline.
        for byte in SLOW_BODY[10:40]:
            pause(0.05)
            conn.sendall(bytes([byte]))
        server.stopping.wait(30)

    server = serve(stall)

    elapsed, error = timed(client_for(server, deadline).get_authenticated_user)

    assert isinstance(error, DeadlineExceeded)
    assert "while reading a GitHub response" in str(error)
    assert deadline * 0.9 <= elapsed < deadline + 0.75
    assert len(server.requests) == 1


def test_ordinary_read_timeout_is_still_a_retried_request_error(serve, monkeypatch):
    # With plenty of time left, a silent server hits the per-read timeout,
    # which stays a request error that read requests retry.
    monkeypatch.setattr(GitHubClient, "TIMEOUT", 0.5)

    def stall(conn, server):
        conn.sendall(head(100) + b"{")
        server.stopping.wait(30)

    server = serve(stall)

    elapsed, error = timed(client_for(server, 60).get_authenticated_user)

    assert isinstance(error, requests.exceptions.ConnectionError)
    assert len(server.requests) == 1 + GitHubClient.READ_RETRIES
    assert elapsed < 10


def test_body_cut_short_by_the_server_is_an_error_not_a_result(serve):
    def truncated(conn, _server):
        conn.sendall(head(len(SLOW_BODY)) + SLOW_BODY[:20])
        conn.shutdown(socket.SHUT_WR)

    server = serve(truncated)

    _elapsed, error = timed(client_for(server, 30).get_authenticated_user)

    assert isinstance(error, requests.exceptions.ChunkedEncodingError)


# D. Cleanup


@pytest.mark.parametrize("handler", [drip_known_length, drip_chunked], ids=["length", "chunked"])
def test_connection_is_closed_after_the_deadline(serve, closes, handler):
    server = serve(handler)

    _elapsed, error = timed(client_for(server, DEADLINE).get_authenticated_user)

    assert isinstance(error, DeadlineExceeded)
    assert len(closes) == 1
    assert closes[0].raw.closed
    # The server sees the connection end long before the body would finish.
    assert server.client_gone.wait(CUT_OFF_BY)


def test_response_is_closed_after_a_complete_read(serve, closes):
    def reply(conn, _server):
        conn.sendall(head(2) + b"[]")

    server = serve(reply)

    assert client_for(server, 30).list_repositories() == []
    assert len(closes) == 1
    assert closes[0].raw.closed


# Merges are never cut short


def test_merge_reply_arriving_after_the_deadline_is_read_in_full(serve, monkeypatch):
    # Normally a merge needs 30 seconds left; lowered so the reply can outlast
    # a short deadline without a slow test.
    monkeypatch.setattr(GitHubClient, "MERGE_TIME_RESERVE", 0)
    body = json.dumps({"merge_type": "fast-forward"}).encode()

    def reply(conn, _server):
        conn.sendall(head(len(body)))
        for byte in body:
            pause(0.04)
            conn.sendall(bytes([byte]))

    server = serve(reply)
    client = client_for(server, 0.5)

    started = time.monotonic()
    result = client.merge_upstream("demo/x", "main")

    assert result["merge_type"] == "fast-forward"
    assert time.monotonic() - started > 0.5  # Finished after the deadline.
    assert [request.split(" ")[0] for request in server.requests] == ["POST"]


# E. Credentials


def test_only_the_bearer_token_is_sent_with_a_netrc_present(serve, tmp_path, monkeypatch):
    netrc = tmp_path / ".netrc"
    netrc.write_text(f"machine 127.0.0.1 login server-user password {NETRC_PASSWORD}\n")
    monkeypatch.setenv("NETRC", str(netrc))
    server = serve(drip_known_length)

    _elapsed, error = timed(client_for(server, DEADLINE).get_authenticated_user)

    assert isinstance(error, DeadlineExceeded)
    authorization = [
        line.split(":", 1)[1].strip()
        for line in server.requests[0].split("\r\n")
        if line.lower().startswith("authorization:")
    ]
    assert authorization == [f"Bearer {TOKEN}"]
    assert NETRC_PASSWORD not in server.requests[0]
    assert TOKEN not in str(error) and TOKEN not in repr(error)
