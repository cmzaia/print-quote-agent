import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from print_quote_agent.cost_engine import (
    JobSpec,
    find_crossover,
    load_rates,
    quote,
    quote_method,
    ups_per_sheet,
)

RATES = load_rates()
PAPERS = sorted(RATES["papers"])


def spec(**kw) -> JobSpec:
    base = dict(
        product="flyer", quantity=1000, size="8.5x11", colors="4/4",
        paper="gloss_text_100", turnaround_business_days=10,
    )  # fmt: skip
    base.update(kw)
    return JobSpec(**base)


specs = st.builds(
    JobSpec,
    product=st.just("flyer"),
    quantity=st.integers(1, 200_000),
    size=st.sampled_from(["8.5x11", "5.5x8.5", "4x6", "3.5x2", "11x17"]),
    colors=st.sampled_from(["4/4", "4/0", "1/1", "1/0", "2/2"]),
    paper=st.sampled_from(PAPERS),
    turnaround_business_days=st.integers(0, 15),
)


# ------------------------------------------------------------------- imposition
def test_ups_known_values():
    assert ups_per_sheet(8.5, 11, 19, 25, 0.5, 0.125) == 4
    assert ups_per_sheet(8.5, 11, 12, 18, 0.3, 0.125) == 2
    assert ups_per_sheet(3.5, 2, 19, 25, 0.5, 0.125) > 40


def test_oversize_piece_has_zero_ups():
    assert ups_per_sheet(30, 40, 19, 25, 0.5, 0.125) == 0
    q = quote_method(spec(size="20x30"), "offset")
    assert not q.feasible and q.total is None


# ------------------------------------------------------------------ line items
def test_lines_sum_exactly_to_total():
    r = quote(spec(product="brochure", fold="tri", quantity=5000))
    for m in (r.offset, r.digital):
        assert round(sum(line.amount for line in m.lines), 2) == m.total


def test_offset_has_plates_and_makeready_digital_does_not():
    r = quote(spec())
    off = {line.label for line in r.offset.lines}
    dig = {line.label for line in r.digital.lines}
    assert {"Plates", "Makeready"} <= off
    assert not ({"Plates", "Makeready"} & dig)


def test_finishing_lines_present():
    r = quote(spec(product="brochure", fold="tri"))
    assert any(line.label.startswith("Fold") for line in r.digital.lines)
    b = quote(spec(product="booklet", pages=16, saddle_stitch=True, size="8.5x11"))
    assert any(line.label == "Saddle-stitch" for line in b.offset.lines)
    assert any(line.label == "Trim to size" for line in b.offset.lines)


def test_more_plates_cost_more_on_offset():
    one = quote_method(spec(colors="1/0"), "offset").total
    four = quote_method(spec(colors="4/4"), "offset").total
    assert four > one


# ----------------------------------------------------------- lead time and rush
def test_offset_infeasible_when_deadline_too_tight():
    r = quote(spec(turnaround_business_days=4))
    assert not r.offset.feasible and "5 business days" in r.offset.infeasible_reason
    assert r.recommended == "digital"


def test_rush_surcharge_tiers():
    std = quote_method(spec(turnaround_business_days=10), "digital")
    r3 = quote_method(spec(turnaround_business_days=3), "digital")
    r1 = quote_method(spec(turnaround_business_days=1), "digital")
    assert std.rush_pct == 0 and r3.rush_pct == 25 and r1.rush_pct == 50
    assert r3.total > std.total and r1.total > r3.total


def test_nothing_feasible_same_day():
    r = quote(spec(turnaround_business_days=0))
    assert r.recommended is None and r.earliest_business_days == 1


# ------------------------------------------------------------------- crossover
def test_crossover_exists_for_standard_job_and_is_the_first_flip():
    s = spec(product="brochure", fold="tri")
    c = find_crossover(s).crossover_quantity
    assert c is not None and c > 1

    def wins(q):
        r = quote(s.model_copy(update={"quantity": q}))
        return r.offset.total <= r.digital.total

    assert wins(c) and not wins(c - 1)
    assert wins(c * 3)


def test_small_runs_favor_digital_large_runs_favor_offset():
    assert quote(spec(quantity=100)).recommended == "digital"
    assert quote(spec(quantity=50_000)).recommended == "offset"


# ---------------------------------------------------------------- properties
@settings(max_examples=60, deadline=None)
@given(specs, st.integers(1, 100_000), st.integers(1, 100_000))
def test_monotonic_in_quantity(s, a, b):
    lo, hi = sorted((a, b))
    for method in ("offset", "digital"):
        qa = quote_method(s.model_copy(update={"quantity": lo}), method)
        qb = quote_method(s.model_copy(update={"quantity": hi}), method)
        if qa.total is not None:
            assert qb.total >= qa.total


@settings(max_examples=100, deadline=None)
@given(specs)
def test_never_negative(s):
    r = quote(s)
    for m in (r.offset, r.digital):
        if m.total is not None:
            assert m.total >= 0 and all(line.amount >= 0 for line in m.lines)
            assert m.unit_price >= 0


@settings(max_examples=30, deadline=None)
@given(specs)
def test_crossover_is_consistent(s):
    s = s.model_copy(update={"turnaround_business_days": 10})
    c = find_crossover(s)
    if c.crossover_quantity is not None and c.crossover_quantity > 1:
        q = c.crossover_quantity
        at = quote(s.model_copy(update={"quantity": q}))
        before = quote(s.model_copy(update={"quantity": q - 1}))
        assert at.offset.total <= at.digital.total
        assert before.offset.total > before.digital.total


def test_invalid_specs_rejected():
    with pytest.raises(ValueError):
        spec(quantity=0)
    with pytest.raises(ValueError):
        spec(colors="0/0")
    with pytest.raises(ValueError):
        spec(size="big")
