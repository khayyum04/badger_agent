"""Offline tests for the submit review (AGENT_SUBMIT_REVIEW) and the known time limit (AGENT_KNOWN_TIME_LIMIT),
docs/plans/review-and-time-limit.md. Patched litellm; no endpoint or Docker."""

import threading

import litellm
import pytest
from harbor.models.agent.context import AgentContext

from badger_mini import review as review_mod
from badger_mini.harbor_agent import (
    SUBMIT_MARKER,
    HarborEnvironment,
    HarborSyncedAgent,
    _harbor_agent_timeout_sec,
    _load_config,
)


# ---------- review ----------


def reply(content: str = "", command: str | None = None) -> litellm.ModelResponse:
    message = {"role": "assistant", "content": content}
    if command is not None:
        message["tool_calls"] = [
            {"id": "t1", "type": "function", "function": {"name": "bash", "arguments": f'{{"command": "{command}"}}'}}
        ]
    return litellm.ModelResponse(
        choices=[{"finish_reason": "tool_calls" if command else "stop", "message": message}],
        usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    )


@pytest.fixture
def script(monkeypatch):
    sent, replies = [], []

    def completion(**kwargs):
        sent.append(kwargs)
        return replies.pop(0)

    monkeypatch.setattr(litellm, "completion", completion)
    return sent, replies


def review(replies_list, script, run_command=None):
    sent, replies = script
    replies += replies_list
    usage = []
    ran = []

    def default_run(command, timeout):
        ran.append(command)
        return {"output": "cmain\nmain.py.c\n", "returncode": 0}

    result = review_mod.run_review(
        task="Write /app/polyglot/main.py.c only.",
        model_name="openai/test",
        model_kwargs={"max_tokens": 16384},
        run_command=run_command or default_run,
        add_usage=lambda i, o: usage.append((i, o)),
    )
    return result, sent, usage, ran


def test_review_inspects_then_reports(script):
    result, sent, usage, ran = review(
        [reply(command="ls /app/polyglot"), reply("UNMET:\n- /app/polyglot has an extra file cmain")], script
    )
    assert ran == ["ls /app/polyglot"]
    assert "extra file cmain" in result["message"] and "submit again" in result["message"]
    assert result["n_commands"] == 1
    assert usage == [(100, 10), (100, 10)]  # every reviewer call is counted
    assert "Write /app/polyglot/main.py.c only." in sent[0]["messages"][1]["content"]  # fresh context: task only
    assert sent[0]["max_tokens"] == review_mod.REVIEW_MAX_TOKENS


def test_review_stops_after_max_commands(script):
    many = [reply(command="ls")] * review_mod.REVIEW_MAX_COMMANDS + [reply("ALL MET")]
    result, sent, _, ran = review(many, script)
    assert len(ran) == review_mod.REVIEW_MAX_COMMANDS
    assert "tools" not in sent[-1]  # the last call can't run commands
    assert result["verdict"] == "ALL MET"


def test_review_gives_verdict_when_time_budget_is_used(script):
    """After REVIEW_TIME_BUDGET_SEC the next call must answer, with a short reply budget, even mid-inspection."""
    sent, replies = script
    replies += [reply(command="ls"), reply(command="cat out.txt"), reply("UNMET:\n- out.txt is empty")]
    now = [0.0]

    def run_command(command, timeout):
        now[0] += 100  # each command takes 100 s
        return {"output": "", "returncode": 0}

    result = review_mod.run_review(
        task="t", model_name="openai/test", model_kwargs={"max_tokens": 16384},
        run_command=run_command, add_usage=lambda i, o: None, clock=lambda: now[0],
    )
    assert result["n_commands"] == 2  # 200 s used: the third call is the verdict
    assert "tools" not in sent[2] and sent[2]["max_tokens"] == review_mod.REVIEW_VERDICT_MAX_TOKENS
    assert result["verdict"] == "UNMET:\n- out.txt is empty"


