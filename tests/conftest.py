import os
from datetime import date

import pytest

os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("ANTHROPIC_API_KEY", None)

from print_quote_agent.agent import FakeProvider, QuoteAgent  # noqa: E402

MONDAY = date(2026, 11, 16)


@pytest.fixture
def agent():
    return QuoteAgent(FakeProvider(), today=MONDAY)
