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
from .manifest import ProductManifest
from .protocol import OukitelAuthError, OukitelConnection, OukitelError

if TYPE_CHECKING:
    from . import OukitelConfigEntry

_LOGGER = logging.getLogger(__name__)

_UPDATE_INTERVAL = timedelta(seconds=60)
# A healthy station streams cmd20 reports continuously. It can however sit in a state
# where it completes the handshake and acks every write while never sending telemetry
# (observed with the device unable to reach the Quectel cloud). Nothing else notices:
# the acks keep the read loop fed so the protocol read watchdog stays happy, and the
# update method only *sends* a read, so it would report success on stale data forever.
_REPORT_TIMEOUT = 150.0


def stall_age(
    now: float,
    last_report: float | None,
    connected_at: float | None,
    timeout: float = _REPORT_TIMEOUT,
) -> float | None:
    """Return how long telemetry has been missing, or None if the stream looks healthy.

    Measured from the last report, or from the connect time when none has arrived yet,
    so a fresh session gets a grace period before being declared stalled. Pure, so the
    policy can be tested without a Home Assistant instance.
    """
    reference = last_report or connected_at
    if reference is None:
        return None
    age = now - reference
    return age if age > timeout else None


class OukitelCoordinator(DataUpdateCoordinator[dict[int, Any]]):
    """Maintain one local session and surface decoded telemetry as {tag: value}."""

    config_entry: OukitelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manifest: ProductManifest) -> None:
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
        self._last_report: float | None = None
        self._connected_at: float | None = None
        self._reconnects = 0
        self.options = dict(entry.options)
        self._manifest = manifest

    @property
    def dk(self) -> str:
        return self.config_entry.data[CONF_DK]

    @property
    def host(self) -> str:
        return self.config_entry.data[CONF_HOST]

    @property
    def manifest(self) -> ProductManifest:
        """The product manifest (TSL-derived capability model)."""
        return self._manifest

    # --- connection lifecycle ---
    def _handle_report(self, report: dict[int, Any]) -> None:
        _LOGGER.debug("report=%s", report)
        self._last_report = self.hass.loop.time()
        # Replace, don't merge: a read returns the full struct, so replacing lets a
        # port that turned off (dropped/zeroed sub-tag) actually clear instead of
        # keeping its last non-zero value forever.
        self._state.update(report)
        self.async_set_updated_data(dict(self._state))

    def _listening(self) -> bool:
        return self._listen_task is not None and not self._listen_task.done()

    async def _ensure_connected(self) -> None:
        if self._conn is not None and self._listening():
            return
        if self._conn is not None:
            # A connection without a running reader decodes nothing: reads would be
            # sent into a void and the cached state returned as if it were fresh.
            _LOGGER.debug("connection has no live listener; dropping it")
            await self._reset_connection()
        host = self.host
        _LOGGER.debug("(re)connecting to %s at %s", self.dk, host)
        conn = OukitelConnection(
            host,
            self.config_entry.data[CONF_AUTH_KEY],
            self._handle_report,
            read_tags=self._manifest.read_tag_ids(),
        )
        try:
            await conn.connect()
        except OukitelAuthError as err:
            await conn.close()
            if self._auth_refetched:
                # already tried a fresh key this outage — credentials, not the key
                raise ConfigEntryAuthFailed(
                    f"local login still rejected after authKey refresh ({err})"
                ) from err
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
        self._connected_at = self.hass.loop.time()
        self._last_report = None
        self._reconnects += 1
        self._auth_refetched = False  # key proved good — allow a future silent refresh
        _LOGGER.debug("connected to %s; subscribing", self.dk)
        # Start the reader before subscribing: if the subscribe fails we must not be
        # left holding a connection nobody reads.
        self._listen_task = self.config_entry.async_create_background_task(
            self.hass, self._listen(), name=f"{DOMAIN}_listen_{self.dk}"
        )
        try:
            await conn.subscribe_and_read()
        except OukitelError:
            await self._reset_connection()
            raise

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
        task = self._listen_task
        self._listen_task = None
        # _listen() calls this from inside the listen task itself; never cancel self.
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._connected_at = None
        self._last_report = None

    async def _refetch_auth_key(self) -> None:
        """Re-fetch the live authKey via regenerateAuthKey.

        One deterministic source: ``userDeviceList`` is frozen at binding time
        on shared accounts, so preferring it over regenerate ping-pongs the
        stored key (K0 rejected → regenerate K1 → reload → list K0 differs →
        write K0 → …) and never reaches reauth. regenerateAuthKey is the app's
        own fetch and returns the current device key without rotating it
        (verified live).
        """
        data = self.config_entry.data
        session = async_get_clientsession(self.hass)
        cloud = OukitelCloud(session, data[CONF_REGION])
        try:
            await cloud.login(data[CONF_EMAIL], data[CONF_PASSWORD])
            auth_key = await cloud.regenerate_auth_key(data[CONF_PK], self.dk)
        except OukitelCloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OukitelCloudError as err:
            raise UpdateFailed(f"cloud error: {err}") from err
        if auth_key == data.get(CONF_AUTH_KEY):
            # The just-rejected key is also the deterministic cloud result.
            # There is nothing a new coordinator/startup retry can change;
            # fail into HA's reauth path instead of retrying forever.
            raise ConfigEntryAuthFailed("regenerateAuthKey returned the rejected device key")
        self._auth_refetched = True
        _LOGGER.debug("authKey refreshed from cloud for %s", self.dk)
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**data, CONF_AUTH_KEY: auth_key}
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

    def _telemetry_stalled(self) -> float | None:
        """Age of the last report if the device has gone quiet, else None."""
        return stall_age(self.hass.loop.time(), self._last_report, self._connected_at)

    async def _async_update_data(self) -> dict[int, Any]:
        # Two attempts: a session the device reset between polls fails on the first
        # send, and reconnecting takes well under a second. Retrying here keeps that
        # invisible instead of blanking every entity until the next cycle.
        for attempt in (1, 2):
            try:
                await self._ensure_connected()
                assert self._conn is not None
                await self._conn.async_read_all()
                break
            except ConfigEntryAuthFailed:
                raise
            except UpdateFailed:
                await self._reset_connection()
                raise
            except OukitelError as err:
                await self._reset_connection()
                if attempt == 1:
                    _LOGGER.debug("read failed (%s); reconnecting and retrying once", err)
                    continue
                raise UpdateFailed(str(err)) from err

        if (age := self._telemetry_stalled()) is not None:
            stats = self._conn.stats() if self._conn else "no session"
            _LOGGER.warning(
                "%s: connected and writes are being acked, but no telemetry for %.0fs "
                "(%s). Dropping the session to resubscribe. The usual cause is the station "
                "having no internet access: it keeps serving the handshake and writes, but "
                "only streams telemetry while it can reach the Quectel cloud. Check for a "
                "firewall rule blocking it (see issue #6)",
                self.dk,
                age,
                stats,
            )
            await self._reset_connection()
            raise UpdateFailed(f"no telemetry for {age:.0f}s")

        await self._poll_cloud_if_due()
        return dict(self._state)

    # --- control ---
    async def async_set_value(self, tag: int, value: Any, *, is_bool: bool) -> None:
        try:
            await self._ensure_connected()
        except Exception:
            # Never leave a half-set-up connection behind on a failed write; the next
            # update would treat it as usable and read into a void.
            await self._reset_connection()
            raise
        assert self._conn is not None
        try:
            await self._conn.async_set(tag, value, is_bool=is_bool)
        except OukitelError:
            await self._reset_connection()
            raise
        # optimistic local update; device will also echo a report
        self._state[tag] = bool(value) if is_bool else value
        self.async_set_updated_data(dict(self._state))

    def connection_diagnostics(self) -> dict[str, Any]:
        """Connection health for the diagnostics download."""
        now = self.hass.loop.time()
        return {
            "connected": self._conn is not None,
            "listener_running": self._listening(),
            "reconnects": self._reconnects,
            "connected_for_s": round(now - self._connected_at, 1) if self._connected_at else None,
            "last_report_age_s": round(now - self._last_report, 1) if self._last_report else None,
            "frames": self._conn.stats() if self._conn else None,
        }

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        if self._listen_task:
            self._listen_task.cancel()
        await self._reset_connection()
