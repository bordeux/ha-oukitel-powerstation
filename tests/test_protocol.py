"""Offline tests for the Oukitel protocol library, using captured reference vectors.

Run:  python3 tests/test_protocol.py
Loads the integration's protocol/const modules without triggering the HA package __init__.
"""

from __future__ import annotations

import base64
import importlib.util
import pathlib
import struct
import sys
import types

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "oukitel_power_station"
_pkg = types.ModuleType("ouk")
_pkg.__path__ = [str(BASE)]
sys.modules["ouk"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"ouk.{name}", BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"ouk.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load("const")
proto = _load("protocol")

# ---- synthetic, self-consistent test vectors (NOT a real device key/session) ----
AUTH_KEY = "MDEyMzQ1Njc4OWFiY2RlZg=="  # base64 of b"0123456789abcdef"
KEY = base64.b64decode(AUTH_KEY)
NONCE = "EXAMPLENONCE0001"
# login_token(KEY, NONCE) precomputed:
P4_TOKEN = "e7657a24b4b4473d5abe6358bfa6764a0789568342187e8b7fe8cc2c75adc5c5"
# cmd17 read request = the product's tag-id list (protocol constant, not secret)
CMD17_PLAINTEXT = bytes.fromhex(
    "0002000800090006001f0007001c001b000e000c000b0005000400030001002200140064002b002c002e"
)
# AES-CBC(KEY, iv=NONCE) of ttlv_encode([(1,'num',97),(43,'bool',False)]):
TELEMETRY_CT = "586e62aac1aab8c7336a1daf71c4d618"
TELEMETRY_EXPECT = {1: 97, 43: False}

_passed = 0


def check(name: str, cond: bool) -> None:
    global _passed
    assert cond, f"FAIL: {name}"
    _passed += 1
    print(f"  ok  {name}")


def main() -> None:
    print("protocol offline tests")

    # 1) p4 login token derivation is deterministic and matches the expected value
    check("login_token == expected", proto.login_token(KEY, NONCE) == P4_TOKEN)
    check("auth_key_to_key -> 16 bytes", len(proto.auth_key_to_key(AUTH_KEY)) == 16)

    # 2) AES decrypt of a known ciphertext yields the expected TTLV
    iv = NONCE.encode()
    decoded = proto.ttlv_decode(proto.aes_decrypt(KEY, iv, bytes.fromhex(TELEMETRY_CT)))
    check("aes_decrypt -> expected TTLV", decoded == TELEMETRY_EXPECT)

    # 3) AES round-trip
    blob = b"hello-oukitel-123"
    check("aes round-trip", proto.aes_decrypt(KEY, iv, proto.aes_encrypt(KEY, iv, blob)) == blob)

    # 4) byte-stuffing round-trip (including AA AA and AA 55 sequences)
    raw = bytes([0xAA, 0xAA, 0x01, 0xAA, 0x55, 0xAA, 0xAA, 0x02, 0x55])
    stuffed = proto.stuff(raw)
    out = proto._Destuffer().feed(stuffed)
    check("stuff/destuff round-trip", out == raw)

    # 5) frame build -> FrameAssembler parse round-trip
    payload = b"\x00\x0a\x00\x1e"
    frame = proto.build_frame(1234, const.CMD_WRITE, payload)
    frames = proto.FrameAssembler().feed(frame)
    check("frame round-trip count", len(frames) == 1)
    pid, cmd, pl = frames[0]
    check("frame pid", pid == 1234)
    check("frame cmd", cmd == const.CMD_WRITE)
    check("frame payload", pl == payload)

    # 6) split frame across two reads still parses (streaming)
    asm = proto.FrameAssembler()
    half = len(frame) // 2
    check("partial read yields nothing", asm.feed(frame[:half]) == [])
    rest = asm.feed(frame[half:])
    check("completed read yields frame", len(rest) == 1 and rest[0][1] == const.CMD_WRITE)

    # 7) cmd17 read payload equals captured plaintext
    built = b"".join(struct.pack(">H", t) for t in const.READ_TAG_IDS)
    check("cmd17 read payload == captured", built == CMD17_PLAINTEXT)

    # 8) p4 login-token TTLV payload matches captured shape (tag2/type3 binary)
    token_payload = (
        struct.pack(">H", (2 << 3) | 3) + struct.pack(">H", len(P4_TOKEN)) + P4_TOKEN.encode()
    )
    check("p4 payload header 0x0013 + len 0x0040", token_payload[:4] == bytes.fromhex("00130040"))

    # 9) TTLV encode/decode round-trip
    enc = proto.ttlv_encode([(43, "bool", True), (20, "num", 73), (28, "num", 230)])
    dec = proto.ttlv_decode(enc)
    check("ttlv encode/decode bool", dec.get(43) is True)
    check("ttlv encode/decode num 73", dec.get(20) == 73)
    check("ttlv encode/decode num 230", dec.get(28) == 230)

    # 10) struct (TTLV type 4) decodes to nested {subtag: value} — per-port telemetry.
    #     TypeC Info (tag 8): sub 2=Typec1 power, sub 7=Typec4 power.
    struct_blob = (
        struct.pack(">H", (8 << 3) | 4)
        + struct.pack(">H", 2)  # 2 sub-fields
        + struct.pack(">H", (2 << 3) | 2)
        + b"\x00\x05"  # sub 2 = 5
        + struct.pack(">H", (7 << 3) | 2)
        + b"\x00\x14"  # sub 7 = 20
    )
    dec_struct = proto.ttlv_decode(struct_blob)
    check("struct tag8 nested sub-tags", dec_struct.get(8) == {2: 5, 7: 20})

    print(f"\nALL PASSED ({_passed} checks)")


def test_offline() -> None:
    """pytest entry point."""
    main()


if __name__ == "__main__":
    main()
