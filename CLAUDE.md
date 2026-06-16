# CLAUDE.md — Oukitel P2001E Plus → Home Assistant

## Goal
Build a **Home Assistant** integration for the **Oukitel P2001E Plus** (2048Wh / 2400W) portable
power station, controlled by the **WonderFree** app. The station has WiFi + Bluetooth.

## Status (current)
**Protocol fully reverse-engineered AND the HA integration is built & live-validated.**
- Reverse engineering: complete, verified end-to-end on the real device (read + write).
- Integration: `custom_components/oukitel/` (config flow + reauth, push coordinator, sensor/switch/
  select/number, diagnostics, icons, strings/translations). Fully local at runtime after a one-time
  cloud `authKey` fetch.
- Validated **live on the real network**: UDP discovery (same-subnet), handshake, AES read, write
  (USB toggle), and authKey-rotation re-fetch all confirmed.
- Quality/CI: `ruff` clean, `pytest` green (synthetic fixtures), GitHub Actions (`ci.yml`:
  ruff + pytest; `validate.yml`: hassfest + HACS). Repo **sanitized** (no device secrets tracked).
- Git: initialized on branch **`master`**, remote `origin` = `git@github.com:bordeux/ha-oukitel-powerstation.git`. **Not committed yet.**

**Remaining:** create the GitHub repo, commit & push; user installs in HA (HACS or copy
`custom_components/oukitel/`) and runs the config flow. Optional: submit a brand icon to
`home-assistant/brands` (`custom_integrations/oukitel/icon.png` 256×256).

## ⭐ Read this first
**`REVERSE_ENGINEERING.md` is the single source of truth** — full protocol, encryption, key
derivation, command codes, the complete tag/property map, secrets, tools, and lab setup.
Do not re-derive anything; read that file. Start at its **section 0 (STATUS)**.

## One-paragraph protocol summary
Firmware is **Quectel / Acceleronix** (NOT Tuya). App ↔ station is **local LAN**: UDP `6606`
discovery, TCP `6607` control. Frames: `AA AA | len | checksum | packetID | cmd | payload`, with
byte-stuffing (`AA`→`AA 55`) and an additive checksum. Payload is **TTLV** (tag/type/len/value).
After a `p2/p3/p4/p5` handshake the payload is **AES-128-CBC/PKCS5** encrypted with
`key = Base64.decode(authKey)` and `IV = the random nonce` the device sends in `p3`.
`authKey` is per-device, fetched once from the cloud. Read = `cmd 17`, write = `cmd 19`,
telemetry report = `cmd 20`.

## Tools (`tools/`)
- `quectel_cloud.py` — cloud login (`emailPwdLogin`) → token, `userDeviceList` (includes `authKey`),
  and product TSL. Run on any host with internet: `python3 tools/quectel_cloud.py`.
- `oukitel_local.py` — the working local client (discover → handshake → AES → live decrypted
  telemetry). **Must run on the Pi** (same LAN as the station): `python3 -u tools/oukitel_local.py`.
- `tsl_p11wN7.json` — authoritative thing-model (tag → name/unit/enum).

## Lab / environment
- Kali Pi 5: `ssh oukitel-kali` (→ `kali@10.60.20.89`, key auth, passwordless sudo). `eth0` = uplink,
  `wlan0` = 2.4GHz hotspot **`oukitel-lab` / `oukitel12345`** (NetworkManager `shared`; needs
  `net.ipv4.ip_forward=1`, persisted). Station joins the hotspot → IP `10.42.0.149`.
- Captures: `/home/kali/oukitel/oukitel-*.pcap`; analyze with `tshark`.
- Decompiled APK: `apk/jadx/sources/` (obfuscated `com.quectel.*` — grep string constants, not method
  names). Original APK: `~/Downloads/Wonderfree_V3.6.0_APKPure.xapk`.
- The Mac **cannot** reach `10.42.0.149` directly (behind the Pi NAT) — run the local client on the Pi.

## Key secrets (this device — full table in REVERSE_ENGINEERING.md §0)
pk `p11wN7` · dk `aabbccddeeff` · **authKey `REDACTED_AUTHKEY`** · cloud EU
`iot-api.quecteleu.com`. Cloud account email/password are NOT stored here — pass them at runtime
(args or `QUECTEL_EMAIL` / `QUECTEL_PASSWORD` env vars).

## Integration design (as built)
The protocol logic lives in `custom_components/oukitel/{protocol,cloud,discovery}.py` (the earlier
`tools/*.py` were the dev/RE prototypes, now gitignored/local-only).

**Connect flow (config flow):** Step1 cloud login (region EU/US/CN + email + password) → fetch
device list (name/pk/dk/authKey). Step2 pick device(s). Step3 locate on LAN: **auto-discover via UDP
6606 by MAC, manual IP fallback**. Step4 validate via real TCP 6607 handshake, then create device +
entities.

**Decided behavior:**
- **Store email + password** in the HA config entry (lives in HA's local `.storage`, NOT in this repo)
  → silent automatic `authKey` re-fetch if it rotates (reauth flow as backstop).
- **IP discovery:** UDP 6606 broadcast matched by MAC; manual entry fallback; re-discover on DHCP change.
- **Runtime is 100% local:** persistent TCP 6607 connection, subscribe (cmd19 tag100=3) + read (cmd17),
  push updates from cmd20 reports, keepalive + auto-reconnect.

**Entities:** sensors (battery %, remain/charge time, total in/out power, AC/DC input, temperature,
per-port AC/USB/TypeC/DC power & voltage, inverter/BMS versions); switches (AC/USB/DC output);
select (output voltage 100–240V, frequency 50/60Hz); number (AC charge limit %).

Optionally first run a toggle test (flip AC/USB/DC in the app while logging on the Pi) to confirm writes.

## Conventions
- **Git commits / PRs:** do NOT mention Claude, AI, Anthropic, "Co-Authored-By: Claude",
  "Generated with Claude Code", or similar in commit messages, PR titles/descriptions, or code
  comments. Write plain, human, conventional commit messages (e.g. `feat: add config flow`,
  `fix: handle authKey rotation`). No AI attribution anywhere in the repo history.
- Repo is **sanitized for public release**: device `authKey`/`bindingCode`/account IDs are replaced
  with placeholders in tracked docs, and tests use **synthetic** vectors. Real device keys are never
  committed — they're fetched at runtime (cloud) or live only in gitignored `tools/` + the home-dir
  agent memory. `.gitignore` excludes `apk/`, `tools/`, pcaps, `.mcp.json`, `.venv/`.
- App-level constants (region base URLs, `appSecret`, `userDomain` in `const.py`) are extracted from
  the public APK and are the same for all users — they're required and intentionally kept.
- Append new protocol findings to `REVERSE_ENGINEERING.md` (keep it the source of truth).
