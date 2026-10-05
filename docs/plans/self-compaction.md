# Self-compaction for mini_agent

> **Parked (2026-09-30).** Build the small experiment in
> [self-compaction-mvp.md](self-compaction-mvp.md) first. This full design is the reference for
> hardening it afterwards, if the experiment shows compaction is worth keeping.

Status: **agreed design, not implemented** (2026-09-30; revised five times the same day: three times
after goldfish tests, twice after comparing with the reference implementation's source, see
[Revision history](#revision-history)). Owner: khayyum04.

**Prerequisite: [strip-old-reasoning](strip-old-reasoning.md).** This design assumes old thinking is
no longer re-sent (`AGENT_STRIP_REASONING=on`); its thresholds, budgets and replay numbers are all
computed on that basis. Build and measure that change first.

Context to read first: `mini_agent/CLAUDE.md` (how the adapter works),
`docs/research/mini-30-vs-baseline.md` (the numbers below come from its run), and the prerequisite
spec above.

## Problem

mini_agent re-sends its whole history on every model call. On the 30-task experiment subset
(`mini_agent/eval/experiment_subset.txt`, job `mini_agent/jobs/2026-09-27__12-44-55`, model
`qwen3.8-27b`) it used **77.2M tokens for 15/30 passes**, and **97% of those tokens were input**:
the history re-sent 42 times per task on average. The leaderboard charges 0.01 points per million
tokens, so a full 89-task run at this rate (~229M tokens) would cost more than the whole TB score.

About 46% of those input tokens are the model's own old thinking being re-sent; the prerequisite
spec removes that (replay: 77.2M → 43.0M). What remains is the visible history (commands, outputs,
replies) re-sent every turn. Even without thinking, the median task's history peaks around 22K and
10 of 30 tasks go above 40K (max 141K). This spec targets that remaining re-sending.

Goal: cut total tokens substantially **without lowering the pass count**, by letting the agent replace
its older history with a short summary at a moment it chooses, with the harness enforcing limits.

## Technical Plan

The harness estimates how big the history is before every model call and compares it with three
thresholds. The defaults are **percentages of the model's context window**, the same 10% / 20% / 30%
the reference implementation ships; the token figures are for `qwen3.8-27b` on the UW gateway
(250K window). All are set in `mini_agent/.env`, as a percentage or as a plain token count (§1):

| Stage | Default | What the harness does |
|---|---|---|
| Notice | 10% of the window (25,000 tokens) | Appends a gentle message: compact at a natural stopping point. All tools stay available |
| Warning | 20% (50,000 tokens) | Appends a firmer message: compact within the next turn or two |
| Hard cutoff | 30% (75,000 tokens) | Appends a "limit reached" message, and the next request offers **only** the `self_compact` tool; `bash` is unavailable until the agent compacts |

The model compacts by calling a second tool, **`self_compact(summary, note_to_self)`**:

- `summary`: what happened so far that still matters (files changed, commands that worked, errors
  seen, what is verified, decisions made). It replaces everything older than the recent turns,
  **including any earlier summary**, so it must carry forward what still matters from it.
- `note_to_self`: the immediate working state, ending with the next action.

Both have a **length limit** (summary 6,000 characters, note 2,000), stated in the tool's
description and enforced by the harness: an over-length call is rejected once with the actual
lengths; if the very next call is over-length again, it is accepted with the over-length text cut at
the limit, so a model that can't shorten never loses the task to repeated format errors. The limits
bound the size after compacting whatever the model writes, and keep the call well inside
`LLM_MAX_TOKENS` (a summary cut off by the reply budget arrives as invalid JSON and wastes the turn).

The model writes the summary itself inside that call. There is **no separate summarization call**.

`self_compact` is offered **from the first turn to the last** (next to `bash`), because Qwen's chat
template writes the tool definitions at the start of the prompt: changing the tool list mid-task
changes the prompt's start and loses the gateway's prefix cache. The only request with a different
tool list is the forced one at the hard cutoff (one cache miss per cycle, accepted).

If the model **fails to compact twice** at the hard cutoff (a reasoning overrun, invalid arguments, a
`bash` call), the harness **stops forcing for that cycle**: `bash` comes back, the model is told so,
and the task continues as it would without this feature. Forcing must never end a task that would
otherwise have kept working; the cost of giving up is only that the history keeps growing.

If the model calls `self_compact` when it isn't needed (history below the notice threshold, or
within 3 turns of the last compaction), the harness **does not compact** and replies to the call
with a short explanation. This is not a format error.

On an accepted `self_compact` call, the harness rebuilds the history it sends to the model (the
**active history**) as:

1. the system prompt, unchanged;
2. the task message, unchanged (**never summarized**, so the literal requirements can't be lost);
3. one compaction message holding the summary and the note;
4. the **recent turns**: the newest turns, walking backwards, until adding the next turn would
   exceed **8,000 tokens**. A tool call and its tool result are never separated, and at least the
   latest full turn is always kept, even if it alone exceeds the budget.

Typical size after compacting: task (~1K) + summary and note (~1–2K; at most ~2.7K under the
length limits, at ~3 characters per token) + recent (≤8K) ≈ 10–12K, comfortably below the notice
threshold. This holds only because old thinking isn't sent (the
prerequisite): with thinking, a single turn can be ~15K on its own. New turns are appended after this, so the start of the
active history (items 1–3) stays byte-identical until the next compaction and keeps hitting the
gateway's prefix cache (confirmed on: an identical ~30K-token prompt took 3.6 s, then 0.7 s).

The **full history is still recorded** in `self.messages`, so the trajectory file
(`agent/mini-swe-agent.trajectory.json`) keeps every turn. Only what is *sent* shrinks.

Accepted `self_compact` turns **don't count toward the step limit** (`AGENT_MAX_TURNS`, default
100), so compaction doesn't take work turns away from long tasks. Their tokens are fully counted.

Everything is behind one switch, `AGENT_COMPACTION=on|off` (default **off**), so it can be A/B
tested against the baseline and disabled without reverting code.

### Expected effect (static replay; an upper bound)

Replaying the run's per-call prompt sizes **with old thinking removed** (the prerequisite), then
compaction at a given hard threshold (counting the extra `self_compact` turn, a ~1.5K summary, the
8K recent budget and the 3-turn loop guard). Savings are relative to today's 77.2M:

