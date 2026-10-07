"""Offline tests for the thinking cap (AGENT_THINKING_CAP, docs/plans/thinking-cap.md). No endpoint."""

import litellm
import pytest

from badger_mini.harbor_agent import BadgerLitellmModel


def response(finish_reason: str) -> litellm.ModelResponse:
    return litellm.ModelResponse(
        choices=[{"finish_reason": finish_reason, "message": {"role": "assistant", "content": "x"}}],
        usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    )


@pytest.fixture
def calls(monkeypatch):
    """Patches litellm.completion: records the max_tokens of each call and replays scripted finish reasons."""
    sent, script = [], []

    def completion(**kwargs):
        sent.append(kwargs.get("max_tokens"))
        return response(script.pop(0))

    monkeypatch.setattr(litellm, "completion", completion)
    return sent, script


def make_model(cap: int, max_tokens: int = 16384) -> BadgerLitellmModel:
    model = BadgerLitellmModel(model_name="openai/test", model_kwargs={"max_tokens": max_tokens})
    model.thinking_cap = cap
    return model


def test_cap_off_sends_full_budget(calls):
    sent, script = calls
    script += ["stop", "length", "stop"]
    model = make_model(cap=0)
    for _ in range(3):
        model._query([])
    assert sent == [16384, 16384, 16384]


def test_capped_until_overrun_then_full_budget_once_it_recovers(calls):
    sent, script = calls
    script += ["tool_calls", "length", "tool_calls", "tool_calls"]
    model = make_model(cap=8192)
    for _ in range(4):
        model._query([])
    # normal, overrun at the cap, retry with the full budget, back to the cap
    assert sent == [8192, 8192, 16384, 8192]
    assert model.n_boosted_calls == 1


def test_stays_boosted_while_full_budget_also_overruns(calls):
    sent, script = calls
    script += ["length", "length", "length", "stop", "stop"]
    model = make_model(cap=8192)
    for _ in range(5):
        model._query([])
    assert sent == [8192, 16384, 16384, 16384, 8192]


def test_cap_never_exceeds_max_tokens(calls):
    sent, script = calls
    script += ["stop"]
    model = make_model(cap=32000, max_tokens=16384)
    model._query([])
    assert sent == [16384]
