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
    def __init__(self, body: dict | None = None, status: int = 200) -> None:
        self._body = body if body is not None else {"code": 200, "data": {}}
        self.status = status

    async def json(self, content_type: object = None) -> dict:
        return self._body


class _FakeSession:
    """Records request kwargs; optionally raises or serves a canned body."""

    def __init__(
        self,
        raises: BaseException | None = None,
        body: dict | None = None,
        status: int = 200,
    ) -> None:
        self.raises = raises
        self.body = body
        self.status = status
        self.kwargs: dict = {}

    def request(self, _method: str, _url: str, **kwargs):
        self.kwargs = kwargs
        raises = self.raises
        body = self.body
        status = self.status

        @contextlib.asynccontextmanager
        async def _cm():
            if raises is not None:
                raise raises
            yield _FakeResponse(body, status)

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


def _regen_with(body: dict) -> object:
    """Run regenerate_auth_key against a fake session; (result_or_none, error_or_none)."""

    async def run():
        client = cloud.OukitelCloud(_FakeSession(body=body), "EU")
        try:
            return await client.regenerate_auth_key("p11wN7", "aabbccddeeff"), None
        except BaseException as err:
            return None, err

    return asyncio.run(run())


def _login_with(body: dict) -> object:
    """Run login against a fake response; return any error it raises."""

    async def run():
        client = cloud.OukitelCloud(_FakeSession(body=body), "EU")
        try:
            await client.login("user@example.com", "s3cret-pass")
        except BaseException as err:  # the test inspects whatever escapes
            return err
        return None

    return asyncio.run(run())


def _devices_with(body: dict) -> object:
    """Run get_devices against a fake response; return any error it raises."""

    async def run():
        client = cloud.OukitelCloud(_FakeSession(body=body), "EU")
        try:
            await client.get_devices()
        except BaseException as err:  # the test inspects whatever escapes
            return err
        return None

    return asyncio.run(run())


def _tsl_with(body: dict) -> object:
    """Run get_tsl against a fake response; return any error it raises."""

    async def run():
        client = cloud.OukitelCloud(_FakeSession(body=body), "EU")
        try:
            await client.get_tsl("p11wN7")
        except BaseException as err:  # the test inspects whatever escapes
            return err
        return None

    return asyncio.run(run())


def _business_attributes_with(body: dict) -> object:
    """Run get_business_attributes against a fake response; return any error it raises."""

    async def run():
        client = cloud.OukitelCloud(_FakeSession(body=body), "EU")
        try:
            await client.get_business_attributes("p11wN7", "aabbccddeeff")
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
    check(
        "ClientError -> OukitelCloudConnectionError",
        isinstance(conn_err, cloud.OukitelCloudConnectionError),
    )
    to_err = _request_with(_FakeSession(TimeoutError()))
    check(
        "TimeoutError -> OukitelCloudTimeoutError",
        isinstance(to_err, cloud.OukitelCloudTimeoutError),
    )
    auth_err = _request_with(_FakeSession(status=401))
    check("HTTP 401 -> OukitelCloudAuthError", isinstance(auth_err, cloud.OukitelCloudAuthError))
    response_err = _request_with(_FakeSession(status=503))
    check(
        "HTTP 503 -> OukitelCloudResponseError",
        isinstance(response_err, cloud.OukitelCloudResponseError),
    )
    password_err = _request_with(
        _FakeSession(body={"code": 400, "msg": "Password format is incorrect."})
    )
    check(
        "password format response -> OukitelCloudPasswordFormatError",
        isinstance(password_err, cloud.OukitelCloudPasswordFormatError),
    )
    malformed_login = _login_with({"code": 200, "data": "not-an-object"})
    check(
        "malformed login payload -> OukitelCloudResponseError",
        isinstance(malformed_login, cloud.OukitelCloudResponseError),
    )
    missing_token = _login_with({"code": 200, "data": {"accessToken": None}})
    check(
        "missing login token -> OukitelCloudAuthError",
        isinstance(missing_token, cloud.OukitelCloudAuthError),
    )
    malformed_devices = _devices_with({"code": 200, "data": {"list": [{}]}})
    check(
        "BLE-only device is ignored",
        malformed_devices is None,
    )
    malformed_tsl = _tsl_with({"code": 200, "data": {"profile": "bad", "properties": "bad"}})
    check(
        "malformed TSL -> OukitelCloudResponseError",
        isinstance(malformed_tsl, cloud.OukitelCloudResponseError),
    )
    malformed_attributes = _business_attributes_with({"code": 200, "data": {}})
    check(
        "missing business attributes -> empty values",
        malformed_attributes is None,
    )

    # 6) regenerate_auth_key: returns the key, posts pk/dk, errors when absent
    key, err = _regen_with({"code": 200, "data": {"authKey": "QUJDREVGRw=="}})
    check("regenerate returns authKey", key == "QUJDREVGRw==" and err is None)
    _, err = _regen_with({"code": 200, "data": {}})
    check(
        "regenerate without key -> OukitelCloudResponseError",
        isinstance(err, cloud.OukitelCloudResponseError),
    )
    _, err = _regen_with({"code": 200, "data": {"authKey": 42}})
    check(
        "regenerate numeric key -> OukitelCloudResponseError",
        isinstance(err, cloud.OukitelCloudResponseError),
    )

    print(f"\nALL PASSED ({_passed} checks)")


def test_offline() -> None:
    """pytest entry point."""
    main()


if __name__ == "__main__":
    main()