| Setup | Total tokens | Saved | Compactions (30 tasks) |
|---|---|---|---|
| Strip old thinking only | 43.0M | 44% | 0 |
| **+ compaction at 75K† (the default hard cutoff, 30%)** | **36.8M** | **52%** | **5** |
| + compaction at 60K | 31.2M | 60% | 10 |
| + compaction at 50K† (the default warning, 20%) | 30.7M | 60% | 13 |
| + compaction at 40K | 27.0M | 65% | 20 |
| + compaction at 30K (the previous version's hard cutoff) | 22.4M | 71% | 32 |
| + compaction at 25K (the default notice, 10%) | 20.7M | 73% | 48 |
| + compaction at 20K | 19.0M | 75% | 75 |
| + compaction at 15K | 17.9M | 77% | 141 |

† Added in a re-run of the replay that takes each reply's thinking size from the gateway's
`reasoning_tokens`. On the shared rows it gives 44.4M (strip only), 33.4M (60K), 26.8M (40K), 22.9M
(30K) and 20.9M (25K), so it runs up to ~2M above the original; read the † rows with that margin.

**What the defaults mean.** Each row assumes the agent compacts as soon as it reaches that size, so
the result with 10% / 20% / 30% depends on **when the model chooses to compact**: only when forced at
75K gives ~36.8M (5 compactions, in 5 of 30 tasks); at the warning (50K), ~30.7M; at the notice
(25K), ~20.7M. The previous version forced compaction at 30K, which guaranteed ~22.4M whatever the
model did. The new defaults trade that guarantee for far fewer forced compactions (each one a risk of
losing state, and a cache miss): in the worst case they cost about 14M more tokens on these 30 tasks
(0.14 leaderboard points) than the 30K cutoff. Whether the model compacts before the cutoff is the
first open question below.

The replay assumes the model behaves the same after compacting. In reality it will re-read some
things it forgot, so real savings will be lower.

## Alternatives

- **A separate summarization call** (as in the pi developer's design this is based on). A dedicated
  prompt would likely produce more thorough summaries, but each compaction re-reads the whole old
  history (25–75K tokens at the default thresholds, plus the model's thinking), a large share of
  what each compaction saves, and adds a model call's latency to a time-limited task. Rejected for
  the first version; revisit if summaries prove too thin.
- **Keep a fixed number of recent turns (e.g. 3).** Simpler, but one large output is kept whole. In
  the baseline run the last-3-turns window was 4K at the median, 12K at the 90th percentile and up to
  35K (those figures include re-sent thinking, so they will be smaller after the prerequisite, but a
  single build log or disassembly can still be tens of thousands of characters). A large output in
  the recent turns would leave the agent near the thresholds right after compacting, so it would
  compact again almost immediately. The token budget caps the post-compaction size whatever the
  task prints.
- **Keep thinking in the kept turns** (instead of requiring the prerequisite). It might preserve the
  model's train of thought mid-step, but one kept turn can be ~15K of thinking, which breaks the 8K
  budget and puts the agent back near the thresholds right after compacting. Rejected: stripping
  old thinking everywhere is simpler and is measured on its own first.
- **Compaction without the prerequisite.** Between compactions every turn would still re-send all
  thinking since the last compaction, and the thresholds would be crossed mostly by thinking rather
  than by useful history. Stripping targets that 46% directly, with no summary and no state at risk.
- **Thresholds near the full context window** (compact only when about to run out, 250K). Only 4 of
  30 tasks ever got there. Our problem is token cost, not running out of window.
- **Absolute thresholds tuned for token cost: 20K / 25K / 30K** (this spec's previous version). A
  30K hard cutoff guarantees the replay's ~22.4M however the model behaves, where the 30% cutoff
  (75K) guarantees only ~36.8M. Replaced by 10% / 20% / 30% at the owner's decision: it matches the
  reference implementation, forces compaction in 5 of 30 tasks instead of 13 (fewer chances to lose
  state; an earlier history-cutting attempt lost long tasks), and follows the window when the model
  changes. The old values remain one env edit away (`COMPACT_NOTICE_AT=20000` etc., §1), and §10
  says when to go back to them.
- **Thresholds below 30K.** About 2 more points of savings per 5K step, for 50% or more extra
  compactions each time (see the replay table).
- **Offer `self_compact` only once the notice fires.** It would stop early calls, but it changes the
  tool list mid-task and costs an extra full cache miss every cycle (see Technical Plan).
- **Accept or reject early `self_compact` calls.** Accepting wastes a turn and a cache miss and
  loses detail for no savings; rejecting as a format error counts toward the 5-in-a-row stop that
  overruns already push against. A no-op reply costs only the turn.
- **No length limit on the summary and note, or a limit that is stated but not enforced.** Simpler,
  but the only bound is then `LLM_MAX_TOKENS` (16,384): an ~8K-token summary plus the 8K recent
  budget puts the agent at ~17K right after compacting, two thirds of the way to the default notice
  threshold, and the summary is re-sent on every later turn. Enforcing by **always rejecting** was also rejected: a model that can't
  shorten would hit the 5-in-a-row format-error stop and lose the task. **Always cutting silently**
  gives the model no chance to choose what to drop. Hence reject once, then cut (§3).
- **Keep the tool list unchanged at the hard cutoff** (the reference implementation does this: it
  rejects every other tool call with a reason; a variant forces the call with `tool_choice`). It
  would avoid the one cache miss per forced cycle, but that miss costs about 3 s (a ~30K-token
  prompt took 3.6 s uncached, 0.7 s cached) and no score, since the penalty counts cached input
  tokens too. Rejection alone lets the model spend 30K-token turns calling `bash`; forced
  `tool_choice` is untested with a reasoning model on this gateway. The swap stays, with the
  bash-in-forced-mode rejection (§3 case 1) as its backstop.
- **Keep forcing until the model compacts.** Without a limit, repeated failures in forced mode
  (overruns are likelier there: the model must write up to ~2.7K tokens of arguments after reading
  75K) run into the 5-in-a-row format-error stop and end a task that today would keep working. The
  tasks that reach the cutoff are the long ones §10 watches.
- **After failed forced attempts, compact without a summary** (keep the recent turns, say no summary
  was written). It keeps the token savings, but drops everything older than the recent 8K with
  nothing in its place, which is the state loss this design exists to avoid. Releasing the force
  (§5) loses only tokens.
- **Rule-based trimming** (shrink old turns to "command + one-line result" by fixed rules, no model
  involvement). Cheaper per turn and deterministic, but it can't carry forward *why* things were
  done or what comes next. It is a separate experiment and not part of this spec.
- **Harness-only compaction at a fixed point** (no notices; compact when the cutoff is hit). Simpler,
  but compacts mid-thought instead of at a natural stopping point. The notice/warning stages give
  the model a chance to choose; the cutoff keeps the guarantee.

## Detailed Implementation

All code changes are in `mini_agent/badger_mini/harbor_agent.py` (or a new module next to it,
e.g. `compaction.py`, imported from it), `mini_agent/badger_mini/config/terminal_bench.yaml`,
`mini_agent/pyproject.toml` (dev dependency) and new tests. **Nothing in the installed
`mini-swe-agent` package is modified.** It is pinned at `2.4.6`, and these points are relative to
that version:

- `DefaultAgent.run()` sets `self.messages = []`, then `add_messages()` the system and task messages,
  then loops `step()` → `query()` + `execute_actions()`. It catches `FormatError` and adds
  `e.messages`, and ends the task after `max_consecutive_format_errors` (5 in our config)
  consecutive format errors.
- `DefaultAgent.query()` checks `step_limit` against `self.n_calls` (and the cost and wall-time
  limits), increments `self.n_calls` for **every** call, sends `self.messages` via
  `self.model.query(self.messages)`, and `add_messages()` the response.
- `DefaultAgent.execute_actions()` runs `self.env.execute(action)` for every action and appends the
  observation messages from `self.model.format_observation_messages()`.
- Templates render with `jinja2.StrictUndefined`: **every variable a template uses must always be
  defined**, even when a feature is off.
- `LitellmModel._query()` passes `tools=[BASH_TOOL]` and merges `**kwargs` into the
  `litellm.completion(...)` call. **Any new keyword argument must be removed before it reaches
  litellm.**
- `LitellmModel._parse_actions()` uses `parse_toolcall_actions(tool_calls, format_error_template=…,
  template_kwargs={"finish_reason": …})`, which raises `FormatError` for no tool call or any tool
  other than `bash`, rendering `format_error_template` with `error`, `actions`, `has_tool_calls` and
  the template kwargs.
- A stored response (`message["extra"]["response"]`) is normally a dict, but mini-swe-agent falls
  back to a `repr` string if it can't serialize it. Code that reads `usage` must skip non-dicts,
  as `HarborSyncedAgent.add_messages()` already does.

### 1. Configuration

Read in `BadgerMiniAgent.run()` from the environment (like `AGENT_MAX_TURNS` today), documented in
`mini_agent/.env.example`:

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_COMPACTION` | `off` | `on` enables everything in this spec; `off` must behave exactly like today |
| `LLM_CONTEXT_WINDOW` | none | The model's context window in tokens (prompt + reply budget); `250000` for `qwen3.8-27b` on the UW gateway. Needed only to resolve percentage thresholds |
| `COMPACT_NOTICE_AT` | `10%` | Notice threshold |
| `COMPACT_WARNING_AT` | `20%` | Warning threshold |
| `COMPACT_HARD_AT` | `30%` | Hard cutoff |
| `COMPACT_RECENT_TOKENS` | `8000` | Token budget for recent turns kept after compacting |
| `COMPACT_MIN_TURNS_BETWEEN` | `3` | Loop guard (see §6) |

**Threshold values.** Each of the three `COMPACT_*_AT` values is either a plain positive integer, a
token count (`30000`), or a positive number below 100 followed by `%` (`30%`, `12.5%`), a
percentage of `LLM_CONTEXT_WINDOW`. A percentage resolves to `int(window * percent / 100)` (rounded
down). The three may mix forms. Resolve them **once at startup**; everything after §1 uses only the
resolved token counts, called the notice, warning and hard thresholds.

`LLM_CONTEXT_WINDOW` has **no default**: the window is a property of the endpoint and model, and a
built-in value would be silently wrong after a model change (the model for the submitted run will
not be `qwen3.8-27b`). Add `LLM_CONTEXT_WINDOW=250000` to `mini_agent/.env.example` next to
`LLM_MAX_TOKENS`, with a comment saying it is the UW gateway's value and must change with the
model, and add it to the env-var list in `mini_agent/CLAUDE.md`.

Validate at startup, **only when `AGENT_COMPACTION=on`**, failing with a clear error otherwise:
every threshold value has one of the two forms above; if any is a percentage, `LLM_CONTEXT_WINDOW`
is set to a positive integer; the resolved thresholds satisfy notice < warning < hard; the other
values are positive; `2 * COMPACT_RECENT_TOKENS` is at most the notice threshold (otherwise the
agent is back at the notice right after compacting); and **`AGENT_COMPACTION=on` requires
`AGENT_STRIP_REASONING=on`** (the prerequisite; the thresholds and the 8K budget assume no old
thinking is sent). With compaction off, none of these variables is read or validated, so today's
runs need no new setting.

**How the failure must surface.** Put the reading, resolving and validating in one function, e.g.
`load_compaction_config(environ) -> CompactionConfig | None` (`None` when off), that raises
`ValueError` with the offending variable and value in the message. Call it in
`BadgerMiniAgent.run()` **before the `try` block** that starts the agent thread, next to
`_model_config()`, which already raises `ValueError` there for a missing model. From that position
the error propagates out of `run()` and Harbor records the trial as an exception. Never validate
inside the `try` or inside the agent thread: that `except Exception` returns normally unless
`_is_config_error()` matches, so a bad `.env` would "finish" every task with no work and be graded
as 89 failures instead of an error.

`CompactionConfig` is a small dataclass with `notice_tokens`, `warning_tokens`, `hard_tokens`,
`recent_tokens` and `min_turns_between`, passed to `HarborSyncedAgent`.

The model needs only the on/off flag. The prerequisite spec adds `BadgerLitellmModelConfig`
(subclass of `LitellmModelConfig`, passed as `config_class=BadgerLitellmModelConfig` by
`BadgerLitellmModel.__init__`); add `compaction_enabled: bool = False` to it, and have
`_model_config()` set it from `AGENT_COMPACTION`. Because `LitellmModel.get_template_vars()` returns
the model config, `compaction_enabled` is then available to `instance_template` automatically.
Format-error templates don't get template vars from the agent; they get it through
`template_kwargs` (§3).

### 2. Estimating the history size

One function, `estimate_tokens(message)`, used everywhere:
`(len(str(message.get("content") or "")) + len(json.dumps(message.get("tool_calls") or [])))
/ 3`. The run's median is about 3 characters per token. Don't `json.dumps` the content: the
observation text is already JSON, and escaping it again inflates the estimate.

This counts only `content` and `tool_calls`, which is exactly what is **sent** for past assistant
messages once the prerequisite is on (it strips `reasoning_content` and
`provider_specific_fields`). Without the prerequisite the estimate would miss the re-sent thinking
(up to ~15K per turn); that's one reason §1 refuses to start compaction without it.

The agent keeps an **anchor**: `anchor_tokens` and `anchor_len`.

- In `query()`, record `sent_len = len(self.active)` just before calling the model.
- When the call returns a response whose `usage` is a dict, set `anchor_tokens =
  usage["prompt_tokens"]` and `anchor_len = sent_len`. Do this for normal responses **and** when the
  call raises `FormatError` (the response is in `e.messages[0]["extra"]["response"]`): catch it in
  `query()`, update the anchor, re-raise.
- If `usage` is missing or not a dict, leave the anchor unchanged.
- **Size** = `anchor_tokens + sum(estimate_tokens(m) for m in self.active[anchor_len:])`. This
  includes the assistant reply itself (it isn't part of its own `prompt_tokens`) and everything
  appended since.
- **After a compaction, reset the anchor** (`anchor_tokens = 0`, `anchor_len = 0`), so the size is
  estimated over the whole new active history. The kept turns carry the old responses' `usage`
  (up to the hard cutoff, 75K by default); those must never be read as the current size. Only responses to
  requests sent after the rebuild set a new anchor.

### 3. The `self_compact` tool and model changes (`BadgerLitellmModel`)

Tool definition (OpenAI function format, like mini-swe-agent's `BASH_TOOL`):

- name: `self_compact`
- parameters (both strings, both required): `summary`, `note_to_self`
- length limits: two module-level constants next to the tool definition, `SUMMARY_MAX_CHARS = 6000`
  and `NOTE_MAX_CHARS = 2000`. They are code constants, not env vars: they aren't experiment knobs
  like the thresholds, and the description below must be the same text on every request. Build the
  description **once at import** from these constants, so the tool definition is byte-identical for
  the whole run (it is part of the cached prompt start).
- description (the model's only instructions for writing a good summary; `{S}` and `{N}` are the two
  constants, rendered as plain digits, `6000` and `2000`):
  > Replace your older history with a summary to keep your context small. Call this alone, not
  > together with bash. `summary` (at most {S} characters) replaces everything before your most
  > recent turns, including any earlier summary, so carry forward anything from it that still
  > matters. Write it in this order: (1) done: files you created or changed, with exact paths, and
  > commands that worked; (2) verified: what you tested and the result; (3) decisions made and why;
  > (4) in progress: the current error or blocker with its exact message. The original task stays
  > visible word for word, so don't restate it. `note_to_self` (at most {N} characters): what you
  > were doing, ending with your next concrete action.

  The fixed order is a checklist, so nothing is skipped. Unlike in the reference implementation, the
  note is **not** the last thing the model reads before resuming: the kept recent turns follow the
  compaction message (§5). The order is for completeness, not position.

Changes in `BadgerLitellmModel` (it already subclasses `LitellmModel`):

- `query(messages, compact_only=False, **kwargs)`: store `compact_only` on the instance (so
  `_parse_actions` can see it), call `super().query(messages, **kwargs)` **without** it, and reset
  it in a `finally`.
- `_query(messages, **kwargs)`: when `compaction_enabled` is false, call `super()._query()`
  unchanged (today's `tools=[BASH_TOOL]`). When true, send `tools=[BASH_TOOL, SELF_COMPACT_TOOL]`
  (always in this order), or `tools=[SELF_COMPACT_TOOL]` while `compact_only` is set. The parent
  hardcodes the tool list, so `tools` **cannot be passed through `**kwargs`** (Python raises
  "multiple values for keyword argument"). Copy the parent's body and change only the list:
  ```python
  try:
      return litellm.completion(
          model=self.config.model_name, messages=messages, tools=<the list above>,
          **(self.config.model_kwargs | kwargs),
      )
  except litellm.exceptions.AuthenticationError as e:
      e.message += " You can permanently set your API key with `mini-extra config set KEY VALUE`."
      raise e
  ```
- `_parse_actions(response)`:
  - `parse_toolcall_actions` rejects every tool that isn't `bash`, so this override must handle
    `self_compact` calls itself. Hand the response to `parse_toolcall_actions` unchanged (as today)
    when it contains no `self_compact` call and case 1 below doesn't apply; that covers no tool
    call at all, plain `bash` calls, malformed `bash` calls and unknown tool names.
  - When `compaction_enabled` is false, behave exactly as today (a hallucinated `self_compact` call
    is rejected by `parse_toolcall_actions` as an unknown tool), except for passing the two extra
    template variables below.
  - Always pass `template_kwargs={"finish_reason": …, "compact_only": <bool>,
    "compaction_enabled": <bool>}` (both booleans always defined, see §8).
  - `bash` calls parse as today (`{"command", "tool_call_id"}`).
  - A `self_compact` call becomes `{"type": "self_compact", "summary", "note_to_self",
    "tool_call_id", "truncated"}` (`truncated` is a bool, false unless the length rule below cut a
    field).
  - Raise `FormatError`, rendering `format_error_template` with the same variables plus `error`,
    `actions=[]`, `has_tool_calls=True`, and the `extra={"interrupt_type": "FormatError"}` shape
    mini-swe-agent uses, in exactly these cases, with exactly these `error` strings. When several
    apply, **the first one in this list wins**:
    1. in `compact_only` mode, any `bash` call (alone or with `self_compact`): `"You called bash."`
       (kept this short because the forced-mode template in §8 already wraps every error in "Your
       context limit was reached, so bash is unavailable. … Reply with exactly one self_compact
       tool call …")
    2. `self_compact` together with any other tool call, or more than one `self_compact` call:
       `"Call self_compact once, alone, not together with other tool calls."`
    3. `self_compact` arguments that aren't valid JSON (likely when a reply is cut off by
       `finish_reason=length`): `"self_compact arguments were not valid JSON. Call it again with a
       summary and a note_to_self."`
    4. `summary` or `note_to_self` missing or empty: `"self_compact needs a non-empty summary and
       note_to_self."`
    5. `summary` longer than `SUMMARY_MAX_CHARS` or `note_to_self` longer than `NOTE_MAX_CHARS`,
       **unless the previous model call was rejected by this same case** (length rule below):
       `"self_compact was too long: summary is {s} characters (limit {S}), note_to_self is {n}
       characters (limit {N}). Call it again with shorter text; keep exact paths, commands and error
       messages."` `{s}` and `{n}` are the actual lengths; both are always shown, also when only one
       is over.
    Any other malformed `bash` call is left to `parse_toolcall_actions`, as today.
  - **Length rule.** Lengths are `len()` of the parsed argument strings (characters, not bytes or
    tokens); a field exactly at its limit is accepted. The model keeps one flag,
    `_length_rejected` (starts false). At the start of every `_parse_actions` call, read it into a
    local and set it to false; set it to true only when raising case 5. So it is true only if the
    immediately preceding model call ended in case 5. When a call is over-length and the local is
    true, **don't reject**: cut each over-length field to its limit and append
    `" [cut at the length limit]"` to it (the marker may exceed the limit), set
    `"truncated": True` on the action, and accept the call. Length alone can therefore cause at most
    one format error in a row, and never the RepeatedFormatError stop.
  - A response with no tool call at all (for example a reasoning overrun, `finish_reason=length`) is
    handled by `parse_toolcall_actions` as today; the new template variables make its message fit the
    mode (§8).

### 4. Agent state (`HarborSyncedAgent`)

- `self.messages`: unchanged meaning, the full log of everything (serialized to the trajectory).
- `self.active`: the list actually sent to the model. **Always a separate list object**, never the
  same list as `self.messages`. In off mode its contents are always equal to `self.messages`.
- Reset `self.active = []` and all counters in a `run()` override **before** calling
  `super().run()`, which then resets `self.messages` and adds the system and task messages through
  `add_messages()`, filling both lists.
- `add_messages()` appends to **both** lists and then calls `self._sync_context()`. Move today's
  token counting and `context.metadata` refresh into `_sync_context()` (token counting stays driven
  by the messages passed in).
- `_log_only(*messages)`: appends to `self.messages` only, then calls `_sync_context()`. Used only by
  an accepted compaction (§5), so the log and metadata stay current.
- Counters: `n_compactions`, `n_compaction_calls` (accepted `self_compact` turns),
  `n_compaction_noops` (early calls answered with a no-op reply, §5), `n_forced_releases` (§5), and
  `turns_since_compaction`, which counts **every** model call (any outcome) and starts at
  `COMPACT_MIN_TURNS_BETWEEN`, so the first cycle isn't blocked.
- Per-cycle state, all reset at every accepted compaction: three flags, `notice_sent`,
  `warning_sent` and `hard_sent`; `forced_failures` (model calls made in forced mode that ended in a
  `FormatError`); and `forced_released` (forcing was given up for this cycle).
- **Forced mode** is not stored separately. It is always
  `compact_only = hard_sent and not forced_released`.
- `size_at_query`: the size estimated at the start of the most recent `query()` (§5 step 3), before
  the model's reply was added. The no-op check in §5 uses it.

### 5. Agent flow

`query()` (override; don't call `DefaultAgent.query()`). **Copy the parent's body and change only
what the steps below name.** In mini-swe-agent 2.4.6 the parent is:

```python
def query(self) -> dict:
    if 0 < self.config.step_limit <= self.n_calls or 0 < self.config.cost_limit <= self.cost:
        raise LimitsExceeded({"role": "exit", "content": "LimitsExceeded",
                              "extra": {"exit_status": "LimitsExceeded", "submission": ""}})
    if 0 < self.config.wall_time_limit_seconds <= int(time.time() - self._start_time):
        raise TimeExceeded({"role": "exit", "content": "TimeExceeded",
                            "extra": {"exit_status": "TimeExceeded", "submission": ""}})
    self.n_calls += 1
    message = self.model.query(self.messages)
    self.cost += message.get("extra", {}).get("cost", 0.0)
    self.add_messages(message)
    return message
```

Everything not mentioned below stays, including the cost limit check, the `self.cost +=` line and
the return value. With compaction off, the override must behave exactly like this parent body.

`{size}`, `{hard}` and `{notice}` in the texts below are token counts shown in thousands by one
helper: `f"{max(1, int(n / 1000 + 0.5))}K"` (round half up, never below `1K`; 400 → `1K`, 27,499 →
`27K`, 27,500 → `28K`).

1. Keep the existing stop-event check.
2. Limits: same as `DefaultAgent.query()` (raise `LimitsExceeded` / `TimeExceeded` with the same
   messages), except the step limit compares `step_limit` with
   `self.n_calls - self.n_compaction_calls`, so accepted compactions don't use up work turns.
3. Estimate the size (§2) and store it as `size_at_query`. If `AGENT_COMPACTION` is on and the loop guard allows it
   (`turns_since_compaction >= COMPACT_MIN_TURNS_BETWEEN`), find the **highest** stage reached and
   append **only that stage's** message, once per cycle:
   - hard reached: if `hard_sent` is false, append the hard message and set all three flags. From
     then on forced mode is on (`compact_only`, §4) for every query until an accepted compaction or
     a release (next paragraph), without re-appending the message;
   - else warning reached and `warning_sent` false: append the warning and set `notice_sent` and
     `warning_sent`;
   - else notice reached and `notice_sent` false: append the notice and set `notice_sent`.
   Stage messages are user messages with `extra={"badger_notice": "notice"|"warning"|"hard"}`,
   added through `add_messages()`. The exact texts (`{size}` is the estimate rounded to thousands,
   e.g. `27K`; `{hard}` is the resolved hard threshold in thousands, e.g. `75K`):
   - notice: `[Context note: your history is about {size} tokens. At a natural stopping point, e.g.
     right after a step succeeds, call self_compact with a summary of your work and a note to
     yourself. You can keep working until then.]`
   - warning: `[Context warning: your history is about {size} tokens. Call self_compact within your
     next one or two turns. At {hard} tokens, bash becomes unavailable until you do.]`
   - hard: `[Context limit reached: your history is about {size} tokens. bash is unavailable until you
     call self_compact. Call it now with a summary of your work and a note to yourself.]`

   **Release.** Then, still before the call: if `hard_sent` is true, `forced_released` is false and
   `forced_failures >= FORCED_MAX_FAILURES` (a module constant, `2`), give up forcing for this
   cycle: set `forced_released = True`, `n_forced_releases += 1`, and append, through
   `add_messages()`, a user message with `extra={"badger_notice": "released"}`:
   `[Context limit: compaction failed {FORCED_MAX_FAILURES} times, so bash is available again.
   Continue the task. When you can, call self_compact with a short summary and a note to yourself.]`
   No further stage message is sent in this cycle (all three flags are already set). A later
   `self_compact` call in the same cycle is handled like any voluntary one, and an accepted
   compaction starts a new cycle in which forcing works again.
4. `self.n_calls += 1`, `turns_since_compaction += 1`; record `sent_len`; call
   `self.model.query(self.active, compact_only=…)` in place of the parent's
   `self.model.query(self.messages)`, with `compact_only` as defined in §4. Update the anchor on
   success or `FormatError` (§2). If the call was made with `compact_only=True` and raises
   `FormatError`, also `forced_failures += 1` before re-raising. Then the parent's last three lines,
   unchanged: add to `self.cost`, `add_messages()`, return the message.

`execute_actions(message)` (override):

- If the message's only action is `self_compact`:
  - **In `compact_only` mode, always compact.** The "not needed" check below never applies to a
    forced request; otherwise estimate errors near the thresholds could leave the agent stuck in
    forced mode, burning turns on no-op replies that don't count as format errors.
  - **Not needed** (not forced, and either `size_at_query` is below the notice threshold or
    `turns_since_compaction < COMPACT_MIN_TURNS_BETWEEN`): don't compact and don't touch the
    environment. Add, through `add_messages()`, a `tool` message answering the call (same
    `tool_call_id`) with, when the guard blocked it:
    `Not compacted: you compacted recently (the last compaction was {k} model call(s) ago). Continue
    working.` (`{k}` is `turns_since_compaction`, which already includes this call), otherwise:
    `Not compacted: your history is about {size} tokens; compaction is only needed from {notice}
    tokens. Continue working.` (`{size}` is `size_at_query` rounded to thousands, e.g. `9K`;
    `{notice}` is the resolved notice threshold in thousands, e.g. `25K`). This is
    a normal turn: it counts toward the step limit and is not a format error. Also
    `n_compaction_noops += 1`.
  - **Shape of the `tool` messages the harness writes itself** (this no-op reply, and the
    "Context compacted." reply in step 7 below): `{"role": "tool", "tool_call_id": <the call's id>,
    "content": <the text>, "extra": {"badger_self_compact": "noop" | "compacted", "timestamp":
    time.time()}}`. These are the same top-level keys `format_observation_messages()` produces for a
    `bash` result; the command-specific `extra` keys (`raw_output`, `returncode`, `exception_info`)
    are left out because no command ran.
  - **Otherwise**, run the compaction below.
- Otherwise defer to `DefaultAgent.execute_actions()`.

The compaction:

1. Take the active history **excluding** the system prompt, the task, any previous compaction
   message, and the `self_compact` assistant message just added.
2. Drop `badger_notice` messages **and format-error notes** (user messages whose `extra` has
   `interrupt_type == "FormatError"`). They describe a situation the compaction just ended; for
   example, a kept forced-mode note saying "bash is unavailable, call self_compact" would contradict
   the compaction message and could make the model call `self_compact` again. Messages that come
   before the first assistant message belong to no turn and are dropped too.
3. Split the rest into **turns**. A turn is one assistant message plus **every** message that
   follows it up to the next assistant message (its `tool` results, and any other message that
   survived step 2), so no message is left outside a turn.
4. Walking backwards from the newest turn, keep whole turns while the running sum of
   `estimate_tokens` stays ≤ `COMPACT_RECENT_TOKENS`. Always keep at least one turn. The kept part
   therefore starts with an assistant message, and no tool result is left without its call.
5. Build the compaction message (role `user`):
   ```
   [Context compacted (#{n}). Your earlier turns were replaced by your own summary below.
   The task above is unchanged. Your most recent turns follow this message.]

   Summary of earlier work:
   {summary}

   Note to self:
   {note_to_self}
   ```
   with `extra={"badger_compaction": {"n": n, "turn": self.n_calls, "size_before": …,
   "size_after": …, "turns_dropped": …, "turns_kept": …, "forced": <was compact_only on>,
   "stage": …, "summary_chars": …, "note_chars": …, "truncated": <the action's flag, §3>,
   "kept_message_indices": [indices into self.messages of the kept messages]}}`.
   `size_before` is `size_at_query` (the size the model saw when it decided to compact).
   `size_after` is the §2 size of the rebuilt active history, computed after step 6 and the anchor
   reset. `stage` is the highest stage message sent in this cycle, read from the flags before
   step 8 resets them: `"hard"`, else `"warning"`, else `"notice"`, else `"none"` (possible when the
   call lands on the first turn the loop guard allows). `forced` is false and `stage` is `"hard"`
   for a compaction made after a release. The two lengths
   are of the text as placed in the message (after any cut). The indices make
   the log exact: the kept turns appear earlier in `self.messages`, not after this message.
6. Set `self.active = [system, task, compaction_message] + kept_turns`. Note that the task and the
   compaction message are two `user` messages in a row. **Confirmed on 2026-09-30** for
   `qwen3.8-27b` on the UW gateway: a request shaped system, user (task), user (compaction message),
   assistant (`bash` call), tool (result) was accepted and the model followed the note. A different
   model or endpoint has a different chat template, so repeat the check there **before** building on
   it (§10); if one rejects it, put the compaction text into the task message's turn instead (one
   `user` message: the task, a blank line, then the compaction text).
7. `_log_only()` a `tool` message answering the `self_compact` call (`"Context compacted."`, same
   `tool_call_id`, the shape given above), then the compaction message. Neither the `self_compact` assistant message nor
   this reply goes into `self.active`; the compaction message stands in for both.
8. `n_compactions += 1`, `n_compaction_calls += 1`, `turns_since_compaction = 0`, reset the
   per-cycle state (the three flags, `forced_failures = 0`, `forced_released = False`), reset the
   anchor (§2).
9. Return the messages added, as `execute_actions()` does.

### 6. Loop guard

- Stage messages and the hard cutoff only apply when `turns_since_compaction >=
  COMPACT_MIN_TURNS_BETWEEN`. Otherwise a single kept turn larger than the cutoff would force
  compaction every turn. The 250K context window remains the ultimate limit.
- Early `self_compact` calls get a no-op reply (§5) and count toward the step limit, so the model
  can't loop on them.
- Existing behavior still applies: 5 consecutive `FormatError`s end the task (RepeatedFormatError).
  An overrun while in `compact_only` mode counts toward that. So does an over-length `self_compact`
  call (§3 case 5), but the next over-length call is accepted, so length adds at most one.
- **Forced mode adds at most `FORCED_MAX_FAILURES` (2) format errors in a row**, then releases
  (§5). So forcing alone can never reach the 5-in-a-row stop. It can still tip a task that entered
  forced mode already 3 or 4 consecutive format errors deep; that task was one or two errors from
  stopping anyway, and this is accepted.
- After a release the history keeps growing as it does without this feature; the 250K context
  window is again the only limit until the model compacts on its own.

### 7. Token accounting and metadata

- No extra model calls are introduced. The `self_compact` turn is an ordinary call, and its usage is
  counted by `add_messages()` → `_sync_context()`, so Harbor's `n_input_tokens` /
  `n_output_tokens` stay accurate. If a later version adds a separate summarization call, its usage
  **must** be added to the same counters.
- Add to `context.metadata`, always: `compaction: true/false` (like the prerequisite's
  `strip_reasoning`), so every job records which mode it ran in. Only when on, also:
  `compaction_thresholds` (`{"notice": …, "warning": …, "hard": …, "recent": …}`, the resolved token
  counts, so a rerun with other thresholds is told apart from its job data alone), `n_compactions`,
  `n_compaction_calls`, `n_compaction_noops`, `n_forced_releases`, and a list of the
  `badger_compaction` records (`n`, `turn`, `size_before`, `size_after`, `turns_dropped`,
  `turns_kept`, `forced`, `stage`, `summary_chars`, `note_chars`, `truncated`). These are what §10's
  report is computed from.

### 8. Prompts (`terminal_bench.yaml`)

With `AGENT_COMPACTION=off`, every rendered prompt and error message must be **byte-identical** to
today's. Use `{%- if … %}` / `{% endif %}` whitespace control accordingly, and test it (§9).
**Before editing the YAML**, render today's versions and save them as golden files for that test,
in `mini_agent/tests/golden/` (`instance_prompt.txt`, and one `format_error_<case>.txt` per case):
the instance prompt for a fixed sample task, and `format_error_template` for each case (no tool call
with `finish_reason` `length`, `tool_calls` and `stop`; an unknown tool; invalid bash arguments).

"Overrun" below means the same condition today's template uses: `finish_reason == "length"`, or
`finish_reason == "tool_calls"` with no tool calls (`has_tool_calls` false).

`instance_template`:

- Replace the line
  `- Every response MUST include exactly one bash tool call. Keep the reasoning text short.`
  with
  `- Every response MUST include exactly one {% if compaction_enabled %}tool call: bash, or self_compact when compacting{% else %}bash tool call{% endif %}. Keep the reasoning text short.`
- After the "Command execution rules" list, add, only when `compaction_enabled`:
  > ## Context limit
  >
  > Your context is limited. When it grows, you'll be asked to call `self_compact` with a summary of
  > your work so far and a note to yourself; do it at a natural stopping point, e.g. right after a
  > step succeeds. If the limit is reached, only `self_compact` is available until you call it.

`format_error_template` (all three branches use `compact_only` and `compaction_enabled`, which are
always passed, §3):

- **Forced mode** (`compact_only` true), checked first, for any error including an overrun:
  `Your context limit was reached, so bash is unavailable. {{error}} Reply with exactly one
  self_compact tool call: a short summary of your work so far and a note to yourself.` For an
  overrun, use `You ran out of thinking budget before making a tool call.` in place of `{{error}}`,
  and add `Keep it brief.`
- **Overrun, not forced**: today's text, except that with `compaction_enabled` its ending,
  today `reply with exactly one bash tool call.`, reads
  `reply with exactly one tool call (bash, or self_compact if you were asked to compact).`
- **Other errors, not forced**: today's text when compaction is off. When on, keep the
  `Tool call error:` line and the `<error>` block, and replace the two guidance lines after it,
  today `Every response must call the 'bash' tool exactly once with {"command":
  "your_command_here"}.` and ``To finish, call it with `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
  and no other command.``, with: `Every response must call exactly one tool: bash with {"command": "..."}, or
  self_compact with {"summary": "...", "note_to_self": "..."}. To finish, call bash with echo
  COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT and no other command.`

### 9. Tests (offline, `mini_agent/tests/`, pytest)

The prerequisite spec adds `pytest` as a dev dependency (`uv pip install -e "mini_agent/[dev]"`).
If this is built first, add it here instead. In `mini_agent/tests/conftest.py`, build the fixtures
first; nothing needs a model endpoint or Docker:

- a **scripted model**: a `BadgerLitellmModel` subclass that doesn't call litellm. Its `_query()`
  returns prepared response objects in order (content, `tool_calls` with `bash`/`self_compact`
  names, `finish_reason`, `usage.prompt_tokens`), and it records the `tools` and `messages` of every
  request, so tests can inspect exactly what was sent;
- a **fake Harbor environment** with an async `exec()` that returns fixed `ExecResult`s;
- an `AgentContext`, and env vars set through `monkeypatch`.

Cases:

- **Off switch:** with `AGENT_COMPACTION=off`, requests offer only `bash`, `self.active` equals
  `self.messages`, and the rendered instance prompt and every format-error message equal the golden
  files (§8) byte for byte.
- **Startup validation:** compaction on with `AGENT_STRIP_REASONING=off`, or thresholds out of
  order, fails with a clear error. So does a percentage threshold without `LLM_CONTEXT_WINDOW`, and
  a malformed value (`abc`, `0`, `-5`, `0%`, `100%`, `30 percent`), and a recent budget above half
  the notice threshold. With compaction off, a missing `LLM_CONTEXT_WINDOW` and malformed thresholds
  are ignored. Each failure is a `ValueError` naming the variable, and
  **`BadgerMiniAgent.run()` itself raises it** (call `run()` with the fake environment and assert it
  raises, so the error can't be swallowed into a normal return).
- **Threshold resolution:** with no `COMPACT_*_AT` set and `LLM_CONTEXT_WINDOW=250000`, the
  thresholds are 25000 / 50000 / 75000; `12.5%` of 250000 is 31250; a result with a fraction is
  rounded down; plain token counts work without `LLM_CONTEXT_WINDOW`; mixed forms work
  (`COMPACT_NOTICE_AT=20000` with the other two as percentages).
- **Size estimate:** uses the anchor from the latest response plus estimates for later messages;
  after a compaction it ignores the kept turns' old `usage`; a `repr`-string response doesn't crash.
- **Stages:** notice and warning each fire once per cycle; only the highest stage's message is
  added when one output crosses several thresholds; the hard cutoff adds its message once and sends
  only `self_compact` until an accepted compaction or a release.
- **Tool list:** with compaction on, every non-forced request offers `[bash, self_compact]` in that
  order.
- **Early calls:** `self_compact` below the notice, or within the guard, gets the matching no-op
  reply (using `size_at_query`), doesn't change `self.active`'s prefix, isn't a format error, and
  counts toward the step limit. In `compact_only` mode, `self_compact` is always accepted, even if
  the size estimate is below the notice.
- **Recent-turn selection:** respects the budget; never separates a tool call from its result;
  keeps at least one turn even when that turn exceeds the budget; starts with an assistant message;
  drops notice messages, format-error notes (including forced-mode ones) and pre-first-assistant
  messages.
- **Rebuild:** the active history is system + task (byte-identical) + compaction message + kept
  turns; its first three messages are unchanged across later turns until the next compaction;
  `self.messages` contains every original message plus the tool reply and compaction message, and
  `kept_message_indices` point at the right messages.
- **Format errors:** each §3 case raises `FormatError` with its exact string (bash in forced mode,
  `self_compact` with `bash`, two `self_compact` calls, invalid JSON arguments, empty arguments);
  `bash` + `self_compact` in forced mode gets the forced-mode error (precedence); an overrun in
  forced mode gets the forced-mode overrun text, for both overrun conditions.
- **Length limits:** the tool description contains both limits and is the same string on every
  request; a field exactly at its limit is accepted; one character over raises case 5 with both
  actual lengths; a second over-length call right after is accepted, with only the over-length
  field(s) cut to the limit plus the marker, `truncated` true in the action and in the compaction
  record; over-length → `bash` → over-length rejects the second one again (the flag reset); empty
  arguments still get case 4, not case 5 (precedence).
- **Forced release:** two format errors in forced mode (any mix of overrun, `bash` call, invalid or
  empty arguments) → the next request offers `[bash, self_compact]`, the release message is appended
  exactly once, `n_forced_releases` is 1, and no stage message follows in that cycle; one failure
  followed by an accepted `self_compact` causes no release; after a release a `self_compact` call is
  accepted with `forced` false and `stage` `"hard"`, and in the next cycle the hard cutoff forces
  again; format errors made outside forced mode don't count as forced failures.
- **Limits:** accepted compactions don't count toward `step_limit`; no-op calls do. The cost limit
  and `self.cost` work as before (give the scripted model a nonzero `cost` and check both).
- **Accounting:** token counts in the Harbor context include the `self_compact` turn; the metadata
  has `compaction`, the resolved thresholds, the four counters and each compaction's record, with
  `size_before` equal to that turn's `size_at_query` and the right `stage` for a compaction at the
  notice, at the warning, when forced, and with no stage message. With compaction off, the only
  metadata change is `compaction: false`.
- **Formatting:** the thousands helper gives `1K` for 400, `27K` for 27,499 and `28K` for 27,500.

### 10. Measurement and success criteria

**Before writing code for a new model or endpoint:** send one live request shaped like a rebuilt
history (system, user task, user compaction-style message, assistant `bash` call, tool result) and
confirm the gateway accepts it. Done for `qwen3.8-27b` on the UW gateway on 2026-09-30 (§5 step 6);
the model for the submitted run needs its own check, because the fallback changes §5 step 6.

Run `op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_subset.sh
eval/experiment_subset.txt` with `AGENT_STRIP_REASONING=on` and `AGENT_COMPACTION=on`. Compare
against **the prerequisite's strip-only run** (so the difference is compaction alone), and also
report the totals against the original baseline job `mini_agent/jobs/2026-09-27__12-44-55`
(77.2M tokens, 15/30). Keep the model and all other settings the same, including `LLM_MAX_TOKENS`.

- **Success:** total tokens at least 25% below the strip-only run (less is not worth the risk)
  **and** passes not below the strip-only run's. The replay's upper bounds against strip-only, for
  the default thresholds: about −17% if the model compacts only when forced (75K), −31% if it
  compacts at the warning (50K), −53% if at the notice (25K). So the defaults can reach 25% **only
  if the model usually compacts before the hard cutoff**.
- **If the result is under 25% and most compactions were forced:** don't drop the feature. Rerun with
  the previous version's thresholds, `COMPACT_NOTICE_AT=20000`, `COMPACT_WARNING_AT=25000`,
  `COMPACT_HARD_AT=30000` (replay: −48%), and judge that run by the same two criteria.
- Also report: compactions per task, how many were forced vs chosen at a notice/warning (the
  records' `stage`), forced releases and whether those tasks passed, no-op
  calls, post-compaction sizes, summary and note lengths, how many calls were rejected for length
  (count the §3 case 5 text in the trajectories) and how many were cut, turns per task, overruns,
  and whether the long tasks
  (`custom-memory-heap-crash`, `video-processing`, `path-tracing`, `mailman`,
  `winning-avg-corewars`) still pass. An earlier history-cutting attempt lost long tasks, so watch
  them specifically.
- Runs are single samples. Judge by changes across many tasks, not single-task flips.

## Open questions (decide from the first run)

- Does Qwen compact at the notice/warning, or mostly only when forced? With the percentage
  defaults this decides most of the savings (replay: 36.8M forced-only vs 20.7M at the notice). If
  mostly forced, the notices are wasted tokens and the thresholds should come down (§10).
- Are the summaries good enough? Check a few compaction messages by hand in the trajectories of
  tasks that failed after compacting.
- Is 10% / 20% / 30% (25K / 50K / 75K) right? In the replay only 13 of 30 tasks ever pass 25K, 9
  pass 50K and 5 pass 75K, so most tasks never see a stage message. Recheck with the strip-only
  run's real history sizes before the first compaction run; the replay's are estimates.
- Would a separate summarization call (rejected above) recover passes lost to thin summaries?
- Are 6,000 / 2,000 characters right? They are sized from the replay's ~1.5K-token summary, not
  measured, and were chosen when the hard cutoff was 30K; at 75K one summary replaces up to ~65K
  tokens of history. If many calls are rejected for length, or summaries of long tasks sit at the limit and
  those tasks fail after compacting, raise them; if most summaries are far below, leave them.

## Revision history

- **2026-09-30, first draft.**
- **2026-09-30, after goldfish test.** Fixed: format-error and prompt wording that told the model to
  call bash while bash was blocked (§8); prompt variables undefined when off (`StrictUndefined`) and
  the off-mode byte-identical requirement (§8, §9); exact texts for the three stage messages and the
  "highest stage only" rule (§5); keeping `self.messages`/`self.active` in sync, including
  `run()`'s reset and metadata refresh for log-only messages (§4); stale size after compaction and
  the reply's own size (§2); undefined turn counting and its starting value (§4, §5); messages before
  the first assistant message (§5); test fixtures that didn't exist (§9); exact log indices, the
  size estimate's escaping, the metadata `turn` field, and `repr`-string responses (§2, §5).
  Decided: early `self_compact` calls get a no-op reply; accepted compactions don't count toward the
  step limit, no-op calls do; `self_compact` is offered for the whole task because the tool list is
  part of the cached prompt start.
- **2026-09-30, after second goldfish test.** Found: every stored assistant message carries its
  thinking (twice), and re-sent thinking was ~46% of input tokens, which the size estimate and the 8K
  budget ignored. Decided: stop re-sending old thinking as a separate prerequisite
  ([strip-old-reasoning](strip-old-reasoning.md)), required by this feature; thresholds lowered to
  20K / 25K / 30K and the replay redone on stripped histories. Fixed: stale format-error notes in kept
  turns (§5); forced mode can't get stuck on no-op replies (§5); the no-op check's size and `{k}`
  wording (§4, §5); two `self_compact` calls, invalid JSON arguments and error precedence (§3); the
  overrun condition matching today's template (§8); golden files for the off-mode test (§8, §9); where
  `compaction_enabled` comes from, and the `config_class` wiring (§1); two consecutive user messages
  listed as an assumption to check (§5, §10). Measurement now compares against the strip-only run.
- **2026-09-30, after comparing with the reference implementation's source**
  (github.com/disler/self-compact-pi-agent). Added: length limits on `summary` and `note_to_self`,
  stated in the tool description and enforced as reject once, then cut (Technical Plan, §3, §5–§7,
  §9, §10); a fixed order for the summary's content, with the note ending on the next action (§3).
  Considered and not changed: keeping the tool list unchanged at the hard cutoff (Alternatives).
- **2026-09-30, thresholds changed to the reference implementation's 10% / 20% / 30%** of the
  context window (25K / 50K / 75K at 250K), replacing 20K / 25K / 30K, at the owner's decision.
  Added: `LLM_CONTEXT_WINDOW`, and `COMPACT_NOTICE_AT` / `COMPACT_WARNING_AT` / `COMPACT_HARD_AT`
  (percentage or token count) in place of the `COMPACT_*_TOKENS` variables (§1, §9); replay rows for
  50K and 75K and what the defaults guarantee (Expected effect); the success criterion restated for
  the new defaults, with a fallback to the old thresholds (§10). Not changed: the 8K recent budget
  and the summary and note length limits, both chosen under the old thresholds (Open questions).
- **2026-09-30, after third goldfish test** (findings checked against the mini-swe-agent 2.4.6
  source). Decided: forced mode gives up after 2 failed attempts and releases `bash` for that cycle,
  instead of forcing until the 5-in-a-row stop or compacting without a summary (Technical Plan,
  Alternatives, §4–§6). Confirmed live: the gateway accepts two `user` messages in a row (§5 step 6,
  §10). Fixed: the forced-mode error said the same sentence twice (§3 case 1); where a startup
  validation error must be raised so it fails the run instead of being graded (§1); `query()` and
  `_query()` are now "copy the parent, change only this", with the parent bodies quoted, because
  `tools` can't go through `**kwargs` and the cost line was missing (§3, §5); `_parse_actions` must
  handle `self_compact` before `parse_toolcall_actions` (§3); the metadata lacked what §10 reports
  (`stage`, no-op and release counters, the mode and resolved thresholds) (§4, §5, §7);
  `size_before` / `size_after`, the thousands rounding, the harness-written `tool` message shape,
  the turn definition, the quoted current prompt text, the golden-file location, and a check that
  the recent budget is at most half the notice threshold (§1, §5, §8).
