# Oukitel Power Station — Home Assistant integration

Local control of the **Oukitel P2001E Plus** (and other Quectel/Acceleronix "WonderFree"-app power
stations) in Home Assistant. After a one-time cloud login to fetch the per-device key, **all runtime
communication is local** (LAN, no cloud) and **push-based** (the station streams updates).

- **iot_class:** `local_push`
- **Requires:** Home Assistant **2026.1+**
- Protocol fully reverse-engineered & verified — see [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md).

## How it works
The station speaks a Quectel TTLV protocol over the LAN (UDP `6606` discovery, TCP `6607` control),
with an AES-128-CBC session keyed by a per-device `authKey`. The integration fetches that `authKey`
once from the Quectel cloud using your account, then connects directly to the station on your network.

## Install (HACS)
1. HACS → three-dot menu → **Custom repositories** → add this repo (category *Integration*).
2. Install **Oukitel Power Station**, then **restart Home Assistant**.
3. **Settings → Devices & Services → Add Integration → Oukitel Power Station**.

(Manual: copy `custom_components/oukitel_power_station/` into your HA `config/custom_components/`, restart.)

## Setup flow
1. **Cloud login** — region (EU/US/CN) + your WonderFree/Oukitel email & password. Used once to get
   the device key; the credentials are stored in HA's local config entry so the key can be refreshed
   automatically if it ever rotates.
2. **Pick device** (skipped if you have only one).
3. **Locate on LAN** — the station is found automatically via UDP discovery; if not (e.g. VLAN), you
   enter its IP.
4. Done — the device and entities are created. Runtime is fully local.

> Tip: give the station a DHCP reservation. If its IP changes, the integration re-discovers it by MAC.

> ⚠️ **Do not block the station's internet access.** Control and polling stay local, but the station
> only streams its telemetry once it has a live cloud connection. Firewalled off the internet it still
> completes the handshake and acks commands, yet sends no data at all — so every sensor goes
> unavailable while the device looks perfectly reachable. This is device behaviour, not something the
> integration can work around. See issue #6.

## Entities
**Sensors:** Battery %, Remaining time, Charging time, Total input power, Total output power,
AC charging input power, DC charging input power, Temperature, Inverter version, BMS version.

> Total input power is everything drawn from the source; the AC/DC *charging* input power sensors
> count only the share going into the battery. Charging from AC while a load sits on the AC output,
> the difference is that passthrough load.

**Switches:** AC output, USB output, DC output.
**Select:** Output voltage (100–240 V), Output frequency (50/60 Hz).
**Number:** AC charge limit (%).

## Troubleshooting
- **Setup fails to connect:** the phone app's "add device" must have completed once so the device is
  bound to your account; make sure HA and the station are on the same L2 network (or enter the IP).
- **"Reauthentication required":** the cloud `authKey` rotated — re-enter your password when prompted.
- **Entities show unavailable:** the station went offline / left WiFi; they recover on reconnect.
- **Diagnostics:** download from the device page (secrets are redacted) for bug reports.

## Status / development
See [`PLAN.md`](PLAN.md). The protocol library is unit-tested against captured device traffic
(`tests/`). Write commands (output toggles) are derived from captured app traffic; verify on your own
device. Per-port (AC/USB/TypeC/DC) detailed power/voltage sensors are planned.

## Credits / disclaimer
Independent, unofficial integration for personal use with your own hardware. Not affiliated with
Oukitel or Quectel.

## License
Released under the [MIT License](LICENSE).
