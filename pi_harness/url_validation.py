"""Loopback/LAN URL validation (SSRF guard).

Shared by the settings routes and model discovery. 'Local model server' means
localhost or a LAN host; accepting an arbitrary URL is SSRF (an attacker could
make us fetch internal services or cloud metadata at 169.254.169.254). We
require http(s) and that EVERY resolved address is loopback, RFC1918-private,
or RFC6598 shared (Tailscale / CGNAT) — never link-local, multicast, or global.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

__all__ = ["validate_local_url"]

# RFC-6598 shared address space (Tailscale / CGNAT). A sovereign LAN/Tailnet —
# the documented v1 deployment reaches a shared Mac Studio inference box over
# Tailscale (e.g. 100.94.117.87). ipaddress reports it as neither private nor
# loopback, so it must be allowed explicitly while link-local/metadata/public
# stay blocked.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def validate_local_url(url: str) -> str:
    """Return ``url`` if it safely points at a loopback/private model server,
    else raise ValueError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("local model URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("local model URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # Unwrap an IPv4-mapped IPv6 address (::ffff:a.b.c.d) and classify the
        # EMBEDDED IPv4 — ipaddress reports the mapped form as generically
        # private (not loopback/link-local), which would let
        # ::ffff:169.254.169.254 (cloud metadata) or ::ffff:8.8.8.8 (public)
        # slip through on a dual-stack host, defeating the guard below.
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if ip.is_unspecified:
            raise ValueError("local model URL resolves to an unspecified address")
        if ip.is_loopback:
            continue  # 127.0.0.0/8 and ::1 are always fine
        # Block link-local explicitly — it covers the cloud metadata endpoint
        # (169.254.169.254) and is otherwise treated as 'private' by ipaddress.
        if ip.is_link_local:
            raise ValueError("local model URL resolves to a link-local address (blocked)")
        # Allow RFC-6598 shared address space (Tailscale / CGNAT) — a sovereign
        # LAN/Tailnet, not the public internet. Checked after the link-local
        # block so the metadata endpoint stays rejected.
        if ip.version == 4 and ip in _CGNAT:
            continue
        if not ip.is_private:
            raise ValueError(
                "local model URL must point at a loopback or private (LAN) address"
            )
    return url
