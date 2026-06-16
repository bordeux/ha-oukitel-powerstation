"""Constants and data-point metadata for the Oukitel Power Station integration.

Protocol and tag map reverse-engineered from the Quectel/Acceleronix "WonderFree" app
(productKey p11wN7). See REVERSE_ENGINEERING.md in the repo root.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "oukitel"

# ---- network ----
DISCOVERY_PORT: Final = 6606  # UDP discovery broadcast
CONTROL_PORT: Final = 6607  # TCP control / telemetry

# ---- protocol commands (cmd field) ----
CMD_HELLO: Final = 28722  # p2  app->dev hello
CMD_NONCE: Final = 28723  # p3  dev->app random nonce
CMD_LOGIN: Final = 28724  # p4  app->dev login token
CMD_LOGIN_RESULT: Final = 28725  # p5  dev->app login result (0 = ok)
CMD_WRITE_ACK: Final = 28726  # p6  dev->app write ack
CMD_PING: Final = 28727  # p7
CMD_PONG: Final = 28728  # p8
CMD_HEARTBEAT: Final = 28729  # p9  heartbeat / subscribe interval
CMD_READ: Final = 17  # read properties (payload = list of 2-byte tag ids)
CMD_WRITE: Final = 19  # write property (payload = TTLV (tag, value))
CMD_REPORT: Final = 20  # dev->app property report (telemetry)

DISCOVERY_PROBE_CMD: Final = 28720  # p0 — app's UDP discovery probe (broadcast)
DISCOVERY_CMD: Final = 28721  # p1 — station's discovery reply

# tag 100 = high-frequency reporting mode (ENUM): 3 = LAN + Wi-Fi high-freq (used as "subscribe")
TAG_HF_REPORTING: Final = 100
HF_REPORTING_LAN_WIFI: Final = 3

# read-list: the tag ids the app requests in a cmd17 (full snapshot)
READ_TAG_IDS: Final = (2, 8, 9, 6, 31, 7, 28, 27, 14, 12, 11, 5, 4, 3, 1, 34, 20, 100, 43, 44, 46)

# ---- cloud (per region): base url, app secret (DOMAIN_SECRET), user domain ----
REGIONS: Final = {
    "EU": {
        "base": "https://iot-api.quecteleu.com",
        "app_secret": "3aRNUwWahjyANa7WfBK2wCCkxCexB6nXxKJwXxfePvzf",
        "user_domain": "E.SP.4294967410",
    },
    "US": {
        "base": "https://iot-api.quectelus.com",
        "app_secret": "pUTp5goB1bLinprRQMmK3EPiiuPiGrJtKUNptWRXVmP",
        "user_domain": "U.SP.8589934603",
    },
    "CN": {
        "base": "https://iot-gateway.quectel.com",
        "app_secret": "EufftRJSuWuVY7c6txzGifV9bJcfXHAFa7hXY5doXSn7",
        "user_domain": "C.DM.5903.1",
    },
}
DEFAULT_REGION: Final = "EU"

# cloud API paths (relative to base + service prefix)
PATH_LOGIN: Final = "/v2/enduser/enduserapi/emailPwdLogin"
PATH_DEVICE_LIST: Final = "/v2/binding/enduserapi/userDeviceList"
PATH_PRODUCT_TSL: Final = "/v2/binding/enduserapi/productTSL"

# ---- config entry keys ----
CONF_REGION: Final = "region"
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_PK: Final = "pk"  # productKey
CONF_DK: Final = "dk"  # deviceKey (== MAC, lowercase, no separators)
CONF_AUTH_KEY: Final = "auth_key"
CONF_HOST: Final = "host"  # station LAN IP
CONF_NAME: Final = "name"

# ---- enum value maps (TSL) ----
FREQUENCY_OPTIONS: Final = {0: "50 Hz", 1: "60 Hz"}
VOLTAGE_OPTIONS: Final = {
    100: "100 V",
    110: "110 V",
    120: "120 V",
    220: "220 V",
    230: "230 V",
    240: "240 V",
}

# manufacturer / model for the device registry
MANUFACTURER: Final = "Oukitel"
DEFAULT_MODEL: Final = "P2001E Plus"
