# PLAN — Oukitel P2001E Plus → Home Assistant integration

Engineering plan for a production-quality HA **custom integration** (`custom_components/oukitel_power_station/`),
HACS-distributable, local-push at runtime, cloud only for one-time `authKey`. Protocol is fully
reverse-engineered and verified — see `REVERSE_ENGINEERING.md`.

## Principles & constraints
- **HA best practices:** fully `async` (no blocking I/O in the event loop), `DataUpdateCoordinator`,
  config flow + reauth, `ConfigEntry.runtime_data`, typed, `unique_id`/`device_info`, availability,
  graceful reconnect. Target HA **2026.1+**.
- **No heavy deps:** stdlib + `cryptography` (bundled in HA) for AES; `aiohttp` (HA) for cloud.
  Local transport via `asyncio` streams (not blocking sockets).
- **Runtime = 100% local.** Cloud touched only at setup and on `authKey` re-fetch.
- **Decided UX:** store email+password in the config entry (HA `.storage`, local) for silent
  `authKey` recovery; auto-discover IP via UDP 6606 (manual fallback); push updates from `cmd20`.
- **Secrets** stay out of the repo; real creds only live in the user's HA instance.

## Verification strategy
- **Offline:** unit-test `protocol.py` (frame/stuffing/TTLV/AES/handshake-token) against the captured
  reference vectors in `REVERSE_ENGINEERING.md` (known plaintext/ciphertext, p4 token, authKey).
- **On-device:** run a small harness on the Pi (same LAN as station `10.42.0.149`) to confirm live
  read and **one write** (toggle an output) before wiring HA controls.
