import os

import pytest
from fastapi.testclient import TestClient

from print_quote_agent.agent import get_provider
from print_quote_agent.api import app
from print_quote_agent.cli import main
from print_quote_agent.evals import THRESHOLDS, run_eval

client = TestClient(app)


def test_health_and_index():
    assert client.get("/health").json()["provider"] == "fake"
    r = client.get("/")
    assert r.status_code == 200 and "Print quote agent" in r.text


def test_chat_endpoint_multi_turn():
    r1 = client.post("/chat", json={"message": "2000 flyers", "today": "2026-11-16"}).json()
    assert r1["status"] == "needs_info"
    r2 = client.post(
        "/chat", json={"message": "4/4 100# gloss text", "session_id": r1["session_id"]}
    ).json()
    assert r2["status"] == "quoted" and r2["quote"]["recommended"] in ("offset", "digital")


def test_bare_quote_endpoint_is_engine_only():
    body = {"product": "flyer", "quantity": 1000, "size": "8.5x11", "colors": "4/4",
            "paper": "gloss_text_100"}  # fmt: skip
    j = client.post("/quote", json=body).json()
    assert j["quote"]["recommended"] == "digital" and j["crossover"]["crossover_quantity"]
    assert client.post("/quote", json={**body, "quantity": 0}).status_code == 422


def test_cli_one_shot(capsys):
    assert main(["chat", "--provider", "fake", "--today", "2026-11-16", "--once",
                 "1000 flyers 4/4 100# gloss text"]) == 0  # fmt: skip
    assert "I recommend" in capsys.readouterr().out


def test_cli_eval_passes_and_fails_on_bad_golden(tmp_path, capsys):
    assert main(["eval"]) == 0
    assert "Overall: PASS" in capsys.readouterr().out
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"id":"x","category":"c","turns":["hello"],"asks":[false],"expected_status":"needs_info",'
        '"expected_spec":{"product":"flyer"}}\n'
    )
    assert main(["eval", "--golden", str(bad)]) == 1


def test_eval_meets_thresholds():
    from pathlib import Path

    rep = run_eval(Path(__file__).parents[1] / "evals" / "golden.jsonl")
    assert rep.n_cases >= 60 and rep.passed
    assert rep.metrics["grounding_pass_rate"] == 1.0
    assert set(THRESHOLDS) <= set(rep.metrics)


def test_provider_selection(monkeypatch):
    assert get_provider("fake").name == "fake"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_provider("anthropic")
    with pytest.raises(ValueError):
        get_provider("nope")
    assert os.environ["LLM_PROVIDER"] == "fake"


def test_chat_is_stateless_when_client_sends_state():
    r1 = client.post("/chat", json={"message": "2000 flyers", "today": "2026-11-16"}).json()
    assert r1["status"] == "needs_info" and r1["state"]["raw"]
    r2 = client.post(
        "/chat", json={"message": "4/4 100# gloss text", "state": r1["state"]}
    ).json()  # no session id: state travels with the request
    assert r2["status"] == "quoted"
    assert r2["crossover"] is not None and r2["quote"]["offset"]["lines"]
