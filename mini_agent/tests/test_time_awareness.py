"""Offline tests for time awareness (AGENT_TIME_AWARENESS, docs/plans/time-awareness.md). No endpoint or Docker."""

import threading

import pytest
from harbor.models.agent.context import AgentContext

from badger_mini.harbor_agent import (
    NUDGE_MESSAGE,
    HarborSyncedAgent,
    _load_config,
)

OLD_RULE = "As soon as you have any plausible answer"
NEW_RULE = "Time is limited (it may be only 15 minutes)"


class FakeEnv:
    def execute(self, action, **kwargs):
        return {"output": "hello\n", "returncode": 0, "exception_info": ""}

    def get_template_vars(self, **kwargs):
        return {"timeout": 180}

    def serialize(self):
        return {}


class FakeModel:
    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": o["output"], "extra": {}} for o in outputs]

    def format_message(self, **kwargs):
        return dict(kwargs)

    def get_template_vars(self, **kwargs):
        return {}

    def serialize(self):
        return {}


@pytest.fixture
def make_agent(tmp_path):
    def make(time_awareness: bool, elapsed: float = 0) -> HarborSyncedAgent:
        agent_config = _load_config()["agent"]
        agent = HarborSyncedAgent(
            FakeModel(),
            FakeEnv(),
            harbor_context=AgentContext(),
            stop=threading.Event(),
            output_path=tmp_path / "trajectory.json",
            **agent_config,
        )
        agent.time_awareness = time_awareness
        agent.extra_template_vars["time_awareness"] = time_awareness
        agent._start_time -= elapsed
        return agent

    return make


def command(cmd: str = "echo hello") -> dict:
    return {"role": "assistant", "content": "", "extra": {"actions": [{"command": cmd}]}}


def test_off_adds_nothing(make_agent):
    agent = make_agent(time_awareness=False, elapsed=700)
    [obs] = agent.execute_actions(command())
    assert obs["content"] == "hello\n"
    assert agent.harbor_context.metadata["nudged_at_sec"] is None


def test_on_shows_whole_minutes_used(make_agent):
    agent = make_agent(time_awareness=True, elapsed=7 * 60 + 40)
    [obs] = agent.execute_actions(command())
    assert obs["content"].startswith("hello\n")
    assert "[time used: 7 min; the limit is unknown and may be as short as 15 min]" in obs["content"]
    assert NUDGE_MESSAGE not in obs["content"]


def test_nudge_once_from_10_minutes(make_agent):
    agent = make_agent(time_awareness=True, elapsed=9 * 60 + 59)
    [before] = agent.execute_actions(command())
    agent._start_time -= 2  # now just past 10 minutes
    [first] = agent.execute_actions(command())
    [second] = agent.execute_actions(command())
    assert NUDGE_MESSAGE not in before["content"]
    assert NUDGE_MESSAGE in first["content"]
    assert NUDGE_MESSAGE not in second["content"]
    assert "[time used: 10 min;" in second["content"]
    assert agent.nudged_at_sec == 601
    assert agent.harbor_context.metadata["nudged_at_sec"] == 601


@pytest.mark.parametrize("time_awareness", [False, True])
def test_prompt_rule_4_switches(make_agent, time_awareness):
    agent = make_agent(time_awareness=time_awareness)
    agent.extra_template_vars["task"] = "do the thing"
    prompt = agent._render_template(agent.config.instance_template)
    assert (NEW_RULE in prompt) is time_awareness
    assert (OLD_RULE in prompt) is not time_awareness
    assert "\n4. " in prompt and "\n5. Verify" in prompt  # list numbering survives the template branch
