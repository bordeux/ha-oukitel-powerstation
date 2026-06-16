"""Import smoke test: every integration module must import against real Home Assistant.

This is the check that catches broken HA imports (e.g. importing DeviceInfo from a
module that doesn't exist) — the kind of bug that prevents the config entry from
setting up but is invisible to ruff and to the protocol/cloud offline tests, since
those never import `homeassistant`.

Skips automatically when `homeassistant` isn't installed (plain dev venv); runs in CI
where HA is present. Modules are imported as a namespace package from the repo root.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

pytest.importorskip("homeassistant")

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PKG = "custom_components.oukitel_power_station"

MODULES = [
    "__init__",
    "const",
    "protocol",
    "cloud",
    "discovery",
    "coordinator",
    "entity",
    "config_flow",
    "sensor",
    "switch",
    "select",
    "number",
    "diagnostics",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    """Importing the module must not raise (catches bad/renamed HA imports)."""
    importlib.import_module(f"{PKG}.{module}")
