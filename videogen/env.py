"""Minimal .env loader.

Keeps the project dependency-free: python-dotenv would work too, but this is a
dozen lines and avoids a dependency for one feature. Real environment variables
always win, so `ARK_API_KEY=... python -m videogen ...` overrides the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path = ".env", override: bool = False) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file into os.environ.

    Ignores blank lines, comments, and a leading `export `. Strips matching
    quotes. Returns what it set. A missing file is not an error.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Blank placeholders (ARK_MODEL_SEEDANCE_2_0_FAST= in .env.example)
        # should not shadow a real value or masquerade as configured.
        if not key or not value:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
