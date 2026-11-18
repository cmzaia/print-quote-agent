from datetime import date

from print_quote_agent.agent import FakeProvider, QuoteAgent, render
from print_quote_agent.agent.guardrail import check_grounding, collect_numbers
from print_quote_agent.cost_engine import JobSpec, find_crossover
from print_quote_agent.cost_engine import quote as engine_quote

FRIDAY_REQ = "5k tri-fold brochures, 4/4, 100# gloss, need by Friday"


def test_one_shot_quote_matches_engine_exactly(agent):
    r = agent.chat("s1", FRIDAY_REQ)
    assert r["status"] == "quoted"
    spec = JobSpec(**r["quote"]["spec"])
    assert spec.quantity == 5000 and spec.turnaround_business_days == 4
    expected = engine_quote(spec)
    assert r["quote"]["digital"]["total"] == expected.digital.total
    assert r["quote"]["recommended"] == "digital"
    assert f"${expected.digital.total:,.2f}" in r["reply"]
    assert "Offset needs 5 business days" in r["reply"]


def test_multi_turn_asks_then_quotes(agent):
    r1 = agent.chat("s", "I need brochures")
    assert r1["status"] == "needs_info" and "quantity" in r1["awaiting"]
    r2 = agent.chat("s", "tri-fold, 3000")
    assert r2["status"] == "needs_info" and "quantity" not in r2["awaiting"]
    r3 = agent.chat("s", "4/4 100# gloss text")
    assert r3["status"] == "quoted" and r3["quote"]["spec"]["quantity"] == 3000


def test_followup_changes_quantity_and_requotes(agent):
    a = agent.chat("s", "1000 flyers 4/4 100# gloss text")
    b = agent.chat("s", "what about 50000 instead?")
    assert a["status"] == b["status"] == "quoted"
    assert a["quote"]["recommended"] == "digital" and b["quote"]["recommended"] == "offset"


def test_conflicting_quantities_trigger_a_question(agent):
    r = agent.chat("s", "500 or 5000 flyers 4/4 100# gloss text")
    assert r["status"] == "needs_info" and "500" in r["reply"] and "5,000" in r["reply"]


def test_vague_request_asks_and_never_quotes(agent):
    r = agent.chat("s", "just make it cheap")
    assert r["status"] == "needs_info" and r["quote"] is None


def test_sessions_are_isolated(agent):
    agent.chat("a", "1000 flyers")
    r = agent.chat("b", "4/4 100# gloss text")
    assert r["status"] == "needs_info" and "product" in r["awaiting"]


# ------------------------------------------------------------------ guardrail
def test_grounding_check_unit():
    facts = {"total": 755.68, "qty": 5000, "label": "100# gloss"}
    assert check_grounding("That is $755.68 for 5,000 on 100# gloss.", facts).ok
    bad = check_grounding("That is $700.00 for 5,000.", facts)
    assert not bad.ok and bad.ungrounded == [700.0]
    assert 100 in collect_numbers(facts)


class HallucinatingProvider(FakeProvider):
    """Simulates an LLM that invents a discount and does its own arithmetic."""

    name = "hallucinator"

    def explain(self, facts: dict) -> str:
        return "Great news, I knocked 61% off, so you pay $123.45 total."


def test_hallucinated_numbers_are_blocked_and_replaced():
    agent = QuoteAgent(HallucinatingProvider(), today=date(2026, 11, 16))
    r = agent.chat("s", FRIDAY_REQ)
    assert r["status"] == "quoted"
    assert r["guard"]["llm_prose_grounded"] is False
    assert set(r["guard"]["llm_ungrounded_numbers"]) >= {61.0, 123.45}
    assert r["guard"]["used_fallback"] and r["guard"]["final_grounded"]
    assert "123.45" not in r["reply"] and "61%" not in r["reply"]


class BrokenProvider(FakeProvider):
    def explain(self, facts):
        raise TimeoutError("provider down")


def test_provider_outage_still_returns_a_verified_quote():
    agent = QuoteAgent(BrokenProvider(), today=date(2026, 11, 16))
    r = agent.chat("s", FRIDAY_REQ)
    assert r["status"] == "quoted" and r["guard"]["final_grounded"]


def test_every_number_in_every_final_answer_is_grounded(agent):
    for i, msg in enumerate([
        FRIDAY_REQ, "1000 flyers 4/4 100# gloss text", "50k postcards 4/4 14pt",
        "16 page booklet 500 copies 4/4 100# gloss text", "800 flyers 4/4 100# gloss text same day",
    ]):  # fmt: skip
        r = agent.chat(f"g{i}", msg)
        assert r["status"] == "quoted" and r["guard"]["final_grounded"], msg
        # independent re-check of the whole reply against fresh engine output
        spec = JobSpec(**r["quote"]["spec"])
        sources = (engine_quote(spec).model_dump(), find_crossover(spec).model_dump())
        assert check_grounding(r["reply"], *sources).ok, (msg, r["reply"])


def test_render_has_no_arithmetic_inputs():
    # the renderer only formats; it must not import the engine's compute functions
    import inspect

    src = inspect.getsource(render)
    assert "quote_method" not in src and "find_crossover" not in src
