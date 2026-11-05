"""Upload Harbor job summaries to Langfuse: one dataset experiment run per job, one item per task.

    python -m badger_mini.langfuse_export --dry-run jobs/full-mini-v1          # print the summary, no upload
    op run --env-file=mini_agent/.env.op -- python -m badger_mini.langfuse_export mini_agent/jobs/<job> ...

Reads only what Harbor already wrote (result.json per trial, plus the mini-swe-agent trajectory when
there is one), so it never touches the agent or a run: the submission is unaffected. Summary only -
no per-call or per-command observations - to keep Langfuse quota low (about 9 units per task: 5 spans the experiment SDK creates + 3 scores + the trace).

In Langfuse:
  dataset   terminal-bench-2.0, one item per task (created on first use)
  run       one experiment run per job, named after the job; ID derived from the job name, so a job
            already exported is skipped (delete the run in the UI to export it again)
  per task  a trace (session = job name) with one generation carrying the task's total tokens,
            and the scores reward (0/1), total_tokens, outcome (Submitted / AgentTimeoutError / ...)
  per run   the scores tb_score, total_tokens, tokens_per_task, leaderboard_score (current competition
            rule, see token_penalty())

Needs LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST (e.g. https://cloud.langfuse.com) and
`uv pip install -e "mini_agent/[tracing]"`. The run_*.sh scripts call this after a run when LANGFUSE_ENABLED=1.
"""

import argparse
import json
import os
import sys
from pathlib import Path

DATASET = "terminal-bench-2.0"


def token_penalty(tokens_per_task: float) -> float:
    """Competition rule: min(0.01, 0.01 * tokens_per_task / 100M), tokens_per_task = total_tokens / 89.
    For a subset job, tokens_per_task is the job's own average, which equals the rule on a full run."""
    return min(0.01, 0.01 * tokens_per_task / 100_000_000)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _trajectory_counts(trajectory: dict) -> dict:
    """Counts from a mini-swe-agent trajectory. Format-error retry notes are stored as user messages
    that carry the rejected response; an overrun is any response that ended with finish_reason=length."""
    counts = {"n_commands": 0, "n_failed_commands": 0, "n_command_timeouts": 0, "n_format_errors": 0, "n_overruns": 0}
    for message in trajectory.get("messages", []):
        extra = message.get("extra") or {}
        if message.get("role") == "tool":
            counts["n_commands"] += 1
            if extra.get("returncode") not in (0, None):
                counts["n_failed_commands"] += 1
            if "timeout" in (extra.get("exception_info") or ""):
                counts["n_command_timeouts"] += 1
        response = extra.get("response")
        if not isinstance(response, dict):
            continue
        if message.get("role") == "user":
            counts["n_format_errors"] += 1
        choices = response.get("choices") or [{}]
        if choices[0].get("finish_reason") == "length":
            counts["n_overruns"] += 1
    return counts


