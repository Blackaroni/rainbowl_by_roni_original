from __future__ import annotations

import os
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_ENV_LOADED = False


def load_env_file(path: Path = ENV_PATH) -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if not path.exists():
        return
    preserved_keys = set(os.environ)

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key in preserved_keys:
            continue
        os.environ[key] = value

    _ENV_LOADED = True


def get_env_value(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def get_env_int(*names: str, default: int) -> int:
    value = get_env_value(*names)
    return int(value) if value is not None else default


def get_env_bool(*names: str, default: bool) -> bool:
    value = get_env_value(*names)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}
