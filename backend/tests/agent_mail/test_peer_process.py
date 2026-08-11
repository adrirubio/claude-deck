"""Kernel-derived peer resolution (spec section 3.3)."""

from app.utils import peer_process


def test_format_endpoint_ipv4():
    assert peer_process.format_endpoint("127.0.0.1", 8000) == "0100007F:1F40"


def test_format_endpoint_ipv6():
    assert peer_process.format_endpoint("::1", 8000) == (
        "00000000000000000000000001000000:1F40"
    )


def test_format_endpoint_rejects_a_hostname():
    """A non-literal host has no /proc/net representation, and must not be guessed at."""
    assert peer_process.format_endpoint("testclient", 123) is None
