"""Outbound URL guard for page capture (SSRF protection).

The capture browser opens URLs that come from the narration or from users, and
the pages it opens can redirect or embed anything. Only public http(s)
destinations are allowed: loopback, private, link-local (cloud metadata),
carrier-grade NAT, multicast and reserved addresses are refused, both for the
pages we open and for every request those pages make.

Set SYNCCUT_ALLOW_PRIVATE_URLS=1 only for local development against sites on
your own machine or network.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
from functools import lru_cache
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata"}


class BlockedURL(ValueError):
    pass


def allow_private() -> bool:
    return os.environ.get("SYNCCUT_ALLOW_PRIVATE_URLS", "").strip().lower() in {"1", "true", "yes"}


_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4 address carried inside an IPv6 one (mapped, 6to4, Teredo, NAT64), if any."""
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    if any(ip in net for net in _NAT64):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Allow only globally routable unicast addresses, including any IPv4 embedded in IPv6."""
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_ipv4(ip)
        if inner is not None:
            return _is_public_ip(inner)
    return ip.is_global and not ip.is_multicast and ip not in ipaddress.ip_network("100.64.0.0/10")


_lock = threading.Lock()


@lru_cache(maxsize=2048)
def _host_is_public(host: str) -> bool:
    host = host.strip("[]").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".internal"):
        return False
    try:
        return _is_public_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # unresolvable: nothing to load anyway
    addresses = {info[4][0] for info in infos}
    # Every address must be public, so a name can't smuggle in one internal record.
    return bool(addresses) and all(_is_public_ip(ipaddress.ip_address(a.split("%")[0])) for a in addresses)


def check_url(url: str) -> None:
    """Raise BlockedURL unless ``url`` is a public http(s) URL."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(f"Only http and https pages can be opened (got {parsed.scheme or 'no scheme'}).")
    if parsed.username or parsed.password:
        raise BlockedURL("URLs with embedded credentials aren't allowed.")
    if allow_private():
        return
    with _lock:
        public = _host_is_public(parsed.hostname or "")
    if not public:
        raise BlockedURL("SyncCut only opens public websites, not local or private network addresses.")


def is_allowed(url: str) -> bool:
    try:
        check_url(url)
        return True
    except BlockedURL:
        return False


