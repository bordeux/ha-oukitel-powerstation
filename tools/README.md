# tools/ — reverse-engineering / dev helpers

Standalone scripts used to reverse-engineer the protocol and validate the integration. They are
**not** part of the Home Assistant integration (the protocol logic lives in
`custom_components/oukitel_power_station/`). Kept here as documentation and for debugging.

All device/account values come from a gitignored **`.env`** (copy `.env.example` → `.env`). Nothing
secret is committed.

- **`quectel_cloud.py`** — cloud login (`emailPwdLogin`) → token, then `userDeviceList` (includes the
  per-device `authKey`). Run anywhere with internet:
  `python3 tools/quectel_cloud.py` (reads `QUECTEL_EMAIL`/`QUECTEL_PASSWORD` from `.env`).
- **`oukitel_local.py`** — minimal local client: discover/connect a station on the LAN, do the
  handshake, and print live decrypted telemetry. Needs `OUKITEL_AUTHKEY` (+ station IP via arg or
  `OUKITEL_HOST`). Must run on the same L2 network as the station.
- **`cloud_temp_check.py`** — prints the cloud's current property values (incl. temperature/voltage,
  which this firmware does not expose over the LAN). Needs cloud creds + `OUKITEL_DK`.
- **`tsl_p11wN7.json`** — the product thing-model (tag → name/unit/enum). Product-level, not secret.

See `REVERSE_ENGINEERING.md` for the full protocol.
