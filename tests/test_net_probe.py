import socket

from ondepi.net_probe import (
    check_internet,
    classify_uplink,
    resolve_host,
    tcp_connect,
)


def test_classify_uplink_all_cases():
    assert classify_uplink(dns_ok=True, server_tcp_ok=True, internet_ok=True) == "ok"
    assert classify_uplink(dns_ok=True, server_tcp_ok=False, internet_ok=False) == "no_internet"
    assert classify_uplink(dns_ok=False, server_tcp_ok=False, internet_ok=True) == "dns_failed"
    assert classify_uplink(dns_ok=True, server_tcp_ok=False, internet_ok=True) == "server_unreachable"
    # server reachable always wins, even if other signals look bad
    assert classify_uplink(dns_ok=False, server_tcp_ok=True, internet_ok=False) == "ok"


def test_resolve_host_localhost_and_bogus():
    assert resolve_host("localhost", timeout=2.0) in ("127.0.0.1", "::1")
    # Reserved TLD that must never resolve; must return None within the timeout.
    assert resolve_host("nonexistent.invalid", timeout=2.0) is None


def test_tcp_connect_open_and_closed():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()
    try:
        ok, latency = tcp_connect(host, port, timeout=2.0)
        assert ok is True
        assert latency is not None and latency >= 0.0
    finally:
        srv.close()

    # Port is now closed → connect must fail, no latency.
    ok, latency = tcp_connect(host, port, timeout=1.0)
    assert ok is False
    assert latency is None


def test_check_internet_with_local_anchor():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()
    try:
        assert check_internet(timeout=2.0, anchors=[(host, port)]) is True
    finally:
        srv.close()
    # Unreachable anchor (now-closed port) → False, bounded by timeout.
    assert check_internet(timeout=1.0, anchors=[(host, port)]) is False
