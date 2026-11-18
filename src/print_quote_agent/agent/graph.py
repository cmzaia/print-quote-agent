"""The LangGraph agent.

extract -> normalize -> (ask | quote -> compare -> respond)

The model touches exactly two nodes (extract, respond's prose). Pricing, comparison,
crossover and every number in the answer are produced by tools and checked by the
grounding guardrail before the user sees them.
"""

from __future__ import annotations

import time
import uuid
from datetime import date
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..cost_engine.rates import load_rates
from . import render
from .guardrail import check_grounding
from .normalize import normalize
from .providers import Provider, get_provider
from .spec import ExtractionContext
from .tools import crossover_tool, quote_tool

RAW_KEYS = ["product", "size", "colors", "paper", "fold", "pages", "saddle_stitch", "deadline"]


class AgentState(TypedDict, total=False):
    user_input: str
    today: str
    raw: dict
    awaiting: list[str]
    known: dict
    assumptions: list[str]
    quote: dict
    facts: dict
    reply: str
    status: str
    guard: dict


def build_graph(provider: Provider, rates: dict | None = None):
    rates = rates or load_rates()

    def extract(state: AgentState) -> dict:
        raw = dict(state.get("raw") or {})
        ctx = ExtractionContext(awaiting=state.get("awaiting") or [], known=state.get("known") or {})
        patch = provider.extract_spec(state["user_input"], ctx)
        if patch.reset:
            raw = {}
        if patch.product and raw.get("product") and patch.product != raw["product"]:
            raw = {}  # a different product is a new job, not an edit
        for key in RAW_KEYS:
            val = getattr(patch, key)
            if val is not None:
                raw[key] = val
        qs = list(dict.fromkeys(patch.quantities))
        if len(qs) > 1 and not patch.quantity_is_correction:
            raw["quantity_conflict"] = sorted(qs)
            raw.pop("quantity", None)
        elif qs:
            raw["quantity"] = qs[-1]
            raw.pop("quantity_conflict", None)
        return {"raw": raw, "quote": {}, "facts": {}, "guard": {}, "reply": ""}

    def validate(state: AgentState) -> dict:
        n = normalize(state["raw"], date.fromisoformat(state["today"]), rates)
        update: dict[str, Any] = {
            "known": n.known,
            "assumptions": n.assumptions,
            "awaiting": [i.field for i in n.issues] + n.missing,
        }
        if n.ready:
            update["quote"] = {"spec": n.spec.model_dump()}
            update["known"] = n.spec.model_dump()
        else:
            update["reply"] = render.clarification(n.missing, n.issues, rates)
            update["status"] = "needs_info"
        return update

    def route(state: AgentState) -> str:
        return "quote" if state.get("quote", {}).get("spec") else END

    def quote_node(state: AgentState) -> dict:
        return {"quote": quote_tool.invoke(state["quote"]["spec"]), "awaiting": []}

    def compare(state: AgentState) -> dict:
        crossover = crossover_tool.invoke(state["quote"]["spec"])
        q = state["quote"]
        facts = {**q, "crossover": crossover}
        return {"facts": facts}

    def respond(state: AgentState) -> dict:
        facts, assumptions = state["facts"], state["assumptions"]
        try:
            prose = provider.explain(facts)
        except Exception:  # provider outage must never block a quote
            prose = ""
        raw_check = check_grounding(prose, facts) if prose else None
        used_fallback = raw_check is None or not raw_check.ok
        if used_fallback:
            prose = render.default_explanation(facts)
        answer = render.itemized_answer(facts, rates, prose, assumptions)
        final = check_grounding(answer, facts, assumptions)
        if not final.ok:  # should be impossible; fail closed rather than show bad numbers
            answer = "I could not produce a verified quote for this request. Please try again."
        return {
            "reply": answer,
            "status": "quoted" if final.ok else "error",
            "guard": {
                "llm_prose_grounded": None if raw_check is None else raw_check.ok,
                "llm_ungrounded_numbers": [] if raw_check is None else raw_check.ungrounded,
                "used_fallback": used_fallback,
                "final_grounded": final.ok,
            },
        }

    g = StateGraph(AgentState)
    g.add_node("extract", extract)
    g.add_node("validate", validate)
    g.add_node("quote", quote_node)
    g.add_node("compare", compare)
    g.add_node("respond", respond)
    g.add_edge(START, "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges("validate", route, {"quote": "quote", END: END})
    g.add_edge("quote", "compare")
    g.add_edge("compare", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


class QuoteAgent:
    """Multi-turn wrapper: one LangGraph thread per session id."""

    def __init__(self, provider: Provider | None = None, today: date | None = None) -> None:
        self.provider = provider or get_provider()
        self.rates = load_rates()
        self.graph = build_graph(self.provider, self.rates)
        self.today = today

    def new_session(self) -> str:
        return uuid.uuid4().hex[:12]

    def chat(self, session_id: str, message: str) -> dict:
        t0 = time.perf_counter()
        today = (self.today or date.today()).isoformat()
        out = self.graph.invoke(
            {"user_input": message, "today": today},
            config={"configurable": {"thread_id": session_id}},
        )
        return {
            "session_id": session_id,
            "reply": out["reply"],
            "status": out["status"],
            "awaiting": out.get("awaiting", []),
            "known": out.get("known", {}),
            "quote": out.get("quote") if out["status"] == "quoted" else None,
            "guard": out.get("guard", {}),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
