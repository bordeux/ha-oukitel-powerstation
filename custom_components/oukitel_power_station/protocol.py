"""Oukitel / Quectel local TTLV protocol over TCP 6607.

Pure-asyncio, no Home Assistant imports, so it can be unit-tested standalone.
Frame:  AA AA | len(2,BE) | checksum(1) | packetID(2,BE) | cmd(2,BE) | payload
        - len counts checksum + packetID + cmd + payload  (total frame = len + 4)
        - checksum = sum(bytes from packetID..end) & 0xFF
        - payload bytes use stuffing AA -> AA 55; payload is AES-128-CBC after handshake
See REVERSE_ENGINEERING.md.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
import contextlib
import hashlib
import logging
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    CMD_HEARTBEAT,
    CMD_HELLO,
    CMD_LOGIN,
    CMD_LOGIN_RESULT,
    CMD_NONCE,
    CMD_PING,
    CMD_PONG,
    CMD_READ,
    CMD_REPORT,
    CMD_WRITE,
    HF_REPORTING_LAN_WIFI,
    READ_TAG_IDS,
    TAG_HF_REPORTING,
)

_LOGGER = logging.getLogger(__name__)

MAGIC = b"\xaa\xaa"

# Keepalive: send a p7 ping this often so the device keeps the session and
# keeps streaming; if no frame arrives within the read timeout the socket is
# treated as dead and the listener exits so the coordinator reconnects.
_PING_INTERVAL = 20.0
_READ_TIMEOUT = 90.0
# Bound the TCP connect + handshake; without this a slow/unresponsive device
# (or a half-open socket during a reload) blocks setup until HA's bootstrap
# timeout, stalling the whole instance.
_CONNECT_TIMEOUT = 15.0


class OukitelError(Exception):
    """Base protocol error."""


class OukitelAuthError(OukitelError):
    """Handshake/login failed (likely wrong or rotated authKey)."""


# --------------------------------------------------------------------------- #
# crypto
# --------------------------------------------------------------------------- #
def _pkcs7_pad(data: bytes) -> bytes:
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data  # tolerate unpadded/garbage rather than raising in a telemetry loop


def aes_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(_pkcs7_pad(plaintext)) + enc.finalize()


def aes_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return _pkcs7_unpad(dec.update(ciphertext) + dec.finalize())


def login_token(key: bytes, nonce: str) -> str:
    """p4 login token = SHA256( lowercase-hex(key) + ';' + nonce )."""
    return hashlib.sha256((key.hex() + ";" + nonce).encode()).hexdigest()


def auth_key_to_key(auth_key_b64: str) -> bytes:
    """AES-128 key = Base64.decode(authKey)."""
    return base64.b64decode(auth_key_b64)


# --------------------------------------------------------------------------- #
# byte stuffing  (AA -> AA 55)
# --------------------------------------------------------------------------- #
def stuff(frame: bytes) -> bytes:
    """Stuff the frame body (everything after the AA AA magic)."""
    out = bytearray(frame[:2])
    body = frame[2:]
    for j, b in enumerate(body):
        out.append(b)
        if b == 0xAA and j + 1 < len(body) and body[j + 1] in (0x55, 0xAA):
            out.append(0x55)
    return bytes(out)


class _Destuffer:
    """Streaming de-stuffer: removes a 0x55 immediately following a 0xAA."""

    def __init__(self) -> None:
        self._prev_aa = False

    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        prev_aa = self._prev_aa
        for b in data:
            if prev_aa and b == 0x55:
                prev_aa = False  # drop stuffed 0x55
                continue
            out.append(b)
            prev_aa = b == 0xAA
        self._prev_aa = prev_aa
        return bytes(out)


# --------------------------------------------------------------------------- #
# TTLV
# --------------------------------------------------------------------------- #
def _encode_number(value: int) -> bytes:
    """Encode an integer as a TTLV number value (ctrl byte + big-endian bytes)."""
    neg = value < 0
    v = abs(value)
    body = b"\x00" if v == 0 else v.to_bytes((v.bit_length() + 7) // 8, "big")
    ctrl = (0x80 if neg else 0) | ((len(body) - 1) & 0x07)
    return bytes([ctrl]) + body


def ttlv_encode(fields: list[tuple[int, str, object]]) -> bytes:
    """Encode TTLV fields. Each: (tag, kind, value); kind in {'bool','num'}."""
    out = bytearray()
    for tag, kind, value in fields:
        if kind == "bool":
            out += struct.pack(">H", (tag << 3) | (1 if value else 0))
        elif kind == "num":
            out += struct.pack(">H", (tag << 3) | 2)
            out += _encode_number(int(value))
        else:
            raise ValueError(f"unsupported TTLV kind: {kind}")
    return bytes(out)


def ttlv_decode(buf: bytes) -> dict[int, object]:
    """Decode a TTLV buffer to {tag: value}. Structs -> nested {tag: value}."""
    out: dict[int, object] = {}
    i = 0
    n = len(buf)

    def read_number(i: int) -> tuple[float | int, int]:
        c = buf[i]
        i += 1
        sign = (c >> 7) & 1
        decimals = (c >> 3) & 0x0F
        nbytes = (c & 0x07) + 1
        v = int.from_bytes(buf[i : i + nbytes], "big")
        i += nbytes
        if sign:
            v = -v
        return (v / (10**decimals) if decimals else v), i

    while i + 2 <= n:
        h = struct.unpack(">H", buf[i : i + 2])[0]
        i += 2
        tag, typ = (h >> 3) & 0x1FFF, h & 7
        if typ in (0, 1):
            out[tag] = typ == 1
        elif typ == 2:
            out[tag], i = read_number(i)
        elif typ in (3, 5):
            if i + 2 > n:
                break
            ln = struct.unpack(">H", buf[i : i + 2])[0]
            i += 2
            val = buf[i : i + ln]
            i += ln
            try:
                out[tag] = val.decode("ascii") if val.isascii() else val
            except Exception:
                out[tag] = val
        elif typ == 4:
            if i + 2 > n:
                break
            count = struct.unpack(">H", buf[i : i + 2])[0]
            i += 2
            sub: dict[int, object] = {}
            for _ in range(count):
                if i + 2 > n:
                    break
                h2 = struct.unpack(">H", buf[i : i + 2])[0]
                i += 2
                t2, ty2 = (h2 >> 3) & 0x1FFF, h2 & 7
                if ty2 in (0, 1):
                    sub[t2] = ty2 == 1
                elif ty2 == 2:
                    sub[t2], i = read_number(i)
                elif ty2 in (3, 5):
                    ln = struct.unpack(">H", buf[i : i + 2])[0]
                    i += 2
                    sub[t2] = buf[i : i + ln]
                    i += ln
            out[tag] = sub
        else:
            break
    return out


# --------------------------------------------------------------------------- #
# frame build / parse
# --------------------------------------------------------------------------- #
def build_frame(packet_id: int, cmd: int, payload: bytes = b"") -> bytes:
    body = struct.pack(">H", packet_id & 0xFFFF) + struct.pack(">H", cmd & 0xFFFF) + payload
    length = len(body) + 1  # + checksum byte
    chk = sum(body) & 0xFF
    return stuff(MAGIC + struct.pack(">H", length) + bytes([chk]) + body)


class FrameAssembler:
    """Feed raw TCP bytes, get back complete (packet_id, cmd, payload) frames."""

    def __init__(self) -> None:
        self._destuffer = _Destuffer()
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        self._buf += self._destuffer.feed(data)
        frames: list[tuple[int, int, bytes]] = []
        while True:
            k = self._buf.find(MAGIC)
            if k < 0:
                if len(self._buf) > 1:  # keep possible trailing AA
                    del self._buf[:-1]
                break
            if k > 0:
                del self._buf[:k]  # drop junk before magic
            if len(self._buf) < 9:
                break
            length = struct.unpack(">H", self._buf[2:4])[0]
            total = 4 + length
            if len(self._buf) < total:
                break
            frame = bytes(self._buf[:total])
            del self._buf[:total]
            body = frame[5:]
            if (sum(body) & 0xFF) != frame[4]:
                _LOGGER.debug("checksum mismatch, dropping frame")
                continue
            pid = struct.unpack(">H", frame[5:7])[0]
            cmd = struct.unpack(">H", frame[7:9])[0]
            frames.append((pid, cmd, frame[9:]))
        return frames


# --------------------------------------------------------------------------- #
# async connection
# --------------------------------------------------------------------------- #
class OukitelConnection:
    """Manage one local TCP session: handshake, subscribe, read, write, listen."""

    def __init__(
        self,
        host: str,
        auth_key_b64: str,
        on_report: Callable[[dict[int, object]], None] | None = None,
        port: int = 6607,
    ) -> None:
        self._host = host
        self._port = port
        self._key = auth_key_to_key(auth_key_b64)
        self._on_report = on_report
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._assembler = FrameAssembler()
        self._iv: bytes | None = None
        self._packet_id = 1000
        self._reader_task: asyncio.Task | None = None
        self._ack_waiters: dict[int, asyncio.Future] = {}

    # --- low level ---
    def _next_pid(self) -> int:
        self._packet_id += 1
        if self._packet_id >= 0xFFFF:
            self._packet_id = 1000
        return self._packet_id

    async def _send(self, cmd: int, payload: bytes = b"", *, encrypt: bool = False) -> int:
        assert self._writer is not None
        if encrypt:
            assert self._iv is not None
            payload = aes_encrypt(self._key, self._iv, payload)
        pid = self._next_pid()
        self._writer.write(build_frame(pid, cmd, payload))
        await self._writer.drain()
        return pid

    async def _read_frames(self) -> list[tuple[int, int, bytes]]:
        assert self._reader is not None
        data = await self._reader.read(4096)
        if not data:
            raise OukitelError("connection closed by peer")
        return self._assembler.feed(data)

    # --- public ---
    async def connect(self) -> None:
        """Open the socket and complete the handshake within a bounded time."""
        try:
            await asyncio.wait_for(self._open_and_handshake(), _CONNECT_TIMEOUT)
        except TimeoutError as err:
            await self.close()
            raise OukitelError("timed out connecting / completing handshake") from err
        except OukitelError:
            await self.close()
            raise

    async def _open_and_handshake(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        await self._send(CMD_HELLO)  # p2
        nonce: str | None = None
        for _ in range(50):
            for _pid, cmd, payload in await self._read_frames():
                if cmd == CMD_NONCE:
                    fields = ttlv_decode(payload)
                    nonce = next((v for v in fields.values() if isinstance(v, str)), None)
            if nonce:
                break
        if not nonce:
            raise OukitelAuthError("no nonce (p3) received")
        self._iv = nonce.encode()
        token = login_token(self._key, nonce)
        token_payload = (
            struct.pack(">H", (2 << 3) | 3) + struct.pack(">H", len(token)) + token.encode()
        )
        await self._send(CMD_LOGIN, token_payload)  # p4 (plaintext)
        for _ in range(50):
            for _pid, cmd, payload in await self._read_frames():
                if cmd == CMD_LOGIN_RESULT:
                    result = next(
                        (v for v in ttlv_decode(payload).values() if isinstance(v, int | float)),
                        None,
                    )
                    if result == 0:
                        return
                    raise OukitelAuthError(f"login rejected (result={result})")
        raise OukitelAuthError("no login result (p5) received")

    async def subscribe_and_read(self) -> None:
        """Enable high-frequency reporting and request a full snapshot."""
        await self._send(
            CMD_WRITE, ttlv_encode([(TAG_HF_REPORTING, "num", HF_REPORTING_LAN_WIFI)]), encrypt=True
        )
        await self._send(
            CMD_READ, b"".join(struct.pack(">H", t) for t in READ_TAG_IDS), encrypt=True
        )
        await self._send(CMD_HEARTBEAT, ttlv_encode([(1, "num", 30), (2, "num", 1)]), encrypt=True)

    async def async_set(self, tag: int, value: object, *, is_bool: bool) -> None:
        """Write a single property (cmd19)."""
        field = (tag, "bool", bool(value)) if is_bool else (tag, "num", int(value))
        await self._send(CMD_WRITE, ttlv_encode([field]), encrypt=True)

    async def async_read_all(self) -> None:
        await self._send(
            CMD_READ, b"".join(struct.pack(">H", t) for t in READ_TAG_IDS), encrypt=True
        )

    async def _ping(self) -> None:
        await self._send(CMD_PING)

    def _dispatch(self, frames: list[tuple[int, int, bytes]]) -> None:
        for _pid, cmd, payload in frames:
            # Telemetry arrives as cmd20 reports AND as the reply to a cmd17 read;
            # decode both so a polled read always refreshes state.
            if cmd in (CMD_REPORT, CMD_READ) and self._iv is not None and payload:
                try:
                    report = ttlv_decode(aes_decrypt(self._key, self._iv, payload))
                except Exception as err:  # tolerate a bad frame in the loop
                    _LOGGER.debug("could not decode cmd %s payload: %s", cmd, err)
                    continue
                if report and self._on_report:
                    self._on_report(report)
            elif cmd not in (CMD_PONG, CMD_PING):
                _LOGGER.debug("unhandled frame cmd=%s len=%s", cmd, len(payload))

    async def _keepalive(self) -> None:
        """Send periodic p7 pings; on failure, close the socket to force a reconnect."""
        try:
            while True:
                await asyncio.sleep(_PING_INTERVAL)
                await self._ping()
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.debug("keepalive ping failed (%s); closing socket", err)
            if self._writer is not None:
                self._writer.close()

    async def listen(self) -> None:
        """Background read loop: decode reports and push them via on_report.

        Runs a keepalive ping concurrently and applies a read watchdog: if no
        frame arrives within _READ_TIMEOUT the connection is considered dead and
        this coroutine raises so the coordinator can reconnect.
        """
        ping_task = asyncio.create_task(self._keepalive())
        try:
            while True:
                try:
                    frames = await asyncio.wait_for(self._read_frames(), _READ_TIMEOUT)
                except TimeoutError as err:
                    raise OukitelError("no data within read timeout") from err
                self._dispatch(frames)
        except asyncio.CancelledError:
            raise
        except OukitelError:
            raise
        except Exception as err:
            raise OukitelError(str(err)) from err
        finally:
            ping_task.cancel()
            with contextlib.suppress(Exception):
                await ping_task

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._reader = self._writer = None
