# Oukitel P2001E Plus — Protocol Reverse Engineering

Complete reference for the local (LAN) and cloud protocol used by the **Oukitel P2001E Plus**
(2048Wh / 2400W) portable power station and the **WonderFree** iOS/Android app, for the purpose
of building a **Home Assistant** integration.

> TL;DR — The app controls the station **directly over the LAN in plaintext-framed, AES-encrypted
> TTLV** (no cloud needed for control). The firmware is **Quectel / Acceleronix** (NOT Tuya).
> The only cloud-provisioned secret needed for local control is the per-device **`authKey`**.

---

## 0. STATUS — reverse engineering COMPLETE ✅

The protocol is fully decoded, **verified end-to-end against the real device**, and we have a working
local client that reads live decrypted telemetry. Remaining work is only the Home Assistant integration
(packaging the proven logic). Sections 7, 11b, 11d are the authoritative results; sections 10/11/11c are
historical "open task" notes that have since been resolved.

### Secrets & identifiers (this device / account)
| item | value |
|---|---|
| cloud account | EU region · uid `REDACTED_UID`, family `fid=REDACTED_FID` (email/password NOT stored here — pass via args or `QUECTEL_EMAIL`/`QUECTEL_PASSWORD` env vars) |
| productKey (pk) | `p11wN7` |
| deviceKey (dk) = MAC | `aabbccddeeff` |
| **authKey** (local AES secret, base64) | **ROTATES on re-provision** — fetch fresh via `userDeviceList`. (seen: `REDACTED_AUTHKEY`, then after WiFi change `REDACTED_AUTHKEY`) |
| bindingCode | `REDACTED_BINDINGCODE` |
| station LAN IP (on lab hotspot) | `10.42.0.149` (TCP 6607) |
| cloud base (EU) | `https://iot-api.quecteleu.com` ; appSecret `3aRNUwWahjyANa7WfBK2wCCkxCexB6nXxKJwXxfePvzf` ; userDomain `E.SP.4294967410` |

> `authKey` is per-device and may rotate if the cloud regenerates it; if local login fails, re-fetch via `userDeviceList`.

### Tools (in `tools/`)
| file | purpose | run |
|---|---|---|
| `quectel_cloud.py` | cloud login → fetch token, device list (incl. `authKey`), and TSL | `python3 tools/quectel_cloud.py [email] [password]` (has internet) |
| `oukitel_local.py` | local client: discover→handshake→AES→read live telemetry | run **on the Pi** (same LAN as station): `python3 -u tools/oukitel_local.py [station_ip]` |
| `tsl_p11wN7.json` | authoritative product thing-model (tag→name/unit/enum) | reference data |

