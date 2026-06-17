#!/usr/bin/env python3
"""
Oukitel P2001E Plus — local LAN client (Quectel TTLV protocol).
Connects directly to the station over TCP 6607, performs the p2..p5 handshake
using the device authKey, enables AES-128-CBC, and prints decrypted live telemetry.

Reverse-engineered from com.quectel.commonappeu — see REVERSE_ENGINEERING.md.
"""
import base64, hashlib, os, socket, struct, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env

load_env()

# ---- per-device secret (from cloud userDeviceList; set in .env, see .env.example) ----
AUTHKEY = os.environ.get("OUKITEL_AUTHKEY", "")
if not AUTHKEY:
    sys.exit("set OUKITEL_AUTHKEY (per-device key, from quectel_cloud.py / cloud) in .env or env")
KEY     = base64.b64decode(AUTHKEY)          # 16-byte AES-128 key
HOST    = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OUKITEL_HOST")
if not HOST:
    sys.exit("usage: oukitel_local.py <station-ip>   (or set OUKITEL_HOST in .env/env)")
PORT    = 6607

CMD_P2, CMD_P3, CMD_P4, CMD_P5 = 28722, 28723, 28724, 28725   # handshake
CMD_PING, CMD_PONG, CMD_HB     = 28727, 28728, 28729
CMD_READ, CMD_WRITE, CMD_REPORT, CMD_ACK = 17, 19, 20, 28726

# cmd17 read request = list of 2-byte tag IDs to read (from decrypted capture)
READ_TAGS = [2,8,9,6,31,7,28,27,14,12,11,5,4,3,1,34,20,100,43,44,46]
READ_PAYLOAD = b"".join(struct.pack(">H", t) for t in READ_TAGS)

# authoritative names from cloud TSL (productTSL pk=p11wN7) — see tools/tsl_p11wN7.json
TAGS = {1:"battery_pct(%)",2:"remain_time(min)",3:"remain_charging_time(min)",
        4:"total_input_power(W)",5:"total_output_power(W)",11:"ac_input(W)",12:"dc_input(W)",
        14:"temp(C)",20:"ac_charging_limit(%)",27:"frequency(0=50Hz,1=60Hz)",
        28:"out_voltage(100/110/120/220/230/240V)",31:"inverter_version",34:"bms_version",
        43:"ac_switch",44:"usb_switch",46:"dc_switch",100:"hf_reporting(3=LAN+WiFi)",
        6:"ac_data{sw,W,V}",7:"usb_data{sw,W,qc2}",8:"typec_data{c1..c4 W}",9:"dc_data{sw,W,V,A}"}

# ---------- AES (via openssl, no external deps) ----------
def aes_dec(ct, iv):
    p = subprocess.run(["openssl","enc","-aes-128-cbc","-d","-nopad",
                        "-K", KEY.hex(), "-iv", iv.hex()],
                       input=ct, capture_output=True)
    return p.stdout
def aes_enc(pt, iv):
    p = subprocess.run(["openssl","enc","-aes-128-cbc","-nopad",
                        "-K", KEY.hex(), "-iv", iv.hex()],
                       input=pad(pt), capture_output=True)
    return p.stdout
def pad(b):    n = 16 - (len(b) % 16); return b + bytes([n])*n
def unpad(b):
    if not b: return b
    n = b[-1]
    return b[:-n] if 1 <= n <= 16 and b[-n:] == bytes([n])*n else b

# ---------- byte stuffing (AA -> AA 55) ----------
def stuff(frame):
    out = bytearray(frame[:2])           # leave header AA AA
    i = 2
    body = frame[2:]
    j = 0
    while j < len(body):
        out.append(body[j])
        if body[j] == 0xAA and j+1 < len(body) and body[j+1] in (0x55, 0xAA):
            out.append(0x55)
        j += 1
    return bytes(out)
def destuff(buf):
    out = bytearray()
    i = 0
    while i < len(buf):
        out.append(buf[i])
        if buf[i] == 0xAA and i+1 < len(buf) and buf[i+1] == 0x55:
            i += 1                       # drop the stuffed 0x55
        i += 1
    return bytes(out)

# ---------- frame build / parse ----------
_pid = [0]
def build(cmd, payload=b"", encrypt=False, iv=None):
    if encrypt and payload:
        payload = aes_enc(payload, iv)
    _pid[0] += 1
    pid = _pid[0]
    body = struct.pack(">H", pid) + struct.pack(">H", cmd) + payload   # packetID, cmd, payload
    length = len(body) + 1                                             # +1 for checksum byte
    chk = sum(body) & 0xFF
    frame = b"\xAA\xAA" + struct.pack(">H", length) + bytes([chk]) + body
    return stuff(frame)

