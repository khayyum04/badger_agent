"""Offline tests for overrun recovery (AGENT_OVERRUN_RECOVERY, docs/plans/overrun-recovery.md). No endpoint."""

import litellm
import pytest
from minisweagent.exceptions import FormatError

from badger_mini.harbor_agent import (
    OVERRUN_NOTES_HEAD,
    OVERRUN_NOTES_TAIL,
    THINKING_OFF_KWARGS,
    BadgerLitellmModel,
    _load_config,
    _switch,
)

FORMAT_ERROR_TEMPLATE = _load_config()["model"]["format_error_template"]


def response(finish_reason: str, reasoning: str = "", tool_call: bool = False) -> litellm.ModelResponse:
    message = {"role": "assistant", "content": "", "reasoning_content": reasoning}
    if tool_call:
        message["tool_calls"] = [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "ls"}'}}
        ]
    return litellm.ModelResponse(
        choices=[{"finish_reason": finish_reason, "message": message}],
        usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    )


@pytest.fixture
def calls(monkeypatch):
    """Patches litellm.completion: records each call's kwargs and replays scripted responses."""
    sent, script = [], []

    def completion(**kwargs):
        sent.append(kwargs)
        return script.pop(0)

    monkeypatch.setattr(litellm, "completion", completion)
    return sent, script


def make_model(recovery: bool, model_kwargs: dict | None = None) -> BadgerLitellmModel:
    model = BadgerLitellmModel(
        model_name="openai/test",
        model_kwargs=model_kwargs or {"max_tokens": 16384},
        format_error_template=FORMAT_ERROR_TEMPLATE,
    )
    model.overrun_recovery = recovery
    return model


def query(model: BadgerLitellmModel) -> dict | FormatError:
    try:
        return model.query([])
    except FormatError as e:
        return e


def thinking_off(kwargs: dict) -> bool:
    return (kwargs.get("extra_body") or {}).get("chat_template_kwargs") == THINKING_OFF_KWARGS["chat_template_kwargs"]


def test_off_keeps_the_old_retry_note(calls):
    sent, script = calls
    script += [response("length", reasoning="my plan")] * 3
    model = make_model(recovery=False)
    errors = [query(model) for _ in range(3)]
    assert all(isinstance(e, FormatError) and "<notes>" not in e.messages[0]["content"] for e in errors)
    assert not any(thinking_off(k) for k in sent)


def test_notes_carry_the_cut_off_thinking(calls):
    _, script = calls
    script += [response("length", reasoning="Plan: brute force the key with a C program.")]
    error = query(make_model(recovery=True))
    content = error.messages[0]["content"]
    assert "ran out of thinking budget" in content  # the template's note is still there
    assert "<notes>\nPlan: brute force the key with a C program.\n</notes>" in content


def test_long_thinking_is_trimmed_to_head_and_tail(calls):
    _, script = calls
    thinking = "H" * OVERRUN_NOTES_HEAD + "M" * 20_000 + "T" * OVERRUN_NOTES_TAIL
    script += [response("length", reasoning=thinking)]
    content = query(make_model(recovery=True)).messages[0]["content"]
    assert "H" * OVERRUN_NOTES_HEAD in content and "T" * OVERRUN_NOTES_TAIL in content
    assert "M" not in content.split("<notes>")[1]
    assert "[... 20000 characters omitted ...]" in content


def test_thinking_off_after_two_overruns_until_a_normal_reply(calls):
    sent, script = calls
    script += [
        response("length", "a"),
        response("length", "b"),
        response("length", "c"),  # third call: thinking off, still overran (switch ignored)
        response("tool_calls", tool_call=True),  # fourth call: thinking off, acts
        response("tool_calls", tool_call=True),  # back to normal
    ]
    model = make_model(recovery=True)
    results = [query(model) for _ in range(5)]
    assert [thinking_off(k) for k in sent] == [False, False, True, True, False]
    assert model.n_thinking_off_calls == 2 and model.n_overrun_notes == 3
    assert results[3]["extra"]["actions"][0]["command"] == "ls"


def test_thinking_off_keeps_other_extra_body(calls):
    sent, script = calls
    script += [response("length", "a"), response("length", "b"), response("tool_calls", tool_call=True)]
    model = make_model(recovery=True, model_kwargs={"max_tokens": 16384, "extra_body": {"top_k": 20}})
    for _ in range(3):
        query(model)
    assert sent[2]["extra_body"] == {"top_k": 20, **THINKING_OFF_KWARGS}


def test_ordinary_format_error_gets_no_notes(calls):
    _, script = calls
    script += [response("stop", reasoning="thinking")]  # replied without a tool call, not cut off
    error = query(make_model(recovery=True))
    assert "<notes>" not in error.messages[0]["content"]


def test_think_tags_in_content_are_used_when_no_reasoning_field(calls):
    _, script = calls
    r = response("length")
    r.choices[0].message.reasoning_content = None
    r.choices[0].message.content = "<think>Try XOR first."
    script += [r]
    assert "<notes>\nTry XOR first.\n</notes>" in query(make_model(recovery=True)).messages[0]["content"]


def test_rejected_switch_falls_back_to_a_normal_call(monkeypatch):
    """A gateway that 400s on chat_template_kwargs must not fail the task: retry without it, stop sending it."""
    sent = []
    script = [response("length", "a"), response("length", "b"), response("tool_calls", tool_call=True),
              response("length", "c"), response("length", "d"), response("tool_calls", tool_call=True)]

    def completion(**kwargs):
        sent.append(thinking_off(kwargs))
        if thinking_off(kwargs):
            raise litellm.exceptions.BadRequestError("unknown field chat_template_kwargs", "openai", "test")
        return script.pop(0)

    monkeypatch.setattr(litellm, "completion", completion)
    model = make_model(recovery=True)
    results = [query(model) for _ in range(6)]
    assert sent == [False, False, True, False, False, False, False]  # rejected once, then never sent again
    assert model.thinking_off_rejected and model.n_thinking_off_calls == 0
    assert results[2]["extra"]["actions"][0]["command"] == "ls"


@pytest.mark.parametrize("value, expected", [(None, True), ("", True), ("on", True), ("ON", True), ("off", False), ("no", False)])
def test_switches_default_on(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("AGENT_X", raising=False)
    else:
        monkeypatch.setenv("AGENT_X", value)
    assert _switch("AGENT_X") is expected
