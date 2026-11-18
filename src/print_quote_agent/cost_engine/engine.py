"""Deterministic offset-vs-digital cost model.

Every dollar amount in the system comes from this module. Amounts are computed in
integer cents so itemized lines always sum exactly to the total.

Simplifications (documented, deliberate):
  * each leaf of a booklet is its own press form (no ganging across forms);
  * finishing costs are identical for both processes (priced per finished piece);
  * one paper stock per job, no separate cover stock;
  * rush is a percentage of production + finishing, applied to feasible methods only.
"""

from __future__ import annotations

import math
from typing import Any

from .imposition import ups_per_sheet
from .models import (
    Crossover,
    JobSpec,
    LineItem,
    Method,
    MethodQuote,
    QuoteResult,
    parse_size,
)
from .rates import load_rates


def _cents(x: float) -> int:
    return int(round(x * 100))


def _units(spec: JobSpec) -> int:
    """Distinct press forms per copy: one flat sheet per leaf for booklets, else 1."""
    return spec.pages // 4 if spec.product == "booklet" else 1


def _flat_size(spec: JobSpec) -> tuple[float, float]:
    w, h = parse_size(spec.size)
    return (2 * w, h) if spec.product == "booklet" else (w, h)


def _sides(colors: str) -> tuple[int, int]:
    f, b = colors.split("/")
    return int(f), int(b)


def _finishing_lines(spec: JobSpec, rates: dict[str, Any]) -> list[tuple[str, int]]:
    fin = rates["finishing"]
    q = spec.quantity
    lines = [
        ("Trim to size", _cents(fin["trim"]["setup"] + fin["trim"]["per_1000_pieces"] * q / 1000))
    ]
    if spec.fold != "none" and spec.product != "booklet":
        f = fin["fold"]
        lines.append(
            (
                f"Fold ({spec.fold})",
                _cents(f["setup"] + f["per_1000_pieces"][spec.fold] * q / 1000),
            )
        )
    if spec.saddle_stitch:
        s = fin["saddle_stitch"]
        per_1000 = s["per_1000_books"] + s["per_1000_books_per_leaf"] * _units(spec)
        lines.append(("Saddle-stitch", _cents(s["setup"] + per_1000 * q / 1000)))
    return lines


def quote_method(spec: JobSpec, method: Method, rates: dict[str, Any] | None = None) -> MethodQuote:
    rates = rates or load_rates()
    cfg = rates[method]
    sheet = rates["sheets"][method]
    paper = rates["papers"][spec.paper]
    fw, fh = _flat_size(spec)
    ups = ups_per_sheet(fw, fh, sheet["width"], sheet["height"], sheet["margin"], rates["bleed"])
    lead = cfg["lead_business_days"]

    base = MethodQuote(method=method, feasible=False, ups=ups, lead_business_days=lead)
    if ups == 0:
        base.infeasible_reason = f"{spec.size} does not fit the {method} press sheet"
        return base

    units = _units(spec)
    front, back = _sides(spec.colors)
    good_per_unit = math.ceil(spec.quantity / ups)
    spoiled = math.ceil(good_per_unit * (1 + cfg["spoilage"]))
    lines: list[tuple[str, int]] = []

    if method == "offset":
        plates_per_unit = front + back
        run_per_unit = spoiled + cfg["waste_sheets_base"] + cfg["waste_sheets_per_plate"] * plates_per_unit
        total_sheets = run_per_unit * units
        plates = plates_per_unit * units
        lines.append(("Plates", _cents(plates * cfg["plate_cost"])))
        lines.append(
            (
                "Makeready",
                _cents(units * (cfg["makeready_fixed"] + cfg["makeready_per_plate"] * plates_per_unit)),
            )
        )
        lines.append(("Press run", _cents(total_sheets / 1000 * cfg["run_cost_per_1000_sheets"])))
        lines.append(("Paper", _cents(total_sheets / 1000 * paper["offset_per_1000"])))
    else:
        total_sheets = (spoiled + cfg["waste_sheets_base"]) * units
        sides = (1 if front else 0) + (1 if back else 0)
        click = cfg["click_color"] if max(front, back) >= 2 else cfg["click_bw"]
        lines.append(("Setup and file prep", _cents(cfg["setup_fee"])))
        lines.append(("Clicks", _cents(total_sheets * sides * click)))
        lines.append(("Paper", _cents(total_sheets / 1000 * paper["digital_per_1000"])))

    lines.extend(_finishing_lines(spec, rates))
    subtotal = sum(c for _, c in lines)

    feasible = spec.turnaround_business_days >= lead
    rush_pct = 0
    if feasible:
        for tier in rates["rush"]:
            if spec.turnaround_business_days <= tier["max_business_days"]:
                rush_pct = tier["pct"]
                break
        if rush_pct:
            lines.append((f"Rush surcharge ({rush_pct}%)", _cents(subtotal * rush_pct / 100)))

    total_c = sum(c for _, c in lines)
    base.feasible = feasible
    base.press_sheets = total_sheets
    base.rush_pct = rush_pct
    base.lines = [LineItem(label=n, amount=c / 100) for n, c in lines]
    base.total = total_c / 100
    base.unit_price = round(total_c / 100 / spec.quantity, 3)
    if not feasible:
        base.infeasible_reason = (
            f"{method} needs {lead} business days; {spec.turnaround_business_days} requested"
        )
    return base


