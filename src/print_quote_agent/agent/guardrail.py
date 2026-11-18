"""Numeric grounding: every number the user is shown must come from tool output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NUM_RE = re.compile(r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)")


def collect_numbers(obj: Any) -> set[float]:
    """All numeric leaves, plus digit runs inside strings (paper weights, sizes, colors)."""
    out: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 4))
    elif isinstance(obj, str):
        for m in re.finditer(r"\d+(?:\.\d+)?", obj):
            out.add(round(float(m.group(0)), 4))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= collect_numbers(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            out |= collect_numbers(v)
    return out


def numbers_in(text: str) -> list[float]:
    return [float(m.group(1).replace(",", "")) for m in NUM_RE.finditer(text)]


@dataclass
class Grounding:
    ok: bool
    ungrounded: list[float] = field(default_factory=list)


def check_grounding(text: str, *sources: Any) -> Grounding:
    allowed: set[float] = set()
    for s in sources:
        allowed |= collect_numbers(s)
    bad = [n for n in numbers_in(text) if round(n, 4) not in allowed]
    return Grounding(ok=not bad, ungrounded=bad)
