# Thinking cap (cut time-limit failures, step 1)

Agreed 2026-10-07 (Mukhriz, with Claude). Branch: `feat/thinking-cap`, from `main`.

## Problem

Under the capped scoring rule, passes come first and tokens only break ties. In `full-mini-v1`
(52/89), **31 of the 37 failures never finished**: 23 hit the task's time limit (900–3,600 s, set per
task), 3 quit after 5 thinking overruns in a row, 3 hit the 100-turn cap, 2 filled the context. Only 6
submitted a wrong answer, and all 6 had tested their work first.

About 84% of task time is model generation, not commands (30-task subset: 6.5 h model, 1.3 h
commands). Replies may think for up to `LLM_MAX_TOKENS` = 16,384 tokens, over 3 minutes at ~80
output tokens/s. Only 2% of replies went above 8K tokens, but they produced 24% of all output.

## Technical Plan

A new setting `AGENT_THINKING_CAP` (default off). When set, each reply gets
`max_tokens = AGENT_THINKING_CAP` (thinking included). A reply that hits its limit
(`finish_reason=length`, which usually has no tool call and becomes a FormatError) makes the next
call use the full `LLM_MAX_TOKENS`; calls stay at the full budget until a reply finishes normally,
then drop back to the cap. Tested value: **8,192**, retry at 16,384.

Normal turns are faster; hard steps still get the full budget, at the cost of one wasted turn first.

## Alternatives

- **Lower `LLM_MAX_TOKENS` alone.** No code, but a reply that needs more thinking has nowhere to go:
  more overruns, and more tasks quitting after 5 in a row.
- **Prompt only** ("think briefly"). The prompt already says "keep the reasoning text short".
- **6,000 or 4,000 cap.** Bigger effect and bigger risk; try only if 8,192 helps.

## Detailed Implementation

- `BadgerLitellmModel` (`mini_agent/badger_mini/harbor_agent.py`): class attributes `thinking_cap = 0`,
  `_boost_next = False`, `n_boosted_calls = 0`. `_query()` sets `max_tokens` to
  `min(thinking_cap, model_kwargs["max_tokens"])` unless boosted, counts boosted calls, and after the
  response sets `_boost_next = finish_reason == "length"`. Works with and without the compactor.
- `BadgerMiniAgent.run()`: `model.thinking_cap = int(AGENT_THINKING_CAP or 0)`, set after `get_model()`
  like the other switches.
- `HarborSyncedAgent._sync_context()`: `thinking_cap` and `n_boosted_calls` in the result metadata.
- `.env.example`, `mini_agent/CLAUDE.md`: the setting and its behaviour.
- Tests: `mini_agent/tests/test_thinking_cap.py` (patched `litellm.completion`): off sends the full
  budget; capped → overrun → full budget → back to the cap; stays boosted while the full budget also
  overruns; the cap never exceeds `LLM_MAX_TOKENS`.

## Measure

- List: `mini_agent/eval/slow_subset.txt` = the 28 tasks that timed out or quit on overruns in
  `full-mini-v1`, plus 6 thinking-heavy passes as a regression check. About 6.5 h at `-n 2`.
- Run on the Victus with `AGENT_THINKING_CAP=8192`, compare against the same 34 tasks in
  `full-mini-v1`: **passes first**, then time-limit stops, overrun quits, boosted calls, wall time.
- **Confound:** server speed changes timeouts by itself (10 → 1 between two days last week). Record the
  median output tokens/s of both runs and only trust a clear gap.

## Next (separate runs)

1. Time awareness: show time used in each observation, plus "write a first answer within ~10 minutes"
   (the agent can't see each task's limit; all limits are at least 15 minutes).
2. Verifier before submitting (one review call), after asking the organizers whether it fits
   "one system prompt, one agent loop".
