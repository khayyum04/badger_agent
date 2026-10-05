"""Offline tests for self-compaction: a scripted model and a fake environment, no endpoint or Docker."""

import json
import threading

import litellm
from harbor.models.agent.context import AgentContext
from minisweagent.exceptions import Submitted

from badger_mini.compaction import Compactor, recent_turns
from badger_mini.harbor_agent import SUBMIT_MARKER, BadgerLitellmModel, HarborSyncedAgent

SUBMIT = f"echo {SUBMIT_MARKER}"


def reply(tool: str, args: dict, prompt_tokens: int) -> litellm.ModelResponse:
    call = {"id": f"call-{prompt_tokens}", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}
    return litellm.ModelResponse(
        choices=[{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
        usage={"prompt_tokens": prompt_tokens, "completion_tokens": 10, "total_tokens": prompt_tokens + 10},
    )


class ScriptedModel(BadgerLitellmModel):
    """Returns prepared replies in order and records what each request sent and offered."""

    def __init__(self, replies: list):
        super().__init__(model_name="scripted", cost_tracking="ignore_errors")
        self.replies = list(replies)
        self.requests: list[list[dict]] = []
        self.offered: list[list[str]] = []
        self.thinking: list[bool] = []

    def _query(self, messages, **kwargs):
        self.requests.append(messages)
        tools = self.compactor.tools() if self.compactor else []
        self.offered.append([tool["function"]["name"] for tool in tools])
        extra = self.compactor.request_kwargs() if self.compactor else {}
        self.thinking.append(extra.get("extra_body", {}).get("chat_template_kwargs", {}).get("enable_thinking", True))
        return self.replies.pop(0)

    def _calculate_cost(self, response) -> dict[str, float]:
        return {"cost": 0.0}


class FakeEnvironment:
    def execute(self, action: dict, cwd: str = "") -> dict:
        if action["command"] == SUBMIT:
            raise Submitted({"role": "exit", "content": "", "extra": {"exit_status": "Submitted", "submission": ""}})
        return {"output": "ok\n", "returncode": 0, "exception_info": ""}

    def get_template_vars(self, **kwargs) -> dict:
        return {}

    def serialize(self) -> dict:
        return {}


def run_agent(tmp_path, replies, thresholds=(1000, 2000, 3000)):
    compactor = Compactor(thresholds, archive_dir=tmp_path)
    model = ScriptedModel(replies)
    model.compactor = compactor
    context = AgentContext()
    agent = HarborSyncedAgent(
        model,
        FakeEnvironment(),
        harbor_context=context,
        stop=threading.Event(),
        compactor=compactor,
        system_template="system",
        instance_template="{{task}}",
        cost_limit=0,
        output_path=tmp_path / "trajectory.json",
    )
    agent.run("the task")
    return agent, model, context


def test_notice_then_forced_compaction(tmp_path):
    replies = [
        reply("bash", {"command": "ls"}, 500),
        reply("bash", {"command": "cat a"}, 1500),  # crosses the notice threshold
        reply("bash", {"command": "cat b"}, 3500),  # crosses warning and hard at once
        reply("bash", {"command": "cat c"}, 3600),  # the one last command after the hard message
        reply("bash", {"command": "cat d"}, 3700),  # bash while forced: rejected
        reply("self_compact", {"summary": "SUMMARY-TEXT", "note_to_self": "NOTE-TEXT"}, 3800),
        reply("bash", {"command": "cat e"}, 400),
        reply("bash", {"command": SUBMIT}, 500),
    ]
    agent, model, context = run_agent(tmp_path, replies)

    both = ["bash", "self_compact"]
    assert model.offered == [both, both, both, both, ["self_compact"], ["self_compact"], both, both]
    assert model.thinking == [True, True, True, True, False, False, True, True]  # off only while forced

    sent = lambda i: [m["content"] for m in model.requests[i] if m["role"] == "user"]  # noqa: E731
    assert "[Context note" in sent(2)[-1]
    assert "[Context limit reached" in sent(3)[-1]  # only the highest stage is announced
    assert not any("[Context warning" in text for text in sent(3))
    assert "[bash is now unavailable" in sent(4)[-1]
    assert "bash is unavailable" in sent(5)[-1]  # the forced-mode format error

    # The four small turns fit the recent budget; the stage messages and the error note are gone.
    after = model.requests[6]
    assert [m["role"] for m in after] == ["system", "user", "user"] + ["assistant", "tool"] * 4
    assert after[1]["content"] == "the task"
    assert "SUMMARY-TEXT" in after[2]["content"] and "NOTE-TEXT" in after[2]["content"]
    assert json.loads(after[-2]["tool_calls"][0]["function"]["arguments"]) == {"command": "cat c"}

    assert context.metadata["compactions"] == [
        {"stage": "hard", "size_before": 3800, "forced_failures": 1, "messages_before": 15, "messages_after": 11}
    ]
    assert len(json.loads((tmp_path / "compaction-1.json").read_text())) == 15
    assert context.n_input_tokens == 500 + 1500 + 3500 + 3600 + 3700 + 3800 + 400 + 500  # the rejected call is billed too
    assert context.metadata["exit_status"] == "Submitted"


def test_bash_is_given_back_after_two_failed_forced_attempts(tmp_path):
    replies = [
        reply("bash", {"command": "ls"}, 3500),  # crosses the hard threshold
        reply("bash", {"command": "cat a"}, 3600),  # the one last command
        reply("bash", {"command": "cat b"}, 3700),  # rejected
        reply("bash", {"command": "cat c"}, 3800),  # rejected
        reply("bash", {"command": "cat d"}, 3900),  # released: runs
        reply("bash", {"command": SUBMIT}, 4000),
    ]
    agent, model, context = run_agent(tmp_path, replies)

    both = ["bash", "self_compact"]
    assert model.offered == [both, both, ["self_compact"], ["self_compact"], both, both]
    released = [m["content"] for m in model.requests[4] if m["role"] == "user"][-1]
    assert "bash is available again" in released
    assert not any("Compaction failed" in m["content"] for m in model.requests[5][len(model.requests[4]):] if m["role"] == "user")
    assert context.metadata["compactions"] == []
    assert context.metadata["exit_status"] == "Submitted"


def test_early_self_compact_is_a_no_op(tmp_path):
    replies = [
        reply("self_compact", {"summary": "s", "note_to_self": "n"}, 500),
        reply("bash", {"command": SUBMIT}, 600),
    ]
    agent, model, context = run_agent(tmp_path, replies)

    assert "Not compacted" in model.requests[1][-1]["content"]
    assert context.metadata["compactions"] == []
    assert not list(tmp_path.glob("compaction-*.json"))


def test_invalid_self_compact_call_is_a_format_error(tmp_path):
    replies = [
        reply("self_compact", {"summary": "", "note_to_self": "n"}, 500),
        reply("bash", {"command": SUBMIT}, 600),
    ]
    agent, model, context = run_agent(tmp_path, replies)

    assert "Tool call error" in model.requests[1][-1]["content"]


def test_recent_turns_keeps_whole_turns_within_budget():
    turn = lambda n, size: [  # noqa: E731
        {"role": "assistant", "content": f"turn {n}"},
        {"role": "tool", "content": "x" * size},
    ]
    history = [*turn(1, 300), {"role": "user", "content": "a stage message"}, *turn(2, 300), *turn(3, 300)]

    kept = recent_turns(history, budget=250)
    assert [m["content"] for m in kept if m["role"] == "assistant"] == ["turn 2", "turn 3"]
    assert all(m["role"] != "user" for m in kept)

    assert [m["content"] for m in recent_turns(history, budget=1)][0] == "turn 3"  # always at least one turn


def test_recent_turns_counts_thinking_when_it_is_re_sent():
    turn = lambda n: [  # noqa: E731
        {"role": "assistant", "content": f"turn {n}", "reasoning_content": "t" * 600},
        {"role": "tool", "content": "x" * 300},
    ]
    history = [*turn(1), *turn(2), *turn(3)]

    assert len(recent_turns(history, budget=250)) == 4  # thinking stripped: two turns fit
    assert len(recent_turns(history, budget=250, reasoning_sent=True)) == 2  # thinking re-sent: one turn fits


def test_strip_reasoning_drops_earlier_thinking():
    model = ScriptedModel([])
    history = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": None, "tool_calls": [], "reasoning_content": "thinking"},
    ]
    assert "reasoning_content" in model._prepare_messages_for_api(history)[1]

    model.strip_reasoning = True
    assert model._prepare_messages_for_api(history)[1] == {"role": "assistant", "content": None, "tool_calls": []}


def test_forced_thinking_option(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COMPACTION", "on")
    forced = lambda c: (setattr(c, "stage", 3), c)[1]  # noqa: E731
    assert forced(Compactor.from_env(tmp_path)).request_kwargs() == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
    }
    monkeypatch.setenv("COMPACT_FORCED_THINKING", "on")
    assert forced(Compactor.from_env(tmp_path)).request_kwargs() == {}
