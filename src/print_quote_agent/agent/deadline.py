"""Turn deadline phrases ("by Friday", "in 3 days", "asap") into business days.

Deterministic on purpose: the LLM only has to *find* the phrase, never interpret a date.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_WD = r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*"
_MO = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

DEADLINE_RE = re.compile(
    r"\b(?:"
    r"asap|rush(?:ed)?|urgent(?:ly)?|immediately|same[- ]day|next[- ]day|tomorrow|today"
    r"|yesterday|no rush|not in a rush|flexible|standard turnaround|next week|end of (?:the )?week"
    rf"|(?:by|before|on|for|due|need(?:ed)?(?: by)?)\s+(?:next\s+)?{_WD}"
    r"|(?:in|within)\s+\d+\s*(?:business\s+days?|working\s+days?|days?|weeks?)"
    rf"|(?:by|before|on|for|due)?\s*{_MO}\s+\d{{1,2}}(?:st|nd|rd|th)?"
    r")\b",
    re.IGNORECASE,
)

STANDARD_PHRASES = ("no rush", "not in a rush", "flexible", "standard turnaround")
ASAP_PHRASES = ("asap", "rush", "urgent", "immediately")


def business_days_between(start: date, end: date) -> int:
    """Business days after `start` up to and including `end` (0 if end <= start)."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def find_phrase(text: str) -> str | None:
    m = DEADLINE_RE.search(text)
    return m.group(0).strip() if m else None


def resolve(phrase: str, today: date, standard: int) -> tuple[int | None, str | None]:
    """Return (business_days, problem). Exactly one of them is None."""
    p = phrase.lower().strip()
    if any(k in p for k in STANDARD_PHRASES):
        return standard, None
    if "yesterday" in p:
        return None, "That date is already in the past."
    if any(k in p for k in ASAP_PHRASES):
        return 2, None
    if "same day" in p or "same-day" in p or p == "today":
        return 0, None
    if "next day" in p or "next-day" in p or p == "tomorrow":
        return business_days_between(today, today + timedelta(days=1)), None
    if "next week" in p:
        return 5, None
    if "end of" in p:
        return business_days_between(today, _next_weekday(today, 4, strict=False)), None
    m = re.search(r"(?:in|within)\s+(\d+)\s*(business|working)?\s*(days?|weeks?)", p)
    if m:
        n = int(m.group(1))
        if m.group(3).startswith("week"):
            return business_days_between(today, today + timedelta(days=7 * n)), None
        if m.group(2):
            return n, None
        return business_days_between(today, today + timedelta(days=n)), None
    m = re.search(_WD, p)
    if m:
        wd = WEEKDAYS.index(m.group(1)[:3])
        target = _next_weekday(today, wd, strict=False)
        if "next " in p and target <= today + timedelta(days=(6 - today.weekday())):
            target += timedelta(days=7)
        return business_days_between(today, target), None
    m = re.search(_MO + r"\s+(\d{1,2})", p)
    if m:
        month, day = MONTHS.index(m.group(1)[:3]) + 1, int(m.group(2))
        try:
            target = date(today.year, month, day)
        except ValueError:
            return None, "I could not read that date."
        if target < today:
            return None, "That date is already in the past."
        return business_days_between(today, target), None
    return None, "I could not read that deadline."


def _next_weekday(today: date, wd: int, strict: bool) -> date:
    delta = (wd - today.weekday()) % 7
    if strict and delta == 0:
        delta = 7
    return today + timedelta(days=delta)
