"""Sensor platform for Oukitel Power Station."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OukitelConfigEntry
from .entity import OukitelEntity


@dataclass(frozen=True, kw_only=True)
class OukitelSensorDescription(SensorEntityDescription):
    """Sensor description bound to a protocol tag."""

    tag: int
    value_fn: Callable[[Any], Any] = lambda v: v


SENSORS: tuple[OukitelSensorDescription, ...] = (
    OukitelSensorDescription(
        key="battery",
        tag=1,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="remaining_time",
        tag=2,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="charging_time",
        tag=3,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="total_input_power",
        tag=4,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="total_output_power",
        tag=5,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="ac_input_power",
        tag=11,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="dc_input_power",
        tag=12,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="temperature",
        tag=14,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OukitelSensorDescription(
        key="inverter_version",
        tag=31,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: str(int(v)),
    ),
    OukitelSensorDescription(
        key="bms_version",
        tag=34,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: str(int(v)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OukitelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(OukitelSensor(coordinator, desc) for desc in SENSORS)


class OukitelSensor(OukitelEntity, SensorEntity):
    """A telemetry sensor."""

    entity_description: OukitelSensorDescription

    def __init__(self, coordinator, description: OukitelSensorDescription) -> None:
        super().__init__(coordinator, description, description.tag)

    @property
    def native_value(self) -> Any:
        value = self.coordinator.data.get(self._tag)
        if value is None or isinstance(value, dict | bytes):
            return None
        return self.entity_description.value_fn(value)
