#!/usr/bin/env python3
"""
Quectel/Acceleronix (WonderFree) cloud client — login + fetch per-device authKey.
Reverse-engineered from com.quectel.commonappeu v3.6.0 (EU region).
Used to obtain the local-control AES secret (authKey) for the Oukitel P2001E Plus.
"""
import base64, hashlib, json, secrets, subprocess, sys, uuid, urllib.request, urllib.parse

# ---- EU region constants (from ag0 / tl3) ----
BASE        = "https://iot-api.quecteleu.com"
USER_DOMAIN = "E.SP.4294967410"
APP_SECRET  = "3aRNUwWahjyANa7WfBK2wCCkxCexB6nXxKJwXxfePvzf"
LOGIN_URL   = BASE + "/v2/enduser/enduserapi/emailPwdLogin"
AUTHKEY_URL = BASE + "/v2/binding/enduserapi/regenerateAuthKey"
DEVLIST_URL = BASE + "/v2/binding/enduserapi/userDeviceList"

def common_headers(token=None):
    h = {
        "X-Q-Language": "en",
        "quec-random-url": str(uuid.uuid4()),
        "app-info": "[Pixel][Google][raven][33]",
    }
    if token:
        h["Authorization"] = token
    return h

def aes_cbc_b64(plaintext: str, key: str, iv: str) -> str:
    """AES-128-CBC/PKCS5 then Android Base64.DEFAULT (trailing newline)."""
    p = subprocess.run(
        ["openssl", "enc", "-aes-128-cbc", "-K", key.encode().hex(), "-iv", iv.encode().hex()],
        input=plaintext.encode(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("openssl: " + p.stderr.decode())
    return base64.encodebytes(p.stdout).decode()   # 76-col wrap + trailing \n, matches Java DEFAULT

def post_form(url, fields, token=None):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in common_headers(token).items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def post_json(url, obj, token=None):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in common_headers(token).items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def login(email, password):
    random = "".join(secrets.choice(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz") for _ in range(16))
    md5u = hashlib.md5(random.encode()).hexdigest().upper()
    key  = md5u[8:24]                 # 16 chars
    iv   = key[8:16] + key[0:8]       # 16 chars (swapped halves)
    encpwd = aes_cbc_b64(password, key, iv)
    signature = hashlib.sha256((email + encpwd + random + APP_SECRET).encode()).hexdigest()
    fields = {"pwd": encpwd, "email": email, "random": random,
              "userDomain": USER_DOMAIN, "signature": signature}
    print(f"[login] random={random} key={key} iv={iv}")
    status, body = post_form(LOGIN_URL, fields)
    print(f"[login] HTTP {status}\n{body}\n")
    try:
        j = json.loads(body)
        return ((j.get("data") or {}).get("accessToken") or {}).get("token")
    except Exception:
        return None

def get_form(url, fields, token=None):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(fields), method="GET")
    for k, v in common_headers(token).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def device_list(token):
    for how, fn in (("GET", lambda: get_form(DEVLIST_URL, {"pageNumber": "1", "pageSize": "50"}, token)),
                    ("POST", lambda: post_form(DEVLIST_URL, {"pageNumber": "1", "pageSize": "50"}, token)),
                    ("GET-noargs", lambda: get_form(DEVLIST_URL, {}, token))):
        status, body = fn()
        print(f"[devlist:{how}] HTTP {status}\n{body[:1500]}\n")
        if status == 200 and '"dk"' in body:
            return body
    return None

def get_authkey(token, pk, dk):
    status, body = post_json(AUTHKEY_URL, {"pk": pk, "dk": dk}, token)
    print(f"[authKey] HTTP {status}\n{body}\n")

if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _env import load_env
    load_env()
    email = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("QUECTEL_EMAIL")
    pw    = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("QUECTEL_PASSWORD")
    if not email or not pw:
        sys.exit("usage: quectel_cloud.py <email> <password>   (or set QUECTEL_EMAIL / QUECTEL_PASSWORD)")
    tok = login(email, pw)
    print("[token]", (tok[:40] + "...") if tok else None)
    if not tok:
        sys.exit(1)
    dl = device_list(tok)
    if dl:
        for d in (json.loads(dl).get("data") or {}).get("list", json.loads(dl).get("data") or []):
            pk, dk = d.get("pk") or d.get("productKey"), d.get("dk") or d.get("deviceKey")
            print(f"[device] pk={pk} dk={dk} name={d.get('deviceName')}")
            if pk and dk:
                get_authkey(tok, pk, dk)
