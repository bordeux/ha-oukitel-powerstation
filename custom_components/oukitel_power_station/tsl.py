"""Parse a Quectel productTSL payload into a product manifest.

Pure functions, no Home Assistant imports — this module (with manifest.py) is
the portable multi-model layer that can be lifted 1:1 into any consumer of the
Quectel/WonderFree thing-model (including an upstream PR to
bordeux/ha-oukitel-powerstation, MIT).

Input shape (the ``data`` object of a ``productTSL?pk=…`` response, or one of
the bundled snapshots under ``custom_components/oukitel_power_station/tsl/``)::

    {
      "profile": {"tslVersion": "1.2.0", "productKey": "p11uve", "version": "…"},
      "properties": [
        {
          "id": 11, "code": "ac_input", "dataType": "INT", "name": "…",
          "subType": "R", "type": "PROPERTY", "desc": "…",
          "specs": {"unit": "W", "min": "0", "max": "65535", "step": "1"}
                 | [{"dataType": "ENUM", "name": "50Hz", "value": "0"}, …]
                 | [<sub-property dicts> for STRUCT],   # STRUCT: list of dicts
        },
        …
      ]
    }

The TSL format is shared across the WonderFree family (verified: p11uve /
P1500 and p11wN7 / P2001E Plus have the same shape, 20 identical tag ids).
"""

from __future__ import annotations

from typing import Any


def parse_property(prop: dict[str, Any]) -> dict[str, Any]:
    """Normalise one TSL property dict.

    Returns a compact dict with only what the integration consumes:
    ``id, code, data_type, name, sub_type, unit, min, max, step,
    enum (raw value -> label), struct ({subtag id: sub-spec})``.
    Unknown/missing fields degrade to None/empty rather than raising — the
    cloud schema is not versioned, so a new field must never break setup.
    """
    specs = prop.get("specs")
    data_type = prop.get("dataType")

    unit = min_v = max_v = step = None
    enum: dict[int, str] = {}
    struct: dict[int, dict[str, Any]] = {}

    if isinstance(specs, dict):
        unit = specs.get("unit") or None
        min_v = _to_number(specs.get("min"))
        max_v = _to_number(specs.get("max"))
        step = _to_number(specs.get("step"))
    elif isinstance(specs, list):
        if data_type == "STRUCT":
            for sub in specs:
                if not isinstance(sub, dict) or "id" not in sub:
                    continue
                sub_specs = sub.get("specs")
                struct[sub["id"]] = {
                    "code": sub.get("code"),
                    "data_type": sub.get("dataType"),
                    "name": sub.get("name"),
                    "unit": (sub_specs or {}).get("unit") or None
                    if isinstance(sub_specs, dict)
                    else None,
                }
        else:
            # ENUM entries: [{"dataType": "ENUM", "name": "50Hz", "value": "0"}]
            for entry in specs:
                if not isinstance(entry, dict):
                    continue
                raw = entry.get("value")
                label = entry.get("name")
                if raw is None or label is None:
                    continue
                value = _to_number(raw)
                if value is not None:
                    enum[int(value)] = str(label)

    return {
        "id": prop.get("id"),
        "code": prop.get("code"),
        "data_type": data_type,
        "name": prop.get("name"),
        "sub_type": prop.get("subType"),
        "unit": unit,
        "min": min_v,
        "max": max_v,
        "step": step,
        "enum": enum,
        "struct": struct,
    }


def parse_tsl(data: dict[str, Any]) -> dict[str, Any]:
    """Parse a full productTSL ``data`` object into manifest dicts.

    Returns::

        {
          "product_key": str,
          "tsl_version": str | None,
          "tags": {tag_id: parsed property},          # int keys
          "code_to_tag": {resource_code: tag_id},      # str -> int
        }

    Properties without a numeric id or without a code are skipped (a
    service/action entry must never break the entity manifest).
    """
    profile = data.get("profile") or {}
    tags: dict[int, dict[str, Any]] = {}
    code_to_tag: dict[str, int] = {}

    for prop in data.get("properties") or []:
        if not isinstance(prop, dict):
            continue
        parsed = parse_property(prop)
        tag = parsed.get("id")
        code = parsed.get("code")
        if not isinstance(tag, int) or not code:
            continue
        tags[tag] = parsed
        code_to_tag[str(code)] = tag

    return {
        "product_key": profile.get("productKey"),
        "tsl_version": profile.get("tslVersion"),
        "tags": tags,
        "code_to_tag": code_to_tag,
    }


def _to_number(raw: Any) -> int | float | None:
    """Coerce a TSL spec scalar (string like "65535") to int/float or None."""
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value == int(value) else value
