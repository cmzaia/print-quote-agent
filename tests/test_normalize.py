from datetime import date

import pytest

from print_quote_agent.agent import deadline as dl
from print_quote_agent.agent.normalize import normalize, normalize_colors, normalize_paper
from print_quote_agent.cost_engine import load_rates

RATES = load_rates()
MON = date(2026, 11, 16)


@pytest.mark.parametrize(
    "text,product,key",
    [
        ("100# gloss text", "flyer", "gloss_text_100"),
        ("100# gloss", "brochure", "gloss_text_100"),
        ("100 lb glossy", "flyer", "gloss_text_100"),
        ("100# gloss cover", "postcard", "gloss_cover_100"),
        ("100# matte", "postcard", "matte_cover_100"),
        ("100# silk", "brochure", "matte_text_100"),
        ("14pt", "postcard", "gloss_cover_100"),
        ("16pt gloss", "business_card", "gloss_cover_130"),
        ("70# uncoated", "flyer", "uncoated_text_70"),
        ("80 pound uncoated text", "flyer", "uncoated_text_80"),
    ],
)
def test_paper_aliases(text, product, key):
    assert normalize_paper(text, product, RATES) == (key, None)


@pytest.mark.parametrize("text", ["gloss", "100#", "55# gloss text", "recycled"])
def test_paper_problems_ask_instead_of_guess(text):
    key, problem = normalize_paper(text, "flyer", RATES)
    assert key is None and problem


@pytest.mark.parametrize(
    "text,expected",
    [("4/4", "4/4"), ("4 / 0", "4/0"), ("full color", "4/4"), ("full color one side", "4/0"),
     ("black and white", "1/1"), ("b&w", "1/1")],
)  # fmt: skip
def test_colors(text, expected):
    assert normalize_colors(text)[0] == expected


@pytest.mark.parametrize(
    "phrase,days",
    [("by Friday", 4), ("tomorrow", 1), ("in 3 days", 3), ("in 10 days", 8), ("asap", 2),
     ("next week", 5), ("no rush", 10), ("in 2 weeks", 10), ("by Nov 20", 4), ("by next Friday", 9),
     ("same day", 0)],
)  # fmt: skip
def test_deadlines(phrase, days):
    assert dl.resolve(phrase, MON, 10) == (days, None)


def test_past_deadline_is_a_problem():
    days, problem = dl.resolve("yesterday", MON, 10)
    assert days is None and problem


def test_tri_fold_brochure_defaults_and_missing():
    raw = {"product": "brochures", "quantity": 5000, "colors": "4/4", "paper": "100# gloss",
           "fold": "tri-fold", "deadline": "by Friday"}  # fmt: skip
    n = normalize(raw, MON, RATES)
    assert n.ready and n.spec.size == "8.5x11" and n.spec.turnaround_business_days == 4
    assert normalize({"product": "brochure"}, MON, RATES).missing == [
        "quantity", "colors", "paper", "fold",
    ]


def test_booklet_pages_must_be_multiple_of_four():
    raw = {"product": "booklet", "quantity": 100, "colors": "4/4", "paper": "100# gloss text", "pages": 10}
    n = normalize(raw, MON, RATES)
    assert not n.ready and n.issues[0].field == "pages"
