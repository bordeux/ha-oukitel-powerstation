"""Minimal .env loader (no external deps) for the dev/RE tools.

Reads KEY=VALUE lines from a `.env` file in the repo root (or CWD) into os.environ,
without overwriting variables already set in the environment. Keeps real secrets out
of the committed scripts — put your device/account values in `.env` (gitignored).
See `.env.example`.
"""

from __future__ import annotations

import os
import pathlib


def load_env() -> None:
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / ".env",
        pathlib.Path.cwd() / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return
