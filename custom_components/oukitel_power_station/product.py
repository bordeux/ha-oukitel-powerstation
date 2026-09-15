"""Product capabilities exposed by a WonderFree power station.

The manifest is the ONLY place model knowledge lives. Platforms never ask
"is this a P1500E Plus?" — they ask the manifest "does this tag (or struct subtag)
exist on this product?" and the coordinator asks it for the read list and
the cloud shadow key map. Adding a new model = adding its productTSL
snapshot under ``tsl/`` (and, when needed, a curated override entry).

Sources of truth, in resolver priority order:

1. **snapshot** — the vendor TSL data captured at config-entry setup and stored
   in the entry data (survives cloud outages and TSL drift);
2. **bundled** — a snapshot shipped with the integration under
   ``custom_components/oukitel_power_station/tsl/<pk>.json`` (offline installs,
   migration of pre-manifest entries);
3. **cloud** — a live ``productTSL`` fetch for a product key we do not ship
   (a new family member works on day one, before the next release).

Curated overrides (``KNOWN_PRODUCTS``) are applied after resolving a source.
They record verified firmware behaviour the TSL itself does not express —
e.g. the P1500E Plus pins remain_time (2) and
remain_charging_time (3) to 5940, so those sensors are excluded there
(verified live 2026-09-06) while the P2001E Plus reports them correctly.

This module (with tsl.py) is the portable multi-model layer: pure Python,
no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import logging
from pathlib import Path
from typing import Any

from .const import CLOUD_ONLY_TAGS, DEFAULT_MODEL, READ_TAG_IDS
from .tsl import parse_tsl

_LOGGER = logging.getLogger(__name__)

_TSL_DIR = Path(__file__).parent / "tsl"

# Verified display names per product key. Used for DeviceInfo.model; a live
# productName from userDeviceList wins when it is available.
KNOWN_PRODUCTS: dict[str, dict[str, Any]] = {
    "p11uve": {
        "model": "P1500E Plus",
        # Pinned to 5940 by this firmware (verified live) — useless sensors.
        "excluded_tags": (2, 3),
    },
    "p11wN7": {
        "model": DEFAULT_MODEL,
        "excluded_tags": (),
    },
    "p11wDf": {
        # IEE P2400 and P3200
        "manufacturer": "IEE",
        "model": "P2400/P3200",
        "excluded_tags": (),
    },
}


@dataclass(frozen=True)
class ProductManifest:
    """What one product key exposes."""

    product_key: str
    model: str
    tsl_version: str | None
    profile_version: str | None
    tags: dict[int, dict[str, Any]]
    code_to_tag: dict[str, int]
    excluded_tags: tuple[int, ...] = field(default_factory=tuple)

    # --- queries the platforms/coordinator rely on ---------------------------
    def has_tag(self, tag: int) -> bool:
        """True when the product exposes the tag and it is not excluded."""
        return tag in self.tags and tag not in self.excluded_tags

    def has_subtag(self, tag: int, subtag: int) -> bool:
        """True when a struct tag exists and contains the given subtag."""
        if not self.has_tag(tag):
            return False
        return subtag in (self.tags[tag].get("struct") or {})

    def tag_spec(self, tag: int) -> dict[str, Any]:
        """Return the parsed TSL property for a tag (empty dict if absent)."""
        return self.tags.get(tag, {})

    def enum_options(self, tag: int) -> dict[int, str]:
        """Return the {raw value: label} map for an ENUM tag (may be empty)."""
        return dict(self.tags.get(tag, {}).get("enum") or {})

    def read_tag_ids(self) -> tuple[int, ...]:
        """The cmd17 snapshot read list: every manifest tag + hf reporting."""
        vendor_order = tuple(tag for tag in READ_TAG_IDS if tag in self.tags or tag == 100)
        extra_tags = tuple(sorted(set(self.tags) - set(vendor_order)))
        return vendor_order + extra_tags

    def cloud_only_tags(self) -> tuple[int, ...]:
        """Cloud-only tags that exist on this product (LAN never reports)."""
        return tuple(t for t in CLOUD_ONLY_TAGS if t in self.tags)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for config-entry storage (snapshot; JSON-safe)."""
        return {
            "product_key": self.product_key,
            "tsl_version": self.tsl_version,
            "profile_version": self.profile_version,
            "tags": {str(t): spec for t, spec in self.tags.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductManifest:
        """Rebuild from a config-entry snapshot."""
        tags = {
            int(tag): _restore_json_keys(spec) for tag, spec in (data.get("tags") or {}).items()
        }
        product_key = str(data.get("product_key") or "")
        return cls(
            product_key=product_key,
            model=product_key or "unknown",
            tsl_version=data.get("tsl_version"),
            profile_version=data.get("profile_version"),
            tags=tags,
            code_to_tag={str(spec["code"]): t for t, spec in tags.items()},
        )


def _restore_json_keys(spec: dict[str, Any]) -> dict[str, Any]:
    """Restore integer keys stringified by config-entry JSON storage."""
    restored = dict(spec)
    if isinstance(enum := restored.get("enum"), dict):
        restored["enum"] = {int(value): label for value, label in enum.items()}
    if isinstance(struct := restored.get("struct"), dict):
        restored["struct"] = {int(tag): sub_spec for tag, sub_spec in struct.items()}
    return restored


def build_manifest(tsl_data: dict[str, Any]) -> ProductManifest:
    """Build a vendor-derived manifest from a raw productTSL ``data`` object."""
    parsed = parse_tsl(tsl_data)
    pk = str(parsed["product_key"] or "")
    return ProductManifest(
        product_key=pk,
        model=pk or "unknown",
        tsl_version=parsed["tsl_version"],
        profile_version=parsed["profile_version"],
        tags=parsed["tags"],
        code_to_tag=parsed["code_to_tag"],
    )


def load_bundled_tsl(product_key: str) -> dict[str, Any] | None:
    """Load a bundled productTSL snapshot, or None when we do not ship it."""
    path = _TSL_DIR / f"{product_key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:  # pragma: no cover
        _LOGGER.warning("bundled TSL %s unreadable: %s", path, err)
        return None


def manifest_from_bundled(product_key: str) -> ProductManifest | None:
    """Build a manifest from a bundled snapshot (None when not shipped)."""
    tsl_data = load_bundled_tsl(product_key)
    if tsl_data is None:
        return None
    return build_manifest(tsl_data)


def resolve_manifest(
    product_key: str,
    snapshot: dict[str, Any] | None = None,
    cloud_tsl: dict[str, Any] | None = None,
) -> ProductManifest | None:
    """Resolve a manifest: snapshot → bundled → cloud. None when all fail."""
    manifest = None
    if snapshot:
        try:
            manifest = ProductManifest.from_dict(snapshot)
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("ignoring corrupt manifest snapshot: %s", err)
    if manifest is None:
        manifest = manifest_from_bundled(product_key)
    if manifest is None and cloud_tsl:
        manifest = build_manifest(cloud_tsl)
    if manifest is None:
        return None

    known = KNOWN_PRODUCTS.get(manifest.product_key, {})
    return replace(
        manifest,
        model=str(known.get("model") or manifest.product_key or "unknown"),
        excluded_tags=tuple(known.get("excluded_tags") or ()),
    )
