"""Number platform for Oukitel Power Station (AC charge upper limit)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .entity import OukitelEntity


@dataclass(frozen=True, kw_only=True)
class OukitelNumberDescription(NumberEntityDescription):
    """Number bound to a protocol tag."""

    tag: int


NUMBERS: tuple[OukitelNumberDescription, ...] = (
    OukitelNumberDescription(
        key="ac_charge_limit",
        tag=20,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=3,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator = entry.runtime_data
    manifest = coordinator.manifest
    async_add_entities(
        OukitelNumber(coordinator, desc) for desc in NUMBERS if manifest.has_tag(desc.tag)
    )


class OukitelNumber(OukitelEntity, NumberEntity):
    """A settable numeric value."""

    entity_description: OukitelNumberDescription

    def __init__(self, coordinator, description: OukitelNumberDescription) -> None:
        super().__init__(coordinator, description, description.tag)

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.get(self._tag)
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_value(self._tag, int(value), is_bool=False)
