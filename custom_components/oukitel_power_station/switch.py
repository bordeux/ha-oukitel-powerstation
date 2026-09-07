"""Switch platform for Oukitel Power Station (AC / USB / DC outputs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .const import CONF_ENABLE_CONTROL
from .entity import OukitelEntity


@dataclass(frozen=True, kw_only=True)
class OukitelSwitchDescription(SwitchEntityDescription):
    """Switch bound to a protocol tag."""

    tag: int


SWITCHES: tuple[OukitelSwitchDescription, ...] = (
    OukitelSwitchDescription(key="ac_output", tag=43, device_class=SwitchDeviceClass.OUTLET),
    OukitelSwitchDescription(key="usb_output", tag=44, device_class=SwitchDeviceClass.OUTLET),
    OukitelSwitchDescription(key="dc_output", tag=46, device_class=SwitchDeviceClass.OUTLET),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches when control is enabled."""
    if not entry.options.get(CONF_ENABLE_CONTROL, False):
        return
    coordinator = entry.runtime_data
    async_add_entities(OukitelSwitch(coordinator, desc) for desc in SWITCHES)


class OukitelSwitch(OukitelEntity, SwitchEntity):
    """An output switch."""

    entity_description: OukitelSwitchDescription

    def __init__(self, coordinator, description: OukitelSwitchDescription) -> None:
        super().__init__(coordinator, description, description.tag)

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._tag)
        return bool(value) if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_value(self._tag, True, is_bool=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_value(self._tag, False, is_bool=True)
