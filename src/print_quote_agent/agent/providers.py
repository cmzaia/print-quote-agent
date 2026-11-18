"""LLM providers. The agent only needs two capabilities from a model:

  extract_spec(text, ctx) -> SpecPatch   find fields in the user's words
  explain(facts)          -> str         phrase the reasoning from tool output

Neither one is allowed to do arithmetic. `FakeProvider` is a deterministic
rule-based stand-in so tests, evals and CI run with no API key.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

from . import deadline as dl
from .normalize import FINISHES, PRODUCT_WORDS
from .render import default_explanation
from .spec import ExtractionContext, SpecPatch


class Provider(Protocol):
    name: str

    def extract_spec(self, text: str, ctx: ExtractionContext) -> SpecPatch: ...

    def explain(self, facts: dict) -> str: ...


# --------------------------------------------------------------------------- fake

UNSUPPORTED = r"posters?|banners?|stickers?|labels?|t-?shirts?|mugs?|signs?|invitations?|envelopes?"
_STRIP = [
    r"\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?",                  # sizes
    r"\b[0-4]\s*/\s*[0-4]\b",                                   # 4/4
    r"\d+\s*(?:#|lbs?\b|pounds?\b|pt\b|gsm\b)",                 # paper weights
    r"\d+\s*[- ]?(?:pages?|pp|pgs?)\b",                         # page counts
    r"\d+\s*(?:business\s+|working\s+)?(?:days?|weeks?|hours?|hrs?)\b",  # durations
    r"\d+\s*(?:st|nd|rd|th)\b",                                 # ordinals
    r"\b\d+\s*[- ]?sided\b",
    r"\d+(?:\.\d+)?\s*%",
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}",  # dates
    r"\b(?:4|four)[- ]colou?r\b",
]
_QTY = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k\b|thousand\b|million\b)?", re.IGNORECASE)
_CORRECTION = re.compile(
    r"\b(actually|no wait|make (?:it|that)|change (?:it |that )?to|instead|sorry|scratch that|correction)\b",
    re.IGNORECASE,
)


class FakeProvider:
    """Regex and rules. Deliberately simple: it is the baseline the evals measure."""

    name = "fake"

    def extract_spec(self, text: str, ctx: ExtractionContext) -> SpecPatch:
        t = text.strip()
        low = t.lower()
        p = SpecPatch()

        if re.search(r"\b(start over|new quote|reset|never ?mind)\b", low):
            p.reset = True

        for key, pat in PRODUCT_WORDS.items():
            if re.search(rf"\b(?:{pat})\b", low):
                p.product = key
                break
        if p.product is None:
            m = re.search(rf"\b({UNSUPPORTED})\b", low)
            if m:
                p.product = m.group(1)

        m = re.search(r"\b(tri|z|half|bi|letter)[- ]?fold(?:ed)?\b", low) or re.search(
            r"\bfolded in half\b", low
        )
        if m:
            p.fold = m.group(0)

        m = re.search(r"\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?", low) or re.search(
            r"\b(letter|legal|tabloid|half[- ]letter)\b", low
        )
        if m:
            p.size = m.group(0)

        m = re.search(r"\b[0-4]\s*/\s*[0-4]\b", low)
        if m:
            p.colors = m.group(0)
        else:
            m = re.search(
                r"full[- ]?colou?r|four[- ]colou?r|cmyk|black (?:and|&) white|black & white|b\s*&\s*w|"
                r"b/w|grayscale|one[- ]colou?r",
                low,
            )
            if m:
                p.colors = m.group(0)
                side = re.search(r"one[- ]side|single[- ]sided|front only|1[- ]sided", low)
                if side:
                    p.colors += " one side"

        m = re.search(
            r"\d{2,3}\s*(?:#|lbs?\b|pounds?\b)\.?\s*(?:gloss|glossy|matte|silk|uncoated)?"
            r"(?:\s*(?:text|cover|card ?stock))?",
            low,
        ) or re.search(r"\b1[46]\s*pt\b(?:\s*(?:gloss|matte))?|\bcard ?stock\b", low)
        if m:
            p.paper = m.group(0).strip()
            fin = re.search(rf"\b({'|'.join(FINISHES)})\b", low)
            if fin and not re.search(r"gloss|matte|silk|uncoated|glossy|matt|satin|plain", p.paper):
                p.paper += f" {fin.group(1)}"
                tk = re.search(r"\b(text|cover)\b", low)
                if tk:
                    p.paper += f" {tk.group(1)}"
        else:
            fin = re.search(rf"\b({'|'.join(FINISHES)})\b", low)
            if fin:
                p.paper = fin.group(1)

        m = re.search(r"(\d+)\s*[- ]?(?:pages?|pp|pgs?)\b", low)
        if m:
            p.pages = int(m.group(1))
        if re.search(r"saddle[- ]?stitch|stapled", low):
            p.saddle_stitch = True

        p.deadline = dl.find_phrase(t)

        scrubbed = low
        for pat in _STRIP:
            scrubbed = re.sub(pat, " ", scrubbed)
        if p.deadline:
            scrubbed = scrubbed.replace(p.deadline.lower(), " ")
        for m in _QTY.finditer(scrubbed):
            n = float(m.group(1).replace(",", ""))
            if m.group(2):
                n *= 1_000_000 if m.group(2).lower() == "million" else 1000
            p.quantities.append(int(n))
        p.quantities = list(dict.fromkeys(p.quantities))
        p.quantity_is_correction = bool(_CORRECTION.search(low))

        # A bare number answers whatever we just asked about.
        if p.quantities and ctx.awaiting:
            bare = re.fullmatch(r"\s*[\d,.]+\s*(k|thousand)?\s*(?:please|pls)?\.?\s*", low)
            if bare and "quantity" not in ctx.awaiting and "pages" in ctx.awaiting:
                p.pages, p.quantities = p.quantities[0], []
        return p

    def explain(self, facts: dict) -> str:
        return default_explanation(facts)


# ----------------------------------------------------------------------- anthropic

EXTRACT_SYSTEM = (
    "You extract print-job fields from a customer message. Return only what the message says; "
    "never guess missing fields and never compute prices. Keep paper, colors, size, fold and "
    "deadline in the customer's own words. List every distinct quantity mentioned in `quantities`."
)
EXPLAIN_SYSTEM = (
    "You are a print estimator writing 2-4 plain-English sentences that justify a recommendation. "
    "You are given JSON produced by a pricing tool. Use ONLY numbers that appear in that JSON, "
    "copied verbatim. Never add, subtract, multiply, round or estimate anything. If a number you "
    "want is not in the JSON, leave it out."
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        from langchain_anthropic import ChatAnthropic  # lazy: only needed with a real key

        self.llm = ChatAnthropic(
            model=model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            temperature=0,
            max_tokens=600,
        )
        self._extractor = self.llm.with_structured_output(SpecPatch)

    def extract_spec(self, text: str, ctx: ExtractionContext) -> SpecPatch:
        hint = f"We are waiting for: {', '.join(ctx.awaiting)}." if ctx.awaiting else ""
        return self._extractor.invoke(
            [("system", EXTRACT_SYSTEM + " " + hint), ("human", text)]
        )

    def explain(self, facts: dict) -> str:
        msg = self.llm.invoke(
            [("system", EXPLAIN_SYSTEM), ("human", json.dumps(facts, default=str))]
        )
        return msg.content if isinstance(msg.content, str) else str(msg.content)


def get_provider(name: str | None = None) -> Provider:
    name = (name or os.environ.get("LLM_PROVIDER") or "auto").lower()
    if name == "auto":
        name = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "fake"
    if name == "fake":
        return FakeProvider()
    if name == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicProvider()
    raise ValueError(f"unknown LLM_PROVIDER: {name!r} (use fake, anthropic or auto)")
