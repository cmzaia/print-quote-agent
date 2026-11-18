"""Deterministic text: itemized quote, clarifying questions, template reasoning."""

from __future__ import annotations

from ..cost_engine.models import MethodQuote
from .normalize import Issue, paper_options

LABELS = {
    "product": "What are we printing (flyers, brochures, postcards, business cards or booklets)?",
    "quantity": "How many do you need?",
    "colors": "What ink coverage: full color both sides (4/4), full color one side (4/0), or black and white?",
    "fold": "How should it fold: half, tri-fold or z-fold?",
    "pages": "How many pages is the booklet (a multiple of 4)?",
}


def money(x: float) -> str:
    return f"${x:,.2f}"


def pretty_spec(spec: dict, rates: dict) -> str:
    paper = rates["papers"][spec["paper"]]["label"]
    prod = spec["product"].replace("_", " ")
    prod = f"{spec['fold']}-fold {prod}" if spec["fold"] != "none" else prod
    pages = f", {spec['pages']} pages" if spec["pages"] else ""
    return (
        f"{spec['quantity']:,} x {prod} ({spec['size']} in{pages}), {spec['colors']}, {paper}"
    )


def clarification(missing: list[str], issues: list[Issue], rates: dict) -> str:
    qs: list[str] = [i.message for i in issues]
    for f in missing:
        if f == "paper":
            qs.append(
                "Which paper? Common choices: "
                + ", ".join(paper_options(rates)[:5])
                + "."
            )
        else:
            qs.append(LABELS[f])
    if not qs:
        qs = ["What would you like to print?"]
    if len(qs) == 1:
        return qs[0]
    return "A few quick questions before I can price this:\n" + "\n".join(
        f"{i}. {q}" for i, q in enumerate(qs, 1)
    )


def itemize(q: MethodQuote) -> str:
    name = q.method.capitalize()
    if q.total is None:
        return f"{name}: not possible. {q.infeasible_reason}"
    head = f"{name}: {money(q.total)}  (${q.unit_price:.3f} each)"
    if not q.feasible:
        head += f"  [unavailable: {q.infeasible_reason}]"
    body = "\n".join(f"  {line.label:<28}{money(line.amount):>12}" for line in q.lines)
    return head + "\n" + body


def default_explanation(facts: dict) -> str:
    rec = facts["recommended"]
    off, dig, x = facts["offset"], facts["digital"], facts["crossover"]
    spec = facts["spec"]
    if rec is None:
        return (
            "I cannot meet that deadline with either process. The fastest option is "
            f"{facts['earliest_business_days']} business day(s)."
        )
    other = "offset" if rec == "digital" else "digital"
    other_q = off if other == "offset" else dig
    rec_q = off if rec == "offset" else dig
    parts: list[str] = []
    if not other_q["feasible"]:
        parts.append(
            f"I recommend {rec}. {other.capitalize()} needs {other_q['lead_business_days']} "
            f"business days and you asked for {spec['turnaround_business_days']}, so {rec} is the "
            "option that makes the date."
        )
    else:
        parts.append(
            f"I recommend {rec}: {money(rec_q['total'])} against {money(other_q['total'])} for "
            f"{other}, a saving of {money(facts['savings'])} ({facts['savings_pct']}%)."
        )
    if rec_q["rush_pct"]:
        parts.append(f"That price includes a {rec_q['rush_pct']}% rush surcharge.")
    cq = x["crossover_quantity"]
    if cq is not None and cq > 1:
        side = "cheaper" if spec["quantity"] >= cq else "more expensive"
        parts.append(
            f"Offset carries fixed plate and makeready costs, so it only becomes cheaper than "
            f"digital from about {cq:,} pieces; at {spec['quantity']:,} offset is {side} "
            "on cost at standard turnaround."
        )
    elif cq is None:
        parts.append("Digital stays cheaper at every quantity I can quote for this spec.")
    return " ".join(parts)


def itemized_answer(
    facts: dict, rates: dict, explanation: str, assumptions: list[str]
) -> str:
    off, dig = MethodQuote(**facts["offset"]), MethodQuote(**facts["digital"])
    rec = facts["recommended"]
    order = [dig, off] if rec == "digital" else [off, dig]
    blocks = [itemize(q) for q in order]
    out = [
        f"Quote for {pretty_spec(facts['spec'], rates)}",
        "",
        explanation,
        "",
        blocks[0],
        "",
        blocks[1],
    ]
    if assumptions:
        out += ["", "Assumptions: " + " ".join(assumptions)]
    return "\n".join(out)
