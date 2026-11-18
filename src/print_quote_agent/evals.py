"""Golden-set evals. Five metrics, hard thresholds, markdown report.

Golden line (JSONL):
  id, category, turns[str], asks[bool] (should the agent ask a question after each turn),
  expected_status ("quoted" | "needs_info") for the final turn, expected_spec (normalized
  fields; complete for quoted cases, a subset for needs_info cases).

"Recommendation correctness" does not trust the agent's own spec: the expected method is
computed by calling the cost engine directly on the golden expected_spec.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agent import QuoteAgent, get_provider
from .cost_engine import JobSpec
from .cost_engine import quote as engine_quote

EVAL_TODAY = date(2026, 11, 16)  # a Monday, so "Friday" is 4 business days away

THRESHOLDS = {
    "extraction_accuracy": 0.90,
    "clarification_precision": 0.90,
    "clarification_recall": 0.90,
    "recommendation_correctness": 0.95,
    "grounding_pass_rate": 1.00,
    "latency_p95_ms": 500.0,
}


@dataclass
class Report:
    n_cases: int
    n_turns: int
    metrics: dict[str, float]
    failures: list[str] = field(default_factory=list)
    provider: str = "fake"

    @property
    def passed(self) -> bool:
        for k, floor in THRESHOLDS.items():
            v = self.metrics[k]
            if k == "latency_p95_ms":
                if v > floor:
                    return False
            elif v < floor:
                return False
        return True

    def markdown(self) -> str:
        m = self.metrics
        rows = [
            ("Spec-extraction accuracy (field level)", f"{m['extraction_accuracy']:.1%}", ">= 90%", m["extraction_accuracy"] >= 0.90),
            ("Clarification precision (asks only when it should)", f"{m['clarification_precision']:.1%}", ">= 90%", m["clarification_precision"] >= 0.90),
            ("Clarification recall (asks when it should)", f"{m['clarification_recall']:.1%}", ">= 90%", m["clarification_recall"] >= 0.90),
            ("Recommendation correctness vs engine", f"{m['recommendation_correctness']:.1%}", ">= 95%", m["recommendation_correctness"] >= 0.95),
            ("Numeric grounding, final answers", f"{m['grounding_pass_rate']:.1%}", "100%", m["grounding_pass_rate"] >= 1.0),
            ("Numeric grounding, raw model prose (before fallback)", f"{m['raw_prose_grounding']:.1%}", "info", True),
            ("Latency p50 per turn", f"{m['latency_p50_ms']:.1f} ms", "info", True),
            ("Latency p95 per turn", f"{m['latency_p95_ms']:.1f} ms", "<= 500 ms", m["latency_p95_ms"] <= 500),
        ]  # fmt: skip
        out = [
            f"### Eval report ({self.n_cases} cases, {self.n_turns} turns, provider: {self.provider})",
            "",
            "| Metric | Result | Threshold | Status |",
            "|---|---|---|---|",
        ]
        out += [f"| {a} | {b} | {c} | {'PASS' if ok else 'FAIL'} |" for a, b, c, ok in rows]
        out += ["", f"**Overall: {'PASS' if self.passed else 'FAIL'}**"]
        if self.failures:
            out += ["", "Misses:"] + [f"- {f}" for f in self.failures]
        return "\n".join(out)


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_eval(path: Path, provider_name: str = "fake") -> Report:
    cases = load_golden(path)
    provider = get_provider(provider_name)
    agent = QuoteAgent(provider, today=EVAL_TODAY)

    field_hits = field_total = 0
    tp = fp = fn = 0
    rec_ok = rec_total = 0
    grounded = quoted = 0
    raw_grounded = raw_total = 0
    latencies: list[float] = []
    failures: list[str] = []
    n_turns = 0

    for case in cases:
        sid = agent.new_session()
        last: dict = {}
        for i, turn in enumerate(case["turns"]):
            last = agent.chat(sid, turn)
            n_turns += 1
            latencies.append(last["latency_ms"])
            asked = last["status"] == "needs_info"
            should = case["asks"][i]
            tp += asked and should
            fp += asked and not should
            fn += (not asked) and should
            if asked != should:
                failures.append(f"{case['id']} turn {i + 1}: asked={asked}, expected {should}")

        for k, v in case["expected_spec"].items():
            field_total += 1
            got = last["known"].get(k)
            if got == v:
                field_hits += 1
            else:
                failures.append(f"{case['id']}: {k} expected {v!r}, got {got!r}")

        if case["expected_status"] == "quoted":
            expected = engine_quote(JobSpec(**case["expected_spec"])).recommended
            got_rec = last["quote"]["recommended"] if last["quote"] else None
            rec_total += 1
            if last["status"] == "quoted" and got_rec == expected:
                rec_ok += 1
            else:
                failures.append(f"{case['id']}: recommended {got_rec!r}, engine says {expected!r}")
        if last["status"] == "quoted":
            quoted += 1
            grounded += bool(last["guard"].get("final_grounded"))
            g = last["guard"].get("llm_prose_grounded")
            if g is not None:
                raw_total += 1
                raw_grounded += bool(g)

    lat = sorted(latencies)
    metrics = {
        "extraction_accuracy": field_hits / field_total if field_total else 1.0,
        "clarification_precision": tp / (tp + fp) if tp + fp else 1.0,
        "clarification_recall": tp / (tp + fn) if tp + fn else 1.0,
        "recommendation_correctness": rec_ok / rec_total if rec_total else 1.0,
        "grounding_pass_rate": grounded / quoted if quoted else 1.0,
        "raw_prose_grounding": raw_grounded / raw_total if raw_total else 1.0,
        "latency_p50_ms": statistics.median(lat) if lat else 0.0,
        "latency_p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0.0,
    }
    return Report(len(cases), n_turns, metrics, failures, provider.name)
