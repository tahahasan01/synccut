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


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or ip in ipaddress.ip_network("100.64.0.0/10")
    )


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
