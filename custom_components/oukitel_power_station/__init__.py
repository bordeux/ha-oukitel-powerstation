"""The Oukitel Power Station integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_MANIFEST, CONF_PK, DEFAULT_MODEL
from .coordinator import OukitelCoordinator
from .manifest import ProductManifest, resolve_manifest

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

type OukitelConfigEntry = ConfigEntry[OukitelCoordinator]


async def _async_resolve_manifest(hass: HomeAssistant, entry: ConfigEntry) -> ProductManifest:
    """Resolve the product manifest off the event loop (file I/O).

    Entry snapshot → bundled TSL → empty fallback (entities gated off rather
    than guessed, e.g. a brand-new product key with no network).
    """
    pk = str(entry.data.get(CONF_PK) or "")
    snapshot = entry.data.get(CONF_MANIFEST)
    manifest = await hass.async_add_executor_job(resolve_manifest, pk, snapshot, None)
    if manifest is None:
        _LOGGER.warning("no product manifest for pk=%s — entities unavailable", pk)
        manifest = ProductManifest(
            product_key=pk,
            model=DEFAULT_MODEL,
            tsl_version=None,
            tags={},
            code_to_tag={},
            excluded_tags=(),
        )
    return manifest


async def async_setup_entry(hass: HomeAssistant, entry: OukitelConfigEntry) -> bool:
    """Set up Oukitel Power Station from a config entry."""
    manifest = await _async_resolve_manifest(hass, entry)
    coordinator = OukitelCoordinator(hass, entry, manifest)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OukitelConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_reload_on_update(hass: HomeAssistant, entry: OukitelConfigEntry) -> None:
    """Reload when options change.

    Data-only updates (authKey, host) are consumed in-place: the coordinator
    reads ``entry.data`` on every connect, so tearing the session down would
    only reset the one-refresh-per-outage guard and loop the key rewrite.
    """
    coordinator = entry.runtime_data
    if dict(entry.options) == coordinator.options:
        return
    await hass.config_entries.async_reload(entry.entry_id)
