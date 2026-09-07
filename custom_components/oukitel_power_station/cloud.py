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
        token = ((data.get("data") or {}).get("accessToken") or {}).get("token")
        if not token:
            raise OukitelCloudAuthError("login returned no token")
        self._token = token
        return token

    async def get_devices(self) -> list[dict[str, Any]]:
        """Return the account's devices (each includes pk/dk/authKey/name)."""
        data = await self._get(PATH_DEVICE_LIST, {"pageNumber": "1", "pageSize": "50"})
        return (data.get("data") or {}).get("list", []) or []

    async def get_tsl(self, pk: str) -> dict[str, Any]:
        """Return the product thing-model (data-point dictionary)."""
        data = await self._get(PATH_PRODUCT_TSL, {"pk": pk})
        return data.get("data") or {}

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
        auth_key = (data.get("data") or {}).get("authKey")
        if not auth_key:
            raise OukitelCloudError("regenerateAuthKey returned no authKey")
        return str(auth_key)

    async def get_business_attributes(self, pk: str, dk: str) -> dict[int, Any]:
        """Return current scalar property values from the cloud as {tag_id: value}.

        Used for tags the LAN never reports (temperature, output voltage). Structs are
        skipped (those come from the local link); INT/ENUM -> int, BOOL -> bool.
        """
        data = await self._get(PATH_BUSINESS_ATTRS, {"pk": pk, "dk": dk})
        out: dict[int, Any] = {}
        for item in (data.get("data") or {}).get("customizeTslInfo") or []:
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
            raise OukitelCloudError(f"timed out after {_HTTP_TIMEOUT.total}s: {path}") from err
        except aiohttp.ClientError as err:
            raise OukitelCloudError(f"request failed: {err}") from err

    @staticmethod
    async def _parse(resp: Any) -> dict[str, Any]:
        if resp.status != 200:
            raise OukitelCloudError(f"HTTP {resp.status}")
        body = await resp.json(content_type=None)
        code = body.get("code")
        if code in (401, 4001, 1003):  # auth-ish codes
            raise OukitelCloudAuthError(body.get("msg") or f"code {code}")
        if code not in (200, 0, None):
            raise OukitelCloudError(body.get("msg") or f"code {code}")
        return body
