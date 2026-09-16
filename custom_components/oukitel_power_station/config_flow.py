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
from homeassistant.const import UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .cloud import (
    OukitelCloud,
    OukitelCloudAuthError,
    OukitelCloudConnectionError,
    OukitelCloudError,
    OukitelCloudPasswordFormatError,
    OukitelCloudTimeoutError,
)
from .const import (
    CLOUD_POLL_INTERVAL_MAX_S,
    CLOUD_POLL_INTERVAL_MIN_S,
    CLOUD_POLL_INTERVAL_S,
    CONF_AUTH_KEY,
    CONF_CLOUD_POLL,
    CONF_CLOUD_POLL_INTERVAL,
    CONF_DK,
    CONF_EMAIL,
    CONF_ENABLE_CONTROL,
    CONF_HF_MODE,
    CONF_HOST,
    CONF_MANIFEST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PK,
    CONF_REARM_POLICY,
    CONF_REGION,
    DEFAULT_REGION,
    DOMAIN,
    HF_REPORTING_LAN,
    HF_REPORTING_LAN_WIFI,
    HF_REPORTING_OFF,
    REARM_ALWAYS,
    REARM_ON_STALL,
    REGIONS,
)
from .discovery import async_discover
from .product import build_manifest
from .protocol import OukitelAuthError, OukitelConnection, OukitelError

_LOGGER = logging.getLogger(__name__)


def _cloud_error_key(err: OukitelCloudError) -> str:
    """Map cloud failures to an actionable config-flow message."""
    if isinstance(err, OukitelCloudPasswordFormatError):
        return "password_format"
    if isinstance(err, OukitelCloudTimeoutError):
        return "cloud_timeout"
    if isinstance(err, OukitelCloudConnectionError):
        return "cloud_unreachable"
    return "cloud_response"


def _device_label(device: dict[str, Any]) -> str:
    """Human label for the picker: deviceName plus the product name."""
    name = str(device.get("deviceName") or device["deviceKey"])
    product = str(device.get("productName") or device.get("productKey") or "")
    return f"{name} ({product})" if product and product not in name else name


def _connect_mode_schema() -> vol.Schema:
    """Return the translated local/cloud-only connection selector."""
    return vol.Schema(
        {
            vol.Required("mode", default="manual"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["manual", "cloud_only"],
                    translation_key="connect_mode",
                )
            )
        }
    )


class OukitelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Cloud login → pick device → locate on LAN → validate."""

    VERSION = 2

    def __init__(self) -> None:
        self._creds: dict[str, str] = {}
        self._devices: list[dict[str, Any]] = []
        self._device: dict[str, Any] = {}
        self._cloud: OukitelCloud | None = None

    async def _async_get_cloud(self) -> OukitelCloud:
        """Return the authenticated client created during the login step."""
        if self._cloud is None:
            cloud = OukitelCloud(async_get_clientsession(self.hass), self._creds[CONF_REGION])
            await cloud.login(self._creds[CONF_EMAIL], self._creds[CONF_PASSWORD])
            self._cloud = cloud
        return self._cloud

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
            except OukitelCloudError as err:
                _LOGGER.debug("cloud login or device lookup failed: %s", err)
                errors["base"] = _cloud_error_key(err)
            else:
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    self._cloud = cloud
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

        options = {d["deviceKey"]: _device_label(d) for d in self._devices}
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
        return await self.async_step_connect_mode()

    async def async_step_connect_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The station was not discovered — manual IP, or cloud-only."""
        if user_input is not None:
            if user_input["mode"] == "manual":
                return await self.async_step_manual()
            return await self._validate_and_create(host=None)
        return self.async_show_form(step_id="connect_mode", data_schema=_connect_mode_schema())

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._validate_and_create(user_input[CONF_HOST], errors)
        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required(CONF_HOST): str}), errors=errors
        )

    async def _validate_and_create(
        self, host: str | None, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        errors = errors if errors is not None else {}
        auth_key = self._device["authKey"]
        if host is not None:
            conn = OukitelConnection(host, auth_key)
            try:
                await conn.connect()
            except OukitelAuthError:
                # Shared accounts serve a binding-time-frozen key in userDeviceList;
                # regenerateAuthKey returns the current key used by the station.
                try:
                    cloud = await self._async_get_cloud()
                    auth_key = await cloud.regenerate_auth_key(
                        self._device["productKey"], self._device["deviceKey"]
                    )
                except OukitelCloudAuthError:
                    errors["base"] = "invalid_auth"
                except OukitelCloudError as err:
                    _LOGGER.debug("auth-key refresh failed: %s", err)
                    errors["base"] = _cloud_error_key(err)
                else:
                    conn = OukitelConnection(host, auth_key)
                    try:
                        await conn.connect()
                    except OukitelAuthError:
                        errors["base"] = "invalid_auth"
                    except OukitelError:
                        errors["base"] = "cannot_connect"
                    finally:
                        await conn.close()
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

        # Capture the thing-model for both connection modes. Cloud-only setup
        # additionally reads the shadow once to validate device access.
        manifest: dict[str, Any] = {}
        try:
            cloud = await self._async_get_cloud()
            tsl = await cloud.get_tsl(self._device["productKey"])
            vendor_manifest = build_manifest(tsl)
            if not vendor_manifest.tags:
                raise OukitelCloudError("productTSL returned no properties")
            if host is None:
                await cloud.get_business_attributes(
                    self._device["productKey"], self._device["deviceKey"]
                )
        except OukitelCloudAuthError as err:
            if host is None:
                return self.async_show_form(
                    step_id="connect_mode",
                    data_schema=_connect_mode_schema(),
                    errors={"base": "invalid_auth"},
                )
            _LOGGER.debug("productTSL fetch failed (bundled fallback): %s", err)
        except OukitelCloudError as err:
            if host is None:
                return self.async_show_form(
                    step_id="connect_mode",
                    data_schema=_connect_mode_schema(),
                    errors={"base": _cloud_error_key(err)},
                )
            _LOGGER.debug("productTSL fetch failed (bundled fallback): %s", err)
        else:
            manifest = vendor_manifest.to_dict()
        return self.async_create_entry(
            title=self._device.get("deviceName") or self._device["deviceKey"],
            data={
                **self._creds,
                CONF_PK: self._device["productKey"],
                CONF_DK: self._device["deviceKey"],
                CONF_AUTH_KEY: auth_key,
                CONF_HOST: host,
                CONF_NAME: self._device.get("deviceName"),
                CONF_MANIFEST: manifest,
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
                auth_key = await cloud.regenerate_auth_key(entry.data[CONF_PK], entry.data[CONF_DK])
            except OukitelCloudAuthError:
                errors["base"] = "invalid_auth"
            except OukitelCloudError as err:
                _LOGGER.debug("reauthentication failed: %s", err)
                errors["base"] = _cloud_error_key(err)
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_AUTH_KEY: auth_key,
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self._creds.get(CONF_EMAIL, "")},
        )


class OukitelOptionsFlow(OptionsFlow):
    """Options: cloud poll + control (local stations) / poll interval (cloud-only)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        if self.config_entry.data.get(CONF_HOST):
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_CLOUD_POLL, default=options.get(CONF_CLOUD_POLL, False)
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_CONTROL, default=options.get(CONF_ENABLE_CONTROL, False)
                    ): bool,
                    # --- issue #32 experiment; defaults reproduce the shipped behaviour ---
                    vol.Required(
                        CONF_HF_MODE,
                        default=str(options.get(CONF_HF_MODE, HF_REPORTING_LAN_WIFI)),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                str(HF_REPORTING_LAN_WIFI),
                                str(HF_REPORTING_LAN),
                                str(HF_REPORTING_OFF),
                            ],
                            translation_key="hf_mode",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_REARM_POLICY,
                        default=options.get(CONF_REARM_POLICY, REARM_ALWAYS),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[REARM_ALWAYS, REARM_ON_STALL],
                            translation_key="rearm_policy",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_CLOUD_POLL_INTERVAL,
                        default=options.get(CONF_CLOUD_POLL_INTERVAL, CLOUD_POLL_INTERVAL_S),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=CLOUD_POLL_INTERVAL_MIN_S,
                            max=CLOUD_POLL_INTERVAL_MAX_S,
                            step=60,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement=UnitOfTime.SECONDS,
                        )
                    )
                }
            )
        return self.async_show_form(step_id="init", data_schema=schema)
