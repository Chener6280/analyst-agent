from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILES = [
    Path("ir_search.env"),
]


def load_env_file(path: str | None = None) -> Path | None:
    candidates = [Path(path).expanduser()] if path else []
    candidates.extend(DEFAULT_ENV_FILES)
    for candidate in candidates:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return candidate
    return None
