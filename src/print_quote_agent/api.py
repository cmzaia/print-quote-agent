"""FastAPI surface: POST /chat for the agent, POST /quote for the bare engine."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agent import QuoteAgent
from .cost_engine import JobSpec, find_crossover
from .cost_engine import quote as engine_quote

app = FastAPI(title="print-quote-agent", version="0.1.0")
WEB = Path(__file__).with_name("web")


@lru_cache(maxsize=1)
def get_agent() -> QuoteAgent:
    return QuoteAgent()


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    today: date | None = None  # for reproducible demos
    state: dict | None = None  # conversation state echoed by the previous reply (stateless hosting)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "provider": get_agent().provider.name}


@app.post("/chat")
def chat(body: ChatIn) -> dict:
    agent = get_agent()
    sid = body.session_id or agent.new_session()
    if body.today:
        agent.today = body.today
    return agent.chat(sid, body.message, body.state)


@app.post("/quote")
def quote_endpoint(spec: JobSpec) -> dict:
    """Deterministic engine only, no LLM involved."""
    return {
        "quote": engine_quote(spec).model_dump(),
        "crossover": find_crossover(spec).model_dump(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
