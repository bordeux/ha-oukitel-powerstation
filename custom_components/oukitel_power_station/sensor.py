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
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
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
    """Sensor description bound to a protocol tag (and optional struct sub-tag)."""

    tag: int
    subtag: int | None = None
    value_fn: Callable[[Any], Any] = lambda v: v


def _power(key: str, tag: int, subtag: int | None = None) -> OukitelSensorDescription:
    return OukitelSensorDescription(
        key=key,
        tag=tag,
        subtag=subtag,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    )


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
    # --- per-port power (struct sub-tags) ---
    # AC Info (tag 6): 2=AC1 power(W), 3=AC1 voltage(V)
    _power("ac_output_power", 6, 2),
    OukitelSensorDescription(
        key="ac_output_voltage",
        tag=6,
        subtag=3,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    # USB Info (tag 7): 2=USB_QC1 power(W), 3=USB_QC2 power(W)
    _power("usb_qc1_power", 7, 2),
    _power("usb_qc2_power", 7, 3),
    # TypeC Info (tag 8): 2=Typec1, 5=Typec2, 6=Typec3, 7=Typec4 (all W)
    _power("typec1_power", 8, 2),
    _power("typec2_power", 8, 5),
    _power("typec3_power", 8, 6),
    _power("typec4_power", 8, 7),
    # DC Info (tag 9): 2=CAR1 power(W), 3=voltage(V), 4=current(A)
    _power("dc_output_power", 9, 2),
    OukitelSensorDescription(
        key="dc_output_voltage",
        tag=9,
        subtag=3,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    OukitelSensorDescription(
        key="dc_output_current",
        tag=9,
        subtag=4,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
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
        super().__init__(coordinator, description, description.tag, description.subtag)

    @property
    def native_value(self) -> Any:
        value = self.coordinator.data.get(self._tag)
        if self._subtag is not None:
            value = value.get(self._subtag) if isinstance(value, dict) else None
        if value is None or isinstance(value, dict | bytes):
            return None
        return self.entity_description.value_fn(value)
