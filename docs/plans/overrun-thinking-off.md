# Thinking off after the first overrun

Setting: `AGENT_OVERRUN_THINKING_OFF_AFTER` (default 2 = unchanged behaviour). Experiment value: 1.

## Why

An overrun is a reply that hits the thinking cap (8192) with no tool call. It is dropped from the history, and the
next request carries notes (start and end of the lost thinking). Measured in full-all-v1/v2/v3 (267 trials):

- Overrun replies are 25-34% of all output tokens, and about 5 minutes of a 15-minute limit in timed-out tasks.
- The retry after an overrun is the costly call: it gets LLM_MAX_TOKENS (16K). A quarter of retries thought over
  7,000 tokens, and 63 of 267 overran again (8K + 16K tokens, about 3.5 minutes, before any command ran).
- Lowering effort doesn't help: replaying 30 real post-overrun requests, `reasoning_effort=low` at the 8192 cap
  overran on 6 of 12. Thinking off always produced a command (2-26 s), and on the 8 comparable cases the commands
  matched what the agent did after long thinking (e.g. circuit-fibsqrt: same notes in 5 s instead of 12,500
  thinking tokens).

Background: the sandwich idea (more effort at plan/verify, less in the middle) was dropped because unset effort is
already the shortest thinker (explicit xhigh ~1.9x, high ~1.5x), so "middle at high" would think more.

## What changes

With 1, only the reply right after an overrun goes out with thinking off; the next call thinks normally again
(the in-a-row counter resets when a reply finishes normally). Nothing else changes.

## How to judge the run

Compare with full-all-v1/v2/v3 (56/56/57), mechanism first:
1. Double overruns (two notes in a row) should be about 0.
2. Overruns per trial: if it rises, the model is just re-thinking on the next call (the main risk).
3. Time lost to overruns in timed-out tasks (was about 5 min), and the timeout count (17/16/13).
4. Which timed-out tasks flipped, and whether early-overrun passes (52 overruns in calls 1-3) turned into fails.
5. Total score and tokens last: +1 to +3 is within reach, and run-to-run noise is about +-1.

## Risks

- The thinking-off reply often only saves notes; the next call may think hard and overrun again.
- Passing tasks that plan through a long early retry may lose that planning if the notes don't carry it.
