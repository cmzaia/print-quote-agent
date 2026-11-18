"""Load the shop's pricing file. The YAML is authoritative; code only applies it."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RATES_PATH = Path(__file__).with_name("rates.yaml")


@lru_cache(maxsize=8)
def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_rates(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    p = path or os.environ.get("RATES_PATH") or DEFAULT_RATES_PATH
    return _load(str(p))
