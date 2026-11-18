"""Typed inputs and outputs of the cost engine."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Product = Literal["flyer", "brochure", "postcard", "business_card", "booklet"]
Fold = Literal["none", "half", "tri", "z"]
Method = Literal["offset", "digital"]

SIZE_RE = re.compile(r"^\d+(\.\d+)?x\d+(\.\d+)?$")
COLORS_RE = re.compile(r"^[0-4]/[0-4]$")


def parse_size(size: str) -> tuple[float, float]:
    w, h = size.lower().split("x")
    return float(w), float(h)


class JobSpec(BaseModel):
    """A fully specified, validated print job. This is the tool's input schema."""

    product: Product
    quantity: int = Field(gt=0, description="Finished pieces (books for booklets)")
    size: str = Field(description="Width x height in inches, e.g. '8.5x11'. Flat size for brochures.")
    colors: str = Field(description="Ink coverage front/back, e.g. '4/4' or '1/0'")
    paper: str = Field(description="Paper key from rates.yaml, e.g. 'gloss_text_100'")
    fold: Fold = "none"
    pages: int = Field(default=0, ge=0, description="Booklets only; multiple of 4")
    saddle_stitch: bool = False
    turnaround_business_days: int = Field(default=10, ge=0)

    @field_validator("size")
    @classmethod
    def _size(cls, v: str) -> str:
        v = v.lower().replace(" ", "")
        if not SIZE_RE.match(v):
            raise ValueError("size must look like '8.5x11'")
        return v

    @field_validator("colors")
    @classmethod
    def _colors(cls, v: str) -> str:
        if not COLORS_RE.match(v) or v == "0/0":
            raise ValueError("colors must look like '4/4' (0-4 inks per side, not 0/0)")
        return v


class LineItem(BaseModel):
    label: str
    amount: float


class MethodQuote(BaseModel):
    method: Method
    feasible: bool
    infeasible_reason: str | None = None
    ups: int = 0
    press_sheets: int = 0
    lead_business_days: int = 0
    rush_pct: int = 0
    lines: list[LineItem] = []
    total: float | None = None
    unit_price: float | None = None


class QuoteResult(BaseModel):
    spec: JobSpec
    offset: MethodQuote
    digital: MethodQuote
    recommended: Method | None
    savings: float | None = None
    savings_pct: float | None = None
    earliest_business_days: int | None = None


class Crossover(BaseModel):
    """Smallest quantity at which offset is no more expensive than digital.

    Computed at standard turnaround so rush surcharges and lead times do not
    distort the volume economics.
    """

    crossover_quantity: int | None
    offset_total_at_crossover: float | None = None
    digital_total_at_crossover: float | None = None
    note: str
