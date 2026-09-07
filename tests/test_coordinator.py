"""Offline tests for the coordinator's telemetry-stall policy and the protocol's
per-session frame tally. Both exist to catch a station that completes the handshake
and acks writes while never streaming telemetry (issue #6).

Run:  python3 tests/test_coordinator.py
The stall policy is a pure function so it needs no Home Assistant instance; the
coordinator module itself does import HA, so it is loaded only when available.
"""

from __future__ import annotations

import importlib.util
import pathlib
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

_passed = 0


def check(name: str, cond: bool) -> None:
    global _passed
    assert cond, f"FAIL: {name}"
    _passed += 1
    print(f"  ok  {name}")


def main() -> None:
    print("coordinator / stall-detection offline tests")

    # --- per-session frame tally: the signature of a stalled device ---
    conn = proto.OukitelConnection("127.0.0.1", "MDEyMzQ1Njc4OWFiY2RlZg==")
    check("stats starts empty", conn.stats() == "tx={} rx={}")
    # simulate what the log showed: writes acked (28726), no telemetry at all
    conn._dispatch([(1, const.CMD_WRITE_ACK, b""), (2, const.CMD_WRITE_ACK, b"")])
    check("acks counted in rx", f"{const.CMD_WRITE_ACK}:2" in conn.stats())
    check("no report counted", f"{const.CMD_REPORT}:" not in conn.stats())

    # --- stall policy ---
    try:
        coord = _load("coordinator")
    except ImportError as err:  # no Home Assistant in this environment
        print(f"  skip stall-policy checks (coordinator needs HA: {err})")
        print(f"\nALL PASSED ({_passed} checks)")
        return

    stall = coord.stall_age
    timeout = 150.0
    check("nothing known -> not stalled", stall(1000.0, None, None, timeout) is None)
    check("fresh report -> not stalled", stall(1000.0, 990.0, 500.0, timeout) is None)
    check("old report -> stalled", stall(1000.0, 800.0, 500.0, timeout) == 200.0)
    # a device that has never reported still gets a grace period from connect time
    check("just connected, no report -> not stalled", stall(1000.0, None, 990.0, timeout) is None)
    check("connected long ago, no report -> stalled", stall(1000.0, None, 700.0, timeout) == 300.0)
    # last_report wins over connect time once one has arrived
    check("report supersedes connect time", stall(1000.0, 990.0, 100.0, timeout) is None)

    print(f"\nALL PASSED ({_passed} checks)")


def test_offline() -> None:
    """pytest entry point."""
    main()


if __name__ == "__main__":
    main()
