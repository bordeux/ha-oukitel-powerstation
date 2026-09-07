"""Offline tests for the product manifest layer (tsl.py + manifest.py).

Loads the modules directly (no Home Assistant needed — the manifest layer is
pure Python by design), same pattern as test_protocol.py.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "oukitel_power_station"
_pkg = types.ModuleType("ouk")
_pkg.__path__ = [str(BASE)]
sys.modules["ouk"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"ouk.{name}", BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"ouk.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


tsl = _load("tsl")
manifest_mod = _load("manifest")

KNOWN_PRODUCTS = manifest_mod.KNOWN_PRODUCTS
ProductManifest = manifest_mod.ProductManifest
build_manifest = manifest_mod.build_manifest
manifest_from_bundled = manifest_mod.manifest_from_bundled
resolve_manifest = manifest_mod.resolve_manifest
parse_tsl = tsl.parse_tsl

TSL_DIR = BASE / "tsl"

# Tag ids from the product thing-models (see tools/tsl_*.json).
TAG_REMAIN_TIME = 2
TAG_REMAIN_CHARGING_TIME = 3
TAG_TOTAL_INPUT_POWER = 4
TAG_AC_STRUCT = 6
TAG_TYPEC_STRUCT = 8
TAG_LED_STATUS = 10
TAG_TEMP = 14
TAG_CHARGE_LIMIT = 20
TAG_FREQUENCY = 27
TAG_VOLTAGE = 28
TAG_USB_SWITCH = 44
TAG_AC_SWITCH = 43


@pytest.fixture
def p1500_tsl() -> dict:
    return json.loads((TSL_DIR / "p11uve.json").read_text(encoding="utf-8"))


@pytest.fixture
def p2001e_tsl() -> dict:
    return json.loads((TSL_DIR / "p11wN7.json").read_text(encoding="utf-8"))


# --- tsl.py -----------------------------------------------------------------
def test_parse_tsl_p1500(p1500_tsl):
    parsed = parse_tsl(p1500_tsl)
    assert parsed["product_key"] == "p11uve"
    assert parsed["tsl_version"] == "1.2.0"
    assert len(parsed["tags"]) == 21
    # every property contributes its code to the reverse map
    assert parsed["code_to_tag"]["total_input_power"] == TAG_TOTAL_INPUT_POWER
    assert parsed["code_to_tag"]["led_status"] == TAG_LED_STATUS
    assert parsed["code_to_tag"]["high_frequency_reporting"] == 100


def test_parse_scalars_and_enums(p1500_tsl):
    parsed = parse_tsl(p1500_tsl)
    charge = parsed["tags"][TAG_CHARGE_LIMIT]
    assert charge["data_type"] == "INT"
    assert charge["sub_type"] == "RW"
    assert charge["min"] == 0
    assert charge["max"] == 100
    freq = parsed["tags"][TAG_FREQUENCY]
    assert freq["enum"] == {0: "50Hz", 1: "60Hz"}
    voltage = parsed["tags"][TAG_VOLTAGE]
    assert voltage["enum"][230] == "230V"
    assert voltage["sub_type"] == "RW"


def test_parse_structs(p1500_tsl, p2001e_tsl):
    p1500 = parse_tsl(p1500_tsl)["tags"]
    p2001e = parse_tsl(p2001e_tsl)["tags"]
    # P1500: 2 Type-C ports; P2001E Plus: 4 (verified TSL diff).
    assert sorted(p1500[TAG_TYPEC_STRUCT]["struct"]) == [2, 5]
    assert sorted(p2001e[TAG_TYPEC_STRUCT]["struct"]) == [2, 5, 6, 7]
    # P2001E Plus structs mirror the output switches as subtag 1; P1500 not.
    assert 1 in p2001e[TAG_AC_STRUCT]["struct"]
    assert 1 not in p1500[TAG_AC_STRUCT]["struct"]
    assert p1500[TAG_AC_STRUCT]["struct"][2]["unit"] == "W"


def test_parse_tolerates_garbage():
    parsed = parse_tsl(
        {
            "profile": {"productKey": "pkX"},
            "properties": [
                None,
                {"no_id": True},
                {"id": "nope", "code": "x"},
                {"id": 1, "dataType": "INT"},  # missing code -> skipped
                {"id": 2, "code": "ok", "dataType": "INT", "specs": {}},
                {"id": 3, "code": "weird_enum", "dataType": "ENUM", "specs": "junk"},
            ],
        }
    )
    assert parsed["product_key"] == "pkX"
    assert set(parsed["tags"]) == {2, 3}
    assert parsed["code_to_tag"] == {"ok": 2, "weird_enum": 3}


# --- manifest.py -------------------------------------------------------------
def test_build_manifest_known_products(p1500_tsl, p2001e_tsl):
    m1500 = build_manifest(p1500_tsl)
    assert m1500.product_key == "p11uve"
    assert m1500.model == "P1500"
    assert m1500.excluded_tags == (TAG_REMAIN_TIME, TAG_REMAIN_CHARGING_TIME)

    m2001e = build_manifest(p2001e_tsl)
    assert m2001e.product_key == "p11wN7"
    assert m2001e.model == "P2001E Plus"
    assert m2001e.excluded_tags == ()


def test_known_products_cover_bundled_snapshots():
    for pk in ("p11uve", "p11wN7"):
        assert pk in KNOWN_PRODUCTS
        manifest = manifest_from_bundled(pk)
        assert manifest is not None
        assert manifest.product_key == pk


def test_manifest_gating(p1500_tsl, p2001e_tsl):
    m1500 = build_manifest(p1500_tsl)
    m2001e = build_manifest(p2001e_tsl)
    # P1500 has LED, no USB switch; P2001E Plus has USB switch, no LED.
    assert m1500.has_tag(TAG_LED_STATUS) and not m1500.has_tag(TAG_USB_SWITCH)
    assert m2001e.has_tag(TAG_USB_SWITCH) and not m2001e.has_tag(TAG_LED_STATUS)
    # curated exclude: the pinned time sensors vanish on the P1500 only.
    assert not m1500.has_tag(TAG_REMAIN_TIME)
    assert not m1500.has_tag(TAG_REMAIN_CHARGING_TIME)
    assert m2001e.has_tag(TAG_REMAIN_TIME)
    # struct subtag gating
    assert m1500.has_subtag(TAG_TYPEC_STRUCT, 2)
    assert not m1500.has_subtag(TAG_TYPEC_STRUCT, 6)
    assert m2001e.has_subtag(TAG_TYPEC_STRUCT, 6)
    assert not m1500.has_subtag(999, 2)


def test_read_tag_ids(p1500_tsl, p2001e_tsl):
    ids1500 = build_manifest(p1500_tsl).read_tag_ids()
    ids2001e = build_manifest(p2001e_tsl).read_tag_ids()
    # vendor app's verified cmd17 list + product-specific tags
    for tag in (1, 4, 5, 6, 7, 8, 9, 11, 12, 14, 20, 27, 28, 31, 34, 43, 46, 100):
        assert tag in ids1500
    assert TAG_LED_STATUS in ids1500 and TAG_USB_SWITCH not in ids1500
    assert TAG_USB_SWITCH in ids2001e and TAG_LED_STATUS not in ids2001e
    assert ids1500 == tuple(sorted(ids1500))


def test_cloud_only_tags(p1500_tsl):
    cloud_only = build_manifest(p1500_tsl).cloud_only_tags()
    assert cloud_only == (TAG_TEMP, TAG_VOLTAGE)


def test_snapshot_roundtrip(p1500_tsl):
    manifest = build_manifest(p1500_tsl)
    restored = ProductManifest.from_dict(manifest.to_dict())
    assert restored == manifest
    assert restored.code_to_tag == manifest.code_to_tag


def test_snapshot_is_json_safe(p1500_tsl):
    snapshot = build_manifest(p1500_tsl).to_dict()
    json.dumps(snapshot)  # must not raise (config-entry storage)


def test_resolve_manifest_priority(p1500_tsl):
    bundled = manifest_from_bundled("p11uve")
    assert bundled is not None
    # snapshot wins over bundled
    fake = bundled.to_dict() | {"model": "snapshotted"}
    resolved = resolve_manifest("p11uve", snapshot=fake)
    assert resolved is not None
    assert resolved.model == "snapshotted"
    # bundled as fallback
    assert resolve_manifest("p11uve") == bundled
    # cloud data as the last resort for an unknown product key
    resolved = resolve_manifest("pkNew", cloud_tsl=p1500_tsl)
    assert resolved is not None
    assert resolved.product_key == "p11uve"  # taken from the TSL payload
    # nothing available -> None
    assert resolve_manifest("pkUnknown") is None
