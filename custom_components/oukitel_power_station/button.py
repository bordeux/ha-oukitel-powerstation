"""Button platform for the Oukitel Power Station integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .coordinator import OukitelCoordinator
from .entity import OukitelEntity

_RELOAD_DESCRIPTION = EntityDescription(key="reload", entity_category=EntityCategory.DIAGNOSTIC)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the reload button."""
    async_add_entities([ReloadButton(entry.runtime_data, entry.entry_id)])


class ReloadButton(OukitelEntity, ButtonEntity):
    """Reload the config entry — same effect as the built-in "Reload" action.

    Functionally identical to Settings -> Devices & Services -> the
    integration's "Reload" menu action, just exposed as a device control so
    it can sit on a dashboard or be pressed from an automation. It is the
    recovery action for a stuck entry, so it overrides availability to
    always be on (a plain CoordinatorEntity would go unavailable exactly
    when the button is needed).
    """

    def __init__(self, coordinator: OukitelCoordinator, entry_id: str) -> None:
        """Initialise the button."""
        super().__init__(coordinator, _RELOAD_DESCRIPTION, tag=-1)
        self._entry_id = entry_id

    @property
    def available(self) -> bool:
        """Always available — this is the recovery action for a stuck entry."""
        return True

    async def async_press(self) -> None:
        """Reload the config entry (tears down and re-sets-up from scratch)."""
        await self.hass.config_entries.async_reload(self._entry_id)
