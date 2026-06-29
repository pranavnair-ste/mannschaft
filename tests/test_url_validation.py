"""Tests for the SSRF guard (validate_local_url).

Uses literal IPs so socket.getaddrinfo resolves each host to itself — no DNS
and no network. Covers the RFC-6598 (Tailscale / CGNAT) allowance added so a
laptop can reach a shared Mac Studio inference box over a Tailnet, while
loopback/RFC-1918 stay allowed and link-local/metadata/public stay blocked.
"""
from __future__ import annotations

import pytest

from pi_harness.url_validation import validate_local_url


def test_allows_tailscale_cgnat() -> None:
    # RFC-6598 shared address space (Tailscale / CGNAT) — a sovereign LAN/Tailnet.
    assert (
        validate_local_url("http://100.94.117.87:15100/v1")
        == "http://100.94.117.87:15100/v1"
    )


def test_allows_cgnat_network_edges() -> None:
    # Boundaries of 100.64.0.0/10.
    assert validate_local_url("http://100.64.0.0:8080/v1")
    assert validate_local_url("http://100.127.255.255:8080/v1")


def test_still_blocks_metadata_ip() -> None:
    with pytest.raises(ValueError):
        validate_local_url("http://169.254.169.254/latest/meta-data")


def test_still_blocks_public_ip() -> None:
    with pytest.raises(ValueError):
        validate_local_url("http://8.8.8.8:15100/v1")


def test_blocks_address_just_outside_cgnat() -> None:
    # 100.128.0.0 is the first public address above 100.64.0.0/10.
    with pytest.raises(ValueError):
        validate_local_url("http://100.128.0.1:8080/v1")


def test_still_allows_loopback() -> None:
    assert validate_local_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"


def test_still_allows_rfc1918_private() -> None:
    assert validate_local_url("http://192.168.1.50:8080/v1")


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError):
        validate_local_url("ftp://100.94.117.87/v1")
