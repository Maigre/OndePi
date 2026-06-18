"""Low-level network probes for the connectivity doctor.

Deliberately stdlib-only (no project imports) so the classification and probe
logic can be unit-tested without the full app/runtime dependencies.

The doctor distinguishes the failure *classes* the operator actually cares about
in the field:

- ``ok``                 — the source server's TCP port is reachable.
- ``no_internet``        — can't even reach a public anchor by IP (link/uplink down).
- ``dns_failed``         — internet works, but the server hostname won't resolve
                           (the classic Tailscale-MagicDNS / broken-resolver case).
- ``server_unreachable`` — internet + DNS fine, but the server port is down/blocked.
- ``not_configured``     — no server set.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional, Sequence, Tuple

# Public anchors probed *by IP* (no DNS needed) to tell "no internet" apart from
# "DNS broken".  Port 53/443 are almost never blocked outbound.
DEFAULT_ANCHORS: tuple[tuple[str, int], ...] = (
    ("1.1.1.1", 443),
    ("9.9.9.9", 443),
    ("8.8.8.8", 53),
)


def resolve_host(host: str, timeout: float) -> Optional[str]:
    """Resolve ``host`` to an IP, bounded by ``timeout``.

    ``socket.getaddrinfo`` ignores socket timeouts and can hang for many seconds
    on a dead resolver (exactly the failure we want to detect, not inherit), so
    we run it in a short-lived daemon thread and give up after ``timeout``.
    """
    result: dict[str, str] = {}

    def _work() -> None:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if infos:
                result["ip"] = infos[0][4][0]
        except OSError:
            pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout)
    return result.get("ip")


def tcp_connect(host: str, port: int, timeout: float) -> Tuple[bool, Optional[float]]:
    """Try a TCP connect. Returns (ok, latency_ms)."""
    start = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, (time.monotonic() - start) * 1000.0
    except OSError:
        return False, None


def check_internet(
    timeout: float, anchors: Sequence[Tuple[str, int]] = DEFAULT_ANCHORS
) -> bool:
    """True if any public anchor is reachable by IP (proves the uplink is up)."""
    for ip, port in anchors:
        ok, _ = tcp_connect(ip, port, timeout)
        if ok:
            return True
    return False


def classify_uplink(
    *, dns_ok: bool, server_tcp_ok: bool, internet_ok: bool
) -> str:
    """Reduce the probe booleans to a single human-meaningful reason code."""
    if server_tcp_ok:
        return "ok"
    if not internet_ok:
        return "no_internet"
    if not dns_ok:
        return "dns_failed"
    return "server_unreachable"
