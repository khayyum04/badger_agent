# Time awareness (cut time-limit failures, step 2)

Agreed 2026-11-01 (Mukhriz, with Claude) in issue #18. Branch: `feat/time-awareness`, from `feat/thinking-cap`
(step 1, `docs/plans/thinking-cap.md`), so runs include the cap.

## Problem

Timeouts are still the biggest failure group: 25 of the 37 failures in `full-mini-v1` hit the task's time
limit, 15 with the cap (`thinkcap-8k-v1`, 34-task slow list). The agent can't see the clock or the limit:
Harbor gives `agent_timeout_sec` only to the oracle agent. 15 of the 25 timeouts were 15-minute tasks, the
shortest limit.

A timeout is not automatically a fail: after the agent is stopped, the tests still grade whatever is in the
container. 2 timed-out tasks in `full-mini-v1` (1 in `thinkcap-8k-v1`) passed that way. Writing a working
answer earlier turns some timeouts into passes. Rule 4 of the prompt already says to write a plausible answer
as soon as there is one, but nothing tells the model how much time has gone.

## Technical Plan

A new setting `AGENT_TIME_AWARENESS` (`on`/`off`, default off). When on:

1. **Clock:** every command result ends with
   `[time used: N min; the limit is unknown and may be as short as 15 min]`
   (N = whole minutes since the agent started; Harbor's limit counts from the same point, not from the
   container build).
2. **Prompt:** rule 4 becomes: "Time is limited (it may be only 15 minutes). Write a working version of the
   required output file(s) early, by about 5-8 minutes if you can, then improve it. Overwrite them when you
   improve them; a missing output file always fails." With the setting off, rule 4 is unchanged.
3. **Nudge, once:** the first command result at or after 10 minutes also gets
   "10 minutes used. If the required output isn't written yet, write your best version now, then keep
   improving it."

## Alternatives

- **Countdown assuming 15 minutes.** Wrong on the 30-60 minute tasks, where it would push the model to
  rush or give up.
- **Clock only after N minutes.** Less text, but the model gets no sense of pace early. The clock costs
  about 20 tokens per turn.
- **A second nudge (e.g. 25 min).** Not now; one is enough to measure.
- **Prompt only.** The current rule 4 already asks for an early answer, and tasks still time out.

## Weak spots

- The model may submit sooner, turning timeouts into wrong answers instead of passes. That's why the text says
  "write a working version, then improve it", not "finish fast".
- On 30-60 minute tasks the "may be as short as 15 min" warning is misleading pressure.
- A turn with no tool call (a FormatError) has no command result, so it shows no clock.
- The 10-minute nudge can arrive late: the clock is only read when a command result is formatted, so after a
  3-minute model call it shows up at about 13 minutes.

## Detailed Implementation

- `HarborSyncedAgent` (`mini_agent/badger_mini/harbor_agent.py`): attribute `time_awareness = False`.
  `execute_actions()` appends the clock line (and, once, the nudge) to the content of the observation
  messages it returns. Elapsed time comes from mini-swe-agent's `self._start_time` (set in `__init__`, right
  before `agent.run`). The `self_compact` path returns no observation and gets no clock.
- Clock and nudge texts are module constants next to the other agent-facing messages (like the command
  timeout message in `HarborEnvironment.execute()`).
- `terminal_bench.yaml`: rule 4 in `instance_template` switches on the template variable `time_awareness`
  with `{% if time_awareness %}...{% else %}...{% endif %}`.
- `BadgerMiniAgent.run()`: reads `AGENT_TIME_AWARENESS`, sets `agent.time_awareness` and
  `agent.extra_template_vars["time_awareness"]` (kept by `DefaultAgent.run()`, which merges into it).
- `_sync_context()`: `time_awareness` and `nudged_at_sec` (elapsed seconds when the nudge was sent, or null)
  in the result metadata.
- `.env.example`, `mini_agent/CLAUDE.md`: the setting and its behaviour.
- Tests (`mini_agent/tests/test_time_awareness.py`, no endpoint or Docker): off adds nothing and keeps the
  old rule 4; on adds the clock with the right minute count; the nudge appears once, only from 10 minutes on;
  the rendered prompt has the new rule 4 only when on.

## Measure

- List: `mini_agent/eval/slow_subset.txt` (34 tasks), on the Victus, new job name, with
  `AGENT_THINKING_CAP=8192 AGENT_TIME_AWARENESS=on`.
- Compare against `thinkcap-8k-v1` (cap only): **passes first**, then timeouts, timed-out tasks that still
  passed, wrong answers (should not go up), time to the first write of an output file where visible.
- Confound: server speed. Record median output tokens/s for both runs and only trust a clear gap.
