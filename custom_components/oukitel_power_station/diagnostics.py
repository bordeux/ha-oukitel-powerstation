"""Diagnostics for the Oukitel Power Station integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import OukitelConfigEntry
from .const import CONF_AUTH_KEY, CONF_EMAIL, CONF_HOST, CONF_PASSWORD

TO_REDACT = {CONF_PASSWORD, CONF_EMAIL, CONF_AUTH_KEY, CONF_HOST}


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OukitelConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (secrets redacted)."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "available": coordinator.last_update_success,
        # Connection health: a session that is up and acking writes while
        # last_report_age_s keeps climbing means the station has stopped streaming.
        "connection": coordinator.connection_diagnostics(),
        "telemetry": {str(tag): _jsonable(val) for tag, val in (coordinator.data or {}).items()},
    }
