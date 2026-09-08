"""Config flow for the Oukitel Power Station integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .cloud import OukitelCloud, OukitelCloudAuthError, OukitelCloudError
from .const import (
    CONF_AUTH_KEY,
    CONF_CLOUD_POLL,
    CONF_DK,
    CONF_EMAIL,
    CONF_ENABLE_CONTROL,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PK,
    CONF_REGION,
    DEFAULT_REGION,
    DOMAIN,
    REGIONS,
)
from .discovery import async_discover
from .protocol import OukitelAuthError, OukitelConnection, OukitelError

_LOGGER = logging.getLogger(__name__)


class OukitelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Cloud login → pick device → locate on LAN → validate."""

    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, str] = {}
        self._devices: list[dict[str, Any]] = []
        self._device: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OukitelOptionsFlow:
        return OukitelOptionsFlow()

    # --- step 1: cloud login ---
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            cloud = OukitelCloud(session, user_input[CONF_REGION])
            try:
                await cloud.login(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                self._devices = await cloud.get_devices()
            except OukitelCloudAuthError:
                errors["base"] = "invalid_auth"
            except OukitelCloudError:
                errors["base"] = "cannot_connect"
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._creds = {
                        CONF_REGION: user_input[CONF_REGION],
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    return await self.async_step_device()

        schema = vol.Schema(
            {
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(list(REGIONS)),
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # --- step 2: pick device ---
    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if len(self._devices) == 1:
            self._device = self._devices[0]
            return await self.async_step_locate()

        if user_input is not None:
            dk = user_input[CONF_DK]
            self._device = next(d for d in self._devices if d["deviceKey"] == dk)
            return await self.async_step_locate()

        options = {d["deviceKey"]: f"{d.get('deviceName', d['deviceKey'])}" for d in self._devices}
        schema = vol.Schema({vol.Required(CONF_DK): vol.In(options)})
        return self.async_show_form(step_id="device", data_schema=schema)

    # --- step 3: locate on LAN (auto, then manual) ---
    async def async_step_locate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        dk = self._device["deviceKey"]
        await self.async_set_unique_id(dk.lower())
        self._abort_if_unique_id_configured()
        host = await async_discover(dk)
        if host:
            return await self._validate_and_create(host)
        return await self.async_step_manual()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._validate_and_create(user_input[CONF_HOST], errors)
        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required(CONF_HOST): str}), errors=errors
        )

    async def _validate_and_create(
        self, host: str, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        errors = errors if errors is not None else {}
        auth_key = self._device["authKey"]
        conn = OukitelConnection(host, auth_key)
        try:
            await conn.connect()
        except OukitelAuthError:
            errors["base"] = "invalid_auth"
        except OukitelError:
            errors["base"] = "cannot_connect"
        finally:
            await conn.close()
        if errors:
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
                errors=errors,
            )
        return self.async_create_entry(
            title=self._device.get("deviceName") or self._device["deviceKey"],
            data={
                **self._creds,
                CONF_PK: self._device["productKey"],
                CONF_DK: self._device["deviceKey"],
                CONF_AUTH_KEY: auth_key,
                CONF_HOST: host,
                CONF_NAME: self._device.get("deviceName"),
            },
        )

    # --- reauth (authKey rotated / cloud creds changed) ---
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._creds = {
            CONF_REGION: entry_data[CONF_REGION],
            CONF_EMAIL: entry_data[CONF_EMAIL],
            CONF_PASSWORD: entry_data.get(CONF_PASSWORD, ""),
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            cloud = OukitelCloud(session, self._creds[CONF_REGION])
            try:
                await cloud.login(self._creds[CONF_EMAIL], user_input[CONF_PASSWORD])
                devices = await cloud.get_devices()
            except OukitelCloudAuthError:
                errors["base"] = "invalid_auth"
            except OukitelCloudError:
                errors["base"] = "cannot_connect"
            else:
                dk = entry.data[CONF_DK]
                match = next((d for d in devices if d["deviceKey"].lower() == dk.lower()), None)
                if not match:
                    errors["base"] = "no_devices"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={
                            **entry.data,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_AUTH_KEY: match["authKey"],
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self._creds.get(CONF_EMAIL, "")},
        )


class OukitelOptionsFlow(OptionsFlow):
    """Options: opt in to cloud-only values; opt in to local control."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_CLOUD_POLL, default=options.get(CONF_CLOUD_POLL, False)): bool,
                vol.Required(
                    CONF_ENABLE_CONTROL, default=options.get(CONF_ENABLE_CONTROL, False)
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
