"""Async Quectel/Acceleronix cloud client.

Used once at setup (and on authKey re-fetch) to log in with the user's account and read the
per-device ``authKey`` plus the product thing-model (TSL). Reverse-engineered from the WonderFree
app — see REVERSE_ENGINEERING.md. Takes an aiohttp ClientSession (HA-provided).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Any
import uuid

import aiohttp

from .const import (
    PATH_BUSINESS_ATTRS,
    PATH_DEVICE_LIST,
    PATH_LOGIN,
    PATH_PRODUCT_TSL,
    PATH_REGENERATE_AUTH_KEY,
    REGIONS,
)
from .protocol import aes_encrypt

_LOGGER = logging.getLogger(__name__)

# Every cloud call sits on a path that must not stall Home Assistant: setup, the authKey
# re-fetch, and the opt-in poll (which runs inside the coordinator update). aiohttp has no
# default timeout, so a firewalled/black-holed route would hang the request -- and with it
# the update loop -- until the OS gave up. See issue #6.
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=10)

_ALPHANUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class OukitelCloudError(Exception):
    """Cloud request failed."""


class OukitelCloudAuthError(OukitelCloudError):
    """Login failed (bad credentials)."""


class OukitelCloudConnectionError(OukitelCloudError):
    """The Quectel cloud could not be reached."""


class OukitelCloudTimeoutError(OukitelCloudConnectionError):
    """The Quectel cloud did not respond before the request deadline."""


class OukitelCloudResponseError(OukitelCloudError):
    """The Quectel cloud returned an unexpected or unsuccessful response."""


class OukitelCloudPasswordFormatError(OukitelCloudError):
    """The cloud rejected the password before attempting authentication."""


def _headers(token: str | None = None) -> dict[str, str]:
    h = {
        "X-Q-Language": "en",
        "quec-random-url": str(uuid.uuid4()),
        "app-info": "[Pixel][Google][raven][33]",
    }
    if token:
        h["Authorization"] = token
    return h


def build_login_fields(
    email: str, password: str, app_secret: str, user_domain: str, random: str | None = None
) -> dict[str, str]:
    """Build the emailPwdLogin form body (pure, testable)."""
    if random is None:
        random = "".join(secrets.choice(_ALPHANUM) for _ in range(16))
    md5u = hashlib.md5(random.encode()).hexdigest().upper()
    key = md5u[8:24]
    iv = key[8:16] + key[0:8]
    enc = aes_encrypt(key.encode(), iv.encode(), password.encode())
    encpwd = base64.encodebytes(enc).decode()  # Android Base64.DEFAULT (76-col wrap + trailing \n)
    signature = hashlib.sha256((email + encpwd + random + app_secret).encode()).hexdigest()
    return {
        "pwd": encpwd,
        "email": email,
        "random": random,
        "userDomain": user_domain,
        "signature": signature,
    }


class OukitelCloud:
    """Minimal async client for the endpoints we need."""

    def __init__(self, session: aiohttp.ClientSession, region: str) -> None:
        if region not in REGIONS:
            raise OukitelCloudError(f"unknown region: {region}")
        self._session = session
        self._region = REGIONS[region]
        self._token: str | None = None

    @property
    def base(self) -> str:
        return self._region["base"]

    async def login(self, email: str, password: str) -> str:
        """Log in; returns and stores the bearer token."""
        fields = build_login_fields(
            email, password, self._region["app_secret"], self._region["user_domain"]
        )
        data = await self._post_form(PATH_LOGIN, fields)
        payload = self._data_object(data, PATH_LOGIN)
        access_token = payload.get("accessToken")
        if access_token is None:
            raise OukitelCloudAuthError("login returned no token")
        if not isinstance(access_token, dict):
            raise OukitelCloudResponseError("login returned invalid accessToken")
        token = access_token.get("token")
        if token is None or token == "":
            raise OukitelCloudAuthError("login returned no token")
        if not isinstance(token, str):
            raise OukitelCloudResponseError("login returned invalid token")
        self._token = token
        return token

    async def get_devices(self) -> list[dict[str, Any]]:
        """Return the account's devices (each includes pk/dk/authKey/name)."""
        data = await self._get(PATH_DEVICE_LIST, {"pageNumber": "1", "pageSize": "50"})
        devices = self._data_object(data, PATH_DEVICE_LIST).get("list") or []
        if not isinstance(devices, list) or not all(isinstance(device, dict) for device in devices):
            raise OukitelCloudResponseError("userDeviceList returned invalid list")
        required_fields = ("deviceKey", "productKey", "authKey")
        # Accounts may also contain BLE-only bindings without a LAN authKey.
        # Ignore those entries so they do not prevent setup of usable stations.
        return [
            device
            for device in devices
            if all(
                isinstance(device.get(field), str) and device[field] for field in required_fields
            )
        ]

    async def get_tsl(self, pk: str) -> dict[str, Any]:
        """Return the product thing-model (data-point dictionary)."""
        data = await self._get(PATH_PRODUCT_TSL, {"pk": pk})
        payload = self._data_object(data, PATH_PRODUCT_TSL)
        properties = payload.get("properties")
        if not isinstance(properties, list):
            raise OukitelCloudResponseError("productTSL returned invalid properties")
        return payload

    async def regenerate_auth_key(self, pk: str, dk: str) -> str:
        """Return the CURRENT device authKey (the app's own fetch endpoint).

        For shared accounts the ``userDeviceList`` copy is frozen at binding
        time and local login with it fails (p5=-1) — this endpoint returns the
        live key. Verified live on a shared P1500 account (2026-09-06):
        repeated calls return the same value and the vendor app keeps working,
        so the feared rotation does not happen in practice; the cloud merely
        re-pushes the key the device already has.
        """
        data = await self._post_form(PATH_REGENERATE_AUTH_KEY, {"pk": pk, "dk": dk})
        auth_key = self._data_object(data, PATH_REGENERATE_AUTH_KEY).get("authKey")
        if not isinstance(auth_key, str) or not auth_key:
            raise OukitelCloudResponseError("regenerateAuthKey returned invalid authKey")
        return auth_key

    async def get_business_attributes(self, pk: str, dk: str) -> dict[int, Any]:
        """Return current scalar property values from the cloud as {tag_id: value}.

        Used for tags the LAN never reports (temperature, output voltage). Structs are
        skipped (those come from the local link); INT/ENUM -> int, BOOL -> bool.
        """
        data = await self._get(PATH_BUSINESS_ATTRS, {"pk": pk, "dk": dk})
        out: dict[int, Any] = {}
        items = self._data_object(data, PATH_BUSINESS_ATTRS).get("customizeTslInfo") or []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise OukitelCloudResponseError("getDeviceBusinessAttributes returned invalid list")
        for item in items:
            tag = item.get("abId")
            raw = item.get("resourceValce")
            dtype = item.get("dataType")
            if tag is None or raw is None or dtype == "STRUCT":
                continue
            try:
                if dtype == "BOOL":
                    out[int(tag)] = str(raw).lower() == "true"
                elif dtype in ("INT", "ENUM"):
                    out[int(tag)] = int(float(raw))
            except (TypeError, ValueError):
                continue
        return out

    # --- http helpers ---
    async def _post_form(self, path: str, fields: dict[str, str]) -> dict[str, Any]:
        return await self._request("POST", path, data=fields)

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    @staticmethod
    def _data_object(response: dict[str, Any], endpoint: str) -> dict[str, Any]:
        """Return an endpoint's object-shaped data payload or raise a cloud error."""
        payload = response.get("data")
        if not isinstance(payload, dict):
            raise OukitelCloudResponseError(f"{endpoint} returned invalid data")
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Perform one bounded request, mapping transport failures to OukitelCloudError.

        Callers (config flow, authKey re-fetch, cloud poll) only handle OukitelCloudError,
        so a raw aiohttp/timeout error escaping here would break the coordinator instead of
        being retried on the next cycle.
        """
        try:
            async with self._session.request(
                method,
                self.base + path,
                headers=_headers(self._token),
                timeout=_HTTP_TIMEOUT,
                **kwargs,
            ) as resp:
                return await self._parse(resp)
        except TimeoutError as err:
            raise OukitelCloudTimeoutError(
                f"timed out after {_HTTP_TIMEOUT.total}s: {path}"
            ) from err
        except aiohttp.ClientError as err:
            raise OukitelCloudConnectionError(f"request failed: {err}") from err

    @staticmethod
    async def _parse(resp: Any) -> dict[str, Any]:
        # Some gateways reject invalid credentials with an HTTP status instead
        # of the normal JSON ``code``. Do not report that as a connection issue.
        if resp.status == 401:
            raise OukitelCloudAuthError(f"HTTP {resp.status}")
        if resp.status != 200:
            raise OukitelCloudResponseError(f"HTTP {resp.status}")
        try:
            body = await resp.json(content_type=None)
        except ValueError as err:
            raise OukitelCloudResponseError("invalid JSON response") from err
        if not isinstance(body, dict):
            raise OukitelCloudResponseError("unexpected JSON response")
        code = body.get("code")
        if code in (401, 4001, 1003):  # auth-ish codes
            raise OukitelCloudAuthError(body.get("msg") or f"code {code}")
        if code not in (200, 0, None):
            message = str(body.get("msg") or f"code {code}")
            if "password format" in message.casefold():
                raise OukitelCloudPasswordFormatError(message)
            raise OukitelCloudResponseError(message)
        return body
