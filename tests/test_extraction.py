import pytest

from print_quote_agent.agent import FakeProvider
from print_quote_agent.agent.spec import ExtractionContext

P = FakeProvider()
CTX = ExtractionContext()


@pytest.mark.parametrize(
    "text,qty",
    [("5k flyers", [5000]), ("2.5k flyers", [2500]), ("1,000 flyers", [1000]),
     ("5 thousand flyers", [5000]), ("500 or 5000 flyers", [500, 5000]),
     ("100# gloss 4/4 8.5x11 16 page 3 days", []), ("2 million flyers", [2_000_000])],
)  # fmt: skip
def test_quantity_extraction_ignores_non_quantities(text, qty):
    assert P.extract_spec(text, CTX).quantities == qty


def test_extracts_full_example():
    p = P.extract_spec("5k tri-fold brochures, 4/4, 100# gloss, need by Friday", CTX)
    assert (p.product, p.fold, p.colors, p.paper, p.deadline) == (
        "brochure", "tri-fold", "4/4", "100# gloss", "need by Friday",
    )


def test_bare_number_answers_pages_when_awaiting_pages():
    p = P.extract_spec("16", ExtractionContext(awaiting=["pages"]))
    assert p.pages == 16 and p.quantities == []
