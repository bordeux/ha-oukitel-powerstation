"""Binary sensor platform for the Oukitel Power Station integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .coordinator import OukitelCoordinator
from .entity import OukitelEntity

_TAG_TOTAL_INPUT_POWER = 4
_ON_BATTERY_DESCRIPTION = EntityDescription(key="on_battery")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    async_add_entities([OnBatteryBinarySensor(entry.runtime_data)])


class OnBatteryBinarySensor(OukitelEntity, BinarySensorEntity):
    """`on` when the station is battery-powered (mains lost).

    Rule confirmed by AC unplug/replug testing: ``total_input_power == 0``
    means on battery; ``> 0`` means on mains. The charging-power sensors
    (tags 11/12) must NOT be used for this: they read 0 on mains too
    whenever the battery is full (float, nothing to charge).

    No device class is set: `power` would make `off` look like "no power",
    while this entity answers the operational question "is the station
    running from its battery?".
    """

    def __init__(self, coordinator: OukitelCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, _ON_BATTERY_DESCRIPTION, tag=_TAG_TOTAL_INPUT_POWER)

    @property
    def is_on(self) -> bool | None:
        """Return True on battery, False on mains, None if input is unknown."""
        raw: Any = self.coordinator.data.get(_TAG_TOTAL_INPUT_POWER)
        if raw is None:
            return None
        try:
            return float(raw) == 0
        except (TypeError, ValueError):
            return None