- **HA static checks:** `hassfest`/`ruff` + manifest validation locally; full runtime load tested by
  the user in their HA (we don't have their instance).

---

## Milestones & steps

Status legend: ⬜ TODO · 🟦 IN PROGRESS · ✅ DONE · ⏭️ DEFERRED

### M0 — Scaffolding
- ✅ M0.1 Create `custom_components/oukitel_power_station/` + `manifest.json` (iot_class=local_push, integration_type=device, v0.1.0)
- ✅ M0.2 `const.py` — domain, ports, cmd codes, regions, read-list, enum maps, config keys
- ✅ M0.3 Repo plumbing: `hacs.json`, `.gitignore` (apk/pcaps/secrets/tsl), `README.md` stub

### M1 — Core protocol library (standalone, no HA imports)
- ✅ M1.1 `protocol.py`: frame build + streaming `FrameAssembler` (checksum), `stuff`/`_Destuffer`
- ✅ M1.2 `protocol.py`: TTLV `ttlv_encode`/`ttlv_decode` (bool/number fixed-point/binary/struct, recursive)
- ✅ M1.3 `protocol.py`: AES-128-CBC (cryptography), `login_token` (SHA256), `auth_key_to_key`
- ✅ M1.4 `protocol.py`: async `OukitelConnection` — connect+handshake, subscribe_and_read, async_set,
  listen (push reports), ping, close
- ✅ M1.5 `tests/test_protocol.py` — 19 checks vs captured vectors all PASS (p4 token matches capture,
  AES→known TTLV, stuff/frame/TTLV round-trips, split-read, cmd17 payload == captured)

### M2 — Cloud client (async)
- ✅ M2.1 `cloud.py`: `build_login_fields` + async `OukitelCloud.login` (random/MD5-key/AES-pwd/SHA256-sig); session injected (no aiohttp import; TYPE_CHECKING only)
- ✅ M2.2 `cloud.py`: `get_devices` (userDeviceList → incl. authKey), `get_tsl` (productTSL), region map (EU/US/CN)
- ✅ M2.3 `tests/test_cloud.py` — 8/8 pass; key/iv match real login-log ground truth, encpwd+signature reproduced

### M3 — On-device write verification (Pi harness)
- ✅ M3.1 Live read via the new `protocol.py` `OukitelConnection` on the Pi — handshake OK, full named
  snapshot (battery 97%, AC/USB off, DC on, limit 73%, 50Hz, inv 106, bms 215)
- ✅ M3.2 Live **write** confirmed: `cmd19 (tag44=true)`→`(false)` toggled USB output; device echoed
  `cmd20 (44=True)`→`(False)`. Bidirectional control proven; device restored to original state.
- ✅ M3.3 Confirmed write frames documented in `REVERSE_ENGINEERING.md`

### M4 — HA integration glue
- ✅ M4.1 `__init__.py`: `async_setup_entry`/`async_unload_entry`, `runtime_data`, `type OukitelConfigEntry`, platform forwarding, reload listener
- ✅ M4.2 `discovery.py`: async UDP 6606 broadcast (DatagramProtocol) + parse reply, match by MAC → IP.
  **Live-verified** (probe p0=28720): auto-found station at 192.168.60.54 when on the same subnet.
- ✅ M4.3 `coordinator.py`: `DataUpdateCoordinator`, persistent conn, push via `async_set_updated_data`, listen task + reconnect, authKey re-fetch → reauth, IP rediscovery
- ✅ M4.4 `config_flow.py`: cloud-login → pick device → UDP discover/manual IP → validate (real handshake); + reauth
- ✅ M4.5 Entities: `entity.py` base + `sensor.py` (10), `switch.py` (AC/USB/DC), `select.py` (voltage/freq), `number.py` (charge limit)
- ✅ M4.6 `strings.json` + `translations/en.json` (flow text + entity names)
- (note) per-port struct sensors (tags 6/7/8/9) deferred — names known, sub-field indices to confirm live

### M5 — Quality & polish
- ✅ M5.1 `diagnostics.py` (redacts password/email/authKey/host); device_info+connections, unique_ids, tag-availability, entity_category (CONFIG/DIAGNOSTIC)
- ✅ M5.2 Error handling: auth → `ConfigEntryAuthFailed` (reauth); connection loss → `UpdateFailed`/unavailable + reconnect; cloud errors mapped; first refresh → `ConfigEntryNotReady`
- ✅ M5.3 `ruff check` clean; compiles under Python 3.13.9; manifest/strings/translation/entity-key parity validation PASS
- ✅ M5.4 `README.md` (HACS install, flow, entities, troubleshooting) + `hacs.json`

### M6 — Handoff
- ✅ M6.1 Final review vs HA quality checklist (below); handoff notes written
- ⬜ M6.2 (User) install in HA, run config flow, verify entities; iterate on feedback

### M7 — Dev tooling & CI (added on request)
- ✅ M7.1 `pyproject.toml` (ruff lint+format config, pytest config), `requirements-dev.txt`, `.venv`
- ✅ M7.2 ruff lint + format clean; pytest discovers tests (`test_offline`), 2 passed
- ✅ M7.3 GitHub Actions: `.github/workflows/ci.yml` (ruff check + format + pytest, Py3.13) and
  `validate.yml` (hassfest + HACS, ignore brands)
- ✅ M7.4 Live re-validation on the user's real network from the Mac: connection+read OK with
  **fresh authKey** (authKey had rotated on re-provision → confirms re-fetch path); discovery probe
  cmd fixed to **p0 (28720)**, now byte-identical to capture

---

## Risks / open items
- ~~Writes not yet sent live~~ ✅ verified (M3.2): USB toggle worked, device echoed state.
- `authKey` rotation — CONFIRMED it rotates on re-provision (WiFi change). Re-fetch path covers it; verified live.
- UDP discovery is broadcast-based → only works when HA is on the **same subnet/VLAN** as the station;
  cross-VLAN setups use the manual-IP step (unicast connection routes fine across VLANs).
- Multiple simultaneous local connections (app + HA) — observed OK; watch for device connection cap.
- Per-port struct sub-field exact indices — names known from TSL; confirm order live when outputs ON.

## Handoff / quality checklist (M6.1)
Integration in `custom_components/oukitel_power_station/` (13 modules, ~1.4k LOC). Verified locally: `ruff` clean,
compiles under Python 3.13.9, offline tests pass, protocol verified live on the real device (reads).
- ✅ async throughout · DataUpdateCoordinator (push) · `runtime_data` · typed · `local_push`
- ✅ config flow + reauth · unique_id (dk) · device_info (+mac connection) · availability · entity categories
- ✅ diagnostics with secret redaction · translations · HACS metadata
- ⚠️ **User must verify in their HA** (we don't have their instance): install via HACS, run config flow,
  confirm entities populate and switches actuate.
- ✅ **Live write confirmed (M3.2)** — `cmd19` USB toggle worked on the real device; switch entities trustworthy.
- ⏭️ Future: per-port struct sensors (tags 6/7/8/9), options flow, more translations, GitHub repo + CI hassfest.

## Progress log
- 2026-06-16: Plan created. Starting M0.
- 2026-06-16: M0 ✅ — manifest.json (local_push, device, v0.1.0), const.py (commands/regions/read-list/enums/config keys), hacs.json, .gitignore, README stub. JSON + const validated.
- 2026-06-16: M1 ✅ — protocol.py (frames/stuffing/TTLV/AES/login_token + async OukitelConnection). tests/test_protocol.py: 19/19 checks pass against captured vectors (cryptography 46.0.5 available locally).
- 2026-06-16: M2 ✅ — cloud.py (login/get_devices/get_tsl, regions, session-injected). tests/test_cloud.py: 8/8 pass; derived key/iv match real login-log ground truth.
- 2026-06-16: M3.1 ✅ — new async OukitelConnection verified live on Pi (cryptography 46.0.5): handshake + full decoded snapshot. M3.2/M3.3 blocked on user OK (live output toggle).
- 2026-06-16: M4 ✅ — full integration glue (__init__, discovery, coordinator, config_flow, entity base, sensor/switch/select/number, strings+translations). All modules compile under Python 3.13.9; offline tests still green. Per-port struct sensors deferred.
- 2026-06-16: M5 ✅ — diagnostics (redacted), error handling, README + hacs.json. ruff clean, compile OK, validation PASS (manifest/strings/keys/steps). Fixed 3 ruff findings.
- 2026-06-16: M6.1 ✅ — final review + handoff checklist. Integration complete (13 modules).
- 2026-06-16: M3.2/M3.3 ✅ — live WRITE confirmed on real device (USB toggle on→off via cmd19, device echoed cmd20). Bidirectional control proven, documented. Only M6.2 (user install in HA) remains.
- 2026-06-17: M7 ✅ — dev tooling (pyproject ruff+pytest, requirements-dev, .venv) + GitHub Actions (ci: ruff+pytest; validate: hassfest+HACS). Live re-validation on user's real LAN: read OK with fresh authKey (authKey rotated on WiFi re-provision → confirms re-fetch). Fixed discovery probe to p0 (28720) — now byte-identical to capture. Discovery is same-subnet only (broadcast); user is on a different VLAN so will switch VLANs to live-test discovery.
- 2026-06-17: Discovery ✅ LIVE-VERIFIED — user moved to the station's VLAN (Mac 192.168.60.159); `async_discover` returned 192.168.60.54 by MAC. Full stack (discover→handshake→read→write→authKey re-fetch) now validated on real hardware/network.
