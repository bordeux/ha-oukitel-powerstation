"""Per-product manifest: what a given WonderFree station actually exposes.

The manifest is the ONLY place model knowledge lives. Platforms never ask
"is this a P1500?" — they ask the manifest "does this tag (or struct subtag)
exist on this product?" and the coordinator asks it for the read list and
the cloud shadow key map. Adding a new model = adding its productTSL
snapshot under ``tsl/`` (and, when needed, a curated override entry).

Sources of truth, in resolver priority order:

1. **snapshot** — the manifest captured at config-entry setup and stored in
   the entry data (survives cloud outages and TSL drift; keeps running even
   if the vendor changes the model upstream);
2. **bundled** — a snapshot shipped with the integration under
   ``custom_components/oukitel_power_station/tsl/<pk>.json`` (offline installs,
   migration of pre-manifest entries);
3. **cloud** — a live ``productTSL`` fetch for a product key we do not ship
   (a new family member works on day one, before the next release).

Curated overrides (``KNOWN_PRODUCTS``) record verified firmware behaviour
the TSL itself does not express — e.g. the P1500 pins remain_time (2) and
remain_charging_time (3) to 5940, so those sensors are excluded there
(verified live 2026-09-06) while the P2001E Plus reports them correctly.

This module (with tsl.py) is the portable multi-model layer: pure Python,
no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any

from .tsl import parse_tsl

_LOGGER = logging.getLogger(__name__)

_TSL_DIR = Path(__file__).parent / "tsl"

# Verified display names per product key. Used for DeviceInfo.model; a live
# productName from userDeviceList wins when it is available.
KNOWN_PRODUCTS: dict[str, dict[str, Any]] = {
    "p11uve": {
        "model": "P1500",
        # Pinned to 5940 by this firmware (verified live) — useless sensors.
        "excluded_tags": (2, 3),
    },
    "p11wN7": {
        "model": "P2001E Plus",
        "excluded_tags": (),
    },
}

# Tags never delivered over the LAN link regardless of product (verified live
# on the P1500 2026-09-06 and the P2001E Plus per bordeux §13): temperature
# and the output-voltage setting are only readable from the cloud shadow.
# The voltage WRITE works locally (bordeux) — only the read-back is missing.
CLOUD_ONLY_TAGS = (14, 28)


@dataclass(frozen=True)
class ProductManifest:
    """What one product key exposes, with verified firmware overrides applied."""

    product_key: str
    model: str
    tsl_version: str | None
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
        return tuple(sorted({*self.tags, 100}))

    def cloud_only_tags(self) -> tuple[int, ...]:
        """Cloud-only tags that exist on this product (LAN never reports)."""
        return tuple(t for t in CLOUD_ONLY_TAGS if t in self.tags)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for config-entry storage (snapshot; JSON-safe)."""
        return {
            "product_key": self.product_key,
            "model": self.model,
            "tsl_version": self.tsl_version,
            "tags": {str(t): spec for t, spec in self.tags.items()},
            "excluded_tags": list(self.excluded_tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductManifest:
        """Rebuild from a config-entry snapshot."""
        tags = {int(t): spec for t, spec in (data.get("tags") or {}).items()}
        return cls(
            product_key=str(data.get("product_key") or ""),
            model=str(data.get("model") or ""),
            tsl_version=data.get("tsl_version"),
            tags=tags,
            code_to_tag={str(spec["code"]): t for t, spec in tags.items()},
            excluded_tags=tuple(data.get("excluded_tags") or ()),
        )


def build_manifest(tsl_data: dict[str, Any]) -> ProductManifest:
    """Build a manifest from a raw productTSL ``data`` object."""
    parsed = parse_tsl(tsl_data)
    pk = str(parsed["product_key"] or "")
    known = KNOWN_PRODUCTS.get(pk, {})
    return ProductManifest(
        product_key=pk,
        model=str(known.get("model") or pk or "unknown"),
        tsl_version=parsed["tsl_version"],
        tags=parsed["tags"],
        code_to_tag=parsed["code_to_tag"],
        excluded_tags=tuple(known.get("excluded_tags") or ()),
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
    if snapshot:
        try:
            return ProductManifest.from_dict(snapshot)
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("ignoring corrupt manifest snapshot: %s", err)
    bundled = manifest_from_bundled(product_key)
    if bundled is not None:
        return bundled
    if cloud_tsl:
        return build_manifest(cloud_tsl)
    return None
