#!/usr/bin/env python3
"""One-off: does the Quectel cloud expose live property values (incl. temperature)?
Reads QUECTEL_EMAIL / QUECTEL_PASSWORD from env. Local-only, nothing stored."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quectel_cloud as qc
from _env import load_env


def main() -> None:
    load_env()
    email = os.environ.get("QUECTEL_EMAIL")
    pw = os.environ.get("QUECTEL_PASSWORD")
    pk = os.environ.get("OUKITEL_PK", "p11wN7")
    dk = os.environ.get("OUKITEL_DK")
    if not email or not pw or not dk:
        sys.exit("set QUECTEL_EMAIL / QUECTEL_PASSWORD / OUKITEL_DK (see .env.example)")
    tok = qc.login(email, pw)
    if not tok:
        sys.exit("login failed")
    url = qc.BASE + "/v2/binding/enduserapi/getDeviceBusinessAttributes"
    status, body = qc.get_form(url, {"pk": pk, "dk": dk}, tok)
    print(f"getDeviceBusinessAttributes HTTP {status}")
    j = json.loads(body)
    tsl = (j.get("data") or {}).get("customizeTslInfo") or []
    print(f"\n{'abId':>5} | {'code':<24} | {'type':<8} | value")
    for it in sorted(tsl, key=lambda x: x.get("abId", 0)):
        print(f"{it.get('abId'):>5} | {it.get('resourceCode'):<24} | {it.get('dataType'):<8} | {it.get('resourceValce')}")
    codes = {it.get("resourceCode") for it in tsl}
    print("\ntemp present:", "temp" in codes, " | voltage present:", "ACvoltage_Switchover" in codes)


if __name__ == "__main__":
    main()
