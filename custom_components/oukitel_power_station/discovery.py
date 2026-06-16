"""UDP 6606 discovery: find a station's current LAN IP by its deviceKey (MAC)."""

from __future__ import annotations

import asyncio
import logging
import socket

from .const import DISCOVERY_CMD, DISCOVERY_PORT, DISCOVERY_PROBE_CMD
from .protocol import FrameAssembler, build_frame, ttlv_decode

_LOGGER = logging.getLogger(__name__)


def _ip_and_mac_from_payload(payload: bytes) -> tuple[str | None, str | None]:
    """Extract (ip, mac) strings from a discovery reply's TTLV payload."""
    ip = mac = None
    for value in ttlv_decode(payload).values():
        if not isinstance(value, str):
            continue
        if value.count(".") == 3 and all(p.isdigit() for p in value.split(".")):
            ip = value
        elif len(value) == 12 and all(c in "0123456789abcdefABCDEF" for c in value):
            mac = value.lower()
    return ip, mac


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, target_dk: str, future: asyncio.Future[str]) -> None:
        self._dk = target_dk.lower()
        self._future = future
        self._assembler = FrameAssembler()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        for _pid, cmd, payload in self._assembler.feed(data):
            if cmd != DISCOVERY_CMD:
                continue
            ip, mac = _ip_and_mac_from_payload(payload)
            if mac == self._dk and not self._future.done():
                self._future.set_result(ip or addr[0])

    def error_received(self, exc: Exception) -> None:  # pragma: no cover
        _LOGGER.debug("discovery socket error: %s", exc)


def _broadcast_targets() -> list[str]:
    """Best-effort list of broadcast addresses: global + local /24-directed."""
    targets = ["255.255.255.255"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))  # no traffic sent; just resolves the local IP
        local_ip = s.getsockname()[0]
        s.close()
        directed = local_ip.rsplit(".", 1)[0] + ".255"
        targets.append(directed)
    except OSError:
        pass
    return targets


async def async_discover(dk: str, timeout: float = 4.0) -> str | None:
    """Broadcast a discovery probe and return the IP of the device with deviceKey==dk."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _DiscoveryProtocol(dk, future), sock=sock
    )
    probe = build_frame(1000, DISCOVERY_PROBE_CMD)  # p0
    targets = _broadcast_targets()
    try:
        for _ in range(3):  # re-broadcast a few times
            for target in targets:
                transport.sendto(probe, (target, DISCOVERY_PORT))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout / 3)
            except TimeoutError:
                continue
        return None
    finally:
        transport.close()
