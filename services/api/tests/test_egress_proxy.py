"""The egress proxy is the SSRF boundary for page capture: DNS rebinding, redirects
and non-HTTP requests (WebSocket tunnels) must all be refused at it."""

import asyncio
import http.server
import ipaddress
import socket
import threading

import pytest

from synccut import netguard
from synccut.capture import chromium_executable
from synccut.netguard import EgressProxy, resolve_pinned


@pytest.fixture(autouse=True)
def no_dev_override(monkeypatch):
    monkeypatch.delenv("SYNCCUT_ALLOW_PRIVATE_URLS", raising=False)


def raw(proxy_port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=10) as s:
        s.sendall(request)
        return s.recv(256)


@pytest.mark.parametrize("request_bytes", [
    b"CONNECT 127.0.0.1:8000 HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n",
    b"CONNECT localhost:443 HTTP/1.1\r\nHost: localhost\r\n\r\n",
    b"CONNECT [::1]:443 HTTP/1.1\r\nHost: [::1]\r\n\r\n",
    b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n",
    b"GET http://10.0.0.1/ HTTP/1.1\r\nHost: 10.0.0.1\r\n\r\n",
    b"CONNECT 8.8.8.8:22 HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n",  # public, but not a web port
    b"GET ftp://8.8.8.8/ HTTP/1.1\r\n\r\n",
])
def test_proxy_refuses_internal_destinations(request_bytes):
    with EgressProxy() as proxy:
        reply = raw(proxy.port, request_bytes)
    assert reply.startswith((b"HTTP/1.1 403", b"HTTP/1.1 400")), reply


def test_dns_rebinding_name_is_refused(monkeypatch):
    """A name that resolves to an internal address (even alongside a public one) is refused,
    and the proxy connects only to the address it checked."""
    answers = {"rebind.example": ["93.184.216.34", "127.0.0.1"], "inside.example": ["10.1.2.3"], "ok.example": ["93.184.216.34"]}

    async def fake_getaddrinfo(self, host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in answers[host]]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    assert asyncio.run(resolve_pinned("rebind.example", 443)) is None
    assert asyncio.run(resolve_pinned("inside.example", 443)) is None
    assert asyncio.run(resolve_pinned("ok.example", 443)) == "93.184.216.34"
    with EgressProxy() as proxy:
        assert raw(proxy.port, b"CONNECT rebind.example:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 403")


class _Handler(http.server.BaseHTTPRequestHandler):
    redirect_to = ""
    hits: list = []

    def do_GET(self):  # noqa: N802
        self.hits.append(self.path)
        if self.redirect_to:
            self.send_response(302)
            self.send_header("Location", self.redirect_to)
            self.end_headers()
        else:
            body = b"INTERNAL-SECRET"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve(host: str, redirect_to: str = ""):
    handler = type("H", (_Handler,), {"redirect_to": redirect_to, "hits": []})
    server = http.server.ThreadingHTTPServer((host, 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_browser_cannot_follow_a_redirect_into_the_internal_network(monkeypatch):
    """A 'public' page (simulated on 127.0.0.2) redirects to an internal one on 127.0.0.1.
    The browser follows redirects itself, so only the proxy can stop the second hop."""
    from playwright.sync_api import sync_playwright

    secret = _serve("127.0.0.1")
    secret_url = f"http://127.0.0.1:{secret.server_address[1]}/secret"
    public = _serve("127.0.0.2", redirect_to=secret_url)
    public_url = f"http://127.0.0.2:{public.server_address[1]}/"

    real = netguard._is_public_ip
    monkeypatch.setattr(netguard, "_is_public_ip", lambda ip: ip == ipaddress.ip_address("127.0.0.2") or real(ip))
    monkeypatch.setattr(netguard, "ALLOWED_PORTS", netguard.ALLOWED_PORTS | {public.server_address[1], secret.server_address[1]})
    try:
        with EgressProxy() as proxy, sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium_executable(), headless=True,
                                        args=proxy.chromium_args(), proxy={"server": proxy.url, "bypass": ""})
            page = browser.new_page()
            try:
                page.goto(public_url, timeout=15000)
            except Exception:
                pass  # a refused hop surfaces as a navigation error; that's the expected outcome
            content = page.content()
            browser.close()
        assert public.RequestHandlerClass.hits, "the first (public) hop should have gone through the proxy"
        assert secret.RequestHandlerClass.hits == [], "the internal server must never be contacted"
        assert "INTERNAL-SECRET" not in content
    finally:
        secret.shutdown()
        public.shutdown()


def test_proxy_still_reaches_public_sites():
    """Sanity check (needs internet): a normal public page loads through the proxy."""
    from playwright.sync_api import sync_playwright

    try:
        socket.create_connection(("www.bing.com", 443), timeout=5).close()
    except OSError:
        pytest.skip("no internet")
    with EgressProxy() as proxy, sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_executable(), headless=True,
                                    args=proxy.chromium_args(), proxy={"server": proxy.url, "bypass": ""})
        page = browser.new_page()
        page.goto("https://www.bing.com/search?q=synccut", timeout=30000)
        title = page.title()
        browser.close()
    assert "synccut" in title.lower()