def quote(spec: JobSpec, rates: dict[str, Any] | None = None) -> QuoteResult:
    """Price the job both ways and pick the cheapest method that meets the deadline."""
    rates = rates or load_rates()
    off = quote_method(spec, "offset", rates)
    dig = quote_method(spec, "digital", rates)
    ok = [q for q in (off, dig) if q.feasible and q.total is not None]
    recommended: Method | None = None
    savings = savings_pct = None
    if ok:
        best = min(ok, key=lambda q: (q.total, q.method))
        recommended = best.method
        if len(ok) == 2:
            other = max(ok, key=lambda q: (q.total, q.method))
            savings = round(other.total - best.total, 2)
            savings_pct = round(100 * savings / other.total, 1) if other.total else 0.0
    earliest = min(
        (q.lead_business_days for q in (off, dig) if q.total is not None), default=None
    )
    return QuoteResult(
        spec=spec,
        offset=off,
        digital=dig,
        recommended=recommended,
        savings=savings,
        savings_pct=savings_pct,
        earliest_business_days=earliest,
    )


def find_crossover(spec: JobSpec, rates: dict[str, Any] | None = None) -> Crossover:
    """Smallest quantity where offset total <= digital total, at standard turnaround."""
    rates = rates or load_rates()
    std = rates["standard_turnaround_business_days"]
    lim = rates["limits"]

    def totals(q: int) -> tuple[float, float] | None:
        s = spec.model_copy(update={"quantity": q, "turnaround_business_days": std})
        o, d = quote_method(s, "offset", rates), quote_method(s, "digital", rates)
        if o.total is None or d.total is None:
            return None
        return o.total, d.total

    def offset_wins(q: int) -> bool:
        t = totals(q)
        return t is not None and t[0] <= t[1]

    if totals(lim["min_quantity"]) is None:
        return Crossover(crossover_quantity=None, note="Job does not fit one of the presses.")
    if offset_wins(lim["min_quantity"]):
        q0 = lim["min_quantity"]
        o, d = totals(q0)  # type: ignore[misc]
        return Crossover(
            crossover_quantity=q0, offset_total_at_crossover=o, digital_total_at_crossover=d,
            note="Offset is already cheapest at the minimum quantity.",
        )

    prev, q = lim["min_quantity"], lim["min_quantity"]
    while q < lim["max_quantity"]:
        q = min(lim["max_quantity"], max(q + 1, int(q * 1.02)))
        if offset_wins(q):
            break
        prev = q
    else:
        if not offset_wins(lim["max_quantity"]):
            return Crossover(
                crossover_quantity=None,
                note="Digital stays cheaper up to the maximum quantity.",
            )
    lo, hi = prev, q  # offset loses at lo, wins at hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if offset_wins(mid):
            hi = mid
        else:
            lo = mid
    c = hi
    while c > lim["min_quantity"] and offset_wins(c - 1):  # guard against ceil() ripples
        c -= 1
    t = totals(c)
    assert t is not None
    return Crossover(
        crossover_quantity=c,
        offset_total_at_crossover=t[0],
        digital_total_at_crossover=t[1],
        note="Offset is cheaper at or above this quantity (standard turnaround).",
    )
