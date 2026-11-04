# Overrun recovery (keep the thinking from cut-off replies)

Agreed 2026-11-04 (Mukhriz, with Claude) after the cross-run task table. Branch: `feat/overrun-recovery`, from
`feat/submit-checklist`.

## Problem

When a reply hits its token limit before calling the tool (`finish_reason=length`), mini-swe-agent drops the
reply and sends a short retry note. The model then starts thinking again from zero: nothing it worked out
survives. Five in a row end the task (`RepeatedFormatError`).

- 31% of all output tokens in `full-capta-v1` were thrown away like this (1.47M of 4.79M; 26% in `full-mini-v1`).
- `regex-chess`, `write-compressor` and `feal-linear-cryptanalysis` ended after five overruns and a single
  command. `winning-avg-corewars` and `dna-assembly` lost 22-44 minutes to overruns, then timed out.
- Across the six recent mini_agent runs, 26 tasks pass sometimes and fail sometimes; many of the reasoning-heavy
  ones (crypto, compression, solvers) lose most of their time this way.

The boost after an overrun (`AGENT_THINKING_CAP`) doesn't fix it: the 16K retries overrun too, and each one is
also thrown away.

## Technical Plan

One setting, `AGENT_OVERRUN_RECOVERY=on`, off by default.

1. **Keep the notes.** The retry note after an overrun includes the start and the end of the cut-off reply's
   thinking (`OVERRUN_NOTES_HEAD` + `OVERRUN_NOTES_TAIL` characters), framed as "your notes so far, continue
   from them, don't start over", and asks for one small tool call now (e.g. save the plan to a file, or test the
   next idea with a short script).
2. **Make it act.** After `OVERRUN_THINKING_OFF_AFTER` (2) overruns in a row, the next calls are sent with
   thinking off (`chat_template_kwargs: {enable_thinking: false}`, Qwen's switch) until a reply finishes
   normally. So the run of five overruns that ends a task can't happen while the switch works.
3. `max_consecutive_format_errors` stays at 5: with step 2, five overruns in a row only happen if the endpoint
   ignores the thinking-off switch, and then ending the task is still the right call.

Generic (no task names), so it fits the one-prompt rule.

## Alternatives

- **Larger LLM_MAX_TOKENS.** The 16K boosted retries overrun too, and longer thinking eats the time limit.
- **Feed the cut-off reply back as an assistant message.** Same information, but the API's thinking fields make
  it fragile (and `AGENT_STRIP_REASONING` would drop it); a user note is plain text.
- **Remove the five-overrun limit.** Without notes or forced action, the model just keeps restarting until
  the time limit.

## Weak spots

- The notes may be half-wrong and anchor the model on a bad idea. The note says they are notes, not answers.
- A reply with thinking off may be a worse command. It only happens after two overruns in a row, and the
  notes carry the thinking.
- If the gateway rejects `chat_template_kwargs` with a 400, every recovering task fails loudly (400s abort).
  Probe the endpoint before a run. If it silently ignores it, step 2 does nothing and steps 1/3 still apply.
- Each note is about 6K characters (about 1.5-2K tokens) re-sent on every later turn: a small token cost.
- Doesn't help tasks that are simply too hard or too slow (the 24 never-pass tasks).

## Detailed Implementation

- `harbor_agent.py`: constants `OVERRUN_NOTES_HEAD`, `OVERRUN_NOTES_TAIL`, `OVERRUN_THINKING_OFF_AFTER`,
  `OVERRUN_NOTES_TEMPLATE`, `THINKING_OFF_KWARGS`. `BadgerLitellmModel`: `overrun_recovery`,
  `_overruns_in_row`, `n_overrun_notes`, `n_thinking_off_calls`; `_query()` adds the thinking-off kwargs (merged
  into any `extra_body`); `_parse_actions()` appends the notes to the FormatError message on an overrun.
- `BadgerMiniAgent.run()` reads the setting; `_sync_context()` writes `overrun_recovery`, `n_overrun_notes`,
  `n_thinking_off_calls`. The Langfuse exporter copies them.
- Tests: `mini_agent/tests/test_overrun_recovery.py` (patched litellm, no endpoint).

## Measure

- List: `mini_agent/eval/overrun_subset.txt`, the sometimes-pass and never-pass tasks that lose the most to
  overruns, plus controls. Same settings as `full-capta-v1` plus `AGENT_OVERRUN_RECOVERY=on`.
- Compare against each task's pass rate across the six earlier runs, and the output tokens thrown away.
  Also read a few trajectories: does the model continue from its notes, and do thinking-off replies make
  sensible commands?
