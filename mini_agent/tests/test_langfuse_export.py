"""Offline tests for the Langfuse exporter (badger_mini/langfuse_export.py). No Langfuse server, endpoint or Docker."""

import json
from types import SimpleNamespace

import pytest

import badger_mini.langfuse_export as ex


def _trial(job_dir, name, task, reward, n_in, n_out, exception=None, metadata=None, messages=None):
    trial = job_dir / name
    (trial / "agent").mkdir(parents=True)
    result = {
        "task_name": task,
        "trial_name": name,
        "agent_info": {"name": "badger-mini-swe-agent"},
        "agent_result": {"n_input_tokens": n_in, "n_output_tokens": n_out, "metadata": metadata or {}},
        "verifier_result": {"rewards": {"reward": reward}} if reward is not None else None,
        "exception_info": {"exception_type": exception} if exception else None,
        "agent_execution": {"started_at": "2026-10-05T23:51:16Z", "finished_at": "2026-10-05T23:52:16Z"},
    }
    (trial / "result.json").write_text(json.dumps(result))
    if messages is not None:
        trajectory = {"info": {"config": {"model": {"model_name": "openai/test-model"}}}, "messages": messages}
        (trial / "agent" / "mini-swe-agent.trajectory.json").write_text(json.dumps(trajectory))


@pytest.fixture
def job_dir(tmp_path):
    job = tmp_path / "my-job"
    job.mkdir()
    (job / "config.json").write_text(json.dumps({"job_name": "my-job"}))
    messages = [
        {"role": "assistant", "extra": {"response": {"choices": [{"finish_reason": "tool_calls"}]}}},
        {"role": "tool", "extra": {"returncode": 0, "exception_info": ""}},
        {"role": "user", "extra": {"response": {"choices": [{"finish_reason": "length"}]}}},  # format-error retry
        {"role": "tool", "extra": {"returncode": 124, "exception_info": "killed after the 180s timeout"}},
        {"role": "tool", "extra": {"returncode": 1, "exception_info": ""}},
    ]
    _trial(job, "a__1", "task-a", 1.0, 1000, 100, metadata={"n_model_calls": 3, "exit_status": "Submitted"}, messages=messages)
    _trial(job, "b__1", "task-b", None, 500, 50, exception="AgentTimeoutError", metadata={"n_model_calls": 9})
    _trial(job, "c__1", "task-c", 0.0, 0, 0, metadata={"turns": 4, "finished": False})  # starter baseline shape
    return job


def test_summary_matches_score_sh_math(job_dir):
    job = ex.summarize_job(job_dir)
    assert job["job"] == "my-job"
    assert job["n_tasks"] == 3 and job["n_passed"] == 1
    assert job["tb_score"] == pytest.approx(1 / 3)  # a missing reward counts as 0, like score.sh
    assert job["total_tokens"] == 1650
    assert job["leaderboard_score"] == pytest.approx(1 / 3 - 0.01 * 1650 / 1e6)


def test_trial_outcomes_and_counts(job_dir):
    trials = {t["task"]: t for t in ex.summarize_job(job_dir)["trials"]}
    a, b, c = trials["task-a"], trials["task-b"], trials["task-c"]
    assert (a["outcome"], b["outcome"], c["outcome"]) == ("Submitted", "AgentTimeoutError", "MaxTurns")
    assert a["n_commands"] == 3 and a["n_failed_commands"] == 2 and a["n_command_timeouts"] == 1
    assert a["n_format_errors"] == 1 and a["n_overruns"] == 1
    assert a["model"] == "openai/test-model" and a["agent_seconds"] == 60.0
    assert "n_commands" not in b  # no trajectory: counts are absent, not zero
    assert c["turns"] == 4


def test_dry_run_uploads_nothing(job_dir, capsys, monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert ex.main(["--dry-run", str(job_dir)]) == 0
    out = capsys.readouterr().out
    assert "my-job  tasks=3 passed=1" in out and "task-b" in out


def test_upload_without_keys_fails_cleanly(job_dir, monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert ex.main([str(job_dir)]) == 2


def test_export_spans(job_dir, monkeypatch):
    pytest.importorskip("langfuse")
    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    spans = InMemorySpanExporter()
    langfuse = Langfuse(public_key="pk-lf-test", secret_key="sk-lf-test", host="http://127.0.0.1:9", span_exporter=spans)
    job = ex.summarize_job(job_dir)
    items = [
        SimpleNamespace(id=ex._item_id(t), dataset_id="ds", input={"task": t}, expected_output=None, metadata=None)
        for t in ("task-a", "task-b", "task-c")
    ]
    monkeypatch.setattr(ex, "_experiment_exists", lambda lf, experiment_id: False)
    monkeypatch.setattr(ex, "_ensure_dataset_items", lambda lf, tasks: SimpleNamespace(items=items))
    ex.export_job(langfuse, job)
    langfuse.flush()

    generations = {
        s.attributes["langfuse.trace.name"]: s
        for s in spans.get_finished_spans()
        if s.attributes.get("langfuse.observation.type") == "generation"
    }
    assert set(generations) == {"task-a", "task-b", "task-c"}
    a = generations["task-a"].attributes
    assert a["session.id"] == "my-job"
    assert a["langfuse.experiment.item.id"] == "tb2-task-a"
    assert json.loads(a["langfuse.observation.usage_details"]) == {"input": 1000, "output": 100}
    assert len({s.context.trace_id for s in generations.values()}) == 3  # one trace per task


def test_experiment_id_is_stable():
    pytest.importorskip("langfuse")
    from langfuse import Langfuse

    assert Langfuse.create_trace_id(seed="badger-agent/my-job") == Langfuse.create_trace_id(seed="badger-agent/my-job")
