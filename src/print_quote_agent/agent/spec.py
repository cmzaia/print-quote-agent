"""Raw extraction schema (what the LLM returns) and the interpretation context."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpecPatch(BaseModel):
    """Fields found in ONE user message. Everything is optional and stays close to
    the user's own words; interpretation (aliases, dates, defaults) is deterministic
    code in normalize.py, not the model's job."""

    product: str | None = Field(None, description="The thing being printed, in the user's words")
    quantities: list[int] = Field(
        default_factory=list, description="Every distinct piece count mentioned, as integers"
    )
    quantity_is_correction: bool = Field(
        False, description="True if the user is changing an earlier quantity ('actually 2500')"
    )
    size: str | None = Field(None, description="Size text as written, e.g. '8.5x11' or 'letter'")
    colors: str | None = Field(None, description="Ink text as written: '4/4', 'full color', 'b&w'")
    paper: str | None = Field(None, description="Paper text as written, e.g. '100# gloss text'")
    fold: str | None = Field(None, description="Fold text as written, e.g. 'tri-fold'")
    pages: int | None = Field(None, description="Page count for booklets")
    saddle_stitch: bool | None = None
    deadline: str | None = Field(None, description="Deadline phrase as written, e.g. 'by Friday'")
    reset: bool = Field(False, description="User wants to start a new quote")


class ExtractionContext(BaseModel):
    awaiting: list[str] = []
    known: dict = {}
