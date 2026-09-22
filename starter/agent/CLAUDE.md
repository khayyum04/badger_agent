# starter/agent/

## Purpose
The agent package Harbor imports (`agent.agent:BaselineAgent`): a minimal ReAct loop that
solves a Terminal-Bench task by issuing bash commands inside the task's Docker container.

## Contents
- `__init__.py` — empty; makes `agent` importable (needs the editable install of `starter/`).
- `agent.py` — `BaselineAgent(BaseAgent)` and the loop in `run()`: build active context (`context.py`) →
  LLM call → `parse_action` → record raw events → `run_shell`. Owns the raw event history (`raw_events`),
  the per-turn telemetry list, and the `next_event_id` counter. Reads `AGENT_MAX_TURNS` (100) and
  `AGENT_COMMAND_TIMEOUT_SEC` (60). `setup()` is a no-op.
- `events.py` — the raw-history dataclasses: `Event` (base: `id`, `turn`, `event_type`, `timestamp`),
  `AssistantActionEvent`, `ObservationEvent`. Plain data, no behavior.
- `context.py` — everything that reads/builds from the raw event history: `canonicalize_action`,
  `select_recent_events`, `build_active_context` (the only place the model-facing message list is
  assembled), `record_observation` (turns a `tools.ShellResult` into an `ObservationEvent`),
  `record_turn_telemetry`, and `ContextConfig`/`load_context_config` (`AGENT_CANONICALIZE`,
  `AGENT_RECENT_WINDOW_PAIRS`). No stateful classes — functions take `raw_events` as a parameter.
- `prompts.py` — all LLM-facing text: `SYSTEM_PROMPT`, `NUDGE_MESSAGE`, `observation_message()` (the
  single renderer of a `tools.ShellResult`/`events.ObservationEvent` into text).
- `tools.py` — `parse_action()` (regex for a fenced code block, else the `TASK_COMPLETE` marker) and
  `run_shell()` (wraps `environment.exec`, returns a structured `ShellResult` — exit code, stdout,
  stderr, pre-truncation sizes, truncated flag, did-not-complete flag — truncation still happens here,
  formatting into text does not).
- `llm.py` — `LLMClient`, an async wrapper over any OpenAI-compatible `/chat/completions`; `_resolve_model()` strips litellm provider prefixes.

## How it fits in
`starter/scripts/run_*.sh` point Harbor at `agent.agent:BaselineAgent`. Each turn: `agent.py` calls
`context.build_active_context()` to get the bounded message list (not the full raw history) →
`llm.py` (text + usage) → `tools.parse_action` (action) → `agent.py` builds an `AssistantActionEvent`
and appends it to `raw_events`; if the action is a shell command, `tools.run_shell` executes it and
`context.record_observation` turns the result into an `ObservationEvent`, also appended to
`raw_events`. `prompts.py` supplies every string shown to the model. `context.metadata["messages"]`
is the *serialized raw event history* (every event, via `dataclasses.asdict`), not what any single
turn actually saw — `scripts/build_dashboard.py` reads this shape. All improvement levers (prompts,
context mgmt, error recovery, self-critique) are edits here. Design and phase specs:
`starter/plan_docs/context_management/`.

## Gotchas
- **Never touch the host.** Only `environment.exec()` may affect anything (`starter/docs/safety.md`).
- **`context` must be updated every turn** — `agent.py`'s `sync_metadata()` closure rebuilds
  `context.metadata` after *every* raw-history mutation (not just once per turn), because serializing
  `raw_events` via `dataclasses.asdict` makes new dicts each time — unlike the old plain `messages`
  list, updates are not "free" via a shared reference. This matters most around `run_shell`, the step
  most likely to be sitting mid-command when an external timeout lands.
- `context.metadata` carries `system_prompt` and `instruction` as their own keys (not part of
  `"messages"`, which DEC-012 scopes to only `AssistantActionEvent`/`ObservationEvent`) purely so
  `build_dashboard.py` can still show what the task was — see `plan_docs/context_management/handoff.md`
  Deviations.
- **Code block beats `TASK_COMPLETE`**, and `CODE_BLOCK_RE` also accepts *untagged* fences (not only ```` ```bash ````). An empty block falls through to the done check. Canonicalization (`context.canonicalize_action`) operates only on the already-parsed `Action`, so it can never change what ran (DEC-016).
- **Active context is bounded, not the full transcript**: `context.build_active_context` sends the
  system prompt, the original task, and the last `AGENT_RECENT_WINDOW_PAIRS` (default 6) complete
  action–observation pairs — never the whole `raw_events` history. Early-context loss (older turns
  dropped from what the model sees) is a known, currently-unmitigated gap — see DEC-014.
- **A `"none"`-kind action (no valid code block or `TASK_COMPLETE`) has no paired `ObservationEvent`**
  (DEC-013) and is invisible to `select_recent_events`. Only the *trailing* `"none"` event (if any) is
  shown to the model, as its raw response plus `NUDGE_MESSAGE`, outside the window budget (DEC-026).
- **Truncation is per stream, not per observation**: stdout and stderr are each capped at `MAX_OBSERVATION_CHARS` (6000, first/last half kept) in `tools.run_shell`, so one observation can reach ~12k chars. `ShellResult`/`ObservationEvent` also carry `original_stdout_chars`/`original_stderr_chars`/`truncated` so a later reader can tell truncation happened. Intentionally blunt; a named improvement target (Phase 3 replaces it).
- **No retry in `llm.chat()`**: an endpoint exception propagates out of `run()` and ends the trial.
- **Reasoning-model fallback**: empty `content` falls back to `reasoning_content`; that text is then parsed as an action, so a code block inside the model's thinking *will be executed*. Real fix is `LLM_MAX_TOKENS` ≥ 8192 (code default is only 2048).
- **Model resolution**: `LLM_MODEL` beats Harbor's `-m`. `.env` loads with `override=True`, so it also clobbers vars injected by `op run` — keep active `LLM_*` lines out of `.env` when using `.env.op`.
- `SYSTEM_PROMPT` asserts "no network"; some tasks may differ, and finale tasks may truly have none, so `setup()` must not rely on downloads.
- No task-specific branches or hardcoded prompts (competition rule; grounds for disqualification).
- `tools.py`'s `CODE_BLOCK_RE` and `prompts.py`'s `NUDGE_MESSAGE` are duplicated in `scripts/build_dashboard.py` — change them together.
