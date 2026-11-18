"""Validate and normalize a raw spec into a priced-ready JobSpec, or say what is missing.

Pure and deterministic. Handles paper aliases ("100# gloss text"), color shorthand
("4/4", "full color"), fold names, default sizes and deadline arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..cost_engine.models import SIZE_RE, JobSpec
from ..cost_engine.rates import load_rates
from . import deadline as dl

PRODUCTS = ["flyer", "brochure", "postcard", "business_card", "booklet"]
PRODUCT_WORDS = {
    "flyer": r"fl(?:ye|ie|y)rs?|leaflets?|handouts?|sell sheets?",
    "brochure": r"brochures?|pamphlets?",
    "postcard": r"post ?cards?",
    "business_card": r"business ?cards?|biz ?cards?",
    "booklet": r"booklets?|catalogs?|catalogues?|magazines?|saddle[- ]?stitch(?:ed)? books?",
}
FOLDS = {"half": "half", "bi": "half", "tri": "tri", "letter": "tri", "z": "z", "none": "none"}
FINISHES = {
    "gloss": "gloss", "glossy": "gloss", "coated": "gloss",
    "matte": "matte", "matt": "matte", "silk": "matte", "satin": "matte",
    "uncoated": "uncoated", "plain": "uncoated", "bond": "uncoated",
}  # fmt: skip

# Required before we can price. Order is the order we ask in.
BASE_REQUIRED = ["product", "quantity", "colors", "paper"]


@dataclass
class Issue:
    field: str
    message: str


@dataclass
class Normalized:
    spec: JobSpec | None = None
    known: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.spec is not None


def normalize_product(text: str) -> str | None:
    t = text.lower()
    for key, pat in PRODUCT_WORDS.items():
        if re.search(rf"\b(?:{pat})\b", t) or t.replace(" ", "_") == key:
            return key
    return None


def normalize_colors(text: str) -> tuple[str | None, str | None]:
    t = text.lower().strip()
    m = re.search(r"\b([0-4])\s*/\s*([0-4])\b", t)
    if m:
        c = f"{m.group(1)}/{m.group(2)}"
        return (c, None) if c != "0/0" else (None, "0/0 would print nothing.")
    one_side = re.search(r"one[- ]side|single[- ]sided|front only|1[- ]sided|one sided", t)
    if re.search(r"full[- ]?colou?r|four[- ]colou?r|cmyk|4[- ]colou?r", t):
        return ("4/0" if one_side else "4/4"), None
    if re.search(r"black|b\s*&\s*w|b/w|grayscale|greyscale|one[- ]colou?r|1[- ]colou?r|mono", t):
        return ("1/0" if one_side else "1/1"), None
    return None, f'I could not read "{text}" as ink coverage.'


def paper_options(rates: dict, finish: str | None = None) -> list[str]:
    return [
        p["label"]
        for k, p in rates["papers"].items()
        if finish is None or k.startswith(finish + "_")
    ]


def normalize_paper(text: str, product: str | None, rates: dict) -> tuple[str | None, str | None]:
    t = re.sub(r"\s+", " ", text.lower().replace("lbs", "#").replace("lb", "#")).strip()
    t = t.replace("pound", "#").replace(" #", "#")
    if t in rates["paper_aliases"]:
        return rates["paper_aliases"][t], None
    m = re.search(r"(\d+)\s*pt", t)
    if m and f"{m.group(1)}pt" in rates["paper_aliases"] and not any(w in t for w in FINISHES):
        return rates["paper_aliases"][f"{m.group(1)}pt"], None
    finish = next((v for k, v in FINISHES.items() if re.search(rf"\b{k}\b", t)), None)
    weight_m = re.search(r"(\d{2,3})\s*#?", t)
    weight = weight_m.group(1) if weight_m else None
    kind = "cover" if "cover" in t or "card" in t else "text" if "text" in t else None
    opts = ", ".join(paper_options(rates, finish))
    if not finish:
        return None, f'Which finish for "{text}"? Options: {opts}.'
    if not weight:
        return None, f"What paper weight in {finish}? Options: {opts}."
    kinds = [kind] if kind else (
        ["cover", "text"] if product in ("postcard", "business_card") else ["text", "cover"]
    )
    for k in kinds:
        key = f"{finish}_{k}_{weight}"
        if key in rates["papers"]:
            return key, None
    return None, f'I do not stock "{text}". Options: {opts}.'


def normalize_size(text: str, rates: dict) -> tuple[str | None, str | None]:
    t = text.lower().strip().replace("×", "x").replace(" ", "")
    t = re.sub(r'["”]|in(?:ch(?:es)?)?$', "", t)
    if SIZE_RE.match(t):
        return t, None
    named = {k.replace("-", "").replace(" ", ""): v for k, v in rates["named_sizes"].items()}
    if t.replace("-", "") in named:
        return named[t.replace("-", "")], None
    return None, f'I could not read the size "{text}". Try something like 8.5x11.'


def normalize(raw: dict[str, Any], today: date, rates: dict | None = None) -> Normalized:
    rates = rates or load_rates()
    out = Normalized()
    k = out.known

    product = None
    if raw.get("product"):
        product = normalize_product(raw["product"])
        if product is None:
            out.issues.append(
                Issue(
                    "product",
                    f'I can only quote flyers, brochures, postcards, business cards and '
                    f'booklets, not "{raw["product"]}".',
                )
            )
        else:
            k["product"] = product

    fold = None
    if raw.get("fold"):
        f = raw["fold"].lower()
        fold = next((v for key, v in FOLDS.items() if re.match(rf"{key}[- ]?(fold|$)", f)), None)
        fold = fold or ("half" if "half" in f else None)
        if fold is None:
            out.issues.append(Issue("fold", f'I could not read the fold "{raw["fold"]}".'))
    if product == "flyer" and fold not in (None, "none"):
        product = k["product"] = "brochure"
        out.assumptions.append("A folded flyer is priced as a brochure.")
    if product in ("postcard", "business_card", "booklet"):
        fold = "none"
    if fold:
        k["fold"] = fold

    if raw.get("quantity_conflict"):
        opts = " or ".join(f"{q:,}" for q in raw["quantity_conflict"])
        out.issues.append(Issue("quantity", f"You mentioned more than one quantity ({opts}). Which one?"))
    elif raw.get("quantity") is not None:
        lim = rates["limits"]
        q = raw["quantity"]
        if q < lim["min_quantity"]:
            out.issues.append(Issue("quantity", "Quantity must be at least 1."))
        elif q > lim["max_quantity"]:
            out.issues.append(
                Issue("quantity", f"{q:,} is above the {lim['max_quantity']:,} I can quote online. "
                      "Please give a smaller quantity or talk to an estimator.")
            )
        else:
            k["quantity"] = q

    colors = None
    if raw.get("colors"):
        colors, problem = normalize_colors(raw["colors"])
        if problem:
            out.issues.append(Issue("colors", problem))
        else:
            k["colors"] = colors
            if not re.search(r"[0-4]\s*/\s*[0-4]", raw["colors"]):
                out.assumptions.append(f'Read "{raw["colors"]}" as {colors} ink coverage.')

    if raw.get("paper"):
        key, problem = normalize_paper(raw["paper"], product, rates)
        if problem:
            out.issues.append(Issue("paper", problem))
        else:
            k["paper"] = key

    size = None
    if raw.get("size"):
        size, problem = normalize_size(raw["size"], rates)
        if problem:
            out.issues.append(Issue("size", problem))
    if size is None and product:
        size = rates["default_sizes"][product]
        if raw.get("size") is None:
            out.assumptions.append(f"No size given; assumed {size} inches.")
    if size:
        k["size"] = size

    pages = raw.get("pages")
    if product == "booklet":
        if pages is None:
            out.missing.append("pages")
        elif pages < 8 or pages % 4:
            out.issues.append(
                Issue("pages", f"Booklets need a page count that is a multiple of 4 (at least 8); "
                      f"{pages} will not work.")
            )
        else:
            k["pages"] = pages
        k["saddle_stitch"] = raw.get("saddle_stitch") is not False

    standard = rates["standard_turnaround_business_days"]
    days = standard
    if raw.get("deadline"):
        d, problem = dl.resolve(raw["deadline"], today, standard)
        if problem:
            out.issues.append(Issue("deadline", problem))
        else:
            days = d  # type: ignore[assignment]
    k["turnaround_business_days"] = days
    if not raw.get("deadline"):
        out.assumptions.append(f"No deadline given; assumed standard turnaround ({standard} business days).")

    issue_fields = {i.field for i in out.issues}
    for f in BASE_REQUIRED:
        if f not in k and f not in issue_fields:
            out.missing.append(f)
    if product == "brochure" and "fold" not in k and "fold" not in issue_fields:
        out.missing.append("fold")
    if product == "booklet" and "pages" not in k and "pages" not in issue_fields:
        if "pages" not in out.missing:
            out.missing.append("pages")

    if not out.missing and not out.issues:
        out.spec = JobSpec(
            product=k["product"], quantity=k["quantity"], size=k["size"], colors=k["colors"],
            paper=k["paper"], fold=k.get("fold", "none"), pages=k.get("pages", 0),
            saddle_stitch=k.get("saddle_stitch", False),
            turnaround_business_days=k["turnaround_business_days"],
        )  # fmt: skip
    return out
