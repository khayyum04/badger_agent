# Self-compaction MVP (experiment)

Status: **implemented; first measured 2026-10-01** on all 89 tasks with thresholds 10% / 15% / 25%,
see [the write-up](../research/full-89-strip-compaction.md). Runs A and B below (the 30-task
strip-only comparison) have **not** been done. Owner: khayyum04.

Purpose: find out **how much compaction saves and whether it costs passes** on mini_agent. Nothing
more. The full design, [self-compaction.md](self-compaction.md), is parked until this experiment
says the idea is worth it; it is the reference for hardening afterwards.

## What was built

| File | Change |
|---|---|
| `mini_agent/badger_mini/compaction.py` | New. `Compactor`: the tool, the stages, parsing, the history rebuild, and all model-facing text |
| `mini_agent/badger_mini/harbor_agent.py` | Hooks only: the model strips old thinking and asks the compactor for its tools and parsing; the agent checks the stage before each query and rebuilds on a `self_compact` call |
| `mini_agent/tests/test_compaction.py` | New. Offline tests with a scripted model |
| `mini_agent/pyproject.toml`, `.env.example` | `pytest` as a dev dependency; the new switches, commented |

`config/terminal_bench.yaml` is unchanged. Two env switches, both default `off`, so today's
behavior is unchanged unless they are set.

**`AGENT_STRIP_REASONING=on`** Before each request, earlier assistant messages are sent with only
`role`, `content` and `tool_calls`. Old thinking was ~46% of input tokens in the baseline run.

**`AGENT_COMPACTION=on`**

- A second tool, `self_compact(summary, note_to_self)`, offered next to `bash` on every request.
- **Size** = `prompt_tokens` of the latest model response (the gateway's own count); 0 right after
  a compaction until the next response arrives.
- **Thresholds** = 10% / 20% / 30% of `LLM_CONTEXT_WINDOW` (default `250000`, so 25K / 50K / 75K).
  Optional overrides in plain tokens: `COMPACT_NOTICE_AT`, `COMPACT_WARNING_AT`, `COMPACT_HARD_AT`.
  - notice: one user message, "compact at a natural stopping point";
  - warning: one user message, "compact within the next turn or two";
  - hard: one user message allowing one last `bash` command; after that requests offer **only**
    `self_compact`. After two failed attempts `bash` is given back for the rest of that cycle
    (added 2026-10-02: forced attempts were failing because the model was mid-step).
    On those forced turns thinking is off by default (`COMPACT_FORCED_THINKING=on` turns it back on;
    added 2026-10-03).
- **On `self_compact`:** the history becomes system prompt + task + one message holding the summary
  and the note + the newest whole turns that fit in a third of the notice threshold (about 8K
  tokens by default, estimated as characters / 3; at least one turn). The old history is first
  saved to `agent/compaction-<n>.json` next to the trajectory, so what was dropped can be inspected.
- A `self_compact` call below the notice threshold gets the reply "Not compacted" and changes
  nothing.
- In forced mode a reply that isn't a valid `self_compact` call gets a format error saying so.
- `context.metadata` gets `strip_reasoning` and, when compaction is on, `compactions`: one record
  per compaction with `stage` (`notice` / `warning` / `hard` / `none`), `size_before`,
  `messages_before` and `messages_after`.

## Left out on purpose

Config validation; percentage parsing; summary length limits; the 3-turn loop guard; exempting compaction turns from the step limit; a separate full
log (the trajectory holds the current history, the side files hold the rest); the anchor-based size
estimate; prompt changes in the YAML (the instance prompt still says "exactly one bash tool call";
the stage messages and the tool description tell the model about `self_compact`).

What that means in practice: a bad env value crashes or misbehaves instead of explaining itself; a
model that can't write a `self_compact` call when forced ends the task through the existing
5-format-errors stop (`RepeatedFormatError`). Count those exits in the result before blaming
compaction for a lost pass.

## Checks before the long run

1. Offline tests: `pytest mini_agent/tests`.
2. One live sample task with small thresholds, to watch a real compaction in minutes instead of
   finding a bug four hours into a run:
   `AGENT_STRIP_REASONING=on AGENT_COMPACTION=on COMPACT_NOTICE_AT=6000 COMPACT_WARNING_AT=8000
   COMPACT_HARD_AT=10000 op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_sample.sh
   fix-code-vulnerability`. Keep the notice well above the first prompt (~3K tokens), or the agent is back at the
   notice right after compacting.

## Experiment

Same 30 tasks (`eval/experiment_subset.txt`), same model and settings as the baseline job
`mini_agent/jobs/2026-09-27__12-44-55` (77.2M tokens, 15/30). A run takes about 4.5 hours at `-n 2`.

- **Run A:** `AGENT_STRIP_REASONING=on`.
- **Run B:** `AGENT_STRIP_REASONING=on AGENT_COMPACTION=on`.

Compaction's effect is **B against A**. Report total tokens, passes, compactions per task and their
stage, `RepeatedFormatError` exits, and whether the long tasks (`custom-memory-heap-crash`,
`video-processing`, `path-tracing`, `mailman`, `winning-avg-corewars`) still pass.

Replay estimates to compare with: A ≈ 43–44M; B between ≈ 21M (the model compacts at the notice)
and ≈ 37M (only when forced at 75K). Runs are single samples; a difference of one or two passes is
noise.

If only one run is affordable, do B and compare it with the baseline and with the replay's estimate
for A.
