"""Vercel entrypoint: expose the FastAPI app from the src layout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from print_quote_agent.api import app  # noqa: E402,F401
