"""Select platform for Oukitel Power Station (output voltage / frequency)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .const import FREQUENCY_OPTIONS, VOLTAGE_OPTIONS
from .entity import OukitelEntity


@dataclass(frozen=True, kw_only=True)
class OukitelSelectDescription(SelectEntityDescription):
    """Select bound to a protocol tag with an int<->label enum map."""

    tag: int
    value_map: dict[int, str]


SELECTS: tuple[OukitelSelectDescription, ...] = (
    OukitelSelectDescription(
        key="output_voltage",
        tag=28,
        value_map=VOLTAGE_OPTIONS,
        entity_category=EntityCategory.CONFIG,
    ),
    OukitelSelectDescription(
        key="output_frequency",
        tag=27,
        value_map=FREQUENCY_OPTIONS,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator = entry.runtime_data
    async_add_entities(OukitelSelect(coordinator, desc) for desc in SELECTS)


class OukitelSelect(OukitelEntity, SelectEntity):
    """An enum setting (voltage/frequency)."""

    entity_description: OukitelSelectDescription

    def __init__(self, coordinator, description: OukitelSelectDescription) -> None:
        super().__init__(coordinator, description, description.tag)
        self._attr_options = list(description.value_map.values())
        self._rev = {label: key for key, label in description.value_map.items()}

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.data.get(self._tag)
        if isinstance(value, int | float):
            return self.entity_description.value_map.get(int(value))
        return None

    async def async_select_option(self, option: str) -> None:
        key = self._rev.get(option)
        if key is None:
            return
        await self.coordinator.async_set_value(self._tag, key, is_bool=False)