@pytest.mark.parametrize("address", [
    "64:ff9b::7f00:1",          # NAT64 → 127.0.0.1
    "64:ff9b::a00:1",           # NAT64 → 10.0.0.1
    "2002:7f00:1::",            # 6to4 → 127.0.0.1
    "2002:a9fe:a9fe::",         # 6to4 → 169.254.169.254
    "::ffff:10.0.0.1",          # IPv4-mapped private
    "fc00::1", "fe80::1", "::1", "ff02::1",
])
def test_ipv6_forms_of_internal_addresses_are_refused(address):
    assert netguard._is_public_ip(ipaddress.ip_address(address)) is False


def test_global_addresses_are_allowed():
    for address in ("8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"):  # last: NAT64 → 8.8.8.8
        assert netguard._is_public_ip(ipaddress.ip_address(address)) is True


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        self.seen.append((self.path, self.headers.get("Host")))
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_one_request_per_connection_and_host_rewritten(monkeypatch):
    """A pipelined second request (for another host) must not ride along to the first server,
    and a spoofed Host header must not reach it."""
    public = http.server.ThreadingHTTPServer(("127.0.0.2", 0), type("A", (_Recorder,), {"seen": []}))
    secret = http.server.ThreadingHTTPServer(("127.0.0.1", 0), type("S", (_Recorder,), {"seen": []}))
    for s in (public, secret):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    pa, sa = public.server_address[1], secret.server_address[1]
    real = netguard._is_public_ip
    monkeypatch.setattr(netguard, "_is_public_ip", lambda ip: ip == ipaddress.ip_address("127.0.0.2") or real(ip))
    monkeypatch.setattr(netguard, "ALLOWED_PORTS", netguard.ALLOWED_PORTS | {pa, sa})
    try:
        pipelined = (f"GET http://127.0.0.2:{pa}/first HTTP/1.1\r\nHost: admin.internal\r\n\r\n"
                     f"GET http://127.0.0.1:{sa}/secret HTTP/1.1\r\nHost: 127.0.0.1:{sa}\r\n\r\n").encode()
        with EgressProxy() as proxy, socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as s:
            s.sendall(pipelined)
            reply = b""
            while chunk := s.recv(4096):
                reply += chunk
        assert reply.count(b"HTTP/1.") == 1  # one response, then the proxy closed the connection
        assert public.RequestHandlerClass.seen == [("/first", f"127.0.0.2:{pa}")]  # Host rewritten
        assert secret.RequestHandlerClass.seen == []
    finally:
        public.shutdown()
        secret.shutdown()


def test_chunked_and_upgrade_requests_are_refused():
    with EgressProxy() as proxy:
        assert raw(proxy.port, b"POST http://8.8.8.8/ HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n").startswith(b"HTTP/1.1 400")
        assert raw(proxy.port, b"GET http://8.8.8.8/ HTTP/1.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n").startswith(b"HTTP/1.1 400")


@pytest.mark.parametrize("address", ["::7f00:1", "::a00:1", "::a9fe:a9fe"])  # IPv4-compatible forms
def test_ipv4_compatible_ipv6_is_refused(address):
    assert netguard._is_public_ip(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("request_bytes", [
    b"GET http://127.0.0.1\@8.8.8.8/ HTTP/1.1\r\n\r\n",          # backslash authority trick
    b"GET http://8.8.8.8@127.0.0.1/ HTTP/1.1\r\n\r\n",             # userinfo
    b"GET http://8.8.8.8/ HTTP/1.1 extra\r\n\r\n",                 # malformed request line
    b"get http://8.8.8.8/ HTTP/1.1\r\n\r\n",                       # non-canonical method
    b"GET http://8.8.8.8/ HTTP/1.1\r\nX: a\r\n Transfer-Encoding: chunked\r\n\r\n",  # obs-fold
    b"GET http://8.8.8.8/ HTTP/1.1\r\nTransfer-Encoding : chunked\r\n\r\n",          # space before colon
    b"POST http://8.8.8.8/ HTTP/1.1\r\nContent-Length: +5\r\n\r\n",                  # non-digit length
    b"CONNECT 127.0.0.1:443@8.8.8.8:443 HTTP/1.1\r\n\r\n",
    b"CONNECT 8.8.8.8 HTTP/1.1\r\n\r\n",                           # no port
    b"GET http://8.8.8.8/\x00 HTTP/1.1\r\n\r\n",
])
def test_ambiguous_requests_are_refused(request_bytes):
    with EgressProxy() as proxy:
        assert raw(proxy.port, request_bytes).startswith((b"HTTP/1.1 400", b"HTTP/1.1 403"))


def test_huge_chunk_is_streamed_not_buffered():
    """A server declaring a giant chunk must not make the proxy allocate it: bytes flow
    through as they arrive."""
    from synccut.netguard import _relay_one_response

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nfffffffff\r\n" + b"x" * 100_000)
        reader.feed_eof()  # server stops after 100 KB of a "64 GB" chunk

        class Sink:
            def __init__(self):
                self.size = 0
            def write(self, b):
                self.size += len(b)
            async def drain(self):
                pass

        sink = Sink()
        with pytest.raises(ConnectionError):
            await _relay_one_response(reader, sink, False)
        return sink.size

    assert asyncio.run(run()) > 100_000  # everything received was forwarded


def test_connections_over_the_limit_are_refused(monkeypatch):
    monkeypatch.setattr(netguard, "MAX_CONNECTIONS", 2)
    with EgressProxy() as proxy:
        idle = [socket.create_connection(("127.0.0.1", proxy.port), timeout=10) for _ in range(2)]
        import time
        time.sleep(0.3)
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as extra:
            assert extra.recv(256).startswith(b"HTTP/1.1 503")  # refused before it can send anything
        for s in idle:
            s.close()
