"""Base entity for the Oukitel Power Station integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import OukitelCoordinator


class OukitelEntity(CoordinatorEntity[OukitelCoordinator]):
    """Common base: device_info, unique_id, tag-based availability."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OukitelCoordinator,
        description: EntityDescription,
        tag: int,
        subtag: int | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._tag = tag
        self._subtag = subtag
        dk = coordinator.dk
        self._attr_unique_id = f"{dk}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dk)},
            name=coordinator.config_entry.data.get(CONF_NAME) or "Oukitel Power Station",
            manufacturer=MANUFACTURER,
            model=DEFAULT_MODEL,
            connections={("mac", dk)} if len(dk) == 12 else set(),
        )

    @property
    def available(self) -> bool:
        # tag < 0 marks entities not backed by a protocol tag (e.g. the
        # reload button) — availability is theirs to decide.
        if self._tag < 0:
            return super().available
        if not (super().available and self._tag in self.coordinator.data):
            return False
        if self._subtag is None:
            return True
        value = self.coordinator.data.get(self._tag)
        return isinstance(value, dict) and self._subtag in value