def _seconds(span: dict | None) -> float | None:
    from datetime import datetime

    if not span or not span.get("started_at") or not span.get("finished_at"):
        return None
    start = datetime.fromisoformat(span["started_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(span["finished_at"].replace("Z", "+00:00"))
    return round((end - start).total_seconds(), 1)


def summarize_trial(trial_dir: Path) -> dict | None:
    result = _load_json(trial_dir / "result.json")
    if not result or not result.get("task_name"):
        return None
    agent_result = result.get("agent_result") or {}
    metadata = agent_result.get("metadata") or {}
    exception = (result.get("exception_info") or {}).get("exception_type")
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0
    n_in = agent_result.get("n_input_tokens") or 0
    n_out = agent_result.get("n_output_tokens") or 0
    if exception:
        outcome = exception
    elif metadata.get("exit_status"):
        outcome = metadata["exit_status"]
    elif "finished" in metadata:  # starter baseline agent
        outcome = "Submitted" if metadata["finished"] else "MaxTurns"
    else:
        outcome = "unknown"
    summary = {
        "task": result["task_name"],
        "trial": result.get("trial_name") or trial_dir.name,
        "agent": (result.get("agent_info") or {}).get("name") or "unknown",
        "reward": float(reward),
        "passed": float(reward) >= 1.0,
        "outcome": outcome,
        "input_tokens": n_in,
        "output_tokens": n_out,
        "total_tokens": n_in + n_out,
        "turns": metadata.get("n_model_calls") or metadata.get("turns"),
        "agent_seconds": _seconds(result.get("agent_execution")),
        "started_at": result.get("started_at"),
        "model": None,
    }
    for key in ("thinking_cap", "time_awareness", "strip_reasoning", "n_boosted_calls", "nudged_at_sec",
                "submit_check", "submit_checked_at_sec", "no_benchmark_lookup",
                "overrun_recovery", "n_overrun_notes", "n_thinking_off_calls", "thinking_off_rejected",
                "submit_review", "review_commands", "review_sec", "time_limit_sec", "reasoning_effort"):
        if key in metadata:
            summary[key] = metadata[key]
    if "compactions" in metadata:
        summary["n_compactions"] = len(metadata["compactions"] or [])
    trajectory = _load_json(trial_dir / "agent" / "mini-swe-agent.trajectory.json")
    if trajectory:
        summary.update(_trajectory_counts(trajectory))
        summary["model"] = (((trajectory.get("info") or {}).get("config") or {}).get("model") or {}).get("model_name")
    return summary


def summarize_job(job_dir: Path) -> dict:
    job_dir = job_dir.resolve()
    trials = [s for d in sorted(job_dir.iterdir()) if d.is_dir() and (s := summarize_trial(d))]
    config = _load_json(job_dir / "config.json") or {}
    job_result = _load_json(job_dir / "result.json") or {}
    n = len(trials)
    tb_score = sum(t["reward"] for t in trials) / n if n else 0.0
    total_tokens = sum(t["total_tokens"] for t in trials)
    return {
        "job": config.get("job_name") or job_dir.name,
        "started_at": job_result.get("started_at"),
        "agents": sorted({t["agent"] for t in trials}),
        "trials": trials,
        "n_tasks": n,
        "n_passed": sum(t["passed"] for t in trials),
        "tb_score": tb_score,
        "total_tokens": total_tokens,
        "tokens_per_task": total_tokens / n if n else 0.0,
        "leaderboard_score": tb_score - token_penalty(total_tokens / n if n else 0.0),
    }


def print_job(job: dict) -> None:
    print(
        f"\n{job['job']}  tasks={job['n_tasks']} passed={job['n_passed']} tb_score={job['tb_score']:.4f} "
        f"total_tokens={job['total_tokens']} tokens_per_task={job['tokens_per_task']:.0f} "
        f"leaderboard_score={job['leaderboard_score']:.5f}"
    )
    for t in job["trials"]:
        print(
            f"  {'PASS' if t['passed'] else 'fail'}  {t['task']:<40} {t['outcome']:<26} "
            f"tokens={t['total_tokens']:>9}  turns={t['turns'] if t['turns'] is not None else '-'}"
        )


# --- upload -------------------------------------------------------------------------------------


def _item_id(task: str) -> str:
    return f"tb2-{task}"


def _ensure_dataset_items(langfuse, tasks: set[str]):
    from langfuse.api import NotFoundError

    try:
        dataset = langfuse.get_dataset(DATASET)
    except NotFoundError:
        langfuse.create_dataset(name=DATASET, description="Terminal-Bench 2.0 tasks, one item per task")
        dataset = langfuse.get_dataset(DATASET)
    known = {item.input.get("task") for item in dataset.items if isinstance(item.input, dict)}
    missing = sorted(tasks - known)
    for task in missing:
        langfuse.create_dataset_item(
            dataset_name=DATASET, id=_item_id(task), input={"task": task}, metadata={"source": "terminal-bench@2.0"}
        )
    return langfuse.get_dataset(DATASET) if missing else dataset


def _experiment_exists(langfuse, experiment_id: str) -> bool:
    from datetime import datetime, timezone

    response = langfuse.api.experiments.list(
        from_start_time=datetime(2020, 1, 1, tzinfo=timezone.utc), id=experiment_id, limit=1
    )
    return bool(response.data)


def export_job(langfuse, job: dict, force: bool = False) -> str | None:
    from langfuse import Evaluation, Langfuse, propagate_attributes

    if not job["trials"]:
        print(f"{job['job']}: no trials, skipped")
        return None
    experiment_id = Langfuse.create_trace_id(seed=f"badger-agent/{job['job']}")
    if not force and _experiment_exists(langfuse, experiment_id):
        print(f"{job['job']}: already exported, skipped (delete the run in Langfuse, or pass --force to add it again)")
        return None

    dataset = _ensure_dataset_items(langfuse, {t["task"] for t in job["trials"]})
    items_by_task = {item.input.get("task"): item for item in dataset.items if isinstance(item.input, dict)}
    pending: dict[str, list[dict]] = {}
    for trial in job["trials"]:
        pending.setdefault(trial["task"], []).append(trial)
    data = [items_by_task[t["task"]] for t in job["trials"]]  # a task run twice in one job appears twice
    tags = [job["job"], *job["agents"]]

    def task(*, item, **kwargs):
        trial = pending[item.input["task"]].pop()
        with propagate_attributes(session_id=job["job"], tags=tags, trace_name=trial["task"]):
            generation = langfuse.start_observation(
                name="agent-run",
                as_type="generation",
                model=trial["model"],
                usage_details={"input": trial["input_tokens"], "output": trial["output_tokens"]},
                metadata=trial,
            )
            generation.end()
        return trial

    def item_scores(*, output, **kwargs):
        return [
            Evaluation(name="reward", value=output["reward"]),
            Evaluation(name="total_tokens", value=output["total_tokens"]),
            Evaluation(name="outcome", value=output["outcome"], data_type="CATEGORICAL"),
        ]

    def run_scores(**kwargs):  # from the whole job, not just the items in this call
        return [
            Evaluation(name="tb_score", value=job["tb_score"]),
            Evaluation(name="total_tokens", value=job["total_tokens"]),
            Evaluation(name="tokens_per_task", value=job["tokens_per_task"]),
            Evaluation(name="leaderboard_score", value=job["leaderboard_score"]),
        ]

    result = langfuse.run_experiment(
        name=DATASET,
        run_name=job["job"],
        description=f"Harbor job {job['job']} ({', '.join(job['agents'])})",
        data=data,
        task=task,
        evaluators=[item_scores],
        run_evaluators=[run_scores],
        max_concurrency=10,
        metadata={"job_started_at": job["started_at"] or "", "agents": ",".join(job["agents"])},
        experiment_id=experiment_id,
    )
    langfuse.flush()
    print(f"{job['job']}: exported {len(data)} tasks  {result.experiment_url or ''}")
    return result.experiment_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("job_dirs", nargs="+", type=Path, help="Harbor job directories (jobs/<job-name>)")
    parser.add_argument("--dry-run", action="store_true", help="print the summaries; upload nothing")
    parser.add_argument("--force", action="store_true", help="export even if the job's run already exists")
    args = parser.parse_args(argv)

    jobs = []
    for job_dir in args.job_dirs:
        if not job_dir.is_dir():
            print(f"not a directory: {job_dir}", file=sys.stderr)
            return 2
        jobs.append(summarize_job(job_dir))
    if args.dry_run:
        for job in jobs:
            print_job(job)
        n = sum(j["n_tasks"] for j in jobs)
        print(f"\n{len(jobs)} jobs, {n} tasks; roughly {9 * n} Langfuse units to upload")
        return 0

    missing = [k for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.environ.get(k)]
    if missing:
        print(f"missing {', '.join(missing)}: launch via op run --env-file=mini_agent/.env.op", file=sys.stderr)
        return 2
    try:
        from langfuse import Langfuse
    except ImportError:
        print('langfuse not installed: uv pip install -e "mini_agent/[tracing]"', file=sys.stderr)
        return 2
    langfuse = Langfuse()
    if not langfuse.auth_check():
        print("Langfuse rejected the keys (check LANGFUSE_HOST: EU vs US region)", file=sys.stderr)
        return 2
    for job in jobs:
        export_job(langfuse, job, force=args.force)
    langfuse.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
