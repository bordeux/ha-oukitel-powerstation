"""Data update coordinator: owns the local connection, pushes updates, recovers."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import OukitelCloud, OukitelCloudAuthError, OukitelCloudError
from .const import (
    CLOUD_ONLY_TAGS,
    CLOUD_POLL_INTERVAL_S,
    CONF_AUTH_KEY,
    CONF_CLOUD_POLL,
    CONF_DK,
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PK,
    CONF_REGION,
    DOMAIN,
)
from .discovery import async_discover
from .protocol import OukitelAuthError, OukitelConnection, OukitelError

if TYPE_CHECKING:
    from . import OukitelConfigEntry

_LOGGER = logging.getLogger(__name__)

_UPDATE_INTERVAL = timedelta(seconds=60)


class OukitelCoordinator(DataUpdateCoordinator[dict[int, Any]]):
    """Maintain one local session and surface decoded telemetry as {tag: value}."""

    config_entry: OukitelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data.get(CONF_DK)}",
            update_interval=_UPDATE_INTERVAL,
            config_entry=entry,
        )
        self._conn: OukitelConnection | None = None
        self._listen_task: asyncio.Task | None = None
        self._state: dict[int, Any] = {}
        self._auth_refetched = False
        self._cloud: OukitelCloud | None = None
        self._last_cloud_poll: float = 0.0

    @property
    def dk(self) -> str:
        return self.config_entry.data[CONF_DK]

    @property
    def host(self) -> str:
        return self.config_entry.data[CONF_HOST]

    # --- connection lifecycle ---
    def _handle_report(self, report: dict[int, Any]) -> None:
        _LOGGER.debug("report=%s", report)
        # Replace, don't merge: a read returns the full struct, so replacing lets a
        # port that turned off (dropped/zeroed sub-tag) actually clear instead of
        # keeping its last non-zero value forever.
        self._state.update(report)
        self.async_set_updated_data(dict(self._state))

    async def _ensure_connected(self) -> None:
        if self._conn is not None:
            return
        host = self.host
        _LOGGER.debug("(re)connecting to %s at %s", self.dk, host)
        conn = OukitelConnection(host, self.config_entry.data[CONF_AUTH_KEY], self._handle_report)
        try:
            await conn.connect()
        except OukitelAuthError as err:
            await conn.close()
            _LOGGER.debug("auth rejected (%s); refetching authKey", err)
            await self._refetch_auth_key()
            raise UpdateFailed("auth key rotated; refetched, retrying") from err
        except OukitelError as err:
            await conn.close()
            # try to rediscover a possibly-changed IP, then fail this cycle
            new_ip = await async_discover(self.dk)
            if new_ip and new_ip != host:
                _LOGGER.debug("rediscovered %s at new IP %s (was %s)", self.dk, new_ip, host)
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, CONF_HOST: new_ip}
                )
            else:
                _LOGGER.debug("connect to %s failed (%s); discovery found %s", host, err, new_ip)
            raise UpdateFailed(f"cannot connect to {host}") from err
        self._conn = conn
        _LOGGER.debug("connected to %s; subscribing", self.dk)
        await conn.subscribe_and_read()
        self._listen_task = self.config_entry.async_create_background_task(
            self.hass, self._listen(), name=f"{DOMAIN}_listen_{self.dk}"
        )

    async def _listen(self) -> None:
        assert self._conn is not None
        try:
            await self._conn.listen()
        except asyncio.CancelledError:
            raise  # shutdown / reload: not a connection loss, don't trigger recovery
        except Exception as err:  # any read/decode failure -> reconnect
            _LOGGER.debug("listen ended (%s); will reconnect", err)
            await self._reset_connection()
            self.async_set_update_error(OukitelError("connection lost"))
            await self.async_request_refresh()

    async def _reset_connection(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _refetch_auth_key(self) -> None:
        """Re-fetch authKey from the cloud using stored credentials (reauth on failure)."""
        data = self.config_entry.data
        session = async_get_clientsession(self.hass)
        cloud = OukitelCloud(session, data[CONF_REGION])
        try:
            await cloud.login(data[CONF_EMAIL], data[CONF_PASSWORD])
            devices = await cloud.get_devices()
        except OukitelCloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OukitelCloudError as err:
            raise UpdateFailed(f"cloud error: {err}") from err
        match = next((d for d in devices if (d.get("deviceKey") or "").lower() == self.dk), None)
        if not match or not match.get("authKey"):
            raise ConfigEntryAuthFailed("device not found on account")
        _LOGGER.debug("authKey refetched from cloud for %s", self.dk)
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**data, CONF_AUTH_KEY: match["authKey"]}
        )

    async def _poll_cloud_if_due(self) -> None:
        """When opted-in, fetch cloud-only values (temp/voltage) on a slow cadence.

        Failures are swallowed: the cloud poll must never break the local update.
        """
        if not self.config_entry.options.get(CONF_CLOUD_POLL):
            return
        now = self.hass.loop.time()
        if self._last_cloud_poll and now - self._last_cloud_poll < CLOUD_POLL_INTERVAL_S:
            return
        self._last_cloud_poll = now
        data = self.config_entry.data
        try:
            if self._cloud is None:
                self._cloud = OukitelCloud(async_get_clientsession(self.hass), data[CONF_REGION])
                await self._cloud.login(data[CONF_EMAIL], data[CONF_PASSWORD])
            attrs = await self._cloud.get_business_attributes(data[CONF_PK], self.dk)
        except OukitelCloudAuthError as err:
            self._cloud = None  # token likely expired; re-login next cycle
            _LOGGER.debug("cloud poll auth failed (%s); will re-login next cycle", err)
            return
        except OukitelCloudError as err:
            _LOGGER.debug("cloud poll failed: %s", err)
            return
        updates = {t: attrs[t] for t in CLOUD_ONLY_TAGS if t in attrs}
        if updates:
            _LOGGER.debug("cloud poll merged %s", updates)
            self._state.update(updates)

    async def _async_update_data(self) -> dict[int, Any]:
        try:
            await self._ensure_connected()
            assert self._conn is not None
            await self._conn.async_read_all()
        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed:
            await self._reset_connection()
            raise
        except OukitelError as err:
            await self._reset_connection()
            raise UpdateFailed(str(err)) from err
        await self._poll_cloud_if_due()
        return dict(self._state)

    # --- control ---
    async def async_set_value(self, tag: int, value: Any, *, is_bool: bool) -> None:
        await self._ensure_connected()
        assert self._conn is not None
        try:
            await self._conn.async_set(tag, value, is_bool=is_bool)
        except OukitelError:
            await self._reset_connection()
            raise
        # optimistic local update; device will also echo a report
        self._state[tag] = bool(value) if is_bool else value
        self.async_set_updated_data(dict(self._state))

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        if self._listen_task:
            self._listen_task.cancel()
        await self._reset_connection()