def guard_context(context) -> None:
    """Abort every request a Playwright context makes to a non-public destination
    (page loads, redirects, iframes, scripts, images, fetch/XHR)."""

    def handle(route):
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")) or is_allowed(url):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    context.route("**/*", handle)


# ── Egress proxy: the enforcement point ──────────────────────────────────────
#
# The route guard above is a fast first filter, but it can't be the boundary:
# Playwright doesn't re-run route handlers for redirects, some request types
# (e.g. WebSockets) never reach it, and the browser does its own DNS lookup after
# our check (DNS rebinding). So the capture browser sends ALL traffic through
# this proxy. For every connection it resolves the host once, requires every
# resolved address to be public, and then connects to exactly that address.
# Redirects are new requests, WebSockets are CONNECT tunnels, and nothing can be
# re-resolved behind our back.

ALLOWED_PORTS = {80, 443, 8080, 8443}
_HEAD_LIMIT = 64 * 1024
_FORBIDDEN = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: 9\r\nConnection: close\r\n\r\nForbidden"
_BAD_REQUEST = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_BAD_GATEWAY = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


async def resolve_pinned(host: str, port: int) -> str | None:
    """Resolve once; return an address to connect to, or None if the destination isn't allowed."""
    import asyncio

    host = (host or "").strip("[]").lower().rstrip(".")
    if port not in ALLOWED_PORTS and not allow_private():
        return None
    if not host or (not allow_private() and (host in _BLOCKED_HOSTNAMES or host.endswith((".localhost", ".internal")))):
        return None
    try:
        literal = ipaddress.ip_address(host)
        return str(literal) if (allow_private() or _is_public_ip(literal)) else None
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addresses = [info[4][0] for info in infos]
    if not addresses:
        return None
    if not allow_private() and not all(_is_public_ip(ipaddress.ip_address(a.split("%")[0])) for a in addresses):
        return None  # one internal record is enough to refuse the whole name
    addresses.sort(key=lambda a: ":" in a)  # prefer IPv4
    return addresses[0]


async def _pipe(reader, writer) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _split_host_port(authority: str, default: int) -> tuple[str, int]:
    if authority.startswith("["):  # [v6]:port
        host, _, rest = authority[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default
    host, sep, port = authority.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return authority, default


async def _handle(reader, writer) -> None:
    import asyncio

    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 20)
    except Exception:
        writer.close()
        return
    if len(head) > _HEAD_LIMIT:
        writer.write(_BAD_REQUEST)
        writer.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    try:
        method, target, version = lines[0].split(" ", 2)
    except ValueError:
        writer.write(_BAD_REQUEST)
        writer.close()
        return

    if method.upper() == "CONNECT":  # HTTPS and WebSockets: a TLS tunnel bound to one host
        host, port = _split_host_port(target, 443)
        address = await resolve_pinned(host, port)
        if address is None:
            await _refuse(writer, _FORBIDDEN)
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 15)
        except Exception:
            await _refuse(writer, _BAD_GATEWAY)
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
        return

    # Plain http: exactly ONE request per client connection. The client stream is never
    # piped to the server, so a second (pipelined) request for another host can't ride
    # along to this one, and the Host header is rewritten to the URL being fetched.
    parsed = urlparse(target)
    if parsed.scheme.lower() != "http" or not parsed.hostname or parsed.username or parsed.password:
        await _refuse(writer, _BAD_REQUEST)
        return
    host, port = parsed.hostname, parsed.port or 80
    headers = [h for h in lines[1:] if h]
    names = [h.split(":", 1)[0].strip().lower() for h in headers]
    if "transfer-encoding" in names or "upgrade" in names:
        await _refuse(writer, _BAD_REQUEST)  # chunked bodies / protocol upgrades only via CONNECT
        return
    length = 0
    for h in headers:
        if h.lower().startswith("content-length:"):
            try:
                length = int(h.split(":", 1)[1].strip())
            except ValueError:
                await _refuse(writer, _BAD_REQUEST)
                return
    if names.count("content-length") > 1 or length < 0 or length > 50 * 1024 * 1024:
        await _refuse(writer, _BAD_REQUEST)
        return
    address = await resolve_pinned(host, port)
    if address is None:
        await _refuse(writer, _FORBIDDEN)
        return
    authority = host if port == 80 else f"{host}:{port}"
    if ":" in host:
        authority = f"[{host}]" if port == 80 else f"[{host}]:{port}"
    drop = ("host:", "proxy-connection:", "proxy-authorization:", "connection:", "keep-alive:")
    kept = [h for h in headers if not h.lower().startswith(drop)]
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    head_out = f"{method} {path} {version}\r\nHost: {authority}\r\n" + "".join(f"{h}\r\n" for h in kept) + "Connection: close\r\n\r\n"
    try:
        body = await asyncio.wait_for(reader.readexactly(length), 30) if length else b""
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 15)
    except Exception:
        await _refuse(writer, _BAD_GATEWAY)
        return
    up_writer.write(head_out.encode("latin-1") + body)
    await up_writer.drain()
    await _pipe(up_reader, writer)  # response only; then both sides close
    try:
        up_writer.close()
    except Exception:
        pass


async def _refuse(writer, response: bytes) -> None:
    try:
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    writer.close()


class EgressProxy:
    """A local HTTP(S) proxy on 127.0.0.1 that only reaches public addresses (see above)."""

    def __init__(self) -> None:
        self.port: int | None = None
        self._loop = None
        self._server = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "EgressProxy":
        import asyncio

        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._server = self._loop.run_until_complete(asyncio.start_server(_handle, "127.0.0.1", 0, limit=_HEAD_LIMIT))
            self.port = self._server.sockets[0].getsockname()[1]
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="egress-proxy", daemon=True)
        self._thread.start()
        if not ready.wait(10):
            raise RuntimeError("egress proxy failed to start")
        return self

    def __exit__(self, *exc) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._server.close)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def chromium_args(self) -> list[str]:
        return [
            f"--proxy-server={self.url}",
            "--proxy-bypass-list=<-loopback>",  # localhost goes through the proxy too (and is refused)
            "--disable-quic",  # HTTP/3 must not bypass the proxy
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        ]
