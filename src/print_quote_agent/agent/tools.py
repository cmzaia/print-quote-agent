"""The cost engine exposed as LangChain tools. These are the ONLY source of numbers."""

from __future__ import annotations

from langchain_core.tools import tool

from ..cost_engine import JobSpec, find_crossover
from ..cost_engine import quote as engine_quote


@tool("quote", args_schema=JobSpec)
def quote_tool(**kwargs) -> dict:
    """Price a fully specified print job with the shop's rates, offset and digital,
    itemized, with lead-time feasibility and the cheaper feasible method."""
    return engine_quote(JobSpec(**kwargs)).model_dump()


@tool("find_crossover", args_schema=JobSpec)
def crossover_tool(**kwargs) -> dict:
    """Find the smallest quantity at which offset becomes cheaper than digital."""
    return find_crossover(JobSpec(**kwargs)).model_dump()


TOOLS = [quote_tool, crossover_tool]
