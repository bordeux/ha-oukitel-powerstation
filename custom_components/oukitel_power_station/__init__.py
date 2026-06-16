"""The Oukitel Power Station integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import OukitelCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

type OukitelConfigEntry = ConfigEntry[OukitelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OukitelConfigEntry) -> bool:
    """Set up Oukitel Power Station from a config entry."""
    coordinator = OukitelCoordinator(hass, entry)
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
    await hass.config_entries.async_reload(entry.entry_id)
