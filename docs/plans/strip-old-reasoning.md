# Stop re-sending old reasoning

Status: **agreed design, not implemented** (2026-09-30). Owner: khayyum04. Comes **before**
[self-compaction](self-compaction.md), which assumes it is on.

Context to read first: `mini_agent/CLAUDE.md` (how the adapter works) and
`docs/research/mini-30-vs-baseline.md` (the run the numbers come from).

## Problem

Qwen is a reasoning model: before each reply it writes private thinking, which the gateway returns
separately from the reply. mini-swe-agent stores each assistant message as the gateway returned it,
and **the thinking is stored twice**: in `reasoning_content` and in
`provider_specific_fields.reasoning`. Before each request, `LitellmModel._prepare_messages_for_api()`
removes only mini-swe-agent's own `extra` field, so **all earlier thinking is sent back to the model
on every later turn**, and the gateway counts it as input.

On the 30-task subset (job `mini_agent/jobs/2026-09-27__12-44-55`, `qwen3.8-27b`), all 1,223
assistant messages carried thinking, and re-sent thinking was about **34M of the 75M prompt tokens
(46%)**. One step's prompt grew by 14,952 tokens, of which the visible reply and command were ~250
and the thinking ~14,900. The gateway never drops old thinking (prompt size never went down within a
task).

This matters more as `LLM_MAX_TOKENS` grows: today every thinking token is paid again on every later
turn, so allowing longer thinking multiplies the waste.

## Technical Plan

Before each request, send each earlier assistant message with **only** the fields the model needs:
`role`, `content` and `tool_calls`. Its thinking is dropped. The model still thinks fresh on every
turn; it just doesn't re-read its old thinking. Its commands, the command outputs and its visible
replies are all kept.

- The trajectory log (`self.messages`) is unchanged and keeps every thinking block. Only what is
  *sent* changes.
- The stripping happens the same way every time, so each message's sent form never changes after it
  is stored. The start of the history stays stable, and the gateway's prefix cache keeps working.
- Token accounting is unchanged: Harbor's counts come from the gateway's `usage`, which will simply
  be smaller.
- Behind a switch, `AGENT_STRIP_REASONING=on|off` (default **off**, so today's behavior doesn't
  change until it's measured).

Expected effect, from a static replay of the run (removing each assistant message's thinking from
every later prompt): **77.2M → 43.0M tokens (−44%)**. The median task's peak history drops to about
22K (max 141K; 10 of 30 tasks still peak above 40K).

**The risk:** Qwen may reason better when it can see its earlier thinking during multi-step tool
use. Qwen3's official chat template keeps the thinking of assistant turns after the last user
message, and in our agent that is every turn. So the pass count, overrun rate and turns per task
must be measured, not assumed.

## Alternatives

- **Keep thinking for the last N turns, drop it from older ones.** Might protect the model's train of
  thought mid-step. But stripping a message when it leaves the window changes an already-sent message,
  which loses the prefix cache from that point on every turn, and it needs a tuned N. Revisit only if
  stripping everything costs passes.
- **Summarize old thinking.** Needs a model call; that's what self-compaction does for the whole
  history.
- **Leave it and rely on compaction.** Compaction would still re-send thinking between compactions,
  and its size budgets would be dominated by thinking (a single kept turn can be ~15K). Stripping is
  simpler, risks no state, and targets the largest single share of input tokens.
- **Raise the thinking budget only on the retry after an overrun** (research item C4, in
  `docs/research/full-89-0924-fix-priorities.md`). A separate lever, about overruns rather than
  re-sent tokens. Compatible with this change.

## Detailed Implementation

All changes are in `mini_agent/badger_mini/harbor_agent.py` (`BadgerLitellmModel`, which already
subclasses mini-swe-agent's `LitellmModel`), `mini_agent/.env.example`, and new tests. **Nothing in
the installed `mini-swe-agent` package (pinned `2.4.6`) is modified.**

1. **Switch.** Read `AGENT_STRIP_REASONING` (`on`/`off`, default `off`) in `_model_config()`, and
   pass it to the model as a config field. Add a `BadgerLitellmModelConfig(LitellmModelConfig)`
   with `strip_reasoning: bool = False`. `BadgerLitellmModel.__init__` must pass
   `config_class=BadgerLitellmModelConfig` to `LitellmModel.__init__` (otherwise the new field fails
   validation). The self-compaction spec adds its own field to the same config class. Document the
   switch in `.env.example`.
2. **Stripping.** Override `_prepare_messages_for_api(messages)`: call `super()` first (it removes
   `extra` and applies cache-control settings), then, if `strip_reasoning` is on, replace every
   message whose `role` is `assistant` with a dict containing only its `role`, `content` and
   `tool_calls` keys (omit `tool_calls` if it is `None` or absent). Leave `system`, `user` and `tool`
   messages untouched. Don't modify the input list or its dicts: build new dicts, so `self.messages`
   and the trajectory keep the thinking.
3. **Off means identical.** With the switch off, `_prepare_messages_for_api` must return exactly
   what it returns today.
4. **Metadata.** Add `strip_reasoning: true/false` to `context.metadata`, so every job records
   which mode it ran in.

### Tests (offline, `mini_agent/tests/`, pytest)

There are no tests yet. Add `pytest` as a dev dependency in `mini_agent/pyproject.toml`
(`[project.optional-dependencies] dev = ["pytest"]`, installed with
`uv pip install -e "mini_agent/[dev]"`). The self-compaction spec reuses this setup.

- With the switch on, prepared assistant messages contain exactly `role`, `content` and
  `tool_calls` (no `reasoning_content`, no `provider_specific_fields`); other roles are unchanged;
  the original message dicts still contain their thinking.
- With the switch off, the prepared messages equal today's output for the same input. Use a stored
  assistant message from a real trajectory as the fixture, since it has both thinking fields.
- Preparing the same history twice gives identical output (a stable prefix).

### Live check before the full run

Run one sample task with the switch on and confirm, from its trajectory, that the growth in
`prompt_tokens` between consecutive calls now roughly matches the visible content added (reply +
command + output). Today, on steps with heavy thinking, it is a median 7.8x larger and up to ~60x. If it doesn't drop, the
gateway gets the thinking some other way and the change has no effect.

### Measurement and success criteria

`op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_subset.sh
eval/experiment_subset.txt` with `AGENT_STRIP_REASONING=on`, compared with the baseline job
`mini_agent/jobs/2026-09-27__12-44-55`. Change nothing else, **including `LLM_MAX_TOKENS`**: one
change per measurement, or the effects can't be told apart.

- **Success:** total tokens down about 40% (the replay says 44%) **and** passes not below 15/30.
- Also report: overruns (replies with no tool call and `finish_reason=length`), RepeatedFormatError
  exits, turns per task, and time per task. More overruns or turns would mean the model misses its
  old thinking.
- Runs are single samples. Judge by changes across many tasks, not single-task flips.

## Revision history

- **2026-09-30, first draft.** Split out of the self-compaction design after its second goldfish
  test found re-sent thinking to be 46% of input tokens.
