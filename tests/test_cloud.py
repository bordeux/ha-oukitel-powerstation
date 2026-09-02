"""Offline parity tests for the cloud login crypto (no network).

Ground truth from a real successful login log:
  random=oV1xhC6Gzz96pzSI  key=887A06A544DFD7CE  iv=44DFD7CE887A06A5
Run:  python3 tests/test_cloud.py
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import importlib.util
import pathlib
import sys
import types

import aiohttp

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


_load("const")
proto = _load("protocol")
cloud = _load("cloud")

RANDOM = "oV1xhC6Gzz96pzSI"
EXPECT_KEY = "887A06A544DFD7CE"
EXPECT_IV = "44DFD7CE887A06A5"
APP_SECRET = "3aRNUwWahjyANa7WfBK2wCCkxCexB6nXxKJwXxfePvzf"  # EU (public app constant)
USER_DOMAIN = "E.SP.4294967410"

_passed = 0


def check(name: str, cond: bool) -> None:
    global _passed
    assert cond, f"FAIL: {name}"
    _passed += 1
    print(f"  ok  {name}")


class _FakeResponse:
    status = 200

    async def json(self, content_type: object = None) -> dict:
        return {"code": 200, "data": {}}


class _FakeSession:
    """Records request kwargs; optionally raises instead of responding."""

    def __init__(self, raises: BaseException | None = None) -> None:
        self.raises = raises
        self.kwargs: dict = {}

    def request(self, _method: str, _url: str, **kwargs):
        self.kwargs = kwargs
        raises = self.raises

        @contextlib.asynccontextmanager
        async def _cm():
            if raises is not None:
                raise raises
            yield _FakeResponse()

        return _cm()


def _request_with(session) -> object:
    """Run one OukitelCloud request against a fake session; return the raised error or None."""

    async def run():
        client = cloud.OukitelCloud(session, "EU")
        try:
            await client._get("/x", {})
        except BaseException as err:  # the test inspects whatever escapes
            return err
        return None

    return asyncio.run(run())


def main() -> None:
    print("cloud login crypto parity tests")
    email = "user@example.com"
    password = "s3cret-pass"

    fields = cloud.build_login_fields(email, password, APP_SECRET, USER_DOMAIN, random=RANDOM)

    # 1) key/iv derivation matches the real login-log ground truth
    md5u = hashlib.md5(RANDOM.encode()).hexdigest().upper()
    check("derived key == logged", md5u[8:24] == EXPECT_KEY)
    check("derived iv == logged", (EXPECT_KEY[8:16] + EXPECT_KEY[0:8]) == EXPECT_IV)

    # 2) encpwd reproducible via the same primitives (independent recompute)
    enc = proto.aes_encrypt(EXPECT_KEY.encode(), EXPECT_IV.encode(), password.encode())
    expect_pwd = base64.encodebytes(enc).decode()
    check("encpwd matches independent recompute", fields["pwd"] == expect_pwd)
    check("encpwd has Base64.DEFAULT trailing newline", fields["pwd"].endswith("\n"))

    # 3) signature = sha256(email + pwd + random + appSecret)
    expect_sig = hashlib.sha256((email + expect_pwd + RANDOM + APP_SECRET).encode()).hexdigest()
    check("signature matches", fields["signature"] == expect_sig)

    # 4) body shape
    check("fields keys", set(fields) == {"pwd", "email", "random", "userDomain", "signature"})
    check("userDomain set", fields["userDomain"] == USER_DOMAIN)
    check("random preserved", fields["random"] == RANDOM)

    # 5) every request is bounded (issue #6: a black-holed route must not hang the
    #    coordinator) and transport failures surface as OukitelCloudError, which is the
    #    only cloud exception the config flow and coordinator handle.
    ok_session = _FakeSession()
    check("plain request succeeds", _request_with(ok_session) is None)
    timeout = ok_session.kwargs.get("timeout")
    check("request passes a ClientTimeout", isinstance(timeout, aiohttp.ClientTimeout))
    check("timeout total is bounded", 0 < (timeout.total or 0) <= 60)

    conn_err = _request_with(_FakeSession(aiohttp.ClientConnectionError("no route")))
    check("ClientError -> OukitelCloudError", isinstance(conn_err, cloud.OukitelCloudError))
    to_err = _request_with(_FakeSession(TimeoutError()))
    check("TimeoutError -> OukitelCloudError", isinstance(to_err, cloud.OukitelCloudError))

    print(f"\nALL PASSED ({_passed} checks)")


def test_offline() -> None:
    """pytest entry point."""
    main()


if __name__ == "__main__":
    main()