### Lab access
Kali Pi 5: `ssh oukitel-kali` (alias → `kali@10.60.20.89`, key auth, passwordless sudo).
Hotspot `oukitel-lab` / `oukitel12345` (2.4GHz). Station + phone join it; capture on `wlan0`.
The Mac cannot reach the station directly (behind the Pi's NAT) — run `oukitel_local.py` on the Pi.
The decompiled APK is in `apk/jadx/sources/` (jadx). Full APK in `~/Downloads/Wonderfree_V3.6.0_APKPure.xapk`.

---

## 1. Device / platform identity

| Item | Value |
|---|---|
| Product | Oukitel P2001E Plus, 2048Wh, 2400W, WiFi + Bluetooth ("APP BT") |
| App | **WonderFree** — Android package `com.quectel.commonappeu` (APKPure v3.6.0), dev **Quectel / Acceleronix B.V.** |
| Platform | Quectel IoT / Acceleronix cloud (a generic multi-vendor IoT framework) |
| Station model id (discovery) | `p1` |
| Station device id (discovery) | `p11wN7` |
| Station MAC = `deviceKey` (dk) | `aa:bb:cc:dd:ee:ff` → string `aabbccddeeff` |
| **Not** Tuya | LocalTuya / HA Tuya integrations do **not** apply |

The station maintains a persistent cloud link to **`18.199.117.67:8886`** (AWS eu-central-1) for
remote access; this is not required for local control.

---

## 2. Lab / capture setup (Kali Raspberry Pi 5)

- SSH: `ssh oukitel-kali` (alias in `~/.ssh/config` → `kali@10.60.20.89`, key auth, passwordless sudo).
  `eth0` = wired uplink/internet; `wlan0` = onboard Broadcom (`brcmfmac`), supports AP mode + 2.4GHz.
- **Hotspot** (NetworkManager): SSID `oukitel-lab` / pass `oukitel12345`, 2.4GHz ch6,
  `ipv4.method shared` (auto NAT + dnsmasq DHCP `10.42.0.0/24`, gw `10.42.0.1`).
  Bring up: `sudo nmcli connection up oukitel-lab`.
- **Gotcha that broke client internet:** NM `shared` only set `wlan0` forwarding; global
  `net.ipv4.ip_forward` stayed `0` → SYNs out, no replies. Fix (persisted in
  `/etc/sysctl.d/99-oukitel-forward.conf`): `net.ipv4.ip_forward=1`.
- Observed clients: iPhone `10.42.0.25`, **power station `10.42.0.149`** (MAC `aa:bb:cc:dd:ee:ff`).
- **Capture:** rotating `tcpdump` on `wlan0` → `/home/kali/oukitel/oukitel-*.pcap` (`-G 3600`).
  Analyze with `tshark` (e.g. `tshark -r f.pcap -q -z follow,tcp,hex,<stream>`).

### Useful tshark recipes
```bash
# find the control stream
tshark -r f.pcap -Y 'tcp.port==6607' -T fields -e tcp.stream | sort -un
# full reassembled control stream as hex
tshark -r f.pcap -q -z follow,tcp,hex,<stream>
# raw payloads per direction
tshark -r f.pcap -Y 'tcp.port==6607 && tcp.len>0 && ip.dst==10.42.0.149' -T fields -e tcp.payload
```

---

## 3. Network ports

| Port | Proto | Purpose |
|---|---|---|
| **6606** | UDP | Device **discovery** (phone broadcasts to `<subnet>.255:6606`, station replies) |
| **6607** | TCP | **Control + telemetry** channel (the important one) |
| 8886 | TCP | Station → cloud (AWS eu-central-1) persistent link (remote access; not needed locally) |

---

## 4. Wire frame format (UDP 6606 and TCP 6607)

All application frames:

```
+------+------+--------------+-----------+-------------+-------------+----------------------+
| 0xAA | 0xAA | len (2, BE)  | checksum  | packetID    | cmd (2, BE) | payload (TTLV)       |
|      |      |              | (1 byte)  | (2, BE)     |             | often AES-encrypted  |
+------+------+--------------+-----------+-------------+-------------+----------------------+
  [0]    [1]    [2][3]          [4]        [5][6]        [7][8]        [9..]
```

- **Magic** `AA AA` marks frame start.
- **len** = number of bytes *after* the length field = `checksum(1) + packetID(2) + cmd(2) + payload`.
  Total frame size = `len + 4`.
- **checksum** (byte [4]) = `(sum of all bytes from [5] to end) & 0xFF` (simple additive sum, not CRC).
- **packetID** = request/response correlation id; client increments, clamped to `[1000, 65534]`
  (`WpKjg24qrN()`); device echoes the id in its reply.
- **cmd** = 16-bit command (see §6).
- **payload** = TTLV (§5), AES-encrypted once the session is established (§7).

### Byte-stuffing (escaping)
Because `AA AA` is the frame delimiter, any `AA` inside the framed bytes is escaped:
- **Encode** (`C2622ls.UnlbNoQFG1`): scan bytes from index 2 to end; if `AA 55` or `AA AA`
  occurs, insert a `55` after the `AA`.
- **Decode** (`DecodeTools.xBGCKRAPVV`): remove a `55` that immediately follows an `AA`.

Apply de-stuffing on receive before parsing length/payload; apply stuffing last on send.

---

## 5. TTLV payload encoding (inner format, after decryption)

Quectel "TTLV". Sequence of fields; each field starts with a 2-byte big-endian header `h`:

```
tag  = (h >> 3) & 0x1FFF      // 13-bit field id
type =  h       & 0x07        // 3-bit type
```

| type | meaning | value encoding |
|---|---|---|
| 0 | boolean **false** | (no value bytes) |
| 1 | boolean **true** | (no value bytes) |
| 2 | **number** (int or fixed-point) | 1 control byte then N value bytes (see below) |
| 3 | **binary / string** | 2-byte BE length, then that many bytes |
| 4 | **struct** (nested) | 2-byte BE element count, then that many nested fields |
| 5 | binary / string | same as type 3 |

**Number (type 2) control byte `c`:**
- `sign  = (c >> 7) & 1`   → 1 means negative
- `decimals = (c >> 3) & 0x0F`  → number of decimal places
- `nbytes = (c & 0x07) + 1`  → value length in bytes
- value = big-endian unsigned integer over `nbytes`; if `sign` → negate; if `decimals>0` →
  `value / 10^decimals` (a Double). So values are fixed-point.

(Encoder mirrors this: `C2622ls.bpXzhSQ74T` for doubles, `C2622ls.mvVcFZrCKP` for longs,
`C2622ls.MPq84ED5BO` for binary, `C2622ls.qtocU84Oav` for structs.)

---

## 6. Command codes (`cmd`)

`cmd` values are often the ASCII of `"pN"`. `"p1"` = `0x7031` = `28721`, etc.

| cmd (dec) | cmd (hex / ascii) | meaning |
|---|---|---|
| 28720 | `0x7030` `p0` | discovery **probe** (app→broadcast, UDP 6606) — frame `aaaa0005<chk><pid>7030` |
| 28721 | `0x7031` `p1` | discovery **reply** (station→app, UDP 6606), TTLV with model/id/mac/ip |
| 28722 | `0x7032` `p2` | handshake: client hello |
| 28723 | `0x7033` `p3` | handshake: device → sends **random nonce** |
| 28724 | `0x7034` `p4` | handshake: client → **login token** (SHA256, see §7) |
| 28725 | `0x7035` `p5` | handshake: login **result** (number; 0 = success) |
| 28726 | `0x7036` `p6` | TLS/encrypted write response (`CMD_TLS_WRITE_RES`) |
| 28727 | `0x7037` `p7` | ping (keepalive) |
| 28728 | `0x7038` `p8` | pong |
| 28729 | `0x7039` `p9` | heartbeat config (payload: tag1=interval=30s, tag2=1) |
| 0x14 (20) | — | telemetry / property **report** (encrypted TTLV) |
| 35 | — | transparent passthrough message |
| 50 | — | device status reply |
| 28754 / 28755 / 28756 | — | device WiFi list report / response |
| 28758 | — | device WiFi switch reply |
| 28771 | — | (channel/property event) |

---

## 7. Encryption & key derivation  ← the core result

**Algorithm:** `AES/CBC/PKCS5Padding` (Java `jf3`: `MPq84ED5BO`=encrypt, `T2wg3R9zLj`=decrypt).

```
key = Base64.decode(authKey)         // per-device secret (base64 string) from the cloud
IV  = random.getBytes()              // the 16-ASCII-char nonce the device sends in p3
```

Only the **TTLV payload** (frame bytes `[9..]`) is encrypted — the `AA AA / len / checksum /
packetID / cmd` header stays in clear. Encryption is enabled only **after** a successful handshake.

### Handshake sequence (TCP 6607)
1. **P→S `p2` (28722):** client hello (no payload).
2. **S→P `p3` (28723):** device returns a **`random`** nonce — a 16-char ASCII string,
   e.g. `REDACTED_NONCE`. (Extracted by `VQRg3VG69F.T2wg3R9zLj`; stored on the device model.)
3. **P→S `p4` (28724):** login token, TTLV `tag=2,type=3 (binary)` =
   ```
   SHA256_hex( duHex( Base64.decode(authKey) ) + ";" + random )
   ```
   where `duHex(x)` = lowercase hex string of bytes `x` (`du3.T2wg3R9zLj`), `SHA256_hex` = `ox4.MPq84ED5BO`.
   (Builder: `wTqglxV5Bh.T2wg3R9zLj(authKey, random)`. Shared-device variant
   `wTqglxV5Bh.MPq84ED5BO(authKey, random, shareCode, permCode)` adds tag5=shareCode(last 16 bytes), tag6=permCode.)
4. **S→P `p5` (28725):** result number; `0` = login success, `2` = already-logged-in path, else fail.
5. On success → `y84.xBGCKRAPVV(channelId, authKey, random)` sets:
   - encoder: key=`Base64.decode(authKey)`, iv=`random`, encryption on
   - decoder: key=`Base64.decode(authKey)`, iv=`random`, decryption on
   Then sends heartbeat (`p9`/28729). Telemetry `cmd 0x14` frames start streaming, encrypted.

### `authKey` — the per-device secret
- Base64 string, fetched from the cloud per device:
  ```
  POST https://iot-api.quecteleu.com/enduserapi/regenerateAuthKey
  body: { "pk": <productKey>, "dk": <deviceKey = aabbccddeeff> }
  resp: { "authKey": "<base64>" }      // model AuthKeyRes
  ```
- Resolution order for the local-login secret (`QuecBaseChannelManager` getLoginPwd):
  `bindingCode` (BLE-only devices) → **`authKey`** → `bindingkey` fallback.
- Region base URLs (`ag0`): EU `https://iot-api.quecteleu.com`, US `https://iot-api.quectelus.com`,
  CN `https://iot-gateway.quectel.com`. WS south: `wss://iot-south.quecteleu.com:8443/ws/v2`.
- ⚠️ The endpoint is `regenerate` — calling it may rotate the key (cloud pushes new key to device).
  Prefer to capture the value the app already uses, or check for a non-regenerating `getAuthKey`.

---

## 8. Decompiled class map (jadx)

APK: `~/Downloads/Wonderfree_V3.6.0_APKPure.xapk`. Decompiled to
`<project>/apk/jadx/sources/` via `jadx --no-res --deobf`.
App is **React Native** (`libreactnative.so`, `libhermes.so`); JS bundle is **not** embedded
(CodePush at runtime) — but the **local protocol is native Java**, fully present in the dex.

| Concern | Class (obfuscated) |
|---|---|
| TTLV **decoder** | `com.quectel.basic.common.utils.ttlv.DecodeTools` |
| TTLV **encoder** / frame builder | `com.quectel.commonappeu.C2622ls` (`ls`) |
| TTLV models | `com.quectel.basic.common.utils.ttlv.model.*` (`TTLVData`, `QuecTtlvCommandModel`, …) |
| AES helper (CBC/PKCS5) | `com.quectel.commonappeu.jf3` |
| SHA-256 → hex | `com.quectel.commonappeu.ox4` |
| bytes → hex (`duHex`) | `com.quectel.commonappeu.du3` |
| UDP discovery (6606) | `com.quectel.commonappeu.n94` (`QuecUdpSocketManager`) |
| TCP socket mgr (6607) | `com.quectel.commonappeu.y84` (`QuecTcpSocketManager`); `xBGCKRAPVV()` sets AES key/iv |
| socket wrapper | `com.quectel.commonappeu.y06` |
| WiFi channel orchestrator | `com.quectel.sdk.iot.channel.kit.chanel.ln7axHPKWH` (`QuecWifiChannelManager`) |
| BLE channel (same handshake/crypto interface) | `com.quectel.commonappeu.ak3`; `setEncryptInfo(key, iv)` = `sgQdYO6Nbu` |
| p4 login-token builder | `com.quectel.commonappeu.wTqglxV5Bh` |
| cloud base URLs | `com.quectel.commonappeu.ag0` |
| device model (fields: authKey, bindingkey, random, pk, dk, …) | `com.quectel.basic.common.entity.QuecDeviceModel` |
| authKey cloud fetch | `QuecBaseChannelManager.MPq84ED5BO()` → `…/enduserapi/regenerateAuthKey` |

> Obfuscation reuses short method names across unrelated classes — grep for **string constants**
> (ports, cmd numbers like `28724`, URLs, `"AES/CBC/PKCS5Padding"`) rather than method names.

---

## 9. Captured reference data (one real session, pcap stream 724)

Station `10.42.0.149` ↔ phone `10.42.0.25`. Useful for offline verification.

```
# discovery reply (UDP 6606, station→phone), de-framed TLV advertises:
#   model "p1", id "p11wN7", MAC "aabbccddeeff", ip "10.42.0.149"

# handshake (TCP 6607)
P→S  aaaa 0005 a4 0002 7032                                  # p2 hello (no payload)
S→P  aaaa 0019 38 0002 7033 000b 0010 <"REDACTED_NONCE">   # p3 random nonce (16 ascii)
P→S  aaaa 0049 fd 0003 7034 0013 0040 <64 hex chars below>   # p4 login token
        token = "REDACTED_TOKEN"
S→P  aaaa 0009 c2 0003 7035 001a 0000                        # p5 result = number 0 (success)

# encrypted telemetry (cmd 0x14), 16-byte AES-CBC blocks (payload after the 9-byte header):
S→P  aaaa 0015 d2 0000 0014  REDACTED_CT
S→P  aaaa 0015 b3 0000 0014  REDACTED_CT
S→P  aaaa 0015 a4 0000 0014  REDACTED_CT
S→P  aaaa 0015 b4 0005 7036  REDACTED_CT   # p6 (repeats identically)
```

**Verification once `authKey` is known:**
1. `SHA256_hex( hex(base64decode(authKey)) + ";REDACTED_NONCE" )` must equal the p4 token above.
2. `AES-128-CBC` decrypt any telemetry block with `key=base64decode(authKey)`,
   `iv="REDACTED_NONCE"` (ASCII) → must yield valid TTLV + valid PKCS5 padding.

Brute-force note: the AES key/IV are **NOT** derivable from local traffic alone (key = the
cloud secret; tested simple derivations from MAC/deviceId/p4-string against ciphertext — none
matched). `authKey` must be obtained from the cloud or the app.

---

## 10. How to get `authKey` (open task)

Need this device's `authKey` once. Options:
1. **MITM the app's HTTPS** on the `oukitel-lab` hotspot with `mitmproxy` (already on the Pi) +
   install mitmproxy CA on the iPhone. Capture the `regenerateAuthKey` response and the login API.
   Risk: certificate pinning (RN apps often don't pin; adapt if they do).
2. **Replicate the cloud login** to `iot-api.quecteleu.com/enduserapi/...` with the WonderFree
   account credentials, then call `regenerateAuthKey` (`{pk, dk}`).
3. Extract from app local storage (`libmmkv.so` / AsyncStorage) — hard on non-jailbroken iOS.

---

## 11. Plan to finish the protocol → Home Assistant

1. Obtain `authKey` (§10) and **verify** the chain (§9).
2. **Decrypt telemetry** and **map TTLV tags → properties**: toggle each function in the app
   (AC output on/off, DC, USB, display, etc.) and watch the live battery %, then diff the decrypted
   TTLV to learn which `tag` = which property and the command frame to set it. Build a tag dictionary
   (battery SOC %, input/output watts, switch states, temperatures, time-to-empty, …).
   (Acceleronix calls these "data points"/dpId; cloud TSL/thing-model JSON may also enumerate them —
   reachable via the cloud API once logged in.)
3. **HA integration** design (local push/poll):
   - One-time: cloud login → fetch `authKey` for each `pk_dk`.
   - Runtime (all local): UDP 6606 discover → TCP 6607 connect → p2/p3/p4/p5 handshake
     (compute p4 from `authKey`+`random`) → enable AES (`key=decode(authKey)`, `iv=random`) →
     read `cmd 0x14` reports, send command frames; keepalive `p7`/heartbeat `p9`.
   - Reusable Python: frame build/parse (with stuffing + checksum), TTLV encode/decode,
     AES-CBC, SHA256 token. Port the logic in §4–§7 directly.

---

## 11b. ✅ VERIFIED — cloud login + authKey + decryption all working

The full chain is proven end-to-end (see `tools/quectel_cloud.py`).

**Cloud login (EU)** — no signing beyond a per-request signature; `Authorization: <token>` after login:
- `POST https://iot-api.quecteleu.com/v2/enduser/enduserapi/emailPwdLogin` (form-encoded)
  - `random` = 16 random alphanumerics; `key = MD5(random).hexUPPER()[8:24]`; `iv = key[8:16]+key[0:8]`
  - `pwd  = Base64.DEFAULT( AES-128-CBC/PKCS5( password, key, iv ) )` (trailing `\n`)
  - `signature = SHA256hex( email + pwd + random + APP_SECRET )`
  - `userDomain = "E.SP.4294967410"`, `APP_SECRET = "3aRNUwWahjyANa7WfBK2wCCkxCexB6nXxKJwXxfePvzf"`
  - headers: `app-info`, `X-Q-Language: en`, `quec-random-url: <uuid>`
  - resp: `data.accessToken.token` = `Bearer <JWT>`
- `GET https://iot-api.quecteleu.com/v2/binding/enduserapi/userDeviceList?pageNumber=1&pageSize=50`
  (Authorization header) → `data.list[]`, **which already includes `authKey`** (no need to call
  `regenerateAuthKey`). Fields: `productKey`, `deviceKey`, `authKey`, `bindingCode`, `deviceName`, …

**This device (uid `REDACTED_UID`, family `fid=REDACTED_FID`):**
| field | value |
|---|---|
| productKey (pk) | `p11wN7` |
| deviceKey (dk) | `aabbccddeeff` |
| **authKey** | `REDACTED_AUTHKEY` → AES key bytes `REDACTED_AES_KEY_HEX` |
| bindingCode | `REDACTED_BINDINGCODE` |
| productName | `P2001-PLUS-TT` ; deviceName `P2001-PLUS-TT_xxxx` |

**Verification results** (capture nonce `REDACTED_NONCE`):
- `SHA256( "REDACTED_AES_KEY_HEX" + ";REDACTED_NONCE" )`
  = `REDACTED_TOKEN` == captured p4 token ✓ (hex is **lowercase**)
- AES-128-CBC decrypt (key=authKey bytes, iv=`REDACTED_NONCE` ASCII), captured telemetry →
  `00 0a 00 00` = TTLV(tag1, number 0); `01 60` = TTLV(tag44, bool false); `01 58` = TTLV(tag43, bool false). Valid PKCS5. ✓

> ⚠️ `authKey` may rotate if the app/cloud regenerates it; if local login starts failing, re-fetch via `userDeviceList`.

## 11c. Next: name the TTLV tags (data-point model)
Each property is a TTLV `tag` (= Acceleronix dpId). To get human names/types/scales, fetch the product
**thing model (TSL)** from the cloud after login (look for endpoints like `productTsl` / `getProductTSL` /
`tslProfile` under `/v2/...`; grep `fw0`/`dw0` for "Tsl"/"tsl"/"thingModel"). Otherwise derive empirically:
decrypt a live session while toggling AC/DC/USB/display in the app and diff which `tag` changes.

## 11d. ✅ Control protocol + property map (VERIFIED with working local client)

Working local client: `tools/oukitel_local.py` (run on a host on the same LAN as the station;
connects to `10.42.0.149:6607`). It discovers → handshakes (p2/p3/p4/p5) with `authKey` →
enables AES → reads & decrypts all properties live. **Proven end-to-end** against the real device.

**Control commands (all use AES-encrypted TTLV payloads after handshake):**
| cmd | dir | meaning | payload |
|---|---|---|---|
| **17** (0x11) | app→dev | **read** properties | list of 2-byte tag IDs (NOT TTLV) — e.g. `0002 0008 0009 0006 001f …` |
| **19** (0x13) | app→dev | **write** property | TTLV `(tag, value)` — e.g. `0322 00 03` = (tag100, num 3); `(43,bool true)` = AC on |
| **20** (0x14) | dev→app | property **report** (telemetry) | TTLV; pushed on change and in response to cmd17 |
| **28726** (p6) | dev→app | write **ack** | TTLV `(1, 0)` |
| **28729** (p9) | app→dev | heartbeat/subscribe interval | TTLV `(1,num 30)(2,num 1)` |

Post-login the app sends: `cmd19 (tag100=3)` (subscribe) + `cmd17` (read all) + `cmd28729` (HB);
device then streams `cmd20` reports.

**Keepalive (issue #7):** the device sends `p7`/28727 (ping) on its own and expects `p8`/28728
(pong, empty payload) back. Ignoring the ping makes the station tear the TCP session down after a
few seconds, so the client must answer every ping from its read loop. The subscribe+read+heartbeat
triple must also be re-asserted well inside the advertised 30s heartbeat window — 20s was still too
slow on some units; 12s is stable. To set a switch: `cmd19` with `(tag, bool)` → device acks `p6`
+ reports new value via `cmd20`.

**✅ WRITE VERIFIED LIVE (M3.2):** sent `cmd19 (tag44=true)` then `(tag44=false)` to the real device
via the new `protocol.py`; the station accepted each write and echoed `cmd20 (44=True)` then
`(44=False)` — USB output toggled on and back off. Bidirectional local control confirmed.
Write frame: `cmd19` payload = encrypted TTLV; bool true header `(tag<<3)|1`, false `(tag<<3)|0`;
number header `(tag<<3)|2` + value. Switch tags: 43=AC, 44=USB, 46=DC.

**Read-list tag IDs (from capture):** `2,8,9,6,31,7,28,27,14,12,11,5,4,3,1,34,20,100,43,44,46`.

**Property map — AUTHORITATIVE, from cloud thing-model (TSL).**
Fetched via `GET https://iot-api.quecteleu.com/v2/binding/enduserapi/productTSL?pk=p11wN7`
(Authorization header) → saved `tools/tsl_p11wN7.json` (tslVersion 1.2.0). tag `id` = dpId.

| tag | code | name | type | unit / enum |
|---|---|---|---|---|
| **1** | battery_percentage | Battery Capacity | INT | % (0–100) |
| **2** | remain_time | Remaining (discharge) Time | INT | min |
| **3** | remain_charging_time | Remaining Charging Time | INT | min |
| **4** | total_input_power | Total Input Power | INT | W |
| **5** | total_output_power | Total Output Power | INT | W |
| **11** | ac_input | AC Charging Input Power | INT | W |
| **12** | dc_input | DC Charging Input Power | INT | W |
| **14** | temp | Device Temperature | INT | ℃ (-100..100) |
| **20** | ac_charging_limit | AC Upper Limit Charging Power | INT | % (3–100) |
| **27** | Frequency_Switchover | Output Frequency Setting | ENUM | 0=50Hz, 1=60Hz |
| **28** | ACvoltage_Switchover | Output Voltage Setting | ENUM | 100/110/120/220/230/240 V |
| **31** | AC_Version | Inverter Version | INT | |
| **34** | BMS_Version | BMS Version | INT | |
| **43** | ac_switch | AC Switch | BOOL | true=On/false=Off |
| **44** | usb_switch | USB Switch | BOOL | true=On/false=Off |
| **46** | dc_switch | DC Switch | BOOL | true=On/false=Off |
| **100** | high_frequency_reporting | high-freq reporting mode | ENUM | 0=off,1=LAN,2=WiFi,**3=LAN+WiFi** (subscribe) |
| **6** | ac_data | AC Info | STRUCT | sub: AC switch, AC1 output power(W), AC1 output voltage(V) |
| **7** | usb_data | USB Info | STRUCT | sub: USB switch, USBA1 power(W), USB_QC2 |
| **8** | typec_data | TypeC Info | STRUCT | sub: typec1..typec4 output power(W) |
| **9** | dc_data | DC Info | STRUCT | sub: DC switch, CAR1 power(W)/voltage(V)/current(A) |

Note on the input-power tags (issue #12): tags 11/12 are the **charging** share only, not the total
draw from the source. Tag 4 (`total_input_power`) is everything coming in, so charging from AC with a
load on the AC output gives `tag4 = tag11 + AC output power` (reported: 570 = 500 + 70).

Notes: ENUM `27/28` are sent/received as the enum *key* (e.g. `28`→`230` means 230V; `27`→`0` means 50Hz).
The fetch generalizes: `productTSL?pk=<pk>` returns the dictionary for any Quectel product.
ENUM values for switches are booleans; struct sub-fields are nested TTLV (decode recursively).

## 12. Open questions / risks
- Does `regenerateAuthKey` rotate the device's key (breaking the app)? Find a read-only variant if so.
- Exact TTLV tag dictionary for the P2001E (the data-point map) — to be derived in step 11.2.
- Cloud login/auth signing scheme (needed for a self-contained HA integration without MITM).
- Bluetooth (BLE) path uses the **same** TTLV + AES handshake (`ak3`) if a WiFi-less fallback is wanted.

## 13. Temperature & output voltage are CLOUD-ONLY (verified 2026-06-16)
Tags **14 (temp)** and **28 (ACvoltage_Switchover)** are **never delivered over the LAN** on this
firmware (FCM100D, comProto 3.0.0). Verified live: full `cmd17` read, focused read of `[14,28]`,
single-tag read of `[14]`, a 150s passive watch, a 10-minute watch (619 frames), and AC-output-on for
20s — none ever produced tag 14 or 28. The app's own captured read list requests them too, so the app
also can't get them locally; it reads them from the **cloud**.

**Cloud current-values endpoint** (used by the app's device panel):
`GET {base}/v2/binding/enduserapi/getDeviceBusinessAttributes?pk=..&dk=..` (Bearer token) →
`data.customizeTslInfo[]` with `{abId (== tag id), resourceCode, dataType, resourceValce (current value)}`
for **all** tags, including `14 temp=22` and `28 ACvoltage_Switchover=230`. `data.deviceData` also has
module info (signalStrength, mcuVersion BMS/DSP/MCU, fw version, etc.). `getPropertyDataList`
(`/v2/quecdatastorage/...`) is the historical-chart endpoint (needs `codeList`+`type`+time range).

Integration: opt-in option `cloud_poll` (default off) polls `getDeviceBusinessAttributes` every 300s
and merges tags 14/28 only; everything else stays local. See `cloud.get_business_attributes`.
