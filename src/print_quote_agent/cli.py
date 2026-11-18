"""`quote` command: chat, eval, serve."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

DEFAULT_GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden.jsonl"


def _chat(args: argparse.Namespace) -> int:
    from .agent import QuoteAgent, get_provider

    provider = get_provider(args.provider)
    today = date.fromisoformat(args.today) if args.today else None
    agent = QuoteAgent(provider, today=today)
    sid = agent.new_session()
    print(f"print-quote-agent (provider: {provider.name}). /new to restart, /quit to exit.\n")
    if args.once:
        print(agent.chat(sid, args.once)["reply"])
        return 0
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text in ("/quit", "/exit"):
            return 0
        if text == "/new":
            sid = agent.new_session()
            print("(new quote)\n")
            continue
        print("\nagent>", agent.chat(sid, text)["reply"], "\n")


def _eval(args: argparse.Namespace) -> int:
    from .evals import run_eval

    report = run_eval(Path(args.golden), provider_name=args.provider)
    print(report.markdown())
    return 0 if report.passed else 1


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("print_quote_agent.api:app", host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="quote", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="interactive CLI chat")
    c.add_argument("--provider", default=None, help="fake | anthropic | auto (default: $LLM_PROVIDER)")
    c.add_argument("--today", default=None, help="pin today's date (YYYY-MM-DD) for reproducible demos")
    c.add_argument("--once", default=None, help="answer a single message and exit")
    c.set_defaults(fn=_chat)

    e = sub.add_parser("eval", help="run the golden-set evals; non-zero exit below thresholds")
    e.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    e.add_argument("--provider", default="fake")
    e.set_defaults(fn=_eval)

    s = sub.add_parser("serve", help="run the FastAPI server and web chat")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=_serve)

    args = p.parse_args(argv)
    return args.fn(args)



