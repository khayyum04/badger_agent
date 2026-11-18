"""Offline tests for the submit check (AGENT_SUBMIT_CHECK) and the no-lookup prompt line
(AGENT_NO_BENCHMARK_LOOKUP), docs/plans/submit-check.md. No endpoint or Docker."""

import threading

import pytest
from harbor.models.agent.context import AgentContext
from minisweagent.exceptions import Submitted

from badger_mini.harbor_agent import (
    SUBMIT_CHECK_MESSAGE,
    SUBMIT_MARKER,
    HarborEnvironment,
    HarborSyncedAgent,
    _load_config,
)

LOOKUP_LINE = "Do not search online for this benchmark"


def make_env(submit_check: bool) -> HarborEnvironment:
    env = HarborEnvironment(environment=None, loop=None, stop=threading.Event())
    env.submit_check = submit_check
    return env


def submit_output(returncode: int = 0) -> dict:
    return {"output": f"{SUBMIT_MARKER}\n", "returncode": returncode, "exception_info": ""}


def test_off_submits_at_once():
    env = make_env(submit_check=False)
    with pytest.raises(Submitted):
        env._check_finished(submit_output())
    assert env.submit_checked_at is None


def test_on_holds_back_the_first_submit_only():
    env = make_env(submit_check=True)
    first = submit_output()
    env._check_finished(first)  # no Submitted
    assert first["output"] == SUBMIT_CHECK_MESSAGE
    assert env.submit_checked_at is not None
    with pytest.raises(Submitted):
        env._check_finished(submit_output())


def test_failed_submit_command_does_not_use_up_the_check():
    env = make_env(submit_check=True)
    env._check_finished(submit_output(returncode=1))  # not a submit: the marker command failed
    assert env.submit_checked_at is None
    env._check_finished(submit_output())
    assert env.submit_checked_at is not None


def test_ordinary_output_is_untouched():
    env = make_env(submit_check=True)
    output = {"output": "hello\n", "returncode": 0, "exception_info": ""}
    env._check_finished(output)
    assert output["output"] == "hello\n" and env.submit_checked_at is None


class FakeModel:
    def get_template_vars(self, **kwargs):
        return {}

    def serialize(self):
        return {}


@pytest.fixture
def make_agent(tmp_path):
    def make(no_benchmark_lookup: bool) -> HarborSyncedAgent:
        agent = HarborSyncedAgent(
            FakeModel(),
            make_env(submit_check=True),
            harbor_context=AgentContext(),
            stop=threading.Event(),
            output_path=tmp_path / "trajectory.json",
            **_load_config()["agent"],
        )
        agent.extra_template_vars["no_benchmark_lookup"] = no_benchmark_lookup
        return agent

    return make


@pytest.mark.parametrize("on", [False, True])
def test_lookup_line_only_when_on(make_agent, on):
    agent = make_agent(no_benchmark_lookup=on)
    system = agent._render_template(agent.config.system_template)
    assert (LOOKUP_LINE in system) is on
    assert system.rstrip().endswith("decisions yourself.") is not on


def test_metadata(make_agent):
    agent = make_agent(no_benchmark_lookup=True)
    agent.env.submit_checked_at = agent._start_time + 125
    agent._sync_context()
    md = agent.harbor_context.metadata
    assert md["submit_check"] is True and md["submit_checked_at_sec"] == 125 and md["no_benchmark_lookup"] is True