def parse_stream(buf):
    """Yield (cmd, packetID, payload, consumed_upto) frames from a destuffed buffer."""
    frames = []
    b = destuff(buf)
    i = 0
    while True:
        k = b.find(b"\xAA\xAA", i)
        if k < 0 or k + 4 > len(b): break
        length = struct.unpack(">H", b[k+2:k+4])[0]
        total = k + 4 + length
        if total > len(b): break
        frame = b[k:total]
        chk = frame[4]
        body = frame[5:]
        if (sum(body) & 0xFF) == chk:
            pid = struct.unpack(">H", frame[5:7])[0]
            cmd = struct.unpack(">H", frame[7:9])[0]
            payload = frame[9:]
            frames.append((cmd, pid, payload))
        i = total
    return frames

# ---------- TTLV decode ----------
def ttlv_decode(buf):
    fields = []
    i = 0
    def num(i):
        c = buf[i]; i += 1
        sign = (c >> 7) & 1; dec = (c >> 3) & 0xF; n = (c & 7) + 1
        v = int.from_bytes(buf[i:i+n], "big"); i += n
        if sign: v = -v
        return (v / (10**dec) if dec else v), i
    while i + 2 <= len(buf):
        h = struct.unpack(">H", buf[i:i+2])[0]; i += 2
        tag, typ = (h >> 3) & 0x1FFF, h & 7
        if typ in (0, 1):
            fields.append((tag, "bool", typ == 1))
        elif typ == 2:
            v, i = num(i); fields.append((tag, "num", v))
        elif typ in (3, 5):
            if i+2 > len(buf): break
            ln = struct.unpack(">H", buf[i:i+2])[0]; i += 2
            val = buf[i:i+ln]; i += ln
            try: sval = val.decode("ascii");
            except: sval = val.hex()
            fields.append((tag, "bin", sval if val.isascii() else val.hex()))
        elif typ == 4:
            if i+2 > len(buf): break
            cnt = struct.unpack(">H", buf[i:i+2])[0]; i += 2
            sub = []
            for _ in range(cnt):
                if i+2 > len(buf): break
                h2 = struct.unpack(">H", buf[i:i+2])[0]; i += 2
                t2, ty2 = (h2 >> 3) & 0x1FFF, h2 & 7
                if ty2 in (0,1): sub.append((t2,"bool",ty2==1))
                elif ty2 == 2: v,i = num(i); sub.append((t2,"num",v))
                elif ty2 in (3,5):
                    ln=struct.unpack(">H",buf[i:i+2])[0]; i+=2; sub.append((t2,"bin",buf[i:i+ln].hex())); i+=ln
            fields.append((tag, "struct", sub))
        else:
            break
    return fields

# ---------- handshake + run ----------
def main():
    s = socket.create_connection((HOST, PORT), timeout=10)
    s.settimeout(8)
    print(f"[+] connected {HOST}:{PORT}")
    s.sendall(build(CMD_P2))                       # hello
    print("[>] sent p2 (hello)")
    rnd = None; iv = None; encrypted = False
    buf = b""; processed = 0
    t0 = time.time()
    while time.time() - t0 < 40:
        try: data = s.recv(4096)
        except socket.timeout:
            continue
        if not data: print("[!] closed by peer"); break
        buf += data
        frames = parse_stream(buf)               # re-parse all; skip already-handled
        new = frames[processed:]
        processed = len(frames)
        for cmd, pid, payload in new:
            if cmd == CMD_P3:                      # device random nonce
                fields = ttlv_decode(payload)
                rnd = next((v for t,ty,v in fields if ty=="bin"), None)
                print(f"[<] p3 random nonce = {rnd}")
                iv = rnd.encode()
                token = hashlib.sha256((KEY.hex() + ";" + rnd).encode()).hexdigest()
                p4 = struct.pack(">H", (2<<3)|3) + struct.pack(">H", len(token)) + token.encode()
                s.sendall(build(CMD_P4, p4))
                print(f"[>] sent p4 login token")
            elif cmd == CMD_P5:                    # login result
                fields = ttlv_decode(payload)
                res = next((v for t,ty,v in fields if ty=="num"), None)
                print(f"[<] p5 login result = {res}  -> {'SUCCESS' if res in (0,) else res}")
                encrypted = True
                # mimic app post-login: subscribe (cmd19 tag100=3) + read-all (cmd17) + heartbeat
                s.sendall(build(CMD_WRITE, b"\x03\x22\x00\x03", encrypt=True, iv=iv))     # (tag100, num 3)
                s.sendall(build(CMD_READ, READ_PAYLOAD, encrypt=True, iv=iv))             # read all
                s.sendall(build(CMD_HB, b"\x00\x0a\x00\x1e\x00\x12\x00\x01", encrypt=True, iv=iv))
                print("[>] encryption ON; subscribed + read-all. telemetry:\n")
            elif cmd in (CMD_PING, CMD_PONG, CMD_ACK):
                pass
            else:                                  # data / telemetry (cmd 20 report)
                pt = unpad(aes_dec(payload, iv)) if (encrypted and payload) else payload
                fields = ttlv_decode(pt)
                if fields:
                    print("[report] " + ", ".join(
                        f"{TAGS.get(t,'tag'+str(t))}={v}" for t,ty,v in fields))
    s.close()

if __name__ == "__main__":
    main()