def test_review_error_never_raises(monkeypatch):
    def boom(**kwargs):
        raise litellm.exceptions.APIConnectionError("down", "openai", "test")

    monkeypatch.setattr(litellm, "completion", boom)
    result = review_mod.run_review(
        task="t", model_name="openai/test", model_kwargs={}, run_command=lambda c, t: {}, add_usage=lambda i, o: None
    )
    assert "review failed" in result["verdict"] and "submit again" in result["message"]


def test_review_replaces_the_checklist_on_first_submit_only():
    env = HarborEnvironment(environment=None, loop=None, stop=threading.Event())
    env.submit_check = True
    env.submit_reviewer = lambda: "REVIEW TEXT"
    first = {"output": f"{SUBMIT_MARKER}\n", "returncode": 0, "exception_info": ""}
    env._check_finished(first)
    assert first["output"] == "REVIEW TEXT"
    from minisweagent.exceptions import Submitted

    with pytest.raises(Submitted):
        env._check_finished({"output": f"{SUBMIT_MARKER}\n", "returncode": 0, "exception_info": ""})


# ---------- known time limit ----------


class FakeTrial:
    """Stands in for harbor's Trial, which holds _agent_timeout_sec and awaits the agent's run()."""

    _agent_timeout_sec = 1800.0

    def run_agent(self):
        return _harbor_agent_timeout_sec()


def test_time_limit_found_up_the_stack():
    assert FakeTrial().run_agent() == 1800.0


def test_time_limit_none_without_a_trial():
    assert _harbor_agent_timeout_sec() is None


class FakeModel:
    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": "ok", "extra": {}} for _ in outputs]

    def get_template_vars(self, **kwargs):
        return {}

    def serialize(self):
        return {}


@pytest.fixture
def agent(tmp_path):
    a = HarborSyncedAgent(
        FakeModel(),
        HarborEnvironment(environment=None, loop=None, stop=threading.Event()),
        harbor_context=AgentContext(),
        stop=threading.Event(),
        output_path=tmp_path / "trajectory.json",
        **_load_config()["agent"],
    )
    a.time_awareness = True
    a.extra_template_vars["time_awareness"] = True
    return a


def test_clock_shows_known_limit_and_nudges_at_60_percent(agent):
    agent.time_limit_sec = 1800
    agent._start_time -= 600  # 10 of 30 min: no nudge yet (the unknown-limit mode nudges here)
    assert agent._clock_text() == "\n[time used: 10 of 30 min]"
    agent._start_time -= 480  # 18 of 30 min = 60%
    text = agent._clock_text()
    assert text.startswith("\n[time used: 18 of 30 min]") and "18 of 30 minutes used" in text
    assert agent.nudged_at_sec == 1080
    assert "minutes used" not in agent._clock_text()  # once only


def test_prompt_states_the_limit(agent):
    agent.extra_template_vars |= {"time_limit_min": 30, "task": "t"}
    system = agent._render_template(agent.config.instance_template)
    assert "You have 30 minutes for this task in total" in system
    assert "it may be only 15 minutes" not in system


def test_prompt_unchanged_without_known_limit(agent):
    agent.extra_template_vars["task"] = "t"
    system = agent._render_template(agent.config.instance_template)
    assert "it may be only 15 minutes" in system and "minutes for this task in total" not in system


def test_time_limit_found_through_harbors_async_call():
    """Harbor's Trial awaits agent.run() inside asyncio.wait_for (trial.py _run_agent_phase)."""
    import asyncio

    class Agent:
        async def run(self):
            await asyncio.sleep(0)  # after a suspension too
            return _harbor_agent_timeout_sec()

    class Trial:
        _agent_timeout_sec = 900.0

        async def _run_agent_phase(self):
            return await asyncio.wait_for(Agent().run(), timeout=5)

    assert asyncio.run(Trial()._run_agent_phase()) == 900.0


def test_reviewer_is_told_to_work_in_tmp():
    prompt = review_mod.REVIEW_SYSTEM
    assert "Never write anything in the task's directories" in prompt and "/tmp" in prompt
